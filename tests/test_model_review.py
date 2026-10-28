import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from noticeforge.api import create_app
from noticeforge.exporters import validate_xml
from noticeforge.models import ModelDecisionRequest, ReviewRequest
from noticeforge.pipeline import compile_notice
from noticeforge.providers import FixtureProvider, ProviderResult
from noticeforge.repository import ConflictError, Repository, ReviewError

SOURCE = """Notice ID: MODEL-PCN-001
Supplier: Owned Model Review Company
Notice type: PCN
Title: Reviewable manufacturing transfer
Issue date: 2026-10-01
Change title: Assembly site change
Change detail: Qualification completed at the alternate assembly site.
Change category: PSITE
Item name: Analog signal component
Item category: ACEL
Contact type: MANUFACTURER
Contact company: Owned Model Review Company
Contact email: notices@owned.example
Contact street: 12 Example Way
Contact postal code: 10115
Contact city: Berlin
Contact country: DE
Part number | Effective change
RX-01A | 2027-01-15
RX-01B | 2027-02-15
Supplier addendum: RX-01A moves on 2027-03-01.
Additional scoped entry: RX-02C moves on 2027-04-01.
Page 1 of 1
"""


def proposal(
    part="RX-01A",
    deadline="2027-03-01",
    quote="Supplier addendum: RX-01A moves on 2027-03-01.",
    source=SOURCE,
    kind="effective_change",
    exception=None,
):
    start = source.index(quote)
    return {
        "part_raw": part,
        "date_type": kind,
        "date": deadline,
        "date_text": deadline or "TBD",
        "exception": exception,
        "evidence": [{"page": 1, "start": start, "end": start + len(quote), "quote": quote}],
    }


class CountingFixture(FixtureProvider):
    def __init__(self, candidates):
        super().__init__(json.dumps({"candidates": candidates}))
        self.calls = 0
        self.config = {"revision": "a" * 40, "precision": "float32"}

    def generate(self, request):
        self.calls += 1
        return super().generate(request)


@pytest.fixture
def setup(tmp_path):
    provider = CountingFixture(
        [proposal(), proposal("RX-02C", "2027-04-01", "Additional scoped entry: RX-02C moves on 2027-04-01.")]
    )
    app = create_app(tmp_path, model_provider=provider)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        record = client.post("/api/notices", files={"file": ("owned.txt", SOURCE.encode())}).json()
        yield client, record, provider
    app.state.model_service.close()


def start_and_wait(client, record):
    response = client.post(
        f"/api/notices/{record['id']}/model-runs", json={"expected_version": record["version"]}
    )
    assert response.status_code == 202, response.text
    identifier = response.json()["id"]
    until = time.monotonic() + 5
    while time.monotonic() < until:
        runs = client.get(f"/api/notices/{record['id']}/model-runs").json()["runs"]
        run = next(item for item in runs if item["id"] == identifier)
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(0.01)
    raise AssertionError("Model test did not finish")


def decide(client, record, run, action="accept", index=0, **kwargs):
    return client.post(
        f"/api/notices/{record['id']}/model-runs/{run['id']}/decisions",
        json={
            "candidate_index": index,
            "action": action,
            "reviewer": "Owned fixture reviewer",
            "reason": "Source scope checked against the cited supplier addendum.",
            "expected_version": record["version"],
            **kwargs,
        },
    )


def test_upload_never_calls_model_and_generation_never_mutates_facts(setup):
    client, record, provider = setup
    assert provider.calls == 0
    assert client.get("/api/model").json()["provider"] == "fixture-offline"
    run = start_and_wait(client, record)
    assert provider.calls == 1 and run["status"] == "ok"
    assert run["result"]["review_required"]
    assert "Offline fixture" in run["result"]["warnings"][0]
    saved = client.get(f"/api/notices/{record['id']}").json()
    assert saved == record
    assert run["candidate_context"][1]["will_create_part"]


