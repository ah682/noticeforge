"""Run real, local Tesseract against owned rasterized development fixtures.

No supplier files, final-test data, OCR mocks, or recognition repairs are used for
the accuracy measurements. Optional bootstrap extracts official Ubuntu packages
into a caller-selected directory; it never installs system packages.
"""

import argparse
import hashlib
import io
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pymupdf
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from noticeforge import ingest  # noqa: E402
from noticeforge.exporters import ExportError, export_json, export_smartpcn  # noqa: E402
from noticeforge.pipeline import compile_notice  # noqa: E402

PACKAGES = [
    (
        "tesseract-ocr",
        "5.3.4-1build5",
        "universe/t/tesseract/tesseract-ocr_5.3.4-1build5_amd64.deb",
        "2dfac382d77215aee0c3de4a2a2205505d5f2195e72e79b54ad32154fc08da77",
    ),
    (
        "libtesseract5",
        "5.3.4-1build5",
        "universe/t/tesseract/libtesseract5_5.3.4-1build5_amd64.deb",
        "a38438115dc203b5abc1e6a6b24eb5273ba82161a11faa2f619bf5f7622efb14",
    ),
    (
        "tesseract-ocr-eng",
        "4.1.0-2",
        "universe/t/tesseract-lang/tesseract-ocr-eng_4.1.0-2_all.deb",
        "b1996b3113c78663f4dd16cf18aa1f288b07e9624f8d4a0ddbd7d9b52a234ba7",
    ),
    (
        "tesseract-ocr-osd",
        "4.1.0-2",
        "universe/t/tesseract-lang/tesseract-ocr-osd_4.1.0-2_all.deb",
        "a266496b3268134493808c1595c9d16ac92c7e1c28e3e0bf46fdb322df95ca68",
    ),
    (
        "liblept5",
        "1.82.0-3build4",
        "universe/l/leptonlib/liblept5_1.82.0-3build4_amd64.deb",
        "c2bb81d58f032b09917c0d50994cce905287a1596304a4e99681a03601456ea8",
    ),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bootstrap(directory):
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("This optional package bootstrap supports Ubuntu-compatible Linux x86_64 only")
    for command in ("curl", "dpkg-deb"):
        if not shutil.which(command):
            raise SystemExit(f"Bootstrap requires {command}; no system changes are performed")
    cache, target = directory / "debs", directory / "root"
    cache.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, version, archive, sha256 in PACKAGES:
        path = cache / f"{name}.deb"
        url = f"https://archive.ubuntu.com/ubuntu/pool/{archive}"
        if not path.exists():
            pending = path.with_suffix(".part")
            subprocess.run(
                ["curl", "-fL", "--connect-timeout", "15", "--max-time", "120", url, "-o", str(pending)],
                check=True,
            )
            if digest(pending) != sha256:
                raise SystemExit(f"Publisher package hash mismatch: {name}")
            pending.replace(path)
        if digest(path) != sha256:
            raise SystemExit(f"Cached package hash mismatch: {name}")
        subprocess.run(["dpkg-deb", "--extract", str(path), str(target)], check=True, timeout=30)
        manifest.append({"package": name, "version": version, "source": url, "sha256": sha256})
    os.environ["PATH"] = str(target / "usr/bin") + os.pathsep + os.environ.get("PATH", "")
    library = str(target / "usr/lib/x86_64-linux-gnu")
    prior_library_path = os.environ.get("LD_LIBRARY_PATH")
    os.environ["LD_LIBRARY_PATH"] = library + (os.pathsep + prior_library_path if prior_library_path else "")
    os.environ["TESSDATA_PREFIX"] = str(target / "usr/share/tesseract-ocr/5/tessdata")
    return manifest


def owned_labelled_source():
    """Independent authored source; explicit distinctions are intentionally retained."""
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(612, 792), invariant=1)
    lines = [
        "OWNED SYNTHETIC OCR VERIFICATION - CC0",
        "Notice ID: OCR-CHECK-2026",
        "Supplier: Owned OCR Components",
        "Notice type: PDN",
        "Title: Literal identifiers",
        "Issue date: 2026-10-01",
        "Revision: A",
    ]
    parts = ["0010-TR", "010-TR", "OO10-TR", "0010-T", "AO10-L", "A010-L"]
    lines += [f"Part: {part}; Last buy: 2027-07-31" for part in parts]
    lines += ["Page 1 of 1"]
    pdf.setFont("Courier", 12)
    for index, line in enumerate(lines):
        pdf.drawString(40, 750 - index * 28, line)
    pdf.save()
    return output.getvalue(), [(part, "last_buy", "2027-07-31", "exact") for part in parts]


