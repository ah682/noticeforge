"""Auditable developmental evaluation and explicitly requested serving benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .datasets import audit_manifest, load_manifest, resolve_document
from .providers import (
    CandidateOutput,
    CompatibleProvider,
    TransformersProvider,
    bound_pages,
    result_from_raw,
    runtime_versions,
)
from .resources import DATA_ROOT
from .training import machine_details


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def percentile(values: list[float], percentile_value: float = 0.95) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * percentile_value) - 1)] if values else None


def _relationship(row: dict[str, Any]) -> tuple[str, str, str | None]:
    return (
        row.get("part", row.get("part_raw", "")),
        row.get("kind", row.get("date_type", "")),
        row.get("date"),
    )


def _revision(row: dict[str, Any]) -> tuple[Any, ...]:
    target = row.get("target_notice_id")
    if isinstance(target, dict):
        target = target.get("value")
    return row["kind"], target, row["scope"], tuple(sorted(row.get("parts", [])))


def _evidence_audit(record: dict[str, Any]) -> dict[str, Any]:
    pages = {page["number"]: page["text"] for page in record["document"]["pages"]}
    localized, total, missing = 0, 0, []
    errors = []

    def visit(value: Any, path: str) -> None:
        nonlocal localized, total
        if isinstance(value, dict):
            if (
                "value" in value
                and "evidence" in value
                and (value.get("value") not in (None, "") or value.get("raw") not in (None, ""))
                and not value["evidence"]
            ):
                missing.append(path)
            for key, child in value.items():
                if key == "evidence" and isinstance(child, list):
                    for index, span in enumerate(child):
                        total += 1
                        text = pages.get(span.get("page"))
                        start, end = span.get("start", -1), span.get("end", -1)
                        okay = (
                            text is not None
                            and 0 <= start < end <= len(text)
                            and text[start:end] == span.get("quote")
                        )
                        localized += int(okay)
                        if not okay:
                            errors.append(f"{path}.evidence.{index}")
                elif key != "document":
                    visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}.{index}")

    visit(record, "record")
    return {
        "evidence_localized": localized,
        "evidence_total": total,
        "evidence_localization": ratio(localized, total),
        "critical_values_without_evidence": missing,
        "bad_evidence_paths": errors,
    }


def score_record(record: Any, expected: dict[str, Any]) -> dict[str, Any]:
    data = record.model_dump(mode="json") if hasattr(record, "model_dump") else record
    predicted_parts = Counter(part["raw_identifier"]["value"] for part in data["parts"])
    expected_parts = Counter(
        part if isinstance(part, str) else part.get("part", part.get("raw_identifier"))
        for part in expected.get("parts", [])
    )
    predicted_relations = Counter(
        (part["raw_identifier"]["value"], deadline["kind"], deadline["value"])
        for part in data["parts"]
        for deadline in part["dates"]
    )
    expected_relations = Counter(_relationship(row) for row in expected.get("relationships", []))
    matched = sum((predicted_relations & expected_relations).values())
    expected_count, predicted_count = sum(expected_relations.values()), sum(predicted_relations.values())
    missing_relations, extra_relations = (
        expected_relations - predicted_relations,
        predicted_relations - expected_relations,
    )
    missing_parts, extra_parts = expected_parts - predicted_parts, predicted_parts - expected_parts
    required = set(expected.get("review_required", []))
    reviewed = {
        part["raw_identifier"]["value"]
        for part in data["parts"]
        if part.get("review_status") == "review_required"
        or any(d.get("review_status") == "review_required" for d in part["dates"])
    }
    expected_revisions = Counter(_revision(row) for row in expected.get("revisions", []))
    predicted_revisions = Counter(_revision(row) for row in data.get("relationships", []))
    revision_correct = sum((expected_revisions & predicted_revisions).values())
    expected_exceptions = expected.get("exceptions", [])
    exception_correct, missing_exceptions, leaked_exceptions = 0, [], []
    for exception in expected_exceptions:
        matching_parts = {
            part["raw_identifier"]["value"]
            for part in data["parts"]
            if any(
                exception["contains"].lower() in str(item.get("value", "")).lower()
                for item in part.get("exceptions", [])
            )
        }
        allowed = {
            other["part"]
            for other in expected_exceptions
            if other["contains"].lower() == exception["contains"].lower()
        }
        if exception["part"] in matching_parts:
            exception_correct += 1
        else:
            missing_exceptions.append(exception)
        for part in sorted(matching_parts - allowed):
            item = {"part": part, "contains": exception["contains"]}
            if item not in leaked_exceptions:
                leaked_exceptions.append(item)
    evidence = _evidence_audit(data)
    incomplete_expected = bool(
        expected.get("incomplete", False)
        or expected.get("complete") is False
        or expected.get("coverage_warning", False)
    )
    incomplete_flagged = data["status"] == "incomplete" or data["document"].get("complete") is False
    document_review_expected = bool(expected.get("review_required_document", False))
    document_review_flagged = data["status"] in {"review_required", "incomplete"}
    omissions = (
        sum(missing_relations.values())
        + sum(missing_parts.values())
        + len(missing_exceptions)
        + sum((expected_revisions - predicted_revisions).values())
    )
    unsupported = (
        sum(extra_relations.values())
        + sum(extra_parts.values())
        + len(leaked_exceptions)
        + sum((predicted_revisions - expected_revisions).values())
        + len(evidence["critical_values_without_evidence"])
        + len(evidence["bad_evidence_paths"])
    )
    return {
        "expected_relationships": expected_count,
        "predicted_relationships": predicted_count,
        "matched_relationships": matched,
        "exact_part_date_relationship_accuracy": ratio(
            matched, sum((expected_relations | predicted_relations).values())
        ),
        "relationship_recall": ratio(matched, expected_count),
        "relationship_precision": ratio(matched, predicted_count),
        "expected_parts": sum(expected_parts.values()),
        "predicted_parts": sum(predicted_parts.values()),
        "matched_parts": sum((expected_parts & predicted_parts).values()),
        "affected_part_recall": ratio(
            sum((expected_parts & predicted_parts).values()), sum(expected_parts.values())
        ),
        "critical_omissions": omissions,
        "unsupported_assertions": unsupported,
        "expected_review_required": len(required),
        "review_required_found": len(required & reviewed),
        "review_required_coverage": ratio(len(required & reviewed), len(required)),
        "expected_revisions": sum(expected_revisions.values()),
        "predicted_revisions": sum(predicted_revisions.values()),
        "matched_revisions": revision_correct,
        "revision_handling_recall": ratio(revision_correct, sum(expected_revisions.values())),
        "expected_exceptions": len(expected_exceptions),
        "matched_exceptions": exception_correct,
        **evidence,
        "expected_incomplete_documents": int(incomplete_expected),
        "incomplete_documents_flagged": int(incomplete_expected and incomplete_flagged),
        "expected_document_review": int(document_review_expected),
        "document_review_flagged": int(document_review_expected and document_review_flagged),
        "errors": {
            "missing_relationships": [list(row) for row in missing_relations.elements()],
            "extra_relationships": [list(row) for row in extra_relations.elements()],
            "missing_parts": list(missing_parts.elements()),
            "extra_parts": list(extra_parts.elements()),
            "missing_exceptions": missing_exceptions,
            "exception_scope_leakage": leaked_exceptions,
            "missing_review_required": sorted(required - reviewed),
            "missing_revisions": [list(row) for row in (expected_revisions - predicted_revisions).elements()],
            "extra_revisions": [list(row) for row in (predicted_revisions - expected_revisions).elements()],
        },
        "status": data["status"],
        "findings": [{"code": f["code"], "severity": f["severity"]} for f in data.get("findings", [])],
    }


def aggregate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "expected_relationships",
        "predicted_relationships",
        "matched_relationships",
        "expected_parts",
        "predicted_parts",
        "matched_parts",
        "critical_omissions",
        "unsupported_assertions",
        "expected_review_required",
        "review_required_found",
        "expected_revisions",
        "predicted_revisions",
        "matched_revisions",
        "expected_exceptions",
        "matched_exceptions",
        "evidence_localized",
        "evidence_total",
        "expected_incomplete_documents",
        "incomplete_documents_flagged",
        "expected_document_review",
        "document_review_flagged",
    )
    result = {key: sum(case["metrics"].get(key, 0) for case in cases) for key in keys}
    result.update(
        {
            "cases": len(cases),
            "exact_part_date_relationship_accuracy": ratio(
                result["matched_relationships"],
                result["expected_relationships"]
                + result["predicted_relationships"]
                - result["matched_relationships"],
            ),
            "relationship_recall": ratio(result["matched_relationships"], result["expected_relationships"]),
            "relationship_precision": ratio(
                result["matched_relationships"], result["predicted_relationships"]
            ),
            "affected_part_recall": ratio(result["matched_parts"], result["expected_parts"]),
            "evidence_localization": ratio(result["evidence_localized"], result["evidence_total"]),
            "review_required_coverage": ratio(
                result["review_required_found"], result["expected_review_required"]
            ),
            "revision_handling_recall": ratio(result["matched_revisions"], result["expected_revisions"]),
        }
    )
    result["incomplete_document_coverage"] = ratio(
        result["incomplete_documents_flagged"], result["expected_incomplete_documents"]
    )
    result["document_review_coverage"] = ratio(
        result["document_review_flagged"], result["expected_document_review"]
    )
    return result


def score_model_proposals(
    outcome: dict[str, Any], expected: dict[str, Any], pages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Score preserved proposals without a new model call or canonical mutation.

    The proposal interface predicts part/date/exception relationships only.
    Source completeness and revision handling remain pipeline responsibilities;
    this report lists those unsupported fields instead of inventing predictions.
    Raw schema validity is separate from evidence-supported proposal quality.
    """
    accepted = outcome.get("result", {}).get("candidates", [])
    predicted_parts = {candidate["part_raw"] for candidate in accepted}
    gold_parts = {
        part if isinstance(part, str) else part.get("part", part.get("raw_identifier"))
        for part in expected.get("parts", [])
    }
    predicted = Counter(_relationship(candidate) for candidate in accepted)
    gold = Counter(_relationship(relation) for relation in expected.get("relationships", []))
    missing_relations, extra_relations = gold - predicted, predicted - gold
    missing_parts, extra_parts = gold_parts - predicted_parts, predicted_parts - gold_parts
    required = set(expected.get("review_required", []))
    flagged = predicted_parts if outcome.get("result", {}).get("review_required") else set()
    missing_exceptions, leaked_exceptions = [], []
    for exception in expected.get("exceptions", []):
        phrase = exception["contains"].lower()
        matching_parts = {
            candidate["part_raw"]
            for candidate in accepted
            if phrase in (candidate.get("exception") or "").lower()
        }
        allowed = {other["part"] for other in expected["exceptions"] if other["contains"].lower() == phrase}
        if exception["part"] not in matching_parts:
            missing_exceptions.append(exception)
        for part in sorted(matching_parts - allowed):
            item = {"part": part, "contains": exception["contains"]}
            if item not in leaked_exceptions:
                leaked_exceptions.append(item)
    page_text = {page["number"]: page["text"] for page in pages}

    def evidence_counts(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        spans = [span for candidate in candidates for span in candidate["evidence"]]
        localized = sum(
            span["page"] in page_text
            and 0 <= span["start"] < span["end"] <= len(page_text[span["page"]])
            and page_text[span["page"]][span["start"] : span["end"]] == span["quote"]
            for span in spans
        )
        return {"localized": localized, "total": len(spans), "ratio": ratio(localized, len(spans))}

    try:
        parsed = CandidateOutput.model_validate_json(outcome.get("raw_output", "")).model_dump()["candidates"]
        raw_evidence: dict[str, Any] = {"schema_valid": True, **evidence_counts(parsed)}
    except ValueError:
        raw_evidence = {"schema_valid": False, "localized": None, "total": None, "ratio": None}
    return {
        "scope": "accepted part/date/exception proposals; not a complete canonical notice",
        "expected_parts": len(gold_parts),
        "predicted_parts": len(predicted_parts),
        "matched_parts": len(gold_parts & predicted_parts),
        "affected_part_recall": ratio(len(gold_parts & predicted_parts), len(gold_parts)),
        "expected_relationships": sum(gold.values()),
        "predicted_relationships": sum(predicted.values()),
        "matched_relationships": sum((gold & predicted).values()),
        "exact_part_date_relationship_accuracy": ratio(
            sum((gold & predicted).values()), sum((gold | predicted).values())
        ),
        "expected_exceptions": len(expected.get("exceptions", [])),
        "matched_exceptions": len(expected.get("exceptions", [])) - len(missing_exceptions),
        "critical_omissions": len(missing_parts) + sum(missing_relations.values()) + len(missing_exceptions),
        "unsupported_assertions": len(extra_parts) + sum(extra_relations.values()) + len(leaked_exceptions),
        "expected_review_required": len(required),
        "review_required_found": len(required & flagged),
        "review_required_coverage": ratio(len(required & flagged), len(required)),
        "accepted_evidence": evidence_counts(accepted),
        "raw_evidence": raw_evidence,
        "outside_proposal_contract": {
            "expected_revision_relationships": len(expected.get("revisions", [])),
            "expected_source_incomplete": bool(
                expected.get("incomplete", False)
                or expected.get("complete") is False
                or expected.get("coverage_warning", False)
            ),
            "explanation": "Revision and source-completeness findings are supplied by the deterministic pipeline, never inferred from candidate JSON.",
        },
        "errors": {
            "missing_parts": sorted(missing_parts),
            "extra_parts": sorted(extra_parts),
            "missing_relationships": [list(row) for row in missing_relations.elements()],
            "extra_relationships": [list(row) for row in extra_relations.elements()],
            "missing_exceptions": missing_exceptions,
            "exception_scope_leakage": leaked_exceptions,
            "missing_review_required": sorted(required - flagged),
        },
    }


def run_evaluation(
    out_dir: Path, manifest_path: Path | None = None, *, repetitions: int = 10, warmup: int = 2
) -> dict[str, Any]:
    from .pipeline import compile_notice

    manifest_path = manifest_path or DATA_ROOT / "fixtures/evaluation/manifest.json"
    if not 1 <= repetitions <= 1000 or not 0 <= warmup <= 100:
        raise ValueError("invalid evaluation repeat/warmup count")
    entries, metadata = load_manifest(manifest_path)
    audit = audit_manifest(manifest_path)
    if not audit["ok"]:
        raise ValueError(f"evaluation dataset audit failed: {audit['issues']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "records").mkdir(exist_ok=True)
    cases: list[dict[str, Any]] = []
    raw: list[dict[str, Any]] = []
    for entry in entries:
        path = resolve_document(manifest_path.parent, entry.path)
        contents = path.read_bytes()
        for _ in range(warmup):
            try:
                compile_notice(contents, path.name, entry.expected_pages)
            except Exception:
                break  # Measured attempts below retain failure outcomes.
        latencies, record = [], None
        failure: str | None = None
        for iteration in range(repetitions):
            start = time.perf_counter()
            try:
                record = compile_notice(contents, path.name, entry.expected_pages)
                failure = None
            except Exception as exc:
                record = None
                failure = type(exc).__name__
            elapsed = time.perf_counter() - start
            latencies.append(elapsed)
            raw.append(
                {
                    "case": entry.id,
                    "iteration": iteration,
                    "success": record is not None,
                    "error_type": failure,
                    "latency_seconds": elapsed,
                    "bytes": len(contents),
                    "pages": len(record.document.pages) if record else None,
                    "characters": sum(len(page.text) for page in record.document.pages) if record else None,
                    "status": record.status if record else "error",
                }
            )
        if record is not None:
            metrics = score_record(record, entry.expected)
            (out_dir / "records" / f"{entry.id}.json").write_text(record.model_dump_json(indent=2) + "\n")
            page_count, character_count = (
                len(record.document.pages),
                sum(len(page.text) for page in record.document.pages),
            )
        else:
            metrics = score_record(
                {
                    "document": {"pages": []},
                    "parts": [],
                    "relationships": [],
                    "status": "incomplete",
                    "findings": [{"code": "evaluation_compile_error", "severity": "error"}],
                },
                entry.expected,
            )
            metrics["execution_error"] = failure
            (out_dir / "records" / f"{entry.id}.json").unlink(missing_ok=True)
            page_count, character_count = 0, 0
        cases.append(
            {
                "id": entry.id,
                "classification": entry.classification,
                "supplier": entry.supplier,
                "template": entry.template,
                "family": entry.family,
                "split": entry.split,
                "source_sha256": audit["document_hashes"][entry.id],
                "pages": page_count,
                "characters": character_count,
                "p95_seconds": percentile(latencies),
                "metrics": metrics,
            }
        )
    suppliers, templates = defaultdict(list), defaultdict(list)
    for case in cases:
        suppliers[case["supplier"]].append(case)
        templates[case["template"]].append(case)
    all_synthetic = all(case["classification"] == "synthetic" for case in cases)
    report = {
        "purpose": "synthetic developmental evaluation; parser designed around the supported fixture grammar; not authentic held-out real supplier validation"
        if all_synthetic
        else "authorized manifest evaluation; split discipline and annotation quality remain review gates",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "deterministic-rules",
        "manifest": str(manifest_path),
        "dataset_audit": audit,
        "manifest_description": metadata.get("description", ""),
        "metrics": aggregate(cases),
        "metric_definitions": {
            "exact_part_date_relationship_accuracy": "multiset intersection / multiset union of exact (raw part, date type, normalized date-or-null) tuples; extras and missing tuples reduce score",
            "critical_omissions": "missing part records + missing date relationships + missing annotated exceptions + missing revision relationships (categories can overlap)",
            "unsupported_assertions": "extra part/date/revision assertions against gold + annotated exception scope leaks + missing/broken critical evidence (categories can overlap)",
            "evidence_localization": "exact page-local Unicode slice equality across all returned citations; does not prove semantic entailment",
            "review_required_coverage": "expected uncertain parts that have a part/date review_required flag",
            "null_metrics": "null means no applicable gold cases or predictions, not perfect performance",
        },
        "by_supplier": {key: aggregate(value) for key, value in suppliers.items()},
        "by_template": {key: aggregate(value) for key, value in templates.items()},
        "cases": cases,
        "benchmark": {
            "p95_extraction_seconds": percentile([row["latency_seconds"] for row in raw]),
            "requests": len(raw),
            "concurrency": 1,
            "warmups_per_case": warmup,
            "repetitions_per_case": repetitions,
            "input_lengths_characters": [case["characters"] for case in cases],
            "hardware": machine_details(),
            "runtime_versions": runtime_versions(),
            "raw_request_outcomes": raw,
            "cost": {
                "external_spend": 0,
                "currency": None,
                "measured_compute_seconds": sum(row["latency_seconds"] for row in raw),
                "utilization": "serial on this shared host; no dedicated capacity assumption",
                "energy_cost": "not measured",
            },
        },
        "model_comparisons": [
            {"mode": "deterministic-rules", "status": "executed"},
            {
                "mode": "untuned-compact",
                "status": "unexecuted",
                "reason": "no selected model weights/runtime execution in default CPU demo",
            },
            {
                "mode": "stronger-prompted-provider",
                "status": "unexecuted",
                "reason": "no authorized external provider/data transfer configured",
            },
            {
                "mode": "LoRA/QLoRA-adapted",
                "status": "unexecuted",
                "reason": "no authorized real training corpus or GPU run",
            },
        ],
        "real_world_validation_gate": "unpassed: obtain permitted real notices and human-adjudicated supplier/template/family holdouts; freeze prompts, thresholds and model choice before final test",
        "review_time_gains": "not measured; require component engineers and recorded timed sessions",
    }
    (out_dir / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    summary = report["metrics"]
    prose = [
        "NoticeForge developmental evaluation",
        "",
        report["purpose"],
        "",
        f"Cases: {len(cases)}. Exact part/date tuples: {summary['matched_relationships']}/{summary['expected_relationships']} expected; {summary['predicted_relationships']} predicted.",
        f"Affected parts: {summary['matched_parts']}/{summary['expected_parts']}. Critical omissions: {summary['critical_omissions']}. Unsupported assertions: {summary['unsupported_assertions']}.",
        f"Evidence slices: {summary['evidence_localized']}/{summary['evidence_total']}. Required review flags: {summary['review_required_found']}/{summary['expected_review_required']}. Revision relations: {summary['matched_revisions']}/{summary['expected_revisions']}.",
        f"Serial p95 extraction: {report['benchmark']['p95_extraction_seconds'] * 1000:.3f} ms over {len(raw)} requests, {warmup} warmups per case.",
        "",
        "These fixtures exercise a documented grammar. No authentic manufacturer corpus, GPU compact model comparison or engineer review-time gain has been validated.",
        "Raw outcomes, denominators, per-case errors and supplier/template breakdowns are in evaluation.json.",
    ]
    (out_dir / "evaluation.txt").write_text("\n".join(prose) + "\n")
    return report


def run_provider_benchmark(
    config_path: Path,
    manifest_path: Path,
    out_dir: Path,
    *,
    batch_size: int = 1,
    concurrency: int = 1,
    warmup: int = 1,
    repetitions: int = 1,
    parsed_inputs_path: Path | None = None,
) -> dict[str, Any]:
    """Run real model requests on the same parsed pages and gold tuple targets.

    Explicit invocation is required. No resource-unavailable estimates are emitted.
    For HTTP concurrency, per-request wall time is measured; local batches record
    batch completion latency for every member. The report says which is which.
    """
    from .pipeline import compile_notice

    config = json.loads(config_path.read_text())
    if (
        not 1 <= batch_size <= 32
        or not 1 <= concurrency <= 16
        or not 0 <= warmup <= 10
        or not 1 <= repetitions <= 100
    ):
        raise ValueError("invalid benchmark workload limits")
    if batch_size > 1 and concurrency > 1:
        raise ValueError("choose local batch size or HTTP concurrency, not both")
    audit = audit_manifest(manifest_path)
    if not audit["ok"]:
        raise ValueError("benchmark manifest permission/leakage audit failed")
    entries, _ = load_manifest(manifest_path)
    parsed_snapshot = json.loads(parsed_inputs_path.read_text()) if parsed_inputs_path else None
    requests = []
    for entry in entries:
        path = resolve_document(manifest_path.parent, entry.path)
        if parsed_snapshot is None:
            pages = compile_notice(path.read_bytes(), path.name, entry.expected_pages).document.pages
        else:
            item = parsed_snapshot["documents"][entry.id]
            if item["source_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError("frozen parsed input source hash mismatch")
            pages = item["pages"]
        requests.append((entry, bound_pages(pages, max_characters=config.get("max_characters", 7000))))
    out_dir.mkdir(parents=True, exist_ok=True)
    public_keys = {
        "provider",
        "model_id",
        "revision",
        "license",
        "device",
        "precision",
        "adapter_path",
        "max_input_tokens",
        "max_new_tokens",
        "max_characters",
        "generation_max_seconds",
        "timeout",
        "cpu_threads",
        "attention_implementation",
        "local_model_path",
    }
    public_config = {key: value for key, value in config.items() if key in public_keys}
    if "base_url" in config:
        parsed = urlparse(config["base_url"])
        public_config["base_url"] = f"{parsed.scheme}://{parsed.hostname or ''}{parsed.path}"
    report: dict[str, Any] = {
        "status": "unexecuted",
        "purpose": "real provider candidate benchmark; outputs require human review; no automatic canonical merge",
        "config": public_config,
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "dataset_audit": audit,
        "concurrency": concurrency,
        "batch_size": batch_size,
        "warmup_iterations": warmup,
        "repetitions": repetitions,
        "precision": config.get("precision", "server-reported/unknown"),
        "runtime_versions": runtime_versions(),
        "raw_request_outcomes": [],
    }
    report["parsed_inputs_sha256"] = (
        hashlib.sha256(parsed_inputs_path.read_bytes()).hexdigest() if parsed_inputs_path else None
    )
    report["input_hashes"] = {entry.id: request.input_sha256 for entry, request in requests}
    report["warmup_outcomes"] = []
    journal = out_dir / "request_outcomes.jsonl"
    journal.write_text("")

    def persist(outcomes: list[dict[str, Any]]) -> None:
        report["raw_request_outcomes"].extend(outcomes)
        with journal.open("a") as stream:
            for outcome in outcomes:
                stream.write(json.dumps(outcome) + "\n")
        print(
            json.dumps(
                {
                    "benchmark": out_dir.name,
                    "completed_requests": len(report["raw_request_outcomes"]),
                    "cases": [outcome["case"] for outcome in outcomes],
                }
            ),
            flush=True,
        )

    try:
        provider: Any
        load_started = time.perf_counter()
        if config.get("provider") == "compatible":
            if batch_size != 1:
                raise ValueError("HTTP adapter does not implement batched chat completions; use concurrency")
            provider = CompatibleProvider(
                config["base_url"],
                config["model_id"],
                token=os.getenv("NOTICEFORGE_MODEL_TOKEN"),
                allow_remote=os.getenv("NOTICEFORGE_ALLOW_REMOTE") == "1",
                timeout=config.get("timeout", 30),
            )
        else:
            if concurrency != 1:
                raise ValueError("local transformer provider supports batching, not concurrent model threads")
            config["allow_download"] = False
            provider = TransformersProvider(config)
        report["model_load_seconds"] = time.perf_counter() - load_started
        report["optimization"] = getattr(provider, "optimization_metadata", {})
        for _ in range(warmup):
            warmup_started = time.perf_counter()
            raw, usage = provider.generate(requests[0][1])
            report["warmup_outcomes"].append(
                {
                    "case": requests[0][0].id,
                    "latency_seconds": time.perf_counter() - warmup_started,
                    "usage": usage,
                    "raw_output": raw,
                }
            )
        work = requests * repetitions
        started = time.perf_counter()

        def measured(group: list[tuple[Any, Any]]) -> list[dict[str, Any]]:
            call_start = time.perf_counter()
            try:
                outputs = (
                    provider.generate_batch([r[1] for r in group])
                    if batch_size > 1
                    else [provider.generate(group[0][1])]
                )
                elapsed = time.perf_counter() - call_start
                outcomes = []
                for (entry, request), (raw, usage) in zip(group, outputs, strict=True):
                    raw_assertions: dict[str, Any]
                    try:
                        parsed = CandidateOutput.model_validate_json(raw)
                        raw_counter: Counter[tuple[str, str, str | None]] = Counter(
                            (c.part_raw, c.date_type, c.date) for c in parsed.candidates
                        )
                        gold_counter = Counter(
                            _relationship(r) for r in entry.expected.get("relationships", [])
                        )
                        raw_assertions = {
                            "raw_schema_valid": True,
                            "raw_candidate_count": len(parsed.candidates),
                            "raw_wrong_relationships": sum((raw_counter - gold_counter).values()),
                            "raw_matched_relationships": sum((raw_counter & gold_counter).values()),
                        }
                    except ValueError:
                        raw_assertions = {
                            "raw_schema_valid": False,
                            "raw_candidate_count": None,
                            "raw_wrong_relationships": None,
                            "raw_matched_relationships": None,
                        }
                    try:
                        result = result_from_raw(raw, request, provider, usage=usage, elapsed=elapsed)
                        predicted: Counter[tuple[str, str, str | None]] = Counter(
                            (c.part_raw, c.date_type, c.date) for c in result.candidates
                        )
                        expected = Counter(_relationship(r) for r in entry.expected.get("relationships", []))
                        correct = sum((predicted & expected).values())
                        outcome: dict[str, Any] = {
                            "status": result.status,
                            "result": result.model_dump(),
                            "matched_relationships": correct,
                            "expected_relationships": sum(expected.values()),
                            "predicted_relationships": sum(predicted.values()),
                            "critical_omissions": sum((expected - predicted).values()),
                            "unsupported_assertions": sum((predicted - expected).values()),
                            "relationship_accuracy": ratio(correct, sum((expected | predicted).values())),
                        }
                    except (ValueError, RuntimeError) as exc:
                        outcome = {
                            "status": "error",
                            "error_type": type(exc).__name__,
                            "critical_omissions": len(entry.expected.get("relationships", [])),
                            "matched_relationships": 0,
                            "expected_relationships": len(entry.expected.get("relationships", [])),
                            "predicted_relationships": 0,
                        }
                    outcomes.append(
                        {
                            "case": entry.id,
                            "supplier": entry.supplier,
                            "template": entry.template,
                            "input_sha256": request.input_sha256,
                            "input_characters": request.original_characters,
                            "included_characters": request.included_characters,
                            "context_truncated": request.truncated,
                            "latency_seconds": elapsed,
                            "latency_scope": "batch completion" if batch_size > 1 else "request completion",
                            "raw_output": raw,
                            "usage": usage,
                            **raw_assertions,
                            **outcome,
                        }
                    )
                return outcomes
            except Exception as exc:
                elapsed = time.perf_counter() - call_start
                return [
                    {
                        "case": entry.id,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "latency_seconds": elapsed,
                        "input_characters": request.original_characters,
                        "included_characters": request.included_characters,
                        "context_truncated": request.truncated,
                        "expected_relationships": len(entry.expected.get("relationships", [])),
                        "matched_relationships": 0,
                        "predicted_relationships": 0,
                        "critical_omissions": len(entry.expected.get("relationships", [])),
                    }
                    for entry, request in group
                ]

        groups = [work[i : i + batch_size] for i in range(0, len(work), batch_size)]
        if concurrency > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                for outcomes in pool.map(measured, groups):
                    persist(outcomes)
        else:
            for group in groups:
                persist(measured(group))
        elapsed = time.perf_counter() - started
        outcomes = report["raw_request_outcomes"]
        totals = {
            k: sum(row.get(k, 0) for row in outcomes)
            for k in (
                "matched_relationships",
                "expected_relationships",
                "predicted_relationships",
                "critical_omissions",
                "unsupported_assertions",
            )
        }
        report.update(
            status="executed",
            elapsed_seconds=elapsed,
            requests_per_second=len(work) / elapsed,
            p95_latency_seconds=percentile([r["latency_seconds"] for r in outcomes]),
            errors=sum(r["status"] == "error" for r in outcomes),
            relationship_metrics={
                **totals,
                "accuracy": ratio(
                    totals["matched_relationships"],
                    totals["expected_relationships"]
                    + totals["predicted_relationships"]
                    - totals["matched_relationships"],
                ),
                "all_candidates_require_review": True,
            },
            cost={
                "training_cost_included": False,
                "serving_wall_seconds": elapsed,
                "provider_currency_cost": "not supplied; no estimate",
                "utilization": f"requested concurrency={concurrency}, batch_size={batch_size} on a shared host",
            },
        )
        report["output_validation"] = {
            "schema_valid_requests": sum(row.get("raw_schema_valid", False) for row in outcomes),
            "schema_invalid_requests": sum(row.get("raw_schema_valid") is False for row in outcomes),
            "incomplete_generations": sum(row.get("usage", {}).get("complete") is False for row in outcomes),
            "evidence_rejected_candidates": sum(
                len(row.get("result", {}).get("rejected", [])) for row in outcomes
            ),
            "raw_wrong_relationships_in_schema_valid_outputs": sum(
                row.get("raw_wrong_relationships") or 0 for row in outcomes
            ),
            "unsupported_assertions_in_invalid_schema_outputs": "not countable; inspect raw outputs; never assume zero",
        }
        report["cost"]["external_spend"] = 0 if config.get("provider") != "compatible" else None
        report["by_supplier"] = {
            supplier: {
                key: sum(row.get(key, 0) for row in outcomes if row.get("supplier") == supplier)
                for key in totals
            }
            for supplier in sorted({row.get("supplier", "unknown") for row in outcomes})
        }
        try:
            import torch

            report["cuda_peak_allocated_bytes"] = (
                torch.cuda.max_memory_allocated() if torch.cuda.is_available() else None
            )
        except ImportError:
            pass
    except Exception as exc:
        report.update(
            status="unexecuted",
            reason=f"{type(exc).__name__}: runtime/weights/configuration or warmup unavailable; see explicit profile prerequisites",
        )
    report["hardware"] = machine_details()
    (out_dir / "serving_benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DATA_ROOT / "fixtures/evaluation/manifest.json")
    parser.add_argument("--output", type=Path, default=Path("output/evaluation"))
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    if args.model_config:
        report = run_provider_benchmark(
            args.model_config,
            args.manifest,
            args.output,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            warmup=args.warmup,
            repetitions=args.repetitions,
        )
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in ("status", "reason", "relationship_metrics", "p95_latency_seconds")
                    if key in report
                },
                indent=2,
            )
        )
        if report["status"] == "unexecuted":
            raise SystemExit(2)
    else:
        report = run_evaluation(args.output, args.manifest, repetitions=args.repetitions, warmup=args.warmup)
        print(json.dumps(report["metrics"], indent=2))


if __name__ == "__main__":
    main()