def test_acceptance_persists_original_provenance_audit_and_valid_xml(setup):
    client, record, _ = setup
    run = start_and_wait(client, record)
    response = decide(client, record, run)
    assert response.status_code == 200, response.text
    updated = response.json()["record"]
    assert updated["parts"][0]["dates"][0]["value"] == "2027-03-01"
    assert updated["parts"][1]["dates"][0]["value"] == "2027-02-15"
    assert updated["parts"][0]["dates"][0]["model_run_id"] == run["id"]
    provenance = updated["model_decisions"][0]
    assert provenance["revision"] == "a" * 40
    assert provenance["context_truncated"] is False
    assert provenance["input_characters"] == provenance["included_characters"] == len(SOURCE)
    assert all(
        len(provenance[key]) == 64 for key in ["configuration_sha256", "input_sha256", "output_sha256"]
    )
    original = client.app.state.repo.original(record["id"])
    assert original.parts[0].dates[0].value == "2027-01-15"
    assert not original.model_decisions
    audit = client.get(f"/api/notices/{record['id']}/audit").json()["events"][0]
    assert audit["action"] == "model_accept"
    assert audit["before"]["part"]["dates"][0]["value"] == "2027-01-15"
    xml = client.get(f"/api/notices/{record['id']}/export?format=smartpcn")
    assert xml.status_code == 200, xml.text
    validate_xml(xml.content)
    assert (
        client.get(f"/api/notices/{record['id']}/export").json()["model_decisions"]
        == updated["model_decisions"]
    )
    reopened = Repository(client.app.state.repo.root)
    assert reopened.get(record["id"]).model_decisions[0].run_id == run["id"]
    assert reopened.model_runs(record["id"])[0]["decisions"][0]["action"] == "accept"


def test_new_part_is_literal_scoped_and_does_not_mutate_other_parts(setup):
    client, record, _ = setup
    run = start_and_wait(client, record)
    response = decide(client, record, run, index=1)
    assert response.status_code == 200, response.text
    updated = response.json()["record"]
    assert updated["parts"][:2] == record["parts"]
    part = updated["parts"][2]
    assert part["raw_identifier"]["value"] == "RX-02C"
    assert part["manufacturer"]["value"] == "Owned Model Review Company"
    assert part["dates"][0]["value"] == "2027-04-01"
    assert part["replacement_suggestions"] == []


def test_reject_does_not_change_canonical_fields_but_survives_reload(setup):
    client, record, _ = setup
    run = start_and_wait(client, record)
    response = decide(client, record, run, action="reject")
    updated = response.json()["record"]
    assert updated["parts"] == record["parts"]
    assert updated["version"] == record["version"] + 1
    assert updated["model_decisions"][0]["action"] == "reject"
    assert client.get(f"/api/notices/{record['id']}/model-runs").json()["runs"][0]["decisions"]
    assert decide(client, updated, run).status_code == 409


def test_multiple_decisions_same_run_can_advance_version(setup):
    client, record, _ = setup
    run = start_and_wait(client, record)
    updated = decide(client, record, run).json()["record"]
    response = decide(client, updated, run, index=1)
    assert response.status_code == 200, response.text
    assert len(response.json()["record"]["model_decisions"]) == 2


def test_unrelated_edits_make_candidate_stale_even_with_current_expected_version(setup):
    client, record, _ = setup
    run = start_and_wait(client, record)
    edited = client.app.state.repo.review(
        record["id"],
        ReviewRequest(
            field_path="metadata.title",
            action="accept",
            reviewer="Another reviewer",
            reason="Checked title in source",
            expected_version=1,
        ),
    ).model_dump(mode="json")
    response = decide(client, edited, run)
    assert response.status_code == 409 and "predates" in response.text
    assert not client.app.state.repo.get(record["id"]).model_decisions
    assert decide(client, edited, run, action="reject").status_code == 200