def rasterize(source, dpi, mixed=False, first_only=False):
    result = pymupdf.open()
    with pymupdf.open(stream=source, filetype="pdf") as original:
        for page in original:
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            target = result.new_page(width=page.rect.width, height=page.rect.height)
            target.insert_image(target.rect, stream=pixmap.tobytes("png"))
            if mixed:
                target.insert_text((12, 12), "OWNED MIXED-CONTENT QA HEADER", fontsize=7)
            if first_only:
                break
        data = result.tobytes(garbage=4, deflate=True, no_new_id=True)
    result.close()
    return data


def build_cases(output):
    cases = []
    site = (ROOT / "fixtures/development/aster-site-transfer.pdf").read_bytes()
    pdn = (ROOT / "fixtures/development/aster-discontinuation.pdf").read_bytes()
    site_gold = [
        ("AMP-230-A", "effective_change", "2027-01-15", "exact"),
        ("AMP-230-B", "effective_change", "2027-02-15", "exact"),
    ]
    pdn_gold = []
    rows = [
        ("00128-Q1", "2027-03-31", "2027-09-30", "2027-08-31"),
        ("00128-Q2", "2027-03-31", "2027-09-30", "2027-08-31"),
        ("NX-4100-A", "2027-06-30", "2027-12-15", "2027-11-30"),
        ("NX-4100-B", "2027-07-15", "2027-12-15", "2027-11-30"),
        ("AO10-L", "2027-04-30", "2027-10-31", "2027-09-30"),
        ("A010-L", "2027-04-30", "2027-10-31", "2027-09-30"),
    ]
    for part, last_buy, delivery, production in rows:
        pdn_gold += [
            (part, "last_buy", last_buy, "inventory_limited" if part == "00128-Q2" else "exact"),
            (part, "last_delivery", delivery, "exact"),
            (part, "end_of_production", production, "exact"),
        ]
    for name, original, gold, family in [
        ("site-transfer", site, site_gold, "aster-052"),
        ("discontinuation", pdn, pdn_gold, "aster-041"),
    ]:
        for dpi in (300, 144):
            cases.append(
                {
                    "id": f"{name}-{dpi}dpi",
                    "source": original,
                    "dpi": dpi,
                    "gold": gold,
                    "family": family,
                    "kind": "image_only",
                    "data": rasterize(original, dpi),
                }
            )
    labelled, labels_gold = owned_labelled_source()
    cases.append(
        {
            "id": "literal-identifiers-300dpi",
            "source": labelled,
            "dpi": 300,
            "gold": labels_gold,
            "family": "ocr-literal-owned",
            "kind": "image_only",
            "data": rasterize(labelled, 300),
        }
    )
    cases.append(
        {
            "id": "mixed-native-image",
            "source": site,
            "dpi": 300,
            "gold": site_gold,
            "family": "aster-052",
            "kind": "mixed_incomplete",
            "data": rasterize(site, 300, mixed=True),
        }
    )
    missing = pymupdf.open()
    for number in (1, 2):
        page = missing.new_page()
        page.insert_text((40, 80), f"OWNED COVERAGE CHECK\nPage {number} of 2", fontsize=16)
    data = missing.tobytes(no_new_id=True)
    missing.close()
    cases.append(
        {
            "id": "missing-page-scan",
            "source": data,
            "dpi": 300,
            "gold": [],
            "family": "ocr-missing-owned",
            "kind": "missing_incomplete",
            "data": rasterize(data, 300, first_only=True),
        }
    )
    blank = pymupdf.open()
    blank.new_page(width=20000, height=20000)
    blank_data = blank.tobytes(no_new_id=True)
    blank.close()
    cases.append(
        {
            "id": "large-blank-page",
            "source": blank_data,
            "dpi": None,
            "gold": [],
            "family": "ocr-blank-owned",
            "kind": "blank_incomplete",
            "data": blank_data,
        }
    )
    for case in cases:
        (output / f"{case['id']}.pdf").write_bytes(case["data"])
        (output / f"{case['id']}-source.pdf").write_bytes(case["source"])
    return cases


