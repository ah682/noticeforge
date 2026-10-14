"""SQLite migrations, immutable originals and atomic optimistic review transactions."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from noticeforge.extraction import valid_iso_date
from noticeforge.models import (
    DateValue,
    ModelDecision,
    ModelDecisionRequest,
    NoticeRecord,
    ReviewRequest,
    now_iso,
)
from noticeforge.proposals import apply_candidate, candidate_context
from noticeforge.providers import ProviderResult
from noticeforge.validation import critical_fields, evidence_valid, validate_record


class ReviewError(ValueError):
    pass


class ConflictError(ReviewError):
    pass


class Repository:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = root / "noticeforge.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notices(
                  id TEXT PRIMARY KEY, document_hash TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
                  source BLOB NOT NULL, original_json TEXT NOT NULL, current_json TEXT NOT NULL,
                  version INTEGER NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, notice_id TEXT NOT NULL REFERENCES notices(id),
                  action TEXT NOT NULL, field_path TEXT, before_json TEXT, after_json TEXT,
                  reviewer TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
                  version INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_notice ON audit(notice_id, id);
                INSERT OR IGNORE INTO schema_migrations VALUES (1, CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS model_runs(
                  id TEXT PRIMARY KEY, notice_id TEXT NOT NULL REFERENCES notices(id),
                  base_version INTEGER NOT NULL, status TEXT NOT NULL,
                  run_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS model_runs_notice ON model_runs(notice_id, created_at);
                INSERT OR IGNORE INTO schema_migrations VALUES (2, CURRENT_TIMESTAMP);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def save(self, record: NoticeRecord, source: bytes) -> NoticeRecord:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT current_json FROM notices WHERE document_hash=?", (record.document.sha256,)
            ).fetchone()
            if existing:
                saved = NoticeRecord.model_validate_json(existing["current_json"])
                if saved.document.expected_pages != record.document.expected_pages:
                    raise ConflictError(
                        "This source already exists with a different expected page count. "
                        "The saved notice and reviews were retained; verify the original coverage."
                    )
                return saved
            payload = record.model_dump_json()
            db.execute(
                "INSERT INTO notices VALUES (?,?,?,?,?,?,?,?)",
                (
                    record.id,
                    record.document.sha256,
                    record.document.filename,
                    source,
                    payload,
                    payload,
                    record.version,
                    record.created_at,
                ),
            )
            db.execute(
                "INSERT INTO audit(notice_id, action, reviewer, reason, created_at, version) VALUES (?,?,?,?,?,?)",
                (
                    record.id,
                    "import",
                    "compiler",
                    f"{record.mode} {record.compiler_version}; source retained",
                    now_iso(),
                    record.version,
                ),
            )
        return record

    def get(self, notice_id: str) -> NoticeRecord:
        with self.connect() as db:
            row = db.execute("SELECT current_json FROM notices WHERE id=?", (notice_id,)).fetchone()
        if not row:
            raise KeyError("Notice not found")
        return NoticeRecord.model_validate_json(row["current_json"])

    def original(self, notice_id: str) -> NoticeRecord:
        with self.connect() as db:
            row = db.execute("SELECT original_json FROM notices WHERE id=?", (notice_id,)).fetchone()
        if not row:
            raise KeyError("Notice not found")
        return NoticeRecord.model_validate_json(row["original_json"])

    def source(self, notice_id: str) -> bytes:
        with self.connect() as db:
            row = db.execute("SELECT source FROM notices WHERE id=?", (notice_id,)).fetchone()
        if not row:
            raise KeyError("Notice not found")
        return bytes(row["source"])

    def all_notices(self) -> list[NoticeRecord]:
        with self.connect() as db:
            rows = db.execute("SELECT current_json FROM notices ORDER BY created_at, id").fetchall()
        return [NoticeRecord.model_validate_json(row["current_json"]) for row in rows]

    def audit(self, notice_id: str) -> list[dict]:
        self.get(notice_id)
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM audit WHERE notice_id=? ORDER BY id DESC", (notice_id,)
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["before"] = json.loads(event.pop("before_json") or "null")
            event["after"] = json.loads(event.pop("after_json") or "null")
            events.append(event)
        return events

    def history(self, notice_id: str) -> dict:
        record = self.get(notice_id)
        incoming = []
        outgoing = []
        records = self.all_notices()
        for newer in records:
            for relationship in newer.relationships:
                targets = [
                    old
                    for old in records
                    if old.metadata.notice_id.value == relationship.target_notice_id.value
                    and old.metadata.supplier.value == newer.metadata.supplier.value
                    and old.id != newer.id
                ]
                target_parts = (
                    {p.raw_identifier.value for p in targets[0].parts} if len(targets) == 1 else set()
                )
                missing_parts = (
                    sorted(set(relationship.parts) - target_parts) if relationship.scope == "subset" else []
                )
                link = {
                    "source_id": newer.id,
                    "source_notice_id": newer.metadata.notice_id.value,
                    "target_notice_id": relationship.target_notice_id.value,
                    "kind": relationship.kind,
                    "scope": relationship.scope,
                    "parts": relationship.parts,
                    "evidence": [ev.model_dump() for ev in relationship.evidence],
                    "resolved": len(targets) == 1
                    and relationship.scope != "unknown"
                    and not missing_parts
                    and relationship.review_status != "review_required",
                    "missing_scope_parts": missing_parts,
                    "target_id": targets[0].id if len(targets) == 1 else None,
                }
                if newer.id == record.id:
                    outgoing.append(link)
                if record in targets:
                    raw_parts = {p.raw_identifier.value for p in record.parts if p.raw_identifier.value}
                    affected = (
                        raw_parts
                        if relationship.scope == "all"
                        else raw_parts.intersection(relationship.parts)
                    )
                    incoming.append(
                        {
                            **link,
                            "affected_parts": sorted(affected),
                            "unaffected_parts": sorted(raw_parts - affected),
                        }
                    )
        return {
            "incoming": incoming,
            "outgoing": outgoing,
            "policy": "Historical records are retained; a subset revision changes only explicitly named parts",
        }

    def review(self, notice_id: str, request: ReviewRequest) -> NoticeRecord:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT current_json, version FROM notices WHERE id=?", (notice_id,)).fetchone()
            if not row:
                raise KeyError("Notice not found")
            if row["version"] != request.expected_version:
                raise ConflictError("This notice changed during review. Reload it before saving")
            record = NoticeRecord.model_validate_json(row["current_json"])
            fields = dict(critical_fields(record))
            if request.field_path not in fields:
                raise ReviewError(
                    "Select a supported critical field; arbitrary schema changes are not permitted"
                )
            value = fields[request.field_path]
            before = value.model_dump()
            if request.action == "accept":
                if not value.value or not evidence_valid(record, value):
                    raise ReviewError(
                        "A missing value or evidence cannot be accepted. Supply a sourced correction"
                    )
                if isinstance(value, DateValue) and value.qualifier != "exact":
                    raise ReviewError("Resolve the ambiguous or tentative date with a sourced correction")
                value.review_status = "accepted"
            else:
                if request.value is None or not request.value.strip():
                    raise ReviewError("A correction must contain a value")
                if isinstance(value, DateValue) and not valid_iso_date(request.value):
                    raise ReviewError("Enter a real calendar date in YYYY-MM-DD format")
                if request.field_path == "metadata.notice_type" and request.value not in {"PCN", "PDN"}:
                    raise ReviewError("Notice type must be PCN or PDN")
                if request.evidence:
                    value.evidence = [request.evidence]
                if not evidence_valid(record, value):
                    raise ReviewError("A correction requires a valid page and exact source text range")
                value.value = request.value.strip()
                value.review_status = "corrected"
                value.method = "human-review"
                if isinstance(value, DateValue):
                    value.qualifier = "exact"
                if request.field_path.endswith(".raw_identifier"):
                    index = int(request.field_path.split(".")[1])
                    record.parts[index].normalized_identifier = value.value
            value.reason = request.reason
            record.version += 1
            validate_record(record)
            db.execute(
                "UPDATE notices SET current_json=?, version=? WHERE id=?",
                (record.model_dump_json(), record.version, notice_id),
            )
            db.execute(
                """INSERT INTO audit(notice_id, action, field_path, before_json, after_json,
                       reviewer, reason, created_at, version) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    notice_id,
                    request.action,
                    request.field_path,
                    json.dumps(before),
                    value.model_dump_json(),
                    request.reviewer,
                    request.reason,
                    now_iso(),
                    record.version,
                ),
            )
        return record

    def model_runs(self, notice_id: str) -> list[dict]:
        record = self.get(notice_id)
        with self.connect() as db:
            rows = db.execute(
                "SELECT run_json FROM model_runs WHERE notice_id=? ORDER BY created_at DESC, id DESC",
                (notice_id,),
            ).fetchall()
        runs = [json.loads(row["run_json"]) for row in rows]
        for run in runs:
            run["candidate_context"] = []
            if run["result"]:
                result = ProviderResult.model_validate(run["result"])
                run["candidate_context"] = [
                    candidate_context(record, candidate) for candidate in result.candidates
                ]
        return runs

    def start_model_run(
        self, notice_id: str, expected_version: int, configuration: dict, input_sha256: str
    ) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version FROM notices WHERE id=?", (notice_id,)).fetchone()
            if not row:
                raise KeyError("Notice not found")
            if row["version"] != expected_version:
                raise ConflictError("This notice changed. Reload it before requesting model review")
            active = db.execute(
                "SELECT COUNT(*) FROM model_runs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if (
                active >= 4
                or db.execute(
                    "SELECT 1 FROM model_runs WHERE notice_id=? AND status IN ('queued','running')",
                    (notice_id,),
                ).fetchone()
            ):
                raise ConflictError(
                    "Model review is already running or the local queue is full; wait for it to finish"
                )
            created = now_iso()
            run = {
                "id": uuid.uuid4().hex,
                "notice_id": notice_id,
                "base_version": expected_version,
                "created_at": created,
                "completed_at": None,
                "status": "queued",
                "result": None,
                "provider": configuration["provider"],
                "model": configuration["model"],
                "configuration": configuration,
                "input_sha256": input_sha256,
                "decisions": [],
            }
            db.execute(
                "INSERT INTO model_runs VALUES (?,?,?,?,?,?)",
                (run["id"], notice_id, expected_version, "queued", json.dumps(run), created),
            )
            db.execute(
                "INSERT INTO audit(notice_id,action,after_json,reviewer,reason,created_at,version) VALUES(?,?,?,?,?,?,?)",
                (
                    notice_id,
                    "model_requested",
                    json.dumps({"run_id": run["id"], "provider": run["provider"], "model": run["model"]}),
                    "local reviewer",
                    "Explicit model review requested; no values applied",
                    created,
                    expected_version,
                ),
            )
        return run

    def set_model_run_result(self, run_id: str, result: ProviderResult | None) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT run_json FROM model_runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError("Model run not found")
            run = json.loads(row["run_json"])
            if run["status"] not in {"queued", "running"}:
                raise ConflictError("Model run has already finished")
            run["status"] = result.status if result else "running"
            if result:
                run["result"] = result.model_dump(mode="json")
                run["completed_at"] = now_iso()
            db.execute(
                "UPDATE model_runs SET status=?,run_json=? WHERE id=?",
                (run["status"], json.dumps(run), run_id),
            )
            if result:
                db.execute(
                    "INSERT INTO audit(notice_id,action,after_json,reviewer,reason,created_at,version) VALUES(?,?,?,?,?,?,?)",
                    (
                        run["notice_id"],
                        "model_completed",
                        json.dumps(
                            {
                                "run_id": run_id,
                                "status": result.status,
                                "candidates": len(result.candidates),
                                "rejected": len(result.rejected),
                            }
                        ),
                        "model service",
                        "Model output retained as proposals; no canonical values applied",
                        run["completed_at"],
                        run["base_version"],
                    ),
                )
        return run

    def interrupt_model_runs(self):
        """A process restart cannot silently re-send source material or lose pending state."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,run_json FROM model_runs WHERE status IN ('queued','running')"
            ).fetchall()
        for row in rows:
            run = json.loads(row["run_json"])
            self.set_model_run_result(
                row["id"],
                ProviderResult(
                    provider=run["provider"],
                    model=run["model"],
                    status="error",
                    errors=[
                        "Model review was interrupted by a server restart. Request a new run explicitly."
                    ],
                ),
            )

    def decide_model_candidate(self, notice_id: str, run_id: str, request: ModelDecisionRequest) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT current_json,version FROM notices WHERE id=?", (notice_id,)).fetchone()
            if not row:
                raise KeyError("Notice not found")
            if row["version"] != request.expected_version:
                raise ConflictError("This notice changed during review. Reload it before saving")
            saved = db.execute(
                "SELECT run_json FROM model_runs WHERE id=? AND notice_id=?", (run_id, notice_id)
            ).fetchone()
            if not saved:
                raise KeyError("Model run not found")
            record = NoticeRecord.model_validate_json(row["current_json"])
            run = json.loads(saved["run_json"])
            if run["status"] in {"queued", "running"} or not run["result"]:
                raise ReviewError("Wait for model review to finish before deciding a candidate")
            result = ProviderResult.model_validate(run["result"])
            if request.candidate_index >= len(result.candidates):
                raise ReviewError("Select a validated proposal; rejected outputs cannot be applied")
            if any(decision["candidate_index"] == request.candidate_index for decision in run["decisions"]):
                raise ConflictError("This candidate already has a recorded decision")
            candidate = result.candidates[request.candidate_index]
            # Other decisions from this run can advance the version. Any unrelated
            # edit makes its snapshot stale, preventing silent overwrite of a review.
            own_versions = {decision["version"] for decision in run["decisions"]}
            if request.action == "accept" and any(
                version not in own_versions for version in range(run["base_version"] + 1, record.version + 1)
            ):
                raise ConflictError(
                    "This proposal predates another edit. Request a fresh model run before applying it"
                )
            before: dict = {"candidate": candidate.model_dump(mode="json")}
            after: dict = {"decision": "rejected"}
            paths: list[str] = []
            if request.action == "accept":
                try:
                    paths, before, after = apply_candidate(record, candidate, request, run_id)
                except (ValueError, StopIteration) as exc:
                    raise ReviewError(str(exc) or "Candidate evidence could not be applied") from exc
            created = now_iso()
            configuration = run["configuration"]
            record.model_decisions.append(
                ModelDecision(
                    run_id=run_id,
                    candidate_index=request.candidate_index,
                    action=request.action,
                    provider=run["provider"],
                    model=run["model"],
                    revision=configuration.get("revision"),
                    configuration_sha256=configuration["configuration_sha256"],
                    input_sha256=run["input_sha256"],
                    output_sha256=result.output_sha256,
                    context_truncated=result.truncated,
                    input_characters=result.input_characters,
                    included_characters=result.included_characters,
                    reviewer=request.reviewer.strip(),
                    reason=request.reason.strip(),
                    decided_at=created,
                    field_paths=paths,
                )
            )
            record.version += 1
            decision = {
                "candidate_index": request.candidate_index,
                "action": request.action,
                "reviewer": request.reviewer.strip(),
                "reason": request.reason.strip(),
                "version": record.version,
                "created_at": created,
                "field_paths": paths,
            }
            run["decisions"].append(decision)
            db.execute(
                "UPDATE notices SET current_json=?,version=? WHERE id=?",
                (record.model_dump_json(), record.version, notice_id),
            )
            db.execute("UPDATE model_runs SET run_json=? WHERE id=?", (json.dumps(run), run_id))
            db.execute(
                """INSERT INTO audit(notice_id,action,field_path,before_json,after_json,reviewer,
                          reason,created_at,version) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    notice_id,
                    f"model_{request.action}",
                    ",".join(paths) or None,
                    json.dumps(before),
                    json.dumps(after),
                    request.reviewer.strip(),
                    request.reason.strip(),
                    created,
                    record.version,
                ),
            )
        run["candidate_context"] = [candidate_context(record, candidate) for candidate in result.candidates]
        return {"record": record, "run": run}