def test_bad_selection_and_cross_notice_access_are_atomic(setup):
    client, record, _ = setup
    run = start_and_wait(client, record)
    assert decide(client, record, run, target_part_id="wrong-part").status_code == 422
    assert decide(client, record, run, replace_date_index=20).status_code == 422
    assert decide(client, record, run, index=99).status_code == 422
    assert client.get(f"/api/notices/{record['id']}").json() == record
    other = client.post(
        "/api/notices", files={"file": ("other.txt", SOURCE.replace("MODEL-PCN-001", "OTHER-PCN").encode())}
    ).json()
    assert decide(client, other, run).status_code == 404


def test_candidate_revalidation_prevents_persisted_bad_evidence_from_being_applied(setup):
    client, record, _ = setup
    run = start_and_wait(client, record)
    with client.app.state.repo.connect() as db:
        # Simulates corrupt persisted output; a stored status is never authority.
        run["result"]["candidates"][0]["part_raw"] = "INVENTED-99"
        db.execute("UPDATE model_runs SET run_json=? WHERE id=?", (json.dumps(run), run["id"]))
    assert decide(client, record, run).status_code == 422
    assert client.get(f"/api/notices/{record['id']}").json() == record


def test_candidate_revalidation_rejects_a_narrow_identifier_fragment(setup):
    client, record, _ = setup
    run = start_and_wait(client, record)
    candidate = run["result"]["candidates"][0]
    candidate["part_raw"] = "01A"
    candidate["evidence"] = [
        {"page": 1, "start": SOURCE.index(quote), "end": SOURCE.index(quote) + len(quote), "quote": quote}
        for quote in ("01A", "2027-03-01")
    ]
    with client.app.state.repo.connect() as db:
        db.execute("UPDATE model_runs SET run_json=? WHERE id=?", (json.dumps(run), run["id"]))
    audit = client.get(f"/api/notices/{record['id']}/audit").json()
    assert decide(client, record, run).status_code == 422
    assert client.get(f"/api/notices/{record['id']}").json() == record
    assert client.get(f"/api/notices/{record['id']}/audit").json() == audit


def test_new_part_evidence_uses_the_complete_identifier_occurrence(tmp_path):
    quote = "Additional scoped entry: RX-02C/A is distinct; RX-02C moves on 2027-04-01."
    source = SOURCE.replace("Additional scoped entry: RX-02C moves on 2027-04-01.", quote)
    provider = CountingFixture([proposal("RX-02C", "2027-04-01", quote, source=source)])
    with TestClient(create_app(tmp_path, model_provider=provider), base_url="http://127.0.0.1") as client:
        record = client.post("/api/notices", files={"file": ("owned.txt", source.encode())}).json()
        run = start_and_wait(client, record)
        response = decide(client, record, run)
        assert response.status_code == 200, response.text
        identifier = response.json()["record"]["parts"][2]["raw_identifier"]
        assert identifier["value"] == "RX-02C"
        assert identifier["evidence"][0]["start"] == source.index("RX-02C moves")


def test_invalid_output_is_visible_and_cannot_be_accepted(tmp_path):
    provider = CountingFixture([{**proposal(), "date": "2030-12-31"}])
    app = create_app(tmp_path, model_provider=provider)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        record = client.post("/api/notices", files={"file": ("owned.txt", SOURCE.encode())}).json()
        run = start_and_wait(client, record)
        assert run["status"] == "partial" and run["result"]["rejected"]
        assert run["result"]["candidates"] == []
        assert decide(client, record, run).status_code == 422
    app.state.model_service.close()


def test_model_error_is_persisted_without_leaking_exception_secret(tmp_path):
    class BrokenProvider:
        name = "failure-test"
        model_id = "test"

        def generate(self, request):
            raise RuntimeError("private-model-token-do-not-log")

    app = create_app(tmp_path, model_provider=BrokenProvider())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        record = client.post("/api/notices", files={"file": ("owned.txt", SOURCE.encode())}).json()
        run = start_and_wait(client, record)
        assert run["status"] == "error" and run["result"]["errors"]
        assert "private-model-token" not in json.dumps(run)
        assert client.get(f"/api/notices/{record['id']}").json() == record
    app.state.model_service.close()