def critical_fields(value):
    if isinstance(value, dict):
        if "review_status" in value and "value" in value:
            yield value
        for child in value.values():
            yield from critical_fields(child)
    elif isinstance(value, list):
        for child in value:
            yield from critical_fields(child)


def evidence_metrics(record, source):
    checks = {
        "total_evidence": 0,
        "offset_quote_correct": 0,
        "bbox_in_page": 0,
        "original_geometry_comparable": 0,
        "original_geometry_intersects": 0,
        "original_text_not_found": 0,
        "original_geometry_mismatches": [],
    }
    with pymupdf.open(stream=source, filetype="pdf") as original:
        for field in critical_fields(record.model_dump(mode="json")):
            for evidence in field["evidence"]:
                checks["total_evidence"] += 1
                page = record.document.pages[evidence["page"] - 1]
                quote, box = evidence["quote"], evidence["bbox"]
                checks["offset_quote_correct"] += page.text[evidence["start"] : evidence["end"]] == quote
                checks["bbox_in_page"] += bool(
                    box and 0 <= box[0] <= box[2] <= page.width and 0 <= box[1] <= box[3] <= page.height
                )
                locations = original[evidence["page"] - 1].search_for(quote)
                if locations:
                    checks["original_geometry_comparable"] += 1
                    intersects = bool(
                        box and any(pymupdf.Rect(box).intersects(location) for location in locations)
                    )
                    checks["original_geometry_intersects"] += intersects
                    if not intersects:
                        checks["original_geometry_mismatches"].append(
                            {"quote": quote, "bbox": box, "page": evidence["page"]}
                        )
                else:
                    checks["original_text_not_found"] += 1
    return checks


def score(case, record):
    gold = Counter(tuple(item) for item in case["gold"])
    actual = Counter(
        (part.raw_identifier.value, deadline.kind, deadline.value, deadline.qualifier)
        for part in record.parts
        for deadline in part.dates
    )
    expected_parts = Counter({item[0]: 1 for item in gold})
    actual_parts = Counter(part.raw_identifier.value for part in record.parts)
    fields = [
        item
        for item in critical_fields(record.model_dump(mode="json"))
        if item["value"] is not None and any(ev["method"] == "ocr" for ev in item["evidence"])
    ]
    return {
        "expected_identifiers": list(expected_parts.elements()),
        "observed_identifiers": list(actual_parts.elements()),
        "expected_relationships": list(gold.elements()),
        "record_count": len(record.parts),
        "unique_record_ids": len({part.id for part in record.parts}),
        "duplicate_observed_identifiers": [
            identifier for identifier, count in actual_parts.items() if count > 1
        ],
        "literal_identity_preserved": all(
            part.raw_identifier.raw == part.raw_identifier.value
            and part.normalized_identifier == (part.raw_identifier.value or "").strip()
            for part in record.parts
        ),
        "part_recall": {
            "correct": sum((expected_parts & actual_parts).values()),
            "total": sum(expected_parts.values()),
        },
        "part_omissions": list((expected_parts - actual_parts).elements()),
        "unexpected_identifier_candidates": list((actual_parts - expected_parts).elements()),
        "relationship_exact": {"correct": sum((gold & actual).values()), "total": sum(gold.values())},
        "missing_or_wrong_relationships": list((gold - actual).elements()),
        "incorrect_relationship_candidates": list((actual - gold).elements()),
        "observed_relationships": list(actual.elements()),
        "ocr_review_coverage": {
            "review_required": sum(field["review_status"] == "review_required" for field in fields),
            "total": len(fields),
        },
        "evidence": evidence_metrics(record, case["source"]),
    }


