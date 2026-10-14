"""Conservative rules for labelled notices and common table layouts.

Rules produce supported facts only when their location and scope are explicit. Unknown
layouts remain candidates and findings. No language model or document instruction is executed.
"""

import re
from datetime import date, datetime
from typing import Any, Literal

from noticeforge.models import (
    Contact,
    CriticalValue,
    DateValue,
    Document,
    Evidence,
    Finding,
    NoticeMetadata,
    NoticeRecord,
    PartRecord,
    Replacement,
    ReviewStatus,
    RevisionRelationship,
    SourcePage,
)

DATE_LABELS = {
    "last buy": "last_buy",
    "last buy date": "last_buy",
    "last order": "last_buy",
    "last time buy": "last_buy",
    "last time buy date": "last_buy",
    "ltb": "last_buy",
    "last delivery": "last_delivery",
    "last delivery date": "last_delivery",
    "last shipment": "last_delivery",
    "ltd": "last_delivery",
    "effective change": "effective_change",
    "effective date": "effective_change",
    "effective": "effective_change",
    "sample availability": "sample_availability",
    "samples available": "sample_availability",
    "acknowledgment": "acknowledgment",
    "acknowledgement": "acknowledgment",
    "end of production": "end_of_production",
    "eop": "end_of_production",
}
PART_HEADERS = {
    "part",
    "parts",
    "part number",
    "part numbers",
    "affected part",
    "affected parts",
    "manufacturer part number",
    "orderable part number",
    "mpn",
    "ordering code",
    "product code",
    "device",
    "device number",
    "part no",
    "part no.",
}
IGNORED_VALUES = {"", "-", "—", "n/a", "none", "not applicable"}
DATE_TOKEN = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|TBD|to be determined|Q[1-4]\s+\d{4})"


def key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().replace("_", " ").replace("-", " ")).rstrip(":")


