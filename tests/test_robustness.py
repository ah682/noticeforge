"""Owned adversarial notices: reject uncertainty rather than assert wrong relationships.

These cases are independent of the release fixtures. Unsupported layouts may be
refused or sent for review; the invariant is that omissions and wrong critical
relationships must not be returned as a complete, supported extraction.
"""

import json
import subprocess
import sys

import pymupdf
import pytest

from noticeforge.bom import match_bom
from noticeforge.exporters import export_smartpcn, validate_xml
from noticeforge.ingest import InputError
from noticeforge.models import BOMRow, CriticalValue, Evidence, ReviewRequest
from noticeforge.pipeline import compile_notice
from noticeforge.repository import ConflictError, Repository, ReviewError
from noticeforge.validation import validate_record


def source(body: str, *, notice_id="OWNED-1", supplier="Owned Devices", revision="A") -> bytes:
    return (
        f"Notice ID: {notice_id}\nSupplier: {supplier}\nNotice type: PDN\n"
        f"Title: Owned robustness fixture\nIssue date: 2026-10-01\nRevision: {revision}\n" + body
    ).encode()


def compile_body(body: str):
    return compile_notice(source(body), "owned-robustness.txt")


def part_map(record):
    return {part.raw_identifier.value: part for part in record.parts}


def deadline(record, identifier: str, kind="last_buy"):
    return [value.value for value in part_map(record)[identifier].dates if value.kind == kind]


def assert_review_or(record, correct: bool):
    assert correct or record.status in {"review_required", "incomplete"}, (
        "An unsupported or incorrect relationship was returned as supported",
        record.model_dump(),
    )


def test_ragged_affected_row_is_extracted_or_coverage_is_flagged():
    record = compile_body(
        "Part number | Last buy\nA1 | 2027-01-01\nB2 | 2027-02-01 | additional qualification note\n"
    )
    assert_review_or(record, "B2" in part_map(record))


def test_headerless_table_continuation_cannot_silently_drop_affected_parts():
    record = compile_body("Part number | Last buy\nA1 | 2027-01-01\fB2 | 2027-02-01\n")
    assert_review_or(record, "B2" in part_map(record))


def test_unrecognized_affected_table_cannot_hide_behind_a_supported_table():
    record = compile_body(
        "Affected product ordering codes\nOrdering code | Last buy\nB2 | 2027-02-01\n"
        "Part number | Last buy\nA1 | 2027-01-01\n"
    )
    assert_review_or(record, "B2" in part_map(record))


def test_conflicting_same_name_columns_cannot_choose_one_date_silently():
    record = compile_body("Part number | Last buy | Last buy\nA1 | 2027-01-01 | 2027-02-01\n")
    assert record.status in {"review_required", "incomplete"}


def test_footnote_with_two_deadlines_cannot_assign_first_date_to_wrong_kind():
    record = compile_body(
        "Part number | Last buy | Last delivery\n"
        "A1 | 2027-01-01[1] | 2027-12-31\n"
        "[1] Last buy: 2027-02-01; Last delivery: 2028-01-01\n"
    )
    correct = deadline(record, "A1") == ["2027-02-01"] and deadline(record, "A1", "last_delivery") == [
        "2028-01-01"
    ]
    assert_review_or(record, correct)


def test_reused_footnote_numbers_across_pages_do_not_cross_attach():
    record = compile_body(
        "Part number | Last buy\nA1 | 2027-01-01[1]\n"
        "[1] Last buy: 2027-02-01\f"
        "Part number | Last buy\nB2 | 2027-03-01[1]\n"
        "[1] Last buy: 2027-04-01\n"
    )
    correct = deadline(record, "A1") == ["2027-02-01"] and deadline(record, "B2") == ["2027-04-01"]
    assert_review_or(record, correct)


def test_explicit_part_scope_in_shared_row_footnote_is_not_ignored():
    record = compile_body(
        "Part number | Last buy\nA1, B2 | 2027-01-01[1]\n"
        "[1] Only A1: Last buy is 2027-02-01. B2 is unchanged.\n"
    )
    correct = deadline(record, "A1") == ["2027-02-01"] and deadline(record, "B2") == ["2027-01-01"]
    assert_review_or(record, correct)


def test_inventory_condition_in_exception_text_cannot_remain_an_unqualified_deadline():
    record = compile_body(
        "Part number | Last buy\nA1 | 2027-01-01\n"
        "Exception for A1: Ordering is only while inventory lasts; deadline not guaranteed.\n"
    )
    dates = part_map(record)["A1"].dates
    assert_review_or(record, any(d.qualifier == "inventory_limited" for d in dates))