def preview(case, record, output):
    if case["kind"] == "blank_incomplete":
        return
    with pymupdf.open(stream=case["data"], filetype="pdf") as pdf:
        page = pdf[0]
        for part in record.parts[:2]:
            for value in [part.raw_identifier, *part.dates[:1]]:
                for evidence in value.evidence:
                    if evidence.page == 1 and evidence.bbox:
                        page.draw_rect(evidence.bbox, color=(1, 0, 0), width=0.8)
        page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(
            output / f"{case['id']}-evidence.png"
        )


def sample_engine_resources(engine, case):
    """Sample the post-exec Tesseract process, excluding parent/fork RSS.

    This is a separate real invocation on one owned page, not a hard memory quota
    or a guaranteed peak. The full-pipeline latencies above do not include it.
    """
    samples = []
    with tempfile.TemporaryDirectory(prefix="noticeforge-ocr-resource-") as directory:
        path = Path(directory) / "page.png"
        with pymupdf.open(stream=case["data"], filetype="pdf") as pdf:
            pdf[0].get_pixmap(dpi=300, alpha=False).save(path)
        env = {**os.environ, "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"}
        with (Path(directory) / "words.tsv").open("wb") as stdout:
            start = time.perf_counter()
            process = subprocess.Popen(
                [engine, str(path), "stdout", "-l", "eng", "--psm", "6", "tsv"],
                stdout=stdout,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            try:
                while process.poll() is None:
                    if time.perf_counter() - start > ingest.OCR_TIMEOUT_SECONDS:
                        raise RuntimeError("Resource probe engine exceeded the page timeout")
                    proc = Path(f"/proc/{process.pid}")
                    try:
                        if (proc / "comm").read_text().strip() == "tesseract":
                            status = dict(
                                line.split(":", 1)
                                for line in (proc / "status").read_text().splitlines()
                                if ":" in line
                            )
                            if "VmRSS" in status:
                                samples.append((int(status["VmRSS"].split()[0]), int(status["Threads"])))
                    except (FileNotFoundError, ProcessLookupError):
                        pass
                    time.sleep(0.005)
                if process.returncode:
                    raise RuntimeError(f"Resource probe engine exited with status {process.returncode}")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
    return {
        "source_case": case["id"],
        "separate_actual_engine_invocation": True,
        "sample_interval_seconds": 0.005,
        "post_exec_samples": len(samples),
        "observed_peak_rss_kib": max((item[0] for item in samples), default=None),
        "observed_peak_threads": max((item[1] for item in samples), default=None),
        "elapsed_seconds": round(time.perf_counter() - start, 6),
        "limitation": "Sampled Linux /proc RSS/threads after exec; may miss brief peaks, not a memory ceiling",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", type=Path, help="Extract pinned Ubuntu binaries locally, without sudo")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/ocr")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 20:
        parser.error("--repetitions must be between 1 and 20")
    packages = bootstrap(args.bootstrap.resolve()) if args.bootstrap else []
    engine = shutil.which("tesseract")
    if not engine:
        raise SystemExit(
            "Actual Tesseract is required. Use --bootstrap /tmp/noticeforge-ocr on Ubuntu-compatible Linux."
        )
    version = subprocess.run(
        [engine, "--version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout
    args.output.mkdir(parents=True, exist_ok=True)
    cases = build_cases(args.output)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Owned synthetic development OCR verification; not held-out supplier evaluation",
        "annotation_provenance": "Manually transcribed identifiers/date types/qualifiers from owned source fixtures",
        "permission": "Owned synthetic fixtures, CC0-1.0; no supplier training or evaluation data",
        "engine": {
            "path": engine,
            "version_output": version,
            "packages": packages,
            "tessdata_prefix": os.environ.get("TESSDATA_PREFIX"),
        },
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "cpu": next(
                (
                    line.partition(":")[2].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")
                ),
                "unknown",
            ),
        },
        "configuration": {
            "dpi_target": ingest.OCR_DPI,
            "max_pixels": ingest.MAX_OCR_PIXELS,
            "threads": 1,
            "page_timeout_seconds": ingest.OCR_TIMEOUT_SECONDS,
            "max_tsv_read_bytes": ingest.MAX_OCR_TSV_BYTES,
            "page_segmentation_mode": 6,
            "language": "eng",
            "repetitions": args.repetitions,
            "warmup": 0,
            "concurrency": 1,
            "character_correction": False,
        },
        "cases": [],
        "limits": [
            "Development fixtures informed layout changes; these are not held-out scores.",
            "Clean PDF rasterizations do not represent skew, noise, handwriting, all fonts, or supplier scans.",
            "Table separation is a wide-gap heuristic for at least three columns; OCR has no general table parser.",
            "Mixed native/image pages remain incomplete; image regions are not merged automatically.",
            "The timeout bounds the engine subprocess; there is no hard process-RAM or disk quota here.",
            "RSS high-water values cover this script or child processes, not concurrent service memory.",
            "Evidence offset correctness is measured against OCR text; recognition errors can still be localized.",
            "Every OCR-derived critical value must be reviewed; confidence is not used as a probability.",
        ],
    }
    failures = []
    for case in cases:
        latencies = []
        for _ in range(args.repetitions):
            start = time.perf_counter()
            record = compile_notice(case["data"], f"{case['id']}.pdf")
            latencies.append(round(time.perf_counter() - start, 6))
        result = {
            "id": case["id"],
            "family": case["family"],
            "split": "development",
            "kind": case["kind"],
            "source_sha256": hashlib.sha256(case["source"]).hexdigest(),
            "scan_sha256": hashlib.sha256(case["data"]).hexdigest(),
            "transformation": (
                (
                    f"PyMuPDF rasterized at {case['dpi']}dpi; "
                    + (
                        "native header plus page image"
                        if case["kind"] == "mixed_incomplete"
                        else "images only"
                    )
                )
                if case["dpi"]
                else "Blank 20000-point square PDF"
            ),
            "status": record.status,
            "complete": record.document.complete,
            "warnings": record.document.warnings,
            "page_methods": [page.method for page in record.document.pages],
            "received_pages": len(record.document.pages),
            "expected_pages": record.document.expected_pages,
            "source_chars": sum(len(p.text) for p in record.document.pages),
            "latency_seconds": latencies,
            "median_seconds": statistics.median(latencies),
            "p95_seconds": sorted(latencies)[max(0, int(len(latencies) * 0.95 + 0.999) - 1)],
            **score(case, record),
        }
        try:
            export_smartpcn(record)
            result["xml_blocked"] = False
            failures.append(f"{case['id']}: unreviewed OCR or incomplete input exported")
        except ExportError as exc:
            result["xml_blocked"] = True
            result["xml_block_reason"] = str(exc)
        if case["kind"].endswith("incomplete") and record.document.complete:
            failures.append(f"{case['id']}: coverage loss was not flagged")
        review = result["ocr_review_coverage"]
        if review["review_required"] != review["total"]:
            failures.append(f"{case['id']}: OCR evidence was accepted without review")
        if not result["literal_identity_preserved"] or result["record_count"] != result["unique_record_ids"]:
            failures.append(f"{case['id']}: recognized identifiers were silently changed or records merged")
        evidence = result["evidence"]
        if (
            evidence["offset_quote_correct"] != evidence["total_evidence"]
            or evidence["bbox_in_page"] != evidence["total_evidence"]
        ):
            failures.append(f"{case['id']}: broken evidence offsets or coordinates")
        (args.output / f"{case['id']}.json").write_bytes(export_json(record))
        preview(case, record, args.output)
        report["cases"].append(result)
        print(
            f"{case['id']}: parts {result['part_recall']}, relationships {result['relationship_exact']}, {record.status}"
        )
    with patch.object(ingest, "OCR_TIMEOUT_SECONDS", 0.001):
        start = time.perf_counter()
        timed_out = ingest.extract_document(cases[0]["data"], "timeout.pdf")
        report["timeout_probe"] = {
            "injected_limit_seconds": 0.001,
            "elapsed_seconds": round(time.perf_counter() - start, 6),
            "complete": timed_out.complete,
            "warnings": timed_out.warnings,
            "actual_engine_invoked": True,
        }
        if timed_out.complete or not any("page limit" in item for item in timed_out.warnings):
            failures.append("Actual Tesseract timeout did not produce incomplete result")
    with patch.dict(os.environ, {"PATH": str(args.output / "no-engine-directory")}):
        unavailable = ingest.extract_document(cases[0]["data"], "unavailable.pdf")
        report["unavailable_probe"] = {"complete": unavailable.complete, "warnings": unavailable.warnings}
        if unavailable.complete:
            failures.append("Unavailable OCR engine did not produce incomplete result")
    report["resource_high_water_kib"] = {
        "script": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "child_processes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
    }
    report["isolated_engine_resource_probe"] = sample_engine_resources(engine, cases[0])
    if report["isolated_engine_resource_probe"]["observed_peak_threads"] not in {1, None}:
        failures.append("The configured one-thread engine probe ran with multiple threads")
    report["safety_failures"] = failures
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Actual local OCR verification",
        "",
        report["scope"] + ".",
        "",
        f"Executed: {report['created_at']}. Engine: {version.splitlines()[0]}. Repetitions: {args.repetitions}, concurrency: 1.",
        "",
        "| Owned input | Exact parts | Exact part/date/qualifier | Status | Median seconds |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in report["cases"]:
        parts, dates = result["part_recall"], result["relationship_exact"]
        lines.append(
            f"| {result['id']} | {parts['correct']}/{parts['total']} | {dates['correct']}/{dates['total']} | "
            f"{result['status']} | {result['median_seconds']:.3f} |"
        )
    lines += [
        "",
        "All raw outcomes, wrong candidates, missing relationships, evidence checks, engine package hashes, "
        "and resource observations are in [report.json](report.json). The `.json` files preserve complete canonical results; "
        "the evidence PNGs show line-level review regions.",
        "",
        "## Reproduce",
        "",
        "```sh",
        ".venv/bin/python scripts/verify_ocr.py --bootstrap /tmp/noticeforge-ocr --output reports/ocr --repetitions 3",
        "```",
        "",
        "The optional bootstrap verifies package hashes and extracts binaries/data locally; it requires an "
        "Ubuntu-compatible x86_64 runtime and does not run package maintainer scripts or change system packages.",
        "",
        "## Boundaries",
        "",
        *[f"- {item}" for item in report["limits"]],
        "",
        f"Safety failures in this run: {len(failures)}. Recognition errors are recorded separately and are not hidden by that count.",
        "",
    ]
    probe = report["isolated_engine_resource_probe"]
    lines += [
        "The fixture-generation process high-water values include image buffers and are not engine-only memory. "
        f"A separate actual Tesseract process was sampled {probe['post_exec_samples']} times after exec: "
        f"observed peak RSS {probe['observed_peak_rss_kib']} KiB and {probe['observed_peak_threads']} thread(s). "
        "Sampling every 5 ms can miss brief peaks; this is an observation, not a hard memory ceiling.",
        "",
    ]
    evidence_total = sum(result["evidence"]["total_evidence"] for result in report["cases"])
    comparable = sum(result["evidence"]["original_geometry_comparable"] for result in report["cases"])
    intersects = sum(result["evidence"]["original_geometry_intersects"] for result in report["cases"])
    reviews = sum(result["ocr_review_coverage"]["review_required"] for result in report["cases"])
    lines += [
        "## Evidence denominators",
        "",
        f"The {reviews} populated OCR-derived critical fields carry {evidence_total} evidence entries; "
        "some fields cite both a table cell and a footnote, and inherited metadata is cited on multiple parts. "
        "Offsets are checked against the retained OCR text and boxes against the received page bounds. "
        "These are internal localization checks, not proof that recognized characters are correct.",
        "",
        f"For comparison with the original native-text PDF, {comparable}/{evidence_total} OCR quotes occur "
        f"somewhere in that source, and {intersects}/{comparable} corresponding boxes intersect a native occurrence. "
        "Unrecognized source strings have no native comparison; substitutions such as O/0 and an invented colon "
        "can match a different native occurrence elsewhere. The report records those mismatches rather than "
        "counting them as successful source localization. None of these checks establish authentic scan performance.",
        "",
    ]
    (args.output / "README.md").write_text("\n".join(lines))
    if failures:
        raise SystemExit("Verification safety failures: " + "; ".join(failures))


if __name__ == "__main__":
    main()
