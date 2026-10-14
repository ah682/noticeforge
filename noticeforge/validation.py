"""Relationship and evidence checks shared by extraction, review and export."""

import math
import re

from noticeforge.extraction import parse_date, valid_iso_date
from noticeforge.models import CriticalValue, DateValue, Finding, NoticeRecord


def critical_fields(record: NoticeRecord):
    for name in (
        "notice_id",
        "supplier",
        "notice_type",
        "title",
        "issue_date",
        "revision",
        "revision_date",
        "change_title",
        "change_detail",
    ):
        yield f"metadata.{name}", getattr(record.metadata, name)
    for name in type(record.metadata.contact).model_fields:
        yield f"metadata.contact.{name}", getattr(record.metadata.contact, name)
    for i, part in enumerate(record.parts):
        for name in ("raw_identifier", "manufacturer", "item_name", "item_category"):
            yield f"parts.{i}.{name}", getattr(part, name)
        for name in ("dates", "exceptions", "exclusions", "change_categories"):
            for j, value in enumerate(getattr(part, name)):
                yield f"parts.{i}.{name}.{j}", value
        for j, suggestion in enumerate(part.replacement_suggestions):
            yield f"parts.{i}.replacement_suggestions.{j}.part_number", suggestion.part_number
    for i, relationship in enumerate(record.relationships):
        yield f"relationships.{i}.target_notice_id", relationship.target_notice_id


def evidence_valid(record: NoticeRecord, value: CriticalValue) -> bool:
    if not value.evidence:
        return False
    for ev in value.evidence:
        page = next((p for p in record.document.pages if p.number == ev.page), None)
        if (
            not page
            or not 0 <= ev.start < ev.end <= len(page.text)
            or page.text[ev.start : ev.end] != ev.quote
        ):
            return False
        if ev.bbox:
            x1, y1, x2, y2 = ev.bbox
            if not all(math.isfinite(v) for v in ev.bbox) or x1 > x2 or y1 > y2 or min(ev.bbox) < 0:
                return False
            if page.width and (x2 > page.width + 1 or y2 > (page.height or 0) + 1):
                return False
            source_lines = [
                line for line in page.lines if line.bbox and line.end > ev.start and line.start < ev.end
            ]
            if source_lines and not any(
                max(x1, line.bbox[0]) < min(x2, line.bbox[2])
                and max(y1, line.bbox[1]) < min(y2, line.bbox[3])
                for line in source_lines
                if line.bbox
            ):
                return False
    return True


def source_value_supported(record: NoticeRecord, value: CriticalValue) -> bool:
    """Check automatic copies/normalizations, separately from location validity.

    Audited human corrections can reinterpret OCR or cite a newly selected source
    range. Their original value remains in ``raw`` and the repository audit. A
    review status alone is not an automatic extractor's license to change facts.
    """
    if value.method == "human-review" and value.review_status in {"corrected", "accepted"}:
        return True
    original = value.raw if value.raw else value.value
    if original is None:
        return False
    matching = [ev for ev in value.evidence if original in ev.quote]
    if not matching:
        return False
    if isinstance(value, DateValue):
        ev = matching[0]
        page = next((page for page in record.document.pages if page.number == ev.page), None)
        if page is None:
            return False
        normalized = parse_date(original, value.kind, page, ev.start)
        return normalized.value == value.value and (
            value.qualifier != "exact" or normalized.qualifier == "exact"
        )
    return original == value.value


VALIDATION_CODES = {
    "missing_metadata",
    "missing_date",
    "invalid_evidence",
    "invalid_date",
    "coverage",
    "no_parts",
    "ambiguous_value",
    "identity_collision",
    "date_order",
    "duplicate_identifier",
    "unknown_revision_scope",
    "invalid_notice_type",
    "conflicting_dates",
    "missing_part_field",
    "unsupported_assertion",
}