def test_no_model_configuration_keeps_cpu_upload_and_export_available(tmp_path, monkeypatch):
    monkeypatch.delenv("NOTICEFORGE_PROVIDER", raising=False)
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        assert client.get("/api/model").json()["configured"] is False
        record = client.post("/api/notices", files={"file": ("owned.txt", SOURCE.encode())}).json()
        response = client.post(f"/api/notices/{record['id']}/model-runs", json={"expected_version": 1})
        assert response.status_code == 422
        assert client.get(f"/api/notices/{record['id']}/export").status_code == 200


@pytest.mark.parametrize(
    "endpoint,timeout",
    [
        ("http://[broken", "30"),
        ("http://localhost:invalid/v1", "30"),
        ("file:///private", "30"),
        ("http://private-token@localhost/v1", "30"),
        ("http://remote.example/v1", "30"),
        ("https://remote.example/v1?token=secret", "30"),
        ("http://localhost:9000/v1", "NaN"),
        ("http://localhost:9000/v1", "301"),
    ],
)
def test_invalid_model_configuration_keeps_rules_available_and_queues_no_work(
    tmp_path, monkeypatch, endpoint, timeout
):
    monkeypatch.setenv("NOTICEFORGE_PROVIDER", "compatible")
    monkeypatch.setenv("NOTICEFORGE_MODEL_BASE_URL", endpoint)
    monkeypatch.setenv("NOTICEFORGE_MODEL_ID", "owned-test")
    monkeypatch.setenv("NOTICEFORGE_MODEL_TIMEOUT", timeout)
    monkeypatch.setenv("NOTICEFORGE_ALLOW_REMOTE", "1")
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        config = client.get("/api/model")
        assert not config.json()["available"]
        assert "private-token" not in config.text and "secret" not in config.text
        record = client.post("/api/notices", files={"file": ("owned.txt", SOURCE.encode())}).json()
        assert (
            client.post(f"/api/notices/{record['id']}/model-runs", json={"expected_version": 1}).status_code
            == 422
        )
        assert client.get(f"/api/notices/{record['id']}/model-runs").json()["runs"] == []
        assert client.get(f"/api/notices/{record['id']}/export?format=smartpcn").status_code == 200


def test_bounded_model_context_remains_explicit_after_acceptance_and_export(tmp_path):
    source = SOURCE + "\n" + "Additional page content. " * 100
    candidate = proposal(source=source)
    app = create_app(tmp_path, model_provider=CountingFixture([candidate]))
    app.state.model_service.config = {"max_characters": len(SOURCE)}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        record = client.post("/api/notices", files={"file": ("long.txt", source.encode())}).json()
        run = start_and_wait(client, record)
        assert run["status"] == "partial" and run["result"]["truncated"]
        updated = decide(client, record, run)
        assert updated.status_code == 200, updated.text
        exported = client.get(f"/api/notices/{record['id']}/export").json()
        provenance = exported["model_decisions"][0]
        assert provenance["context_truncated"] is True
        assert provenance["input_characters"] == sum(
            len(page["text"]) for page in record["document"]["pages"]
        )
        assert provenance["included_characters"] == len(SOURCE)
        assert exported["parts"][1]["dates"] == record["parts"][1]["dates"]
    app.state.model_service.close()


def test_running_queue_is_bounded_and_restart_requires_explicit_retry(tmp_path):
    repo = Repository(tmp_path)
    record = repo.save(compile_notice(SOURCE.encode(), "owned.txt"), SOURCE.encode())
    config = {"provider": "fixture-offline", "model": "fixture-json-v1", "configuration_sha256": "a" * 64}
    first = repo.start_model_run(record.id, 1, config, "b" * 64)
    with pytest.raises(ConflictError, match="already running"):
        repo.start_model_run(record.id, 1, config, "b" * 64)
    with pytest.raises(ReviewError, match="Wait"):
        repo.decide_model_candidate(
            record.id,
            first["id"],
            ModelDecisionRequest(
                candidate_index=0,
                action="accept",
                reviewer="Engineer",
                reason="Checked the source",
                expected_version=1,
            ),
        )
    repo.interrupt_model_runs()
    interrupted = repo.model_runs(record.id)[0]
    assert interrupted["status"] == "error" and "restart" in interrupted["result"]["errors"][0]
    assert repo.start_model_run(record.id, 1, config, "b" * 64)["id"] != first["id"]