def test_tentative_footnote_does_not_lose_qualifier_when_date_token_is_parsed():
    record = compile_body("Part number | Last buy\nA1 | 2027-01-01[1]\n[1] Last buy: tentative 2027-02-01\n")
    assert_review_or(record, any(d.qualifier == "tentative" for d in part_map(record)["A1"].dates))


def test_shared_footnote_with_distinct_part_deadlines_does_not_flatten_scope():
    record = compile_body(
        "Part number | Last buy\nA1, B2 | 2027-01-01[1]\n"
        "[1] A1 Last buy: 2027-02-01; B2 Last buy: 2027-03-01\n"
    )
    assert_review_or(
        record, deadline(record, "A1") == ["2027-02-01"] and deadline(record, "B2") == ["2027-03-01"]
    )


def test_explicit_global_deadline_conflicting_with_row_requires_review():
    record = compile_body(
        "Part number | Last buy\nA1 | 2027-01-01\nAll affected parts: Last buy: 2027-02-01\n"
    )
    assert record.status in {"review_required", "incomplete"}


def test_malformed_ambiguous_row_is_not_hidden_by_date_token_heuristic():
    record = compile_body("Part number | Last buy\nA1 | 2027-01-01\nB2 | TBD | needs review\n")
    assert_review_or(record, "B2" in part_map(record))


@pytest.mark.parametrize("field", ["raw_identifier", "manufacturer"])
def test_canonical_validation_requires_nonempty_part_identity_and_scope(field):
    record = compile_body("Part number | Last buy\nA1 | 2027-01-01\n")
    setattr(record.parts[0], field, CriticalValue())
    validate_record(record)
    assert record.status == "review_required"
    assert getattr(record.parts[0], field).review_status == "review_required"


def test_canonical_validation_cannot_count_an_empty_date_as_present():
    record = compile_body("Part number | Last buy\nA1 | 2027-01-01\n")
    value = record.parts[0].dates[0]
    value.value, value.raw, value.qualifier = None, None, "missing"
    validate_record(record)
    assert record.status == "review_required"
    assert value.review_status == "review_required"


def test_canonical_validation_enforces_ambiguous_date_review_independently():
    record = compile_body("Part number | Last buy\nA1 | 2027-01-01\n")
    record.parts[0].dates[0].qualifier = "ambiguous"
    validate_record(record)
    assert record.status == "review_required"
    assert record.parts[0].dates[0].review_status == "review_required"


def test_valid_offsets_do_not_prove_a_hallucinated_identifier():
    record = compile_body("Part number | Last buy\nA1 | 2027-01-01\n")
    record.parts[0].raw_identifier.value = "UNSUPPORTED-9"
    record.parts[0].raw_identifier.raw = "UNSUPPORTED-9"
    validate_record(record)
    assert record.status == "review_required"
    assert record.parts[0].raw_identifier.review_status == "review_required"


def test_auto_date_normalization_cannot_change_an_iso_date_to_another_year():
    record = compile_body("Part number | Last buy\nA1 | 2027-01-01\n")
    record.parts[0].dates[0].value = "2099-01-01"
    validate_record(record)
    assert record.status == "review_required"
    assert record.parts[0].dates[0].review_status == "review_required"


def test_canonical_validation_detects_undocumented_identifier_normalization():
    record = compile_body("Part number | Last buy\n0001-A | 2027-01-01\n")
    record.parts[0].normalized_identifier = "1-A"
    validate_record(record)
    assert record.status == "review_required"


def test_manufacturer_conflict_cannot_produce_a_definite_bom_match():
    record = compile_body("Supplier: Another Manufacturer\nPart number | Last buy\nA1 | 2027-01-01\n")
    result = match_bom(record, [BOMRow(part_number="A1", manufacturer="Owned Devices")])[0]
    assert result["status"] == "ambiguous"


def test_excluded_part_cannot_produce_an_unqualified_bom_match():
    record = compile_body("Part number | Last buy | Exclusions\nA1 | 2027-01-01 | A1\n")
    result = match_bom(record, [BOMRow(part_number="A1", manufacturer="Owned Devices")])[0]
    assert result["status"] != "literal_match"


def test_conditional_exclusion_needs_bom_review_when_bom_has_no_condition_data():
    record = compile_body(
        "Part number | Last buy | Exclusions\nA1 | 2027-01-01 | Customer-qualified lots are excluded\n"
    )
    result = match_bom(record, [BOMRow(part_number="A1", manufacturer="Owned Devices")])[0]
    assert result["status"] != "literal_match"


def test_common_compact_page_fraction_detects_missing_pages():
    record = compile_body("Part number | Last buy\nA1 | 2027-01-01\nPage 1/3\n")
    assert not record.document.complete
    assert record.status == "incomplete"


