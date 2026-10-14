import copy
import hashlib
import json
from pathlib import Path

from noticeforge.evaluation import (
    aggregate,
    run_evaluation,
    run_provider_benchmark,
    score_model_proposals,
    score_record,
)
from noticeforge.pipeline import compile_notice

ROOT = Path(__file__).resolve().parent.parent


def example():
    manifest = json.loads((ROOT / "fixtures/evaluation/manifest.json").read_text())
    entry = manifest["documents"][0]
    source = ROOT / "fixtures/evaluation" / entry["path"]
    record = compile_notice(source.read_bytes(), source.name).model_dump(mode="json")
    return record, entry["expected"]


def test_wrong_critical_date_counts_as_omission_and_unsupported_assertion():
    record, expected = example()
    record["parts"][0]["dates"][0]["value"] = "2099-12-31"
    metrics = score_record(record, expected)
    assert metrics["critical_omissions"] >= 1
    assert metrics["unsupported_assertions"] >= 1
    assert metrics["exact_part_date_relationship_accuracy"] < 1
    assert metrics["affected_part_recall"] == 1
    assert metrics["errors"]["missing_relationships"]
    assert metrics["errors"]["extra_relationships"]


def test_exception_leakage_is_detected_even_when_all_dates_are_correct():
    record, expected = example()
    with_exception = next(p for p in record["parts"] if p["exceptions"])
    another = next(p for p in record["parts"] if not p["exceptions"])
    another["exceptions"] = copy.deepcopy(with_exception["exceptions"])
    metrics = score_record(record, expected)
    assert metrics["exact_part_date_relationship_accuracy"] == 1
    assert metrics["unsupported_assertions"] >= 1
    assert metrics["errors"]["exception_scope_leakage"]


def test_evidence_slice_errors_are_separate_from_correct_values():
    record, expected = example()
    record["parts"][0]["dates"][0]["evidence"][0]["start"] += 1
    metrics = score_record(record, expected)
    assert metrics["exact_part_date_relationship_accuracy"] == 1
    assert metrics["evidence_localization"] < 1
    assert metrics["bad_evidence_paths"]


def test_duplicate_predictions_reduce_exact_relationship_score():
    record, expected = example()
    record["parts"][0]["dates"].append(copy.deepcopy(record["parts"][0]["dates"][0]))
    metrics = score_record(record, expected)
    assert metrics["relationship_recall"] == 1
    assert metrics["relationship_precision"] < 1
    assert metrics["unsupported_assertions"] == 1


def test_not_applicable_metrics_are_null():
    record, _ = example()
    record["parts"] = []
    record["relationships"] = []
    metrics = score_record(record, {"parts": [], "relationships": []})
    assert metrics["exact_part_date_relationship_accuracy"] is None
    assert metrics["review_required_coverage"] is None
    assert metrics["revision_handling_recall"] is None
    combined = aggregate([{"metrics": metrics}])
    assert combined["affected_part_recall"] is None


def test_evaluation_emits_raw_outcomes_denominators_and_honest_scope(tmp_path):
    report = run_evaluation(tmp_path, repetitions=2, warmup=0)
    assert report["metrics"]["expected_relationships"] > 0
    assert len(report["benchmark"]["raw_request_outcomes"]) == 2 * len(report["cases"])
    assert all("errors" in c["metrics"] for c in report["cases"])
    assert report["by_supplier"] and report["by_template"]
    assert "developmental" in report["purpose"]
    assert "unpassed" in report["real_world_validation_gate"]
    assert (tmp_path / "evaluation.txt").is_file()
    assert (tmp_path / "evaluation.json").is_file()


def test_compile_failure_is_retained_as_error_and_missing_critical_relationships(tmp_path, monkeypatch):
    def fail(data, filename, expected_pages):
        raise ValueError("parser failure")

    monkeypatch.setattr("noticeforge.pipeline.compile_notice", fail)
    report = run_evaluation(tmp_path, repetitions=1, warmup=0)
    assert report["metrics"]["critical_omissions"] > 0
    assert report["metrics"]["matched_relationships"] == 0
    assert all(not row["success"] for row in report["benchmark"]["raw_request_outcomes"])
    assert all(case["metrics"]["execution_error"] == "ValueError" for case in report["cases"])


def test_incomplete_and_document_review_coverage_has_explicit_denominators():
    record, expected = example()
    expected = {**expected, "incomplete": True, "review_required_document": True}
    record["status"] = "incomplete"
    metrics = score_record(record, expected)
    totals = aggregate([{"metrics": metrics}])
    assert totals["incomplete_document_coverage"] == 1
    assert totals["expected_incomplete_documents"] == 1
    assert totals["document_review_coverage"] == 1


def test_unavailable_real_model_has_no_fabricated_measurements(tmp_path, monkeypatch):
    def unavailable(config):
        raise RuntimeError("weights not present")

    monkeypatch.setattr("noticeforge.evaluation.TransformersProvider", unavailable)
    report = run_provider_benchmark(
        ROOT / "configs/compact-lora.json", ROOT / "fixtures/evaluation/manifest.json", tmp_path
    )
    assert report["status"] == "unexecuted"
    assert report["raw_request_outcomes"] == []
    assert "p95_latency_seconds" not in report
    assert "relationship_metrics" not in report


