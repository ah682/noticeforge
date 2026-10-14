"""Literal identifiers, manufacturer-scoped matches, explicit uncertainty."""

from noticeforge.models import BOMRow, NoticeRecord


def manufacturer_key(value: str | None) -> str:
    # Only surrounding/repeated whitespace and case; no company aliases or fuzzy identity.
    return " ".join((value or "").split()).casefold()


def match_bom(record: NoticeRecord, rows: list[BOMRow]) -> list[dict]:
    results = []
    for row in rows:
        literal = [p for p in record.parts if p.raw_identifier.value == row.part_number.strip()]
        scoped = [
            p
            for p in literal
            if row.manufacturer
            and manufacturer_key(p.manufacturer.value) == manufacturer_key(row.manufacturer)
        ]
        status = "unmatched"
        reason = "No exact identifier in this notice"
        candidates = []
        if row.manufacturer:
            if (
                len(scoped) == 1
                and scoped[0].raw_identifier.review_status != "review_required"
                and scoped[0].manufacturer.review_status != "review_required"
                and not scoped[0].exclusions
            ):
                status, reason, candidates = "literal_match", "Exact identifier and manufacturer", scoped
            elif scoped:
                status, reason, candidates = (
                    "ambiguous",
                    "Multiple records, exclusions, or identifier/manufacturer requires review",
                    scoped,
                )
            elif literal:
                reason = "Identifier exists under a different manufacturer"
        elif literal:
            status, reason, candidates = (
                "ambiguous",
                "Manufacturer missing; supply it to resolve scope",
                literal,
            )
        results.append(
            {
                "part_number": row.part_number,
                "manufacturer": row.manufacturer,
                "status": status,
                "reason": reason,
                "part_ids": [p.id for p in candidates],
                "candidates": [
                    {
                        "part_id": p.id,
                        "part_number": p.raw_identifier.value,
                        "manufacturer": p.manufacturer.value,
                    }
                    for p in candidates
                ],
            }
        )
    return results