@pytest.mark.skipif(sys.platform == "win32", reason="The memory-limit probe uses POSIX resource limits")
@pytest.mark.parametrize("total", ["1000000000", "9" * 5000, "0"], ids=["huge", "long_digits", "zero"])
def test_invalid_printed_page_counts_are_bounded_coverage_warnings(total):
    probe = """
import json, resource, sys
from noticeforge.ingest import extract_document
resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
document = extract_document(sys.stdin.buffer.read(), "owned-page-count.txt")
print(json.dumps({"complete": document.complete, "warnings": document.warnings}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        input=f"Page 1 of {total}",
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert not document["complete"]
    assert any("Printed page count" in warning for warning in document["warnings"])


def test_mixed_pdf_text_and_raster_table_cannot_be_reported_complete_without_inspection(monkeypatch):
    # Owned source: native A1 row plus a raster B2 table on the same PDF page.
    with pymupdf.open() as raster:
        page = raster.new_page(width=400, height=80)
        page.insert_text((10, 20), "Part number | Last buy\nB2 | 2027-02-01")
        png = page.get_pixmap().tobytes("png")
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), source("Part number | Last buy\nA1 | 2027-01-01\n").decode())
        page.insert_image(pymupdf.Rect(72, 250, 472, 330), stream=png)
        binary = pdf.tobytes()

    def unavailable_ocr(_page):
        raise InputError("OCR unavailable in this bounded failure-path test")

    monkeypatch.setattr("noticeforge.ingest._ocr", unavailable_ocr)
    record = compile_notice(binary, "owned-mixed-page.pdf")
    assert_review_or(record, "B2" in part_map(record))


def ruled_table(page, y, header, rows):
    columns = [72, 260, 470]
    lines = [y + i * 30 for i in range(len(rows) + 2)]
    for x in columns:
        page.draw_line((x, lines[0]), (x, lines[-1]))
    for line in lines:
        page.draw_line((columns[0], line), (columns[-1], line))
    for row_index, row in enumerate([header, *rows]):
        for column_index, text in enumerate(row):
            page.insert_text((columns[column_index] + 5, y + 20 + row_index * 30), text)


def test_unrecognized_ruled_pdf_table_is_not_silently_dropped():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), source("").decode())
        ruled_table(page, 250, ["Ordering code", "Last buy"], [["B2", "2027-02-01"]])
        ruled_table(page, 400, ["Part number", "Last buy"], [["A1", "2027-01-01"]])
        record = compile_notice(pdf.tobytes(), "owned-two-tables.pdf")
    assert_review_or(record, "B2" in part_map(record))


def test_pdf_evidence_offsets_and_cell_region_refer_to_the_same_occurrence():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text(
            (72, 72), source("Reference 2027-01-01 is mentioned in this unrelated note.\n").decode()
        )
        ruled_table(page, 400, ["Part number", "Last buy"], [["A1", "2027-01-01"]])
        record = compile_notice(pdf.tobytes(), "owned-duplicate-date.pdf")
    date_field = record.parts[0].dates[0]
    consistent = True
    for evidence in date_field.evidence:
        page = next(p for p in record.document.pages if p.number == evidence.page)
        lines = [line for line in page.lines if line.start <= evidence.start < line.end]
        if evidence.bbox and lines:
            box = pymupdf.Rect(evidence.bbox)
            consistent = consistent and any(
                line.bbox and box.intersects(pymupdf.Rect(line.bbox)) for line in lines
            )
    assert_review_or(record, consistent)


def test_same_notice_number_revision_does_not_link_to_itself(tmp_path):
    repo = Repository(tmp_path)
    first = source("Part number | Last buy\nA1 | 2027-01-01\n", notice_id="SHARED", revision="A")
    second = source(
        "Part number | Last buy\nA1 | 2027-02-01\nSupersedes: SHARED; Parts: A1\n",
        notice_id="SHARED",
        revision="B",
    )
    old = repo.save(compile_notice(first, "old.txt"), first)
    new = repo.save(compile_notice(second, "new.txt"), second)
    history = repo.history(new.id)
    assert not any(link["source_id"] == new.id for link in history["incoming"])
    assert history["outgoing"][0]["target_id"] == old.id
    assert history["outgoing"][0]["resolved"] is True


def test_subset_scope_missing_from_target_cannot_be_reported_resolved(tmp_path):
    repo = Repository(tmp_path)
    first = source("Part number | Last buy\nA1 | 2027-01-01\n", notice_id="OLD")
    second = source(
        "Part number | Last buy\nB2 | 2027-02-01\nSupersedes: OLD; Parts: MISSING-X\n", notice_id="NEW"
    )
    old = repo.save(compile_notice(first, "old.txt"), first)
    repo.save(compile_notice(second, "new.txt"), second)
    assert repo.history(old.id)["incoming"][0]["resolved"] is False


def test_revision_targets_remain_supplier_scoped(tmp_path):
    repo = Repository(tmp_path)
    data_a = source("Part number | Last buy\nA1 | 2027-01-01\n", notice_id="OLD", supplier="Supplier Alpha")
    data_b = source("Part number | Last buy\nA1 | 2027-01-01\n", notice_id="OLD", supplier="Supplier Beta")
    data_new = source(
        "Part number | Last buy\nA1 | 2027-02-01\nSupersedes: OLD; Parts: A1\n",
        notice_id="NEW",
        supplier="Supplier Alpha",
    )
    alpha = repo.save(compile_notice(data_a, "alpha.txt"), data_a)
    beta = repo.save(compile_notice(data_b, "beta.txt"), data_b)
    newer = repo.save(compile_notice(data_new, "newer.txt"), data_new)
    assert repo.history(newer.id)["outgoing"][0]["target_id"] == alpha.id
    assert repo.history(beta.id)["incoming"] == []


def test_reviewer_correction_preserves_source_original_and_audit(tmp_path):
    repo = Repository(tmp_path)
    data = source("Part number | Last buy\n00O1-A | 2027-01-01\n")
    record = repo.save(compile_notice(data, "owned-original.txt"), data)
    updated = repo.review(
        record.id,
        ReviewRequest(
            field_path="parts.0.raw_identifier",
            action="correct",
            value="0001-A",
            reviewer="Owned reviewer",
            reason="Verified the original identifier against source image",
            expected_version=record.version,
        ),
    )
    assert updated.parts[0].raw_identifier.value == "0001-A"
    assert updated.parts[0].raw_identifier.raw == "00O1-A"
    assert updated.parts[0].normalized_identifier == "0001-A"
    assert repo.original(record.id).parts[0].raw_identifier.value == "00O1-A"
    assert repo.source(record.id) == data
    assert repo.audit(record.id)[0]["before"]["value"] == "00O1-A"
    assert repo.audit(record.id)[0]["after"]["value"] == "0001-A"
    with pytest.raises(ConflictError):
        repo.review(
            record.id,
            ReviewRequest(
                field_path="parts.0.raw_identifier",
                action="accept",
                reviewer="Owned reviewer",
                reason="Stale browser review",
                expected_version=record.version,
            ),
        )


def test_failed_review_cannot_partially_mutate_record_or_audit(tmp_path):
    repo = Repository(tmp_path)
    data = source("Part number | Last buy\nA1 | 2027-01-01\n")
    record = repo.save(compile_notice(data, "owned-original.txt"), data)
    before = repo.get(record.id).model_dump()
    events = repo.audit(record.id)
    with pytest.raises(ReviewError):
        repo.review(
            record.id,
            ReviewRequest(
                field_path="parts.0.dates.0",
                action="correct",
                value="2027-02-01",
                reviewer="Owned reviewer",
                reason="Invalid evidence must fail atomically",
                expected_version=record.version,
                evidence=Evidence(page=999, start=0, end=5, quote="wrong"),
            ),
        )
    assert repo.get(record.id).model_dump() == before
    assert repo.audit(record.id) == events


def test_corrected_field_with_new_source_evidence_can_export_without_erasing_original(tmp_path):
    body = """Change title: Transfer
