#!/usr/bin/env python3
"""Reproduce real pretrained CPU inference, synthetic LoRA and serving comparisons.

Stages run in separate processes so model memory is released between variants.
Only free public model files are downloaded; notice documents are never uploaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noticeforge.datasets import audit_manifest, load_manifest, resolve_document  # noqa: E402
from noticeforge.evaluation import ratio, run_evaluation, run_provider_benchmark, score_model_proposals  # noqa: E402
from noticeforge.pipeline import compile_notice  # noqa: E402
from noticeforge.providers import SYSTEM_PROMPT, CompactConfig  # noqa: E402
from noticeforge.training import train_compact, validation_loss  # noqa: E402

MODELS = {
    "0.5b": ("Qwen/Qwen2.5-0.5B-Instruct", "7ae557604adf67be50417f59c2c2f167def9a775"),
    "1.5b": ("Qwen/Qwen2.5-1.5B-Instruct", "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"),
}
FILES = [
    "config.json",
    "generation_config.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.json",
    "merges.txt",
    "model.safetensors",
    "LICENSE",
    "README.md",
]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def download_models(model_root: Path, reports: Path) -> None:
    records = []
    for size, (model, revision) in MODELS.items():
        folder = model_root / model.split("/")[-1]
        folder.mkdir(parents=True, exist_ok=True)
        source = reports / f"model-{size}-source.json"
        if not source.exists():
            subprocess.run(
                [
                    "curl",
                    "-fL",
                    "--retry",
                    "2",
                    "--max-time",
                    "60",
                    "-s",
                    f"https://huggingface.co/api/models/{model}/revision/{revision}?blobs=true",
                    "-o",
                    str(source),
                ],
                check=True,
            )
        metadata = json.loads(source.read_text())
        if metadata["sha"] != revision or metadata.get("cardData", {}).get("license") != "apache-2.0":
            raise ValueError("model revision or license differs from selected official snapshot")
        remote = {row["rfilename"]: row for row in metadata["siblings"]}
        hashes = {}
        for filename in FILES:
            target = folder / filename
            expected = remote[filename].get("lfs", {}).get("sha256")
            if not target.exists() or (expected and digest(target) != expected):
                subprocess.run(
                    [
                        "curl",
                        "-fL",
                        "--retry",
                        "2",
                        "--max-time",
                        "600",
                        f"https://huggingface.co/{model}/resolve/{revision}/{filename}",
                        "-o",
                        str(target),
                    ],
                    check=True,
                )
            hashes[filename] = digest(target)
            if expected and hashes[filename] != expected:
                raise ValueError("downloaded pretrained weight hash mismatch")
        records.append(
            {
                "model_id": model,
                "revision": revision,
                "license": "Apache-2.0",
                "source": f"https://huggingface.co/{model}",
                "local_model_path": str(folder),
                "artifact_sha256": hashes,
                "download_bytes": sum((folder / filename).stat().st_size for filename in FILES),
                "weight_hash_verified_against_official_lfs": True,
            }
        )
    write_json(reports / "model-artifacts.json", records)


def create_owned_training() -> Path:
    folder = ROOT / "fixtures/model-training"
    folder.mkdir(exist_ok=True)
    documents, annotations = [], []
    kinds = [
        ("last_buy", "Last buy"),
        ("last_delivery", "Last delivery"),
        ("effective_change", "Effective change"),
        ("sample_availability", "Sample availability"),
        ("acknowledgment", "Acknowledgment"),
        ("end_of_production", "End of production"),
    ]
    for index in range(20):
        identifier = f"owned-model-{index:02d}"
        split = "train" if index < 16 else "validation"
        supplier = (
            ("Cobalt training semiconductor" if index < 8 else "Copper training devices")
            if split == "train"
            else f"Larch validation works {index}"
        )
        kind, label = kinds[index % len(kinds)]
        date: str | None = f"2029-{index % 12 + 1:02d}-{index % 20 + 1:02d}"
        part = f"00CF-{index + 1101}-A"
        literal, exception = date, None
        if index in {4, 10}:
            literal, date, exception = "while inventory lasts", None, "while inventory lasts"
        if index == 7:
            literal, date = "05/06/2029", None
        row = f"{part} | {label}: {literal}"
        if split == "train":
            text = f"Supplier: {supplier}\nNotice: OWN-TRAIN-{index:03d}\nAffected identifier and deadline:\n{row}\n"
        else:
            text = (
                f"Engineering bulletin from {supplier}.\nQualification programme {index} concerns a distinct ceramic package and a revised factory inspection protocol.\n"
                f"The component-specific schedule is recorded below.\n{row}\nA responsible engineer must verify the original source before approving any record.\n"
            )
        relationships = [
            {
                "part_raw": part,
                "date_type": kind,
                "date": date,
                "date_text": literal,
                "exception": exception,
                "review_required": date is None,
                "evidence": [
                    {"page": 1, "start": text.index(row), "end": text.index(row) + len(row), "quote": row}
                ],
            }
        ]
        parts = [part]
        if index in {3, 9, 15}:
            another = f"00CF-{index + 1101}-B"
            another_date = f"2030-{index % 12 + 1:02d}-20"
            another_row = f"{another} | {label}: {another_date}"
            start = len(text)
            text += another_row + "\n"
            parts.append(another)
            relationships.append(
                {
                    "part_raw": another,
                    "date_type": kind,
                    "date": another_date,
                    "date_text": another_date,
                    "exception": None,
                    "review_required": False,
                    "evidence": [
                        {"page": 1, "start": start, "end": start + len(another_row), "quote": another_row}
                    ],
                }
            )
        path = folder / f"{identifier}.txt"
        path.write_text(text)
        annotation = {
            "document_id": identifier,
            "annotator": "NoticeForge owned fixture author",
            "created_at": "2026-10-14T00:00:00Z",
            "parts": parts,
            "relationships": relationships,
            "notes": "Literal hand-authored/generated gold; no model-generated labels; no authentic manufacturer document.",
        }
        annotations.append(annotation)
        documents.append(
            {
                "id": identifier,
                "path": path.name,
                "source": "NoticeForge authored synthetic model-training fixture, seed 17",
                "permission_status": "owned_synthetic",
                "license": "CC0-1.0",
                "supplier": supplier,
                "template": "owned-training-schedule-v1"
                if split == "train"
                else f"larch-validation-prose-v{index}",
                "family": f"OWN-MODEL-FAMILY-{index:03d}",
                "classification": "synthetic",
                "split": split,
                "annotation_provenance": "Deterministically authored literal gold; independent of model outputs",
                "created_at": "2026-10-14T00:00:00Z",
                "transformations": ["authored locally with seed 17", "UTF-8 text"],
                "sha256": digest(path),
                "expected": {
                    "parts": parts,
                    "relationships": [
                        {
                            "part": relation["part_raw"],
                            "kind": relation["date_type"],
                            "date": relation["date"],
                        }
                        for relation in relationships
                    ],
                },
            }
        )
    manifest = folder / "manifest.json"
    write_json(
        manifest,
        {
            "description": "Owned synthetic model training and validation; distinct supplier/template/family from developmental evaluation",
            "seed": 17,
            "documents": documents,
        },
    )
    (folder / "annotations.jsonl").write_text("".join(json.dumps(row) + "\n" for row in annotations))
    if not audit_manifest(manifest)["ok"]:
        raise ValueError("new training corpus split audit failed")
    return manifest


def prepare(model_root: Path, reports: Path) -> None:
    if (reports / "freeze.json").exists():
        verify_freeze(reports)
        return
    download_models(model_root, reports)
    training_manifest = create_owned_training()
    frozen = reports / "frozen-evaluation"
    shutil.copytree(ROOT / "fixtures/evaluation", frozen)
    entries, _ = load_manifest(frozen / "manifest.json")
    parsed: dict[str, Any] = {
        "purpose": "Frozen model inputs, shared without reparsing across every model variant",
        "documents": {},
    }
    for entry in entries:
        source = resolve_document(frozen, entry.path)
        record = compile_notice(source.read_bytes(), source.name, entry.expected_pages)
        parsed["documents"][entry.id] = {
            "source_sha256": digest(source),
            "pages": [page.model_dump() for page in record.document.pages],
        }
    write_json(reports / "parsed-inputs.json", parsed)
    # A single combined audit detects training/validation/evaluation overlap.
    audit_folder = reports / "corpus-audit"
    audit_folder.mkdir()
    combined = []
    for manifest in (training_manifest, frozen / "manifest.json"):
        corpus, _ = load_manifest(manifest)
        for document in corpus:
            source = resolve_document(manifest.parent, document.path)
            target = audit_folder / (document.id + source.suffix)
            shutil.copyfile(source, target)
            values = document.model_dump(exclude_none=True)
            values["path"] = target.name
            if manifest.parent == frozen:
                values["split"] = "test"
            combined.append(values)
    write_json(audit_folder / "manifest.json", {"documents": combined})
    audit = audit_manifest(audit_folder / "manifest.json")
    write_json(reports / "combined-split-audit.json", audit)
    if not audit["ok"]:
        raise ValueError("model-training corpus overlaps frozen evaluation")
    model, revision = MODELS["0.5b"]
    base = CompactConfig(
        model_id=model,
        revision=revision,
        license="Apache-2.0",
        local_model_path=str(model_root / model.split("/")[-1]),
        device="cpu",
        precision="float32",
        cpu_threads=4,
        attention_implementation="sdpa",
        max_input_tokens=2048,
        max_sequence_tokens=3072,
        max_new_tokens=1024,
        generation_max_seconds=120,
    ).model_dump()
    profiles = {
        "untuned": base,
        "batched": base,
        "quantized": {**base, "precision": "cpu_dynamic_int8"},
        "training": {
            **base,
            "precision": "bfloat16",
            "epochs": 3,
            "learning_rate": 0.0003,
            "batch_size": 1,
            "gradient_accumulation_steps": 2,
            "target_modules": ["q_proj", "v_proj"],
        },
        "adapted": {**base, "adapter_path": str(reports / "adapter")},
        "adapted-batched": {**base, "adapter_path": str(reports / "adapter")},
        "adapted-quantized": {
            **base,
            "adapter_path": str(reports / "adapter"),
            "precision": "cpu_dynamic_int8",
        },
        "stronger": {
            **base,
            "model_id": MODELS["1.5b"][0],
            "revision": MODELS["1.5b"][1],
            "local_model_path": str(model_root / MODELS["1.5b"][0].split("/")[-1]),
            "precision": "bfloat16",
        },
    }
    for name, value in profiles.items():
        write_json(reports / "profiles" / f"{name}.json", value)
    freeze = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Freeze before any evaluation model scores; owned synthetic developmental evaluation, not authentic held-out manufacturer validation",
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "parsed_inputs_sha256": digest(reports / "parsed-inputs.json"),
        "evaluation_manifest_sha256": digest(frozen / "manifest.json"),
        "training_manifest_sha256": digest(training_manifest),
        "annotations_sha256": digest(training_manifest.parent / "annotations.jsonl"),
        "profile_sha256": {name: digest(reports / "profiles" / f"{name}.json") for name in profiles},
        "policy": "Do not alter prompts, training hyperparameters, model selection, context bounds or thresholds in response to frozen evaluation results.",
        "warmup_iterations": 1,
        "repetitions": 1,
        "batch_size": 2,
        "classification": "synthetic",
        "final_test_authentic_real_data": False,
        "source_documents": {entry.id: digest(resolve_document(frozen, entry.path)) for entry in entries},
    }
    write_json(reports / "freeze.json", freeze)
    print(
        json.dumps(
            {
                "prepared": True,
                "training_documents": 16,
                "validation_documents": 4,
                "frozen_evaluation_documents": len(entries),
                "combined_split_audit": audit["ok"],
            }
        ),
        flush=True,
    )


def verify_freeze(reports: Path) -> None:
    freeze = json.loads((reports / "freeze.json").read_text())
    checks = {
        "prompt": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest() == freeze["prompt_sha256"],
        "parsed_inputs": digest(reports / "parsed-inputs.json") == freeze["parsed_inputs_sha256"],
        "evaluation_manifest": digest(reports / "frozen-evaluation/manifest.json")
        == freeze["evaluation_manifest_sha256"],
        "training_manifest": digest(ROOT / "fixtures/model-training/manifest.json")
        == freeze["training_manifest_sha256"],
        "annotations": digest(ROOT / "fixtures/model-training/annotations.jsonl")
        == freeze["annotations_sha256"],
    }
    checks.update(
        {
            f"profile:{name}": digest(reports / "profiles" / f"{name}.json") == value
            for name, value in freeze["profile_sha256"].items()
        }
    )
    entries, _ = load_manifest(reports / "frozen-evaluation/manifest.json")
    checks.update(
        {
            f"document:{entry.id}": digest(resolve_document(reports / "frozen-evaluation", entry.path))
            == freeze["source_documents"][entry.id]
            for entry in entries
        }
    )
    if not all(checks.values()):
        raise ValueError(
            f"frozen evaluation contract changed: {[name for name, valid in checks.items() if not valid]}"
        )


def summarize(reports: Path) -> dict:
    freeze = json.loads((reports / "freeze.json").read_text())
    entries, _ = load_manifest(reports / "frozen-evaluation/manifest.json")
    expected = {entry.id: entry.expected for entry in entries}
    parsed = json.loads((reports / "parsed-inputs.json").read_text())["documents"]
    rows: list[dict[str, Any]] = []
    for stage in (
        "untuned",
        "adapted",
        "batched",
        "quantized",
        "adapted-batched",
        "adapted-quantized",
        "stronger",
    ):
        path = reports / stage / "serving_benchmark.json"
        if not path.exists():
            rows.append({"profile": stage, "status": "unexecuted"})
            continue
        data = json.loads(path.read_text())
        cases = [
            {
                "id": outcome["case"],
                "supplier": outcome.get("supplier"),
                "template": outcome.get("template"),
                "metrics": score_model_proposals(
                    outcome, expected[outcome["case"]], parsed[outcome["case"]]["pages"]
                ),
            }
            for outcome in data["raw_request_outcomes"]
        ]
        count_keys = (
            "expected_parts",
            "predicted_parts",
            "matched_parts",
            "expected_relationships",
            "predicted_relationships",
            "matched_relationships",
            "expected_exceptions",
            "matched_exceptions",
            "critical_omissions",
            "unsupported_assertions",
            "expected_review_required",
            "review_required_found",
        )

        def total_metrics(group: list[dict[str, Any]]) -> dict[str, Any]:
            totals = {key: sum(case["metrics"][key] for case in group) for key in count_keys}
            return {
                **totals,
                "affected_part_recall": ratio(totals["matched_parts"], totals["expected_parts"]),
                "exact_part_date_relationship_accuracy": ratio(
                    totals["matched_relationships"],
                    totals["expected_relationships"]
                    + totals["predicted_relationships"]
                    - totals["matched_relationships"],
                ),
                "review_required_coverage": ratio(
                    totals["review_required_found"], totals["expected_review_required"]
                ),
            }

        quality = {
            "purpose": "Post-execution scoring from preserved outputs; no new generation or tuning",
            "scope": "Accepted part/date/exception proposals only. Critical omissions combine missing parts, relationships and annotated exceptions; revision and source-completeness handling stay in the deterministic baseline.",
            "metrics": total_metrics(cases),
            "by_supplier": {
                supplier: total_metrics([case for case in cases if case["supplier"] == supplier])
                for supplier in sorted({case["supplier"] or "unknown" for case in cases})
            },
            "by_template": {
                template: total_metrics([case for case in cases if case["template"] == template])
                for template in sorted({case["template"] or "unknown" for case in cases})
            },
            "cases": cases,
        }
        write_json(reports / stage / "proposal_quality.json", quality)
        outcomes = data["raw_request_outcomes"]
        elapsed = data.get("elapsed_seconds")
        throughput = {
            "counts_include_failed_requests": True,
            "all_completed_requests": len(outcomes),
            "schema_valid_requests": sum(bool(row.get("raw_schema_valid")) for row in outcomes),
            "requests_with_accepted_candidates": sum(
                bool(row.get("result", {}).get("candidates")) for row in outcomes
            ),
            "matched_supported_relationships": data.get("relationship_metrics", {}).get(
                "matched_relationships", 0
            ),
        }
        throughput["per_second"] = {
            key: value / elapsed if elapsed else None
            for key, value in throughput.items()
            if key != "counts_include_failed_requests"
        }
        rows.append(
            {
                "profile": stage,
                **{
                    key: data.get(key)
                    for key in (
                        "status",
                        "precision",
                        "model_load_seconds",
                        "elapsed_seconds",
                        "p95_latency_seconds",
                        "requests_per_second",
                        "errors",
                        "relationship_metrics",
                        "output_validation",
                        "hardware",
                        "parsed_inputs_sha256",
                        "optimization",
                    )
                },
                "proposal_quality": quality["metrics"],
                "throughput": throughput,
            }
        )
    training_path = reports / "adapter/checkpoint_manifest.json"
    training = json.loads(training_path.read_text()) if training_path.exists() else {"status": "unexecuted"}
    baseline_path = reports / "rules-baseline/evaluation.json"
    baseline: dict[str, Any] = (
        json.loads(baseline_path.read_text()) if baseline_path.exists() else {"status": "unexecuted"}
    )
    validations = {
        stage: json.loads((reports / f"{stage}.json").read_text())
        if (reports / f"{stage}.json").exists()
        else {"status": "unexecuted"}
        for stage in ("validation-base", "validation-adapted")
    }
    frozen_inputs_equal = all(
        row.get("parsed_inputs_sha256") == freeze["parsed_inputs_sha256"]
        for row in rows
        if row["status"] == "executed"
    )
    summary = {
        "purpose": "Real pretrained inference and LoRA execution on OWNED SYNTHETIC material; no authentic manufacturer validation or engineer study",
        "freeze": freeze,
        "all_executed_models_used_identical_frozen_parsed_inputs": frozen_inputs_equal,
        "rules_baseline": {
            key: baseline.get(key)
            for key in ("purpose", "metrics", "benchmark", "by_supplier", "by_template")
        },
        "comparisons": rows,
        "training": {
            key: training.get(key)
            for key in (
                "status",
                "model_id",
                "revision",
                "training_material",
                "optimizer_steps",
                "training_seconds",
                "adapter_weights_changed",
                "trainable_parameters",
                "losses",
                "hardware",
            )
        },
        "teacher_forced_validation": validations,
        "inference_profile_decision": "Do not deploy model proposals without evidence review. Fine-tuning/optimization earns deployment only if measured supported relationship coverage improves with no new critical errors.",
        "unexecuted": [
            "CUDA/QLoRA: NVIDIA driver/device unavailable",
            "authorized real manufacturer supplier/template/family held-out evaluation",
            "component-engineer review-time study",
            "paid external prompted provider (no credentials/spend authorized); larger local model comparator used",
        ],
        "external_spend": 0,
        "energy_cost": "not measured",
        "training_and_serving_costs_separate": True,
    }
    write_json(reports / "comparison.json", summary)
    lines = [
        "NoticeForge real model verification — synthetic material",
        "",
        "Profile | Status | Matched/expected relationships | Schema-valid requests | p95 seconds | Peak RSS MiB",
        "--- | --- | --- | --- | --- | ---",
    ]
    for row in rows:
        metrics = row.get("relationship_metrics") or {}
        validation = row.get("output_validation") or {}
        hardware = row.get("hardware") or {}
        latency = row.get("p95_latency_seconds")
        latency_label = f"{latency:.3f}" if latency is not None else "n/a"
        lines.append(
            f"{row['profile']} | {row['status']} | {metrics.get('matched_relationships', 'n/a')}/{metrics.get('expected_relationships', 'n/a')} | {validation.get('schema_valid_requests', 'n/a')}/{len(entries) * freeze['repetitions']} | {latency_label} | {hardware.get('process_peak_rss_bytes', 0) / 1048576:.1f}"
        )
    if baseline.get("metrics"):
        metrics = baseline["metrics"]
        lines.extend(
            [
                "",
                f"Rules baseline: {metrics['matched_relationships']}/{metrics['expected_relationships']} exact supported tuples; {metrics['matched_parts']}/{metrics['expected_parts']} affected parts; {metrics['critical_omissions']} critical omissions and {metrics['unsupported_assertions']} unsupported assertions.",
            ]
        )
    lines.extend(
        [
            "",
            "One measured request for each of 8 short synthetic documents, 1 excluded warmup, concurrency 1, 4 CPU threads on a shared host. Nearest-rank p95 is the maximum here; batch-size-2 profiles measure batch completion, not independent single-request latency.",
            "RSS is the process lifetime peak including weight loading and INT8 conversion, not steady serving memory. The larger model uses BF16; compact comparisons use FP32 or real dynamic INT8.",
            "Raw model strings, token counts, schema/evidence failures and per-request omissions remain in each profile's serving_benchmark.json and request_outcomes.jsonl.",
            "proposal_quality.json adds part recall, exception scope, evidence localization, review coverage and per-supplier/template outcomes from those preserved strings.",
            "All-request throughput includes errors; comparison.json separately records schema-valid and evidence-accepted throughput.",
            "Wrong relationship counts on invalid-schema outputs are unknown, never assumed zero. Accepted candidates still require review.",
            "The frozen parsed input digest must match across all variants. GPU, authentic supplier validation and engineer-time gains remain unperformed.",
        ]
    )
    (reports / "comparison.txt").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "summary": str(reports / "comparison.json"),
                "profiles": [{"profile": row["profile"], "status": row["status"]} for row in rows],
            }
        ),
        flush=True,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    stages = [
        "all",
        "prepare",
        "baseline",
        "train",
        "validation-base",
        "validation-adapted",
        "untuned",
        "adapted",
        "batched",
        "quantized",
        "adapted-batched",
        "adapted-quantized",
        "stronger",
        "summarize",
    ]
    parser.add_argument("stage", choices=stages)
    parser.add_argument("--model-root", type=Path, default=Path("/tmp/noticeforge-models"))
    parser.add_argument("--reports", type=Path, default=ROOT / "reports/model-verification")
    args = parser.parse_args()
    args.reports = args.reports.resolve()
    args.model_root = args.model_root.resolve()
    args.reports.mkdir(parents=True, exist_ok=True)
    if args.stage == "prepare":
        prepare(args.model_root, args.reports)
        return
    if args.stage == "all":
        for stage in [
            "prepare",
            "baseline",
            "train",
            "validation-base",
            "validation-adapted",
            "untuned",
            "adapted",
            "batched",
            "quantized",
            "adapted-batched",
            "adapted-quantized",
            "stronger",
            "summarize",
        ]:
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    stage,
                    "--model-root",
                    str(args.model_root),
                    "--reports",
                    str(args.reports),
                ],
                check=True,
                cwd=ROOT,
            )
        return
    verify_freeze(args.reports)
    if args.stage == "baseline":
        run_evaluation(
            args.reports / "rules-baseline",
            args.reports / "frozen-evaluation/manifest.json",
            repetitions=10,
            warmup=2,
        )
    elif args.stage == "train":
        train_compact(
            args.reports / "profiles/training.json",
            ROOT / "fixtures/model-training/manifest.json",
            ROOT / "fixtures/model-training/annotations.jsonl",
            args.reports / "adapter",
        )
    elif args.stage in {"validation-base", "validation-adapted"}:
        validation_loss(
            args.reports / "profiles/training.json",
            ROOT / "fixtures/model-training/manifest.json",
            ROOT / "fixtures/model-training/annotations.jsonl",
            args.reports / (args.stage + ".json"),
            adapter_path=args.reports / "adapter" if args.stage == "validation-adapted" else None,
        )
    elif args.stage == "summarize":
        summarize(args.reports)
    else:
        output = args.reports / args.stage
        if (output / "serving_benchmark.json").exists():
            raise ValueError("preserve executed benchmarks; choose a fresh report directory for another run")
        run_provider_benchmark(
            args.reports / "profiles" / f"{args.stage}.json",
            args.reports / "frozen-evaluation/manifest.json",
            output,
            batch_size=2 if "batched" in args.stage else 1,
            concurrency=1,
            warmup=1,
            repetitions=1,
            parsed_inputs_path=args.reports / "parsed-inputs.json",
        )


if __name__ == "__main__":
    main()