def test_condition_cannot_be_erased_by_accepting_exact_model_date(tmp_path):
    source = SOURCE.replace("Notice type: PCN", "Notice type: PDN").replace("Effective change", "Last buy")
    source += "Exception for RX-01A: Orders accepted only while inventory lasts.\n"
    record = compile_notice(source.encode(), "conditional.txt")
    repo = Repository(tmp_path)
    repo.save(record, source.encode())
    config = {"provider": "fixture-offline", "model": "fixture", "configuration_sha256": "a" * 64}
    run = repo.start_model_run(record.id, 1, config, "b" * 64)
    candidate = proposal(source=source, kind="last_buy")
    repo.set_model_run_result(
        run["id"],
        ProviderResult(provider="fixture-offline", model="fixture", status="ok", candidates=[candidate]),
    )
    response = repo.decide_model_candidate(
        record.id,
        run["id"],
        ModelDecisionRequest(
            candidate_index=0,
            action="accept",
            reviewer="Engineer",
            reason="Confirm scoped date, retain inventory condition",
            expected_version=1,
        ),
    )
    date = response["record"].parts[0].dates[0]
    assert date.qualifier == "inventory_limited" and date.review_status == "review_required"


def test_unicode_evidence_offsets_survive_model_acceptance(tmp_path):
    source = SOURCE.replace("Supplier addendum:", "Supplier addendum 🧩:")
    candidate = proposal(source=source, quote="Supplier addendum 🧩: RX-01A moves on 2027-03-01.")
    app = create_app(tmp_path, model_provider=CountingFixture([candidate]))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        record = client.post("/api/notices", files={"file": ("unicode.txt", source.encode())}).json()
        run = start_and_wait(client, record)
        updated = decide(client, record, run).json()["record"]
        for ev in updated["parts"][0]["dates"][0]["evidence"]:
            assert updated["document"]["pages"][0]["text"][ev["start"] : ev["end"]] == ev["quote"]
    app.state.model_service.close()


def test_existing_legacy_database_accepts_additive_model_migration(tmp_path):
    record = compile_notice(SOURCE.encode(), "owned.txt")
    payload = record.model_dump(mode="json")
    payload.pop("model_decisions")

    def legacy(value):
        if isinstance(value, dict):
            value.pop("model_run_id", None)
            value.pop("model_candidate_index", None)
            for child in value.values():
                legacy(child)
        elif isinstance(value, list):
            for child in value:
                legacy(child)

    legacy(payload)
    with sqlite3.connect(tmp_path / "noticeforge.sqlite3") as db:
        db.execute(
            "CREATE TABLE notices(id TEXT PRIMARY KEY, document_hash TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,"
            " source BLOB NOT NULL, original_json TEXT NOT NULL, current_json TEXT NOT NULL,"
            " version INTEGER NOT NULL, created_at TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO notices VALUES(?,?,?,?,?,?,?,?)",
            (
                record.id,
                record.document.sha256,
                "owned.txt",
                SOURCE.encode(),
                json.dumps(payload),
                json.dumps(payload),
                1,
                record.created_at,
            ),
        )
    reopened = Repository(tmp_path)
    assert reopened.get(record.id).model_decisions == []
    assert reopened.original(record.id).parts == record.parts
    assert reopened.source(record.id) == SOURCE.encode()
    with reopened.connect() as db:
        assert {row[0] for row in db.execute("SELECT version FROM schema_migrations")} >= {1, 2}