Change detail: Transfer to the new owned facility.
Item name: Owned controller
Item category: ACEL
Change category: PSITE
Contact type: MANUFACTURER
Contact company: Owned Devices
Contact email: notice@example.invalid
Contact street: 1 Example Way
Contact postal code: CB1 1AA
Contact city: Cambridge
Contact country: GB
Part number | Effective change
A1 | 2027-01-01
Approved correction for A1: 2027-02-01
"""
    data = source(body).replace(b"Notice type: PDN", b"Notice type: PCN")
    repo = Repository(tmp_path)
    record = repo.save(compile_notice(data, "owned-correction.txt"), data)
    page = record.document.pages[0]
    start = page.text.index("2027-02-01")
    updated = repo.review(
        record.id,
        ReviewRequest(
            field_path="parts.0.dates.0",
            action="correct",
            value="2027-02-01",
            reviewer="Owned reviewer",
            reason="Applied the explicit approved correction for this part",
            expected_version=record.version,
            evidence=Evidence(page=1, start=start, end=start + 10, quote="2027-02-01"),
        ),
    )
    assert updated.parts[0].dates[0].raw == "2027-01-01"
    assert updated.parts[0].dates[0].evidence[0].quote == "2027-02-01"
    validate_xml(export_smartpcn(updated))
