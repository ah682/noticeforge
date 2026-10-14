"""Explicit human application of evidence-checked model proposals.

Model generation never edits canonical records. This module is used only inside
an atomic, version-checked reviewer transaction and revalidates source evidence.
"""

import re

from noticeforge.extraction import field, labelled, locate, parse_date
from noticeforge.models import CriticalValue, Evidence, ModelDecisionRequest, NoticeRecord, PartRecord
from noticeforge.providers import CandidateRelation, bound_pages, validate_output
from noticeforge.validation import evidence_valid, validate_record


def candidate_context(record: NoticeRecord, candidate: CandidateRelation) -> dict:
    matches = [part for part in record.parts if part.raw_identifier.value == candidate.part_raw]
    return {
        "will_create_part": not matches,
        "matching_parts": [
            {
                "id": part.id,
                "identifier": part.raw_identifier.value,
                "manufacturer": part.manufacturer.value,
                "dates": [
                    {
                        "index": index,
                        "kind": value.kind,
                        "value": value.value,
                        "raw": value.raw,
                        "qualifier": value.qualifier,
                    }
                    for index, value in enumerate(part.dates)
                    if value.kind == candidate.date_type
                ],
            }
            for part in matches
        ],
    }


def _evidence(record: NoticeRecord, candidate: CandidateRelation) -> list[Evidence]:
    evidence = []
    for span in candidate.evidence:
        page = next(page for page in record.document.pages if page.number == span.page)
        found = locate(page, span.quote, span.start)
        if found is None or found.start != span.start or found.end != span.end:
            raise ValueError("Candidate source locations no longer match the stored document")
        evidence.append(found)
    return evidence


def apply_candidate(
    record: NoticeRecord, candidate: CandidateRelation, request: ModelDecisionRequest, run_id: str
) -> tuple[list[str], dict, dict]:
    """Add/replace only a chosen exact part's date and optional scoped exception."""
    checked, rejected = validate_output(
        '{"candidates":[' + candidate.model_dump_json() + "]}",
        bound_pages(record.document.pages, max_characters=200000, max_pages=200),
    )
    if rejected or not checked:
        raise ValueError("Candidate failed exact source/evidence validation")
    evidence = _evidence(record, candidate)
    matches = [part for part in record.parts if part.raw_identifier.value == candidate.part_raw]
    if request.target_part_id:
        matches = [part for part in matches if part.id == request.target_part_id]
        if not matches:
            raise ValueError("Selected target part does not have the candidate's exact identifier")
    if len(matches) > 1:
        raise ValueError("This exact identifier has multiple records; select a target part and manufacturer")
    before: dict = {"part": matches[0].model_dump(mode="json") if matches else None}
    if not matches:
        if request.replace_date_index is not None:
            raise ValueError("A new part has no existing date to replace")
        # Manufacturer scope remains explicit; a model cannot invent it.
        supplier = record.metadata.supplier.model_copy(deep=True)
        if not supplier.value or not evidence_valid(record, supplier):
            raise ValueError("A new part requires sourced supplier/manufacturer metadata first")
        identifier_span = next(
            ev
            for ev in evidence
            if re.search(
                r"(?<![A-Za-z0-9_.-])" + re.escape(candidate.part_raw) + r"(?![A-Za-z0-9_.-])", ev.quote
            )
        )
        page = next(page for page in record.document.pages if page.number == identifier_span.page)
        identifier = field(candidate.part_raw, page, identifier_span.start)
        identifier.review_status = "accepted"
        identifier.method = "human-review"
        identifier.reason = request.reason
        identifier.model_run_id = run_id
        identifier.model_candidate_index = request.candidate_index
        part_id = f"model-{run_id[:12]}-{request.candidate_index}"
        part = PartRecord(
            id=part_id,
            raw_identifier=identifier,
            normalized_identifier=candidate.part_raw.strip(),
            manufacturer=supplier,
            group="Reviewed model additions",
            item_name=labelled(record.document, ["Item name"]),
            item_category=labelled(record.document, ["Item category"]),
        )
        category = labelled(record.document, ["Change category"])
        if category.value:
            part.change_categories.append(category)
        record.parts.append(part)
    else:
        part = matches[0]
    index = record.parts.index(part)
    date_indexes = [i for i, value in enumerate(part.dates) if value.kind == candidate.date_type]
    target_index: int | None
    if request.replace_date_index is not None:
        if request.replace_date_index not in date_indexes:
            raise ValueError("Selected date does not have the candidate's date kind")
        target_index = request.replace_date_index
    elif len(date_indexes) > 1:
        raise ValueError("This part has multiple dates of this kind; select the specific date to replace")
    else:
        target_index = date_indexes[0] if date_indexes else None
    original = part.dates[target_index] if target_index is not None else None
    literal = candidate.date_text
    first = next((ev for ev in evidence if literal and literal in ev.quote), evidence[0])
    page = next(page for page in record.document.pages if page.number == first.page)
    parsed = parse_date(literal, candidate.date_type, page, first.start)
    if candidate.date is not None and parsed.value != candidate.date:
        raise ValueError("The exact proposed date is not supported by its literal source")
    # A proposal cannot erase a conditional source relationship. Broad citations
    # conservatively retain uncertainty if the model failed to delimit its scope.
    context = "\n".join(ev.quote for ev in evidence)
    if candidate.date_type == "last_buy" and re.search(
        r"inventory|supplies last|remaining stock", context, re.I
    ):
        parsed.qualifier = "inventory_limited"
    elif re.search(r"\btentative|estimated|approximately\b", context, re.I):
        parsed.qualifier = "tentative"
    if original and original.qualifier in {"inventory_limited", "tentative"}:
        parsed.qualifier = original.qualifier
    parsed.value = candidate.date
    parsed.evidence = evidence
    parsed.method = "human-review"
    parsed.review_status = "accepted" if parsed.value and parsed.qualifier == "exact" else "review_required"
    parsed.reason = request.reason
    parsed.model_run_id = run_id
    parsed.model_candidate_index = request.candidate_index
    if original and original.value != parsed.value and parsed.review_status == "accepted":
        parsed.review_status = "corrected"
    if target_index is None:
        target_index = len(part.dates)
        part.dates.append(parsed)
    else:
        part.dates[target_index] = parsed
    paths = [f"parts.{index}.dates.{target_index}"]
    if before["part"] is None:
        paths.extend([f"parts.{index}.raw_identifier", f"parts.{index}.manufacturer"])
    if candidate.exception and not any(value.value == candidate.exception for value in part.exceptions):
        part.exceptions.append(
            CriticalValue(
                value=candidate.exception,
                raw=candidate.exception,
                evidence=evidence,
                method="human-review",
                review_status="accepted",
                reason=request.reason,
                model_run_id=run_id,
                model_candidate_index=request.candidate_index,
            )
        )
        paths.append(f"parts.{index}.exceptions.{len(part.exceptions) - 1}")
    # Coverage warnings are not erased by approving a candidate. An unparsed row
    # can contain additional information beyond this one accepted relationship.
    record.mode = "deterministic-rules+reviewed-model-proposals"
    validate_record(record)
    return paths, before, {"part": part.model_dump(mode="json")}