def validate_record(record: NoticeRecord) -> NoticeRecord:
    record.findings = [f for f in record.findings if f.code not in VALIDATION_CODES]
    for part in record.parts:
        if any(
            re.search(r"inventory|supplies last|remaining stock", value.value or "", re.I)
            for value in part.exceptions
        ):
            for deadline in part.dates:
                if deadline.kind == "last_buy" and deadline.qualifier != "inventory_limited":
                    deadline.qualifier = "inventory_limited"
                    deadline.review_status = "review_required"
                    deadline.reason = "The source still contains an inventory condition for this part"
    for name in ("notice_id", "supplier", "notice_type", "issue_date"):
        value = getattr(record.metadata, name)
        if not value.value:
            record.findings.append(
                Finding(
                    code="missing_metadata",
                    severity="error",
                    field_path=f"metadata.{name}",
                    message=f"Required notice metadata missing: {name.replace('_', ' ')}",
                )
            )
    if record.metadata.notice_type.value not in {"PCN", "PDN"}:
        record.findings.append(
            Finding(
                code="invalid_notice_type",
                severity="error",
                field_path="metadata.notice_type",
                message="Notice type must be PCN or PDN; source needs review",
            )
        )
    if not record.document.complete:
        for message in record.document.warnings:
            record.findings.append(Finding(code="coverage", severity="error", message=message))
    if not record.parts:
        record.findings.append(
            Finding(
                code="no_parts",
                severity="error",
                message="No supported affected-part rows found; this layout needs annotation",
            )
        )
    for path, value in critical_fields(record):
        present = value.value is not None or bool(value.raw)
        located = evidence_valid(record, value) if present else False
        if present and not located:
            value.review_status = "review_required"
            record.findings.append(
                Finding(
                    code="invalid_evidence",
                    severity="error",
                    field_path=path,
                    message="Critical value is missing valid source evidence",
                )
            )
        elif present and not source_value_supported(record, value):
            value.review_status = "review_required"
            value.reason = (
                "The automatic value is not an exact copy or supported date normalization of its cited source"
            )
            record.findings.append(
                Finding(
                    code="unsupported_assertion",
                    severity="error",
                    field_path=path,
                    message=value.reason,
                    evidence=value.evidence,
                )
            )
        if isinstance(value, DateValue) and value.value and not valid_iso_date(value.value):
            value.review_status = "review_required"
            record.findings.append(
                Finding(
                    code="invalid_date",
                    severity="error",
                    field_path=path,
                    message="Date is not a valid ISO calendar date",
                )
            )
        needs_date_review = (
            isinstance(value, DateValue)
            and (path.startswith("parts.") or present)
            and (not value.value or value.qualifier != "exact")
        )
        if needs_date_review:
            value.review_status = "review_required"
            value.reason = (
                value.reason or "This date is missing, conditional, or ambiguous; source review is required"
            )
        if value.review_status == "review_required" and (present or needs_date_review):
            record.findings.append(
                Finding(
                    code="ambiguous_value",
                    severity="warning",
                    field_path=path,
                    message=value.reason or "This critical value needs source review",
                    evidence=value.evidence,
                )
            )
    identifiers = {}
    for i, part in enumerate(record.parts):
        for name in ("raw_identifier", "manufacturer"):
            value = getattr(part, name)
            if not value.value or not value.value.strip():
                value.review_status = "review_required"
                record.findings.append(
                    Finding(
                        code="missing_part_field",
                        severity="error",
                        part_ids=[part.id],
                        field_path=f"parts.{i}.{name}",
                        message=f"Required affected-part field is missing: {name.replace('_', ' ')}",
                    )
                )
        if part.raw_identifier.value and part.normalized_identifier != part.raw_identifier.value.strip():
            record.findings.append(
                Finding(
                    code="identity_collision",
                    severity="error",
                    part_ids=[part.id],
                    field_path=f"parts.{i}.raw_identifier",
                    message="Identifier normalization changed more than surrounding whitespace; review the exact identity",
                )
            )
        identity = (part.manufacturer.value, part.raw_identifier.value)
        if identity in identifiers:
            record.findings.append(
                Finding(
                    code="duplicate_identifier",
                    severity="warning",
                    part_ids=[part.id],
                    message="Identifier appears in multiple source rows; records have been retained separately",
                )
            )
        identifiers[identity] = part.id
        required_kind = "last_buy" if record.metadata.notice_type.value == "PDN" else "effective_change"
        if not any(d.kind == required_kind and d.value for d in part.dates):
            record.findings.append(
                Finding(
                    code="missing_date",
                    severity="warning",
                    part_ids=[part.id],
                    message=f"{part.raw_identifier.value}: no supported {required_kind.replace('_', ' ')} relationship",
                )
            )
        date_by_kind: dict[str, list[DateValue]] = {}
        for d in part.dates:
            date_by_kind.setdefault(d.kind, []).append(d)
        if any(len({d.value for d in values}) > 1 for values in date_by_kind.values()):
            record.findings.append(
                Finding(
                    code="conflicting_dates",
                    severity="error",
                    part_ids=[part.id],
                    message="Conflicting deadlines of the same kind on this part",
                )
            )
        dates = {d.kind: d.value for d in part.dates if d.value and d.qualifier == "exact"}
        if (
            dates.get("last_buy")
            and dates.get("last_delivery")
            and dates["last_buy"] > dates["last_delivery"]
        ):
            record.findings.append(
                Finding(
                    code="date_order",
                    severity="warning",
                    part_ids=[part.id],
                    message="Last delivery precedes last buy; verify this relationship",
                )
            )
        fields = [part.raw_identifier, part.manufacturer, *part.dates, *part.exceptions, *part.exclusions]
        if any(v.review_status == "review_required" for v in fields) or any(
            part.id in f.part_ids and f.severity != "info" for f in record.findings
        ):
            part.review_status = "review_required"
        elif all(v.review_status in {"accepted", "corrected"} for v in fields):
            part.review_status = "accepted"
        else:
            part.review_status = "supported"
    for relation in record.relationships:
        if (
            relation.target_notice_id.review_status == "review_required"
            or not relation.target_notice_id.value
        ):
            relation.review_status = "review_required"
        if relation.scope == "unknown":
            relation.review_status = "review_required"
            record.findings.append(
                Finding(
                    code="unknown_revision_scope",
                    severity="error",
                    message="Revision scope is unknown; historical parts remain active",
                )
            )
    record.unsupported_fields = [
        f.message
        for f in record.findings
        if f.code
        in {
            "unparsed_part_row",
            "unscoped_date",
            "unlinked_exception",
            "unlinked_footnote",
            "duplicate_columns",
            "ambiguous_footnote",
        }
    ]
    if not record.document.complete:
        record.status = "incomplete"
    elif any(f.severity in {"warning", "error"} for f in record.findings):
        record.status = "review_required"
    elif record.parts and all(p.review_status == "accepted" for p in record.parts):
        record.status = "reviewed"
    else:
        record.status = "supported"
    return record
