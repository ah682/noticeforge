"""Measure real local PDF/text parsing with raw outcomes, separately from models."""

import json
import platform
import resource
import time
from importlib.metadata import version
from pathlib import Path

from noticeforge.evaluation import percentile
from noticeforge.pipeline import compile_notice

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "fixtures/development/manifest.json").read_text())
    outcomes = []
    for entry in manifest["documents"]:
        path = ROOT / "fixtures/development" / entry["path"]
        data = path.read_bytes()
        for _ in range(2):
            compile_notice(data, path.name)
        for iteration in range(10):
            start = time.perf_counter()
            try:
                record = compile_notice(data, path.name)
                result = {
                    "outcome": "success",
                    "parts": len(record.parts),
                    "status": record.status,
                    "characters": sum(len(p.text) for p in record.document.pages),
                    "pages": len(record.document.pages),
                    "sha256": record.document.sha256,
                }
            except Exception as exc:
                result = {"outcome": "error", "error": type(exc).__name__}
            outcomes.append(
                {
                    "filename": path.name,
                    "bytes": len(data),
                    "iteration": iteration,
                    "seconds": time.perf_counter() - start,
                    **result,
                }
            )
    by_format = {
        extension: {"requests": len(rows), "p95_seconds": percentile([r["seconds"] for r in rows])}
        for extension in ("pdf", "txt")
        if (rows := [r for r in outcomes if r["filename"].endswith("." + extension)])
    }
    report = {
        "purpose": "Owned developmental fixtures; PDF and text pipeline timings, not real supplier accuracy",
        "hardware": {
            "platform": platform.platform(),
            "cpu": next(
                (
                    line.split(":", 1)[1].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")
                ),
                platform.processor(),
            ),
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        },
        "runtime_versions": {name: version(name) for name in ["pymupdf", "pydantic", "fastapi", "lxml"]},
        "workload": {
            "concurrency": 1,
            "warmup_per_document": 2,
            "repetitions_per_document": 10,
            "documents": len(manifest["documents"]),
        },
        "by_format": by_format,
        "raw_outcomes": outcomes,
        "cost": {
            "external_spend": 0,
            "energy_cost": "not measured",
            "currency": None,
            "utilization": "Serial run on a shared host; no dedicated-capacity cost claim",
        },
    }
    (ROOT / "reports/pipeline-benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"by_format": by_format, "hardware": report["hardware"]}, indent=2))


if __name__ == "__main__":
    main()
