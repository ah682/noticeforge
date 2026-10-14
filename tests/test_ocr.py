"""OCR layout/failure contracts plus explicitly enabled real-engine integration.

Run the real checks with Tesseract on PATH and NOTICEFORGE_TEST_REAL_OCR=1.
Accuracy measurements across all owned scans live in scripts/verify_ocr.py.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pymupdf
import pytest

from noticeforge import ingest
from noticeforge.exporters import ExportError, export_smartpcn
from noticeforge.pipeline import compile_notice

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def tsv_row(text, x=10, y=20, width=30, height=10, line=1, word=1):
    return f"5\t1\t1\t1\t{line}\t{word}\t{x}\t{y}\t{width}\t{height}\t70\t{text}\n"


def blank_pdf(width=612, height=792):
    with pymupdf.open() as pdf:
        pdf.new_page(width=width, height=height)
        return pdf.tobytes()


def fake_engine(monkeypatch, output):
    monkeypatch.setattr(ingest.shutil, "which", lambda _name: "/local/tesseract")

    def run(_command, **options):
        options["stdout"].write(output)

    monkeypatch.setattr(ingest.subprocess, "run", run)


def test_ocr_keeps_zero_letter_suffix_and_leading_zero_differences_literal():
    tokens = ["0010-TR", "010-TR", "OO10-TR", "0010-T", "AO10-L", "A010-L"]
    tsv = HEADER + "".join(
        tsv_row(token, line=index + 1, y=20 + index * 20) for index, token in enumerate(tokens)
    )
    lines = ingest._ocr_lines(tsv, 2, 612, 792)
    assert [text for text, _box in lines] == tokens
    assert lines[0][1] == (5, 10, 20, 15)
    assert len(set(text for text, _box in lines)) == 6


def test_ocr_wide_gaps_preserve_table_columns_without_repairing_recognition():
    tsv = HEADER + tsv_row("Group", width=45) + tsv_row("Part", x=140, word=2)
    tsv += tsv_row("number", x=175, width=50, word=3) + tsv_row("Last", x=310, word=4)
    tsv += tsv_row("buy", x=345, word=5)
    tsv += tsv_row("Analog", x=10, width=50, line=2) + tsv_row("‘AMP-230-8", x=140, width=80, line=2, word=2)
    tsv += tsv_row("2027-02-15", x=310, width=90, line=2, word=3)
    lines = ingest._ocr_lines(tsv, 1, 612, 792)
    assert lines[0][0] == "Group\tPart number\tLast buy"
    assert lines[1][0] == "Analog\t‘AMP-230-8\t2027-02-15"


def test_single_footer_gap_is_not_invented_as_table_layout():
    lines = ingest._ocr_lines(HEADER + tsv_row("Owned") + tsv_row("Page", x=400, word=2), 1, 612, 792)
    assert lines[0][0] == "Owned Page"


@pytest.mark.parametrize(
    "tsv",
    [
        "not a TSV",
        HEADER + tsv_row("Bad", x=-1),
        HEADER + tsv_row("Bad", x=1000),
        HEADER + tsv_row("Bad").replace("\t20\t", "\tinvalid\t"),
    ],
)
def test_malformed_ocr_output_is_a_readable_input_error(tsv):
    with pytest.raises(ingest.InputError, match="malformed"):
        ingest._ocr_lines(tsv, 1, 612, 792)


@pytest.mark.parametrize(
    "output,warning",
    [
        (b"\xff", "invalid UTF-8"),
        (b"broken TSV", "malformed"),
        (b"x" * (ingest.MAX_OCR_TSV_BYTES + 1), "output limit"),
    ],
)
def test_failed_ocr_is_incomplete_and_never_silently_empty(monkeypatch, output, warning):
    fake_engine(monkeypatch, output)
    document = ingest.extract_document(blank_pdf(), "scan.pdf")
    assert not document.complete
    assert document.pages[0].method == "unreadable"
    assert any(warning in message for message in document.warnings)


def test_subprocess_has_one_thread_timeout_and_bounded_image(monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "99")
    monkeypatch.setenv("OMP_THREAD_LIMIT", "99")
    monkeypatch.setattr(ingest.shutil, "which", lambda _name: "/local/tesseract")
    calls = []

    def run(command, **options):
        pixmap = pymupdf.Pixmap(command[1])
        assert pixmap.width * pixmap.height <= ingest.MAX_OCR_PIXELS
        assert options["env"]["OMP_NUM_THREADS"] == "1"
        assert options["env"]["OMP_THREAD_LIMIT"] == "1"
        assert options["timeout"] == 30
        assert options["check"] is True
        assert command[-5:] == ["-l", "eng", "--psm", "6", "tsv"]
        options["stdout"].write(HEADER.encode())
        calls.append(command)

    monkeypatch.setattr(ingest.subprocess, "run", run)
    document = ingest.extract_document(blank_pdf(20000, 20000), "large.pdf")
    assert calls
    assert not document.complete
    assert any("no readable text" in message for message in document.warnings)


def test_engine_timeout_becomes_coverage_warning(monkeypatch):
    monkeypatch.setattr(ingest.shutil, "which", lambda _name: "/local/tesseract")

    def timeout(command, **options):
        raise subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(ingest.subprocess, "run", timeout)
    document = ingest.extract_document(blank_pdf(), "timeout.pdf")
    assert not document.complete
    assert any("30-second page limit" in message for message in document.warnings)


def test_missing_engine_is_explicit(monkeypatch):
    monkeypatch.setattr(ingest.shutil, "which", lambda _name: None)
    document = ingest.extract_document(blank_pdf(), "scan.pdf")
    assert not document.complete
    assert any("Tesseract OCR is unavailable" in message for message in document.warnings)


def test_native_header_does_not_hide_substantial_unread_image():
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((50, 200), "Part number | Last buy\nHIDDEN-001 | 2027-01-01")
    image = page.get_pixmap().tobytes("png")
    source.close()
    with pymupdf.open() as mixed:
        page = mixed.new_page()
        page.insert_image(page.rect, stream=image)
        page.insert_text((50, 50), "Native covering header")
        record = compile_notice(mixed.tobytes(), "mixed.pdf")
    assert not record.document.complete
    assert any("not been OCR-verified" in message for message in record.document.warnings)
    assert record.parts == []
    with pytest.raises(ExportError):
        export_smartpcn(record)


@pytest.mark.skipif(
    os.getenv("NOTICEFORGE_TEST_REAL_OCR") != "1" or not shutil.which("tesseract"),
    reason="Explicit real Tesseract profile; use scripts/verify_ocr.py to provision and measure",
)
def test_real_owned_scan_recovers_distinct_relationships_with_review_and_located_evidence():
    path = Path(__file__).resolve().parents[1] / "fixtures/development/aster-site-transfer.pdf"
    with pymupdf.open(path) as original, pymupdf.open() as scan:
        source = original[0]
        target = scan.new_page(width=source.rect.width, height=source.rect.height)
        target.insert_image(target.rect, stream=source.get_pixmap(dpi=300).tobytes("png"))
        record = compile_notice(scan.tobytes(garbage=4, deflate=True), "real-owned-scan.pdf")
        assert {(part.raw_identifier.value, date.value) for part in record.parts for date in part.dates} == {
            ("AMP-230-A", "2027-01-15"),
            ("AMP-230-B", "2027-02-15"),
        }
        assert record.status == "review_required"
        for part in record.parts:
            for value in [part.raw_identifier, *part.dates]:
                assert value.review_status == "review_required"
                evidence = value.evidence[0]
                page = record.document.pages[evidence.page - 1]
                assert page.text[evidence.start : evidence.end] == evidence.quote
                assert evidence.method == "ocr"
                assert evidence.bbox is not None
                assert any(
                    pymupdf.Rect(evidence.bbox).intersects(box) for box in source.search_for(evidence.quote)
                )
    with pytest.raises(ExportError, match="review"):
        export_smartpcn(record)