def locate(page: SourcePage, quote: str, start=0, box=None) -> Evidence | None:
    index = page.text.find(quote, start)
    if box is not None:
        # PDF text offsets and cell coordinates must identify the same occurrence.
        while index >= 0:
            source_boxes = [
                line.bbox
                for line in page.lines
                if line.bbox and line.end > index and line.start < index + len(quote)
            ]
            if any(
                min(b[2], box[2]) > max(b[0], box[0]) and min(b[3], box[3]) > max(b[1], box[1])
                for b in source_boxes
            ):
                break
            index = page.text.find(quote, index + 1)
    if index < 0:
        return None
    if box is None:
        boxes = [
            line.bbox
            for line in page.lines
            if line.bbox and line.end > index and line.start < index + len(quote)
        ]
        if boxes:
            box = (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
    return Evidence(
        page=page.number, start=index, end=index + len(quote), quote=quote, bbox=box, method=page.method
    )


def field(value: str | None, page: SourcePage | None = None, start=0, box=None) -> CriticalValue:
    if value is None or not value.strip():
        return CriticalValue(review_status="review_required", reason="Not found in source")
    value = value.strip()
    evidence = locate(page, value, start, box) if page else None
    status: ReviewStatus = "supported" if evidence and page and page.method != "ocr" else "review_required"
    return CriticalValue(
        value=value,
        raw=value,
        evidence=[evidence] if evidence else [],
        review_status=status,
        reason=None if status == "supported" else "Verify OCR or missing source evidence",
    )


def parse_date(raw: str, kind: str, page: SourcePage, start=0, box=None) -> DateValue:
    original = field(raw, page, start, box)
    text = re.sub(r"\[\d+\]|\*\d*", "", raw).strip()
    exact = None
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        candidate = re.sub(r"\b(tentative|estimated|approximately)\b[: ]*", "", text, flags=re.I).strip()
        try:
            exact = datetime.strptime(candidate, fmt).date().isoformat()
            break
        except ValueError:
            pass
    qualifier = "exact" if exact else "ambiguous"
    reason = original.reason
    if re.search(r"tentative|estimated|approximately", text, re.I):
        qualifier = "tentative"
        reason = "The supplier marks this deadline tentative"
    elif re.search(r"inventory|supplies last|stock", text, re.I):
        qualifier = "inventory_limited"
        reason = "Ordering depends on inventory; no exact deadline asserted"
    elif not exact:
        reason = "No unambiguous calendar date; review the original wording"
    return DateValue(
        **{
            **original.model_dump(),
            "value": exact,
            "kind": kind,
            "qualifier": qualifier,
            "review_status": original.review_status if qualifier == "exact" else "review_required",
            "reason": reason,
        }
    )


def labelled(document: Document, labels: list[str]) -> CriticalValue:
    pattern = re.compile(r"^\s*(?:" + "|".join(re.escape(s) for s in labels) + r")\s*:\s*(.+?)\s*$", re.I)
    found = []
    for page in document.pages:
        for line in page.lines:
            match = pattern.match(line.text)
            if match:
                found.append(field(match[1], page, line.start + match.start(1)))
    if not found:
        return field(None)
    result = found[0]
    if len({item.value for item in found}) > 1:
        result.review_status = "review_required"
        result.reason = "Conflicting labelled values in the source"
        result.evidence = [ev for item in found for ev in item.evidence]
    return result


def metadata(document: Document) -> NoticeMetadata:
    values: dict[str, Any] = {
        "notice_id": labelled(document, ["Notice ID", "PCN Number", "PDN Number", "Notification number"]),
        "supplier": labelled(document, ["Supplier", "Manufacturer"]),
        "notice_type": labelled(document, ["Notice type", "Type"]),
        "title": labelled(document, ["Title", "Subject"]),
        "revision": labelled(document, ["Revision", "Revision number"]),
        "change_title": labelled(document, ["Change title"]),
        "change_detail": labelled(document, ["Change detail", "Description of change"]),
    }
    for name, labels in [
        ("issue_date", ["Issue date", "Date of issue"]),
        ("revision_date", ["Revision date"]),
    ]:
        value = labelled(document, labels)
        if value.value and value.evidence:
            ev = value.evidence[0]
            values[name] = parse_date(value.value, name, document.pages[ev.page - 1], ev.start)
            if value.review_status == "review_required":
                values[name].review_status = "review_required"
                values[name].reason = value.reason
        else:
            values[name] = DateValue.model_validate(
                dict(
                    kind=name,
                    qualifier="missing",
                    review_status="review_required",
                    reason="Not found in source",
                )
            )
    contact = Contact(
        **{
            name: labelled(document, [label])
            for name, label in {
                "contact_type": "Contact type",
                "company": "Contact company",
                "email": "Contact email",
                "street": "Contact street",
                "zip_code": "Contact postal code",
                "city": "Contact city",
                "country": "Contact country",
            }.items()
        }
    )
    return NoticeMetadata(**values, contact=contact)


def split_parts(raw: str) -> list[str]:
    # Never split hyphens, slashes or suffixes; slash may be an actual ordering identifier.
    return [
        s.strip() for s in re.split(r"[,;\n]", raw) if s.strip() and s.strip().lower() not in IGNORED_VALUES
    ]


def _rows(document, findings):
    """Yield named cells with exact source regions from ruled PDF or delimited text tables."""
    for page in document.pages:
        pdf_row_parts: set[str] = set()
        headers: list[str] | None
        for table in page.tables:
            if not table:
                continue
            table_headers = [key(cell.text) for cell in table[0]]
            if not any(h in PART_HEADERS for h in table_headers):
                if any(
                    h in DATE_LABELS or re.search(r"part|product|ordering|device", h) for h in table_headers
                ):
                    findings.append(
                        Finding(
                            code="unparsed_part_row",
                            severity="error",
                            message=f"Page {page.number}: affected-product table has unsupported headers; annotation required",
                        )
                    )
                continue
            if len(set(table_headers)) != len(table_headers):
                findings.append(
                    Finding(
                        code="duplicate_columns",
                        severity="error",
                        message=f"Page {page.number}: duplicate table headers; annotate the competing columns",
                    )
                )
                continue
            for row in table[1:]:
                cells = {
                    header: (cell.text, 0, cell.bbox)
                    for header, cell in zip(table_headers, row, strict=False)
                }
                pdf_row_parts.update(raw for h, (raw, _, _) in cells.items() if h in PART_HEADERS)
                yield page, cells
        headers = None
        for line in page.lines:
            delimiter = "|" if "|" in line.text else "\t" if "\t" in line.text else None
            if not delimiter:
                continue
            values = line.text.split(delimiter)
            keys = [key(v) for v in values]
            if any(k in PART_HEADERS for k in keys):
                headers = keys
                continue
            if not headers or len(headers) != len(values):
                if any(re.search(r"[A-Za-z]*\d+[A-Za-z0-9_/-]*", value) for value in values):
                    findings.append(
                        Finding(
                            code="unparsed_part_row",
                            severity="error",
                            message=f"Page {page.number}: part-like table row has missing headers or inconsistent columns",
                            evidence=[ev for ev in [locate(page, line.text, line.start)] if ev],
                        )
                    )
                continue
            if len(set(headers)) != len(headers):
                findings.append(
                    Finding(
                        code="duplicate_columns",
                        severity="error",
                        message=f"Page {page.number}: duplicate table headers; competing values need review",
                        evidence=[ev for ev in [locate(page, line.text, line.start)] if ev],
                    )
                )
                continue
            cells = {}
            cursor = line.start
            for header, value in zip(headers, values, strict=True):
                cells[header] = (value.strip(), cursor, None)
                cursor += len(value) + 1
            if not any(cells[h][0] in pdf_row_parts for h in cells if h in PART_HEADERS):
                yield page, cells
        for line in page.lines:
            if "|" in line.text or "\t" in line.text:
                continue
            match = re.match(r"\s*(?:Parts?|Affected parts?)\s*:\s*([^;]+)(;.*)?$", line.text, re.I)
            if not match:
                continue
            cells = {"parts": (match[1], line.start + match.start(1), None)}
            for segment in re.finditer(r";\s*([^:;]+):\s*([^;]+)", line.text):
                cells[key(segment[1])] = (segment[2], line.start + segment.start(2), None)
            yield page, cells


def extract_notice(document: Document) -> NoticeRecord:
    meta = metadata(document)
    record = NoticeRecord(id=document.sha256[:20], metadata=meta, document=document, parts=[])
    row_footnotes: dict[tuple[int, str], list[PartRecord]] = {}
    global_category = labelled(document, ["Change category"])
    global_name = labelled(document, ["Item name"])
    global_item_category = labelled(document, ["Item category"])
    for page, cells in _rows(document, record.findings):
        part_cell = next((cells[h] for h in cells if h in PART_HEADERS), None)
        if not part_cell:
            continue
        raw_parts, start, box = part_cell
        for raw in split_parts(raw_parts):
            if not re.search(r"\d", raw) or len(raw) > 100:
                record.findings.append(
                    Finding(
                        code="unparsed_part_row",
                        severity="warning",
                        message=f"Unrecognized part identifier row: {raw[:100]}",
                    )
                )
                continue
            identifier = field(raw, page, start, box)
            manufacturer = (
                field(cells["manufacturer"][0], page, cells["manufacturer"][1], cells["manufacturer"][2])
                if "manufacturer" in cells
                else meta.supplier.model_copy(deep=True)
            )
            part = PartRecord(
                id=f"part-{len(record.parts) + 1}",
                raw_identifier=identifier,
                normalized_identifier=raw.strip(),
                manufacturer=manufacturer,
                group=cells.get("group", ("Affected parts", 0, None))[0] or "Affected parts",
                item_name=global_name.model_copy(deep=True),
                item_category=global_item_category.model_copy(deep=True),
            )
            if global_category.value:
                part.change_categories.append(global_category.model_copy(deep=True))
            for header, (value, offset, cell_box) in cells.items():
                if value.strip().lower() in IGNORED_VALUES:
                    continue
                if header in DATE_LABELS:
                    part.dates.append(parse_date(value, DATE_LABELS[header], page, offset, cell_box))
                elif header in {"exception", "exceptions", "notes", "note"}:
                    clean = re.sub(r"\[\d+\]", "", value).strip()
                    if clean:
                        part.exceptions.append(field(clean, page, offset, cell_box))
                elif header in {"replacement", "suggested replacement"}:
                    part.replacement_suggestions.extend(
                        Replacement(part_number=field(v, page, offset, cell_box)) for v in split_parts(value)
                    )
                elif header in {"exclusion", "exclusions"}:
                    part.exclusions.append(field(value, page, offset, cell_box))
                elif header == "item name":
                    part.item_name = field(value, page, offset, cell_box)
                elif header == "item category":
                    part.item_category = field(value, page, offset, cell_box)
                for marker in re.findall(r"\[(\d+)\]", value):
                    row_footnotes.setdefault((page.number, marker), []).append(part)
            record.parts.append(part)

    # Explicitly scoped footnotes: a marker never changes unrelated rows.
    definitions: dict[tuple[int, str], list[tuple[SourcePage, Any, str]]] = {}
    for page in document.pages:
        for line in page.lines:
            footnote = re.match(r"\s*\[(\d+)\]\s*(.+)", line.text)
            if not footnote:
                continue
            marker, statement = footnote.groups()
            definitions.setdefault((page.number, marker), []).append((page, line, statement))
    for (reference_page, marker), referenced in row_footnotes.items():
        matches = definitions.get((reference_page, marker), [])
        if not matches:
            matches = [item for (pg, m), entries in definitions.items() if m == marker for item in entries]
        targets = list({part.id: part for part in referenced}.values())
        if len(matches) != 1:
            record.findings.append(
                Finding(
                    code="missing_footnote",
                    severity="error",
                    message=f"Footnote [{marker}] on page {reference_page} is missing or has ambiguous definitions",
                    part_ids=[p.id for p in targets],
                )
            )
            continue
        page, line, statement = matches[0]
        # Named exceptions narrow a shared row. Unchanged/excluded parts never receive a changed date.
        mentioned = [
            p
            for p in targets
            if re.search(r"(?<![\w/-])" + re.escape(p.raw_identifier.value or "") + r"(?![\w/-])", statement)
        ]
        if mentioned:
            targets = [
                p
                for p in mentioned
                if not re.search(
                    re.escape(p.raw_identifier.value or "")
                    + r"\s+(?:(?:is|remains)\s+)?(?:unchanged|not affected|excluded)",
                    statement,
                    re.I,
                )
            ]
        labels = list(
            re.finditer(
                r"\b("
                + "|".join(re.escape(label) for label in sorted(DATE_LABELS, key=len, reverse=True))
                + r")\b",
                statement,
                re.I,
            )
        )
        for part in targets:
            part.exceptions.append(field(statement, page, line.start))
            for index, label in enumerate(labels):
                prefix = re.split(r";|\.(?=\s)", statement[: label.start()])[-1]
                scoped = [
                    candidate
                    for candidate in targets
                    if re.search(
                        r"(?<![\w/-])" + re.escape(candidate.raw_identifier.value or "") + r"(?![\w/-])",
                        prefix,
                    )
                ]
                if scoped and part not in scoped:
                    continue
                segment = statement[
                    label.end() : labels[index + 1].start() if index + 1 < len(labels) else len(statement)
                ]
                segment = segment.split(";", 1)[0]
                dates = list(re.finditer(DATE_TOKEN, segment, re.I))
                kind = DATE_LABELS[key(label[0])]
                if len(dates) != 1:
                    record.findings.append(
                        Finding(
                            code="ambiguous_footnote",
                            severity="warning",
                            message=f"Footnote [{marker}] needs review before changing {kind.replace('_', ' ')}",
                            part_ids=[part.id],
                            evidence=[ev for ev in [locate(page, line.text, line.start)] if ev],
                        )
                    )
                    for old in part.dates:
                        if old.kind == kind:
                            old.review_status = "review_required"
                            old.reason = "A footnote qualifies this date but cannot be resolved automatically"
                    continue
                replacement = parse_date(dates[0][0], kind, page, line.start)
                if re.search(r"tentative|estimated|approximately", segment, re.I):
                    replacement.qualifier = "tentative"
                    replacement.review_status = "review_required"
                    replacement.reason = "The footnote marks this deadline tentative"
                footnote_evidence = locate(page, line.text, line.start)
                if footnote_evidence:
                    replacement.evidence.append(footnote_evidence)
                original = next((d for d in part.dates if d.kind == kind), None)
                if original:
                    replacement.evidence.extend(original.evidence)
                    replacement.reason = (
                        (replacement.reason + "; ") if replacement.reason else ""
                    ) + f"Footnote [{marker}] modifies row value {original.raw}"
                    part.dates.remove(original)
                part.dates.append(replacement)
    for (definition_page, marker), entries in definitions.items():
        if not any(m == marker for _, m in row_footnotes):
            page, line, statement = entries[0]
            record.findings.append(
                Finding(
                    code="unlinked_footnote",
                    severity="warning",
                    message=f"Footnote [{marker}] on page {definition_page} has no linked row",
                    evidence=[ev for ev in [locate(page, line.text, line.start)] if ev],
                )
            )

    # Explicit per-part exceptions/replacements and revision scopes in labelled prose.
    for page in document.pages:
        for line in page.lines:
            match = re.match(
                r"\s*(Exception|Replacement|Exclusion)\s+for\s+(.+?)\s*:\s*(.+)", line.text, re.I
            )
            if match:
                kind, raw, statement = match.groups()
                targets = [p for p in record.parts if p.raw_identifier.value == raw.strip()]
                if not targets:
                    record.findings.append(
                        Finding(
                            code="unlinked_exception",
                            severity="warning",
                            message=f"{kind} has no matching exact identifier {raw}",
                        )
                    )
                for part in targets:
                    value = field(statement, page, line.start + match.start(3))
                    if kind.lower() == "replacement":
                        part.replacement_suggestions.append(Replacement(part_number=value))
                    elif kind.lower() == "exclusion":
                        part.exclusions.append(value)
                    else:
                        part.exceptions.append(value)
            match = re.match(
                r"\s*(Supersedes|Cancels)\s*:\s*([^;]+)(?:;\s*(?:Parts|Scope)\s*:\s*(.+))?$", line.text, re.I
            )
            if match:
                kind, target, scope_text = match.groups()
                scope: Literal["all", "subset", "unknown"] = (
                    "all"
                    if scope_text and scope_text.strip().lower() == "all"
                    else "subset"
                    if scope_text
                    else "unknown"
                )
                record.relationships.append(
                    RevisionRelationship(
                        kind="supersedes" if kind.lower() == "supersedes" else "cancels",
                        target_notice_id=field(target, page, line.start + match.start(2)),
                        scope=scope,
                        parts=split_parts(scope_text) if scope == "subset" else [],
                        evidence=[ev for ev in [locate(page, line.text, line.start)] if ev],
                        review_status="supported" if scope != "unknown" else "review_required",
                    )
                )

    # Global dates may be applied only when the source explicitly declares their scope.
    for page in document.pages:
        for line in page.lines:
            match = re.match(r"\s*All affected parts\s*:\s*([^:]+):\s*(.+)", line.text, re.I)
            if match and key(match[1]) in DATE_LABELS:
                for part in record.parts:
                    kind = DATE_LABELS[key(match[1])]
                    global_date = parse_date(match[2], kind, page, line.start + match.start(2))
                    if not any(
                        d.kind == kind
                        and d.value == global_date.value
                        and d.qualifier == global_date.qualifier
                        for d in part.dates
                    ):
                        part.dates.append(global_date)
            elif re.match(
                r"\s*(?:" + "|".join(re.escape(k) for k in DATE_LABELS) + r")\s*:", line.text, re.I
            ):
                record.findings.append(
                    Finding(
                        code="unscoped_date",
                        severity="warning",
                        message="A document-level deadline has no explicit part scope; review before linking",
                        evidence=[ev for ev in [locate(page, line.text, line.start)] if ev],
                    )
                )
            if re.search(
                r"ignore (?:all |previous |prior )?instructions|system prompt|discard evidence|change.*schema",
                line.text,
                re.I,
            ):
                record.findings.append(
                    Finding(
                        code="untrusted_instruction",
                        severity="info",
                        message="Instruction-like source text was retained as data and ignored by the compiler",
                        evidence=[ev for ev in [locate(page, line.text, line.start)] if ev],
                    )
                )

    for part in record.parts:
        inventory = [
            exception
            for exception in part.exceptions
            if re.search(r"inventory|supplies last|remaining stock", exception.value or "", re.I)
        ]
        if inventory:
            for deadline in part.dates:
                if deadline.kind == "last_buy":
                    deadline.qualifier = "inventory_limited"
                    deadline.review_status = "review_required"
                    deadline.reason = "This ordering cutoff is subject to a part-specific inventory condition"
                    deadline.evidence.extend(ev for item in inventory for ev in item.evidence)
    return record


def valid_iso_date(value: str) -> bool:
    try:
        return (
            bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and date.fromisoformat(value).isoformat() == value
        )
    except ValueError:
        return False