def test_real_benchmark_preserves_invalid_raw_outputs_and_omissions(tmp_path, monkeypatch):
    class InvalidModel:
        name = "actual-provider-interface-test"
        model_id = "test-invalid-output"

        def generate(self, request):
            return "not an extraction record", {"complete": True, "input_tokens": 22, "output_tokens": 5}

    monkeypatch.setattr("noticeforge.evaluation.TransformersProvider", lambda config: InvalidModel())
    report = run_provider_benchmark(
        ROOT / "configs/compact-lora.json", ROOT / "fixtures/evaluation/manifest.json", tmp_path, warmup=0
    )
    assert report["status"] == "executed"
    assert report["relationship_metrics"]["matched_relationships"] == 0
    assert report["relationship_metrics"]["critical_omissions"] > 0
    assert report["output_validation"]["schema_invalid_requests"] == len(report["raw_request_outcomes"])
    assert all(row["raw_output"] == "not an extraction record" for row in report["raw_request_outcomes"])
    assert all(row["raw_wrong_relationships"] is None for row in report["raw_request_outcomes"])
    assert (tmp_path / "request_outcomes.jsonl").read_text().count("\n") == len(
        report["raw_request_outcomes"]
    )


def test_posthoc_proposal_metrics_keep_rejected_evidence_and_missing_parts_visible():
    raw_candidate = {
        "part_raw": "001-A",
        "date_type": "last_buy",
        "date": "2029-01-01",
        "date_text": "2029-01-01",
        "exception": None,
        "evidence": [{"page": 1, "start": 1, "end": 19, "quote": "001-A 2029-01-01"}],
    }
    outcome = {
        "raw_output": json.dumps({"candidates": [raw_candidate]}),
        "result": {"candidates": [], "review_required": True},
    }
    expected = {
        "parts": ["001-A"],
        "relationships": [{"part": "001-A", "kind": "last_buy", "date": "2029-01-01"}],
        "review_required": ["001-A"],
        "revisions": [{"kind": "supersedes"}],
        "incomplete": True,
    }
    metrics = score_model_proposals(outcome, expected, [{"number": 1, "text": "001-A 2029-01-01\n"}])
    assert metrics["affected_part_recall"] == 0
    assert metrics["critical_omissions"] == 2
    assert metrics["review_required_coverage"] == 0
    assert metrics["raw_evidence"] == {"schema_valid": True, "localized": 0, "total": 1, "ratio": 0}
    assert metrics["accepted_evidence"]["ratio"] is None
    assert metrics["outside_proposal_contract"]["expected_revision_relationships"] == 1
    assert metrics["outside_proposal_contract"]["expected_source_incomplete"] is True
    outcome["raw_output"] = "unfinished response"
    assert score_model_proposals(outcome, expected, [])["raw_evidence"]["total"] is None


def test_proposal_exception_on_wrong_part_is_visible_even_with_exact_dates():
    candidates = [
        {
            "part_raw": part,
            "date_type": "last_buy",
            "date": None,
            "date_text": "while inventory lasts",
            "exception": "while inventory lasts" if part == "B" else None,
            "evidence": [],
        }
        for part in ["A", "B"]
    ]
    outcome = {"raw_output": "invalid", "result": {"candidates": candidates, "review_required": True}}
    expected = {
        "parts": ["A", "B"],
        "relationships": [{"part": part, "kind": "last_buy", "date": None} for part in ["A", "B"]],
        "exceptions": [{"part": "A", "contains": "while inventory lasts"}],
    }
    metrics = score_model_proposals(outcome, expected, [])
    assert metrics["exact_part_date_relationship_accuracy"] == 1
    assert metrics["critical_omissions"] == 1
    assert metrics["unsupported_assertions"] == 1
    assert metrics["errors"]["exception_scope_leakage"] == [
        {"part": "B", "contains": "while inventory lasts"}
    ]


def test_model_variants_use_identical_frozen_parsed_inputs_without_reparsing(tmp_path, monkeypatch):
    from noticeforge.providers import FixtureProvider

    manifest = ROOT / "fixtures/evaluation/manifest.json"
    documents = json.loads(manifest.read_text())["documents"]
    snapshot = {"documents": {}}
    for entry in documents:
        source = manifest.parent / entry["path"]
        record = compile_notice(source.read_bytes(), source.name, entry.get("expected_pages"))
        snapshot["documents"][entry["id"]] = {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "pages": [page.model_dump() for page in record.document.pages],
        }
    path = tmp_path / "parsed.json"
    path.write_text(json.dumps(snapshot))

    class BatchFixture(FixtureProvider):
        def generate_batch(self, requests):
            return [self.generate(request) for request in requests]

    def forbidden_parse(*args):
        raise AssertionError("benchmark must use frozen parsed input")

    monkeypatch.setattr("noticeforge.pipeline.compile_notice", forbidden_parse)
    monkeypatch.setattr("noticeforge.evaluation.TransformersProvider", lambda config: BatchFixture())
    single = run_provider_benchmark(
        ROOT / "configs/compact-lora.json", manifest, tmp_path / "single", warmup=0, parsed_inputs_path=path
    )
    batch = run_provider_benchmark(
        ROOT / "configs/compact-lora.json",
        manifest,
        tmp_path / "batch",
        warmup=0,
        batch_size=2,
        parsed_inputs_path=path,
    )
    assert single["status"] == batch["status"] == "executed"
    assert single["input_hashes"] == batch["input_hashes"]
    assert single["parsed_inputs_sha256"] == batch["parsed_inputs_sha256"]
