"""Canonical JSON and a deliberately restricted, original-XSD-validated smartPCN body.

This is an XML body profile, not a .smartPCN transport container. Native lifecycle
dates are always item-specific. See docs/SMARTPCN.md for the exact interoperability
boundary and the NoticeForge extension encoding.
"""

import base64
import hashlib
import json
import re
from datetime import date
from functools import lru_cache

from lxml import etree

from noticeforge.models import CriticalValue, DateValue, NoticeRecord
from noticeforge.resources import DATA_ROOT
from noticeforge.validation import evidence_valid, source_value_supported, validate_record

SMARTPCN_VERSION = "SmartPCN_3.08"
SMARTPCN_NAMESPACE = "http://www.smartpcn.org/images/files/VDMA24903Schema/PCNbody"
SCHEMA_PATH = DATA_ROOT / "schemas" / "smartpcn" / "PCNbody_V3_08.xsd"
SCHEMA_SHA256 = "0e6f6b6b7edb8a34b0258e8996f25349a070d7b2ef67a6b84fb0951fe84de38d"
MAX_XML_BYTES = 20 * 1024 * 1024
_XSD = {"xs": "http://www.w3.org/2001/XMLSchema"}
_NATIVE_DATE_ATTRIBUTES = {"last_buy": "itemEOS", "last_delivery": "itemLTD"}


class ExportError(ValueError):
    """Export cannot represent the record safely, or XML fails the pinned XSD."""


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)


@lru_cache(maxsize=1)
def _schema_document() -> etree._Element:
    try:
        raw = SCHEMA_PATH.read_bytes()
    except OSError as exc:
        raise ExportError(f"Pinned smartPCN XSD is unavailable: {SCHEMA_PATH}") from exc
    if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
        raise ExportError("Pinned smartPCN XSD integrity check failed; restore the original COGD XSD.")
    return etree.fromstring(raw, parser=_parser())


@lru_cache(maxsize=1)
def _schema() -> etree.XMLSchema:
    return etree.XMLSchema(_schema_document())


def validate_xml(xml: bytes) -> None:
    """Validate an XML PCNbody against the unmodified COGD SmartPCN_3.08 XSD.

    This checks schema validity, not extraction truth or NoticeForge profile
    eligibility. DTDs and entity references are outside this local profile.
    """
    if not xml or len(xml) > MAX_XML_BYTES:
        raise ExportError("XML must be nonempty and at most 20 MiB.")
    try:
        root = etree.fromstring(xml, parser=_parser())
        if root.getroottree().docinfo.doctype:
            raise ExportError("DTD declarations are not allowed in smartPCN XML.")
        _schema().assertValid(root)
    except (etree.XMLSyntaxError, etree.DocumentInvalid) as exc:
        detail = "; ".join(str(entry.message) for entry in list(exc.error_log)[-3:])
        raise ExportError(f"smartPCN {SMARTPCN_VERSION} XSD validation failed: {detail or str(exc)}") from exc


def export_json(record: NoticeRecord) -> bytes:
    """The complete canonical record remains exportable, including uncertainty."""
    checked = NoticeRecord.model_validate(record.model_dump(mode="json"))
    return (checked.model_dump_json(indent=2) + "\n").encode("utf-8")


def _value(record: NoticeRecord, field: CriticalValue | None, path: str) -> str:
    if field is None or field.value is None or not field.value.strip():
        raise ExportError(f"{path}: required value is missing. Use canonical JSON until it is supplied.")
    if field.review_status == "review_required":
        raise ExportError(f"{path}: review is required before smartPCN export.")
    if not field.evidence:
        raise ExportError(f"{path}: source evidence is missing.")
    for evidence in field.evidence:
        page = next((p for p in record.document.pages if p.number == evidence.page), None)
        if page is None or page.text[evidence.start : evidence.end] != evidence.quote or not evidence.quote:
            raise ExportError(f"{path}: evidence does not match the source page and offsets.")
    if not evidence_valid(record, field):
        raise ExportError(f"{path}: evidence does not match the source page, offsets and region.")
    if not source_value_supported(record, field):
        if path.endswith(".raw_identifier") and field.raw != field.value:
            raise ExportError(f"{path}: an automatic identifier change requires explicit review.")
        raise ExportError(f"{path}: the value is not an exact source copy or supported date normalization.")
    return field.value


def _date(record: NoticeRecord, field: DateValue, path: str) -> str:
    if field.qualifier != "exact":
        raise ExportError(
            f"{path}: {field.qualifier} date cannot be emitted as an exact smartPCN deadline. "
            "Use canonical JSON."
        )
    value = _value(record, field, path)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("expected YYYY-MM-DD")
    except ValueError as exc:
        raise ExportError(f"{path}: an exact ISO calendar date (YYYY-MM-DD) is required.") from exc
    return value


def _enum_values(name: str) -> set[str]:
    return set(
        _schema_document().xpath(
            "xs:simpleType[@name=$name]/xs:restriction/xs:enumeration/@value", namespaces=_XSD, name=name
        )
    )


def _element(parent: etree._Element, tag: str, value: str | None = None, **attrs: str) -> etree._Element:
    try:
        node = etree.SubElement(parent, f"{{{SMARTPCN_NAMESPACE}}}{tag}", **attrs)
        if value is not None:
            node.text = value
    except (ValueError, TypeError) as exc:
        raise ExportError(f"{tag}: content cannot be represented as XML text: {exc}") from exc
    return node


def _extension(parent: etree._Element, payload: dict, *, item: bool, subtype: str) -> None:
    """Add a bounded, explicitly proprietary JSON substructure."""
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 4096:
        raise ExportError("A NoticeForge item extension exceeds the XSD's 4096 character limit; use JSON.")
    prefix = "item" if item else "pcn"
    sub = _element(
        parent, f"{prefix}SubStructure", **{f"{prefix}SubType": subtype, f"{prefix}SubRevision": "1.0"}
    )
    _element(sub, f"{prefix}SubData", encoded)


def _canonical_extension(root: etree._Element, record: NoticeRecord) -> None:
    """Keep a complete canonical snapshot, with a hash and ordered Base64 chunks.

    Chunking honors the original XSD's per-container 4096-character maximum.
    It never turns unsupported relationships into native smartPCN assertions.
    """
    canonical = export_json(record)
    digest = hashlib.sha256(canonical).hexdigest()
    encoded = base64.b64encode(canonical).decode("ascii")
    chunks = [encoded[i : i + 3000] for i in range(0, len(encoded), 3000)]
    subs = _element(root, "pcnSubStructures")
    for index, chunk in enumerate(chunks):
        _extension(
            subs,
            {
                "encoding": "base64-utf8-json",
                "index": index,
                "total": len(chunks),
                "sha256": digest,
                "data": chunk,
            },
            item=False,
            subtype="NOTICEFORGE_CANONICAL",
        )


def export_smartpcn(record: NoticeRecord) -> bytes:
    """Return an original-XSD-valid PCNbody, or block a lossy/unsupported export.

    Supported native dates: exact last_buy, last_delivery, and PCN effective_change
    or PDN end_of_production. Required manufacturer, contact, item and change
    metadata must have source evidence. Unknown/review-required values are never
    filled with placeholders. All native values and extensions are validated
    before any output is returned.
    """
    record = NoticeRecord.model_validate(record.model_dump(mode="json"))
    expected_pages = record.document.expected_pages
    pages_missing = expected_pages is not None and expected_pages != len(
        {p.number for p in record.document.pages}
    )
    if not record.document.complete or record.status == "incomplete" or pages_missing:
        raise ExportError(
            "Document is incomplete; smartPCN export is blocked. Canonical JSON retains the warning."
        )
    if record.status == "review_required":
        raise ExportError(
            "Notice has unresolved review-required findings; use canonical JSON until reviewed."
        )
    if record.unsupported_fields:
        raise ExportError(
            "Unsupported source fields would be omitted; use canonical JSON: "
            + "; ".join(record.unsupported_fields)
        )
    if any(f.severity == "error" for f in record.findings):
        raise ExportError("Notice has unresolved validation errors; use canonical JSON.")
    if record.relationships:
        raise ExportError(
            "Supersession/cancellation relationships are unsupported by this restricted XML profile; "
            "canonical JSON preserves the exact relationship and subset scope."
        )
    if not record.parts:
        raise ExportError("At least one affected part is required for smartPCN export.")

    meta = record.metadata
    notice_type = _value(record, meta.notice_type, "metadata.notice_type")
    if notice_type not in {"PCN", "PDN"}:
        raise ExportError("metadata.notice_type: only literal PCN or PDN is supported.")
    supplier = _value(record, meta.supplier, "metadata.supplier")
    contact = meta.contact
    if contact is None:
        raise ExportError(
            "metadata.contact: smartPCN requires an evidenced contact and postal address; use JSON."
        )
    contact_type = _value(record, contact.contact_type, "metadata.contact.contact_type")
    if contact_type != "MANUFACTURER":
        raise ExportError(
            "metadata.contact.contact_type: this restricted profile supports MANUFACTURER only."
        )

    root = etree.Element(f"{{{SMARTPCN_NAMESPACE}}}PCNbody", nsmap={None: SMARTPCN_NAMESPACE})
    master = _element(root, "masterData", pcnFormatVersion=SMARTPCN_VERSION)
    _element(master, "pcnNumber", _value(record, meta.notice_id, "metadata.notice_id"))
    _element(master, "pcnTitle", _value(record, meta.title, "metadata.title"))
    _element(master, "pcnType", notice_type)
    _element(master, "pcnMfrName", supplier)
    _element(master, "pcnIssueDate", _date(record, meta.issue_date, "metadata.issue_date"))
    _element(
        master,
        "pcnAddInfo",
        "Restricted NoticeForge profile. Per-item conditions and unassessed "
        "supplier suggestions are in NOTICEFORGE_PART substructures. Retain all extensions and the "
        "complete NOTICEFORGE_CANONICAL snapshot; generic readers may ignore these extensions.",
    )
    if meta.revision.value is not None or meta.revision.raw is not None or meta.revision.evidence:
        _element(master, "pcnRevision", _value(record, meta.revision, "metadata.revision"))
    if meta.revision_date.value is not None or meta.revision_date.qualifier != "missing":
        if meta.revision.value is None:
            raise ExportError("metadata.revision_date requires an evidenced revision identifier.")
        revisions = _element(master, "revisions")
        _element(
            revisions,
            "revision",
            pcnRevisionNumber=_value(record, meta.revision, "metadata.revision"),
            pcnRevDate=_date(record, meta.revision_date, "metadata.revision_date"),
        )
    contacts = _element(master, "contacts")
    contact_node = _element(contacts, "contact", pcnContactType=contact_type)
    _element(contact_node, "pcnCompany", _value(record, contact.company, "metadata.contact.company"))
    _element(contact_node, "pcnEmail", _value(record, contact.email, "metadata.contact.email"))
    address = _element(contact_node, "address")
    for field, tag in (
        ("street", "pcnStreet"),
        ("zip_code", "pcnZipCode"),
        ("city", "pcnCity"),
        ("country", "pcnCountry"),
    ):
        _element(address, tag, _value(record, getattr(contact, field), f"metadata.contact.{field}"))

    difference = _element(root, "difference")
    _element(difference, "pcnChangeTitle", _value(record, meta.change_title, "metadata.change_title"))
    _element(difference, "pcnChangeDetail", _value(record, meta.change_detail, "metadata.change_detail"))
    items = _element(root, "ItemNumbers")
    emitted: set[tuple[str, str]] = set()
    required_date = "effective_change" if notice_type == "PCN" else "end_of_production"
    for part in record.parts:
        path = f"parts[{part.id}]"
        if part.review_status == "review_required":
            raise ExportError(f"{path}: unresolved review-required part.")
        if part.exclusions:
            raise ExportError(
                f"{path}: exclusions need canonical JSON; the restricted XML profile cannot represent them."
            )
        identifier = _value(record, part.raw_identifier, f"{path}.raw_identifier")
        if (
            part.raw_identifier.raw is not None
            and part.raw_identifier.raw != identifier
            and part.raw_identifier.review_status not in {"accepted", "corrected"}
        ):
            raise ExportError(
                f"{path}.raw_identifier: an identifier change requires explicit review; "
                "normalization must not silently alter a part number."
            )
        if any(c in identifier for c in "\r\n\t") or identifier != identifier.strip():
            raise ExportError(
                f"{path}.raw_identifier: whitespace-sensitive identifier cannot be safely exported."
            )
        manufacturer = _value(record, part.manufacturer, f"{path}.manufacturer")
        if manufacturer != supplier:
            raise ExportError(f"{path}.manufacturer: mixed manufacturer scopes require canonical JSON.")
        key = manufacturer, identifier
        if key in emitted:
            raise ExportError(f"{path}: duplicate manufacturer/part scope would be ambiguous in XML.")
        emitted.add(key)
        item = _element(items, "ItemNumber")
        _element(item, "itemMfrNumber", identifier)
        _element(item, "itemMfrName", _value(record, part.item_name, f"{path}.item_name"))
        category = _value(record, part.item_category, f"{path}.item_category")
        if category not in _enum_values("productCategoryType"):
            raise ExportError(
                f"{path}.item_category: {category!r} is not an official smartPCN category code."
            )
        _element(item, "itemCategory", category)
        dates: dict[str, str] = {}
        for index, deadline in enumerate(part.dates):
            if deadline.kind not in {*_NATIVE_DATE_ATTRIBUTES, required_date}:
                raise ExportError(
                    f"{path}.dates[{index}]: {deadline.kind} is unsupported in this XML profile; use JSON."
                )
            if deadline.kind in dates:
                raise ExportError(f"{path}: more than one {deadline.kind} relationship requires review.")
            dates[deadline.kind] = _date(record, deadline, f"{path}.dates[{index}]")
        if required_date not in dates:
            raise ExportError(
                f"{path}: smartPCN requires an explicit {required_date}; another deadline cannot substitute."
            )
        attributes = {"itemEOPeffDate": dates[required_date]}
        attributes.update(
            {tag: dates[kind] for kind, tag in _NATIVE_DATE_ATTRIBUTES.items() if kind in dates}
        )
        _element(item, "itemLifeCycleData", **attributes)

        exceptions = []
        for index, exception in enumerate(part.exceptions):
            _value(record, exception, f"{path}.exceptions[{index}]")
            exceptions.append(exception.model_dump(mode="json"))
        suggestions = []
        for index, replacement in enumerate(part.replacement_suggestions):
            _value(record, replacement.part_number, f"{path}.replacement_suggestions[{index}]")
            suggestions.append(replacement.model_dump(mode="json"))
        substructures = _element(item, "itemSubStructures")
        _extension(
            substructures,
            {
                "part_id": part.id,
                "group": part.group,
                "manufacturer": manufacturer,
                "exceptions": exceptions,
                "supplier_replacement_suggestions": suggestions,
                "compatibility": "not_assessed",
            },
            item=True,
            subtype="NOTICEFORGE_PART",
        )
        changes = _element(item, "itemChanges")
        if not part.change_categories:
            raise ExportError(
                f"{path}.change_categories: at least one evidenced smartPCN change code is required."
            )
        change_codes = []
        for index, change in enumerate(part.change_categories):
            code = _value(record, change, f"{path}.change_categories[{index}]")
            if code not in _enum_values("typeOfChangeType"):
                raise ExportError(
                    f"{path}.change_categories[{index}]: {code!r} is not an official change code."
                )
            change_codes.append(code)
            _element(changes, "itemChange", itemChangeType=code)
        if (notice_type == "PDN") != ("PDN" in change_codes):
            raise ExportError(
                f"{path}: mixed change/discontinuation semantics are outside this XML profile; "
                "PDN items need an explicit PDN change code, and PCN items must not have one."
            )
        if {"CANCN", "CANDN"}.intersection(change_codes):
            raise ExportError(
                f"{path}: cancellation change codes need the unsupported cancellation relationship profile."
            )

    # Direct callers must not bypass semantic checks by retaining a stale status
    # after changing a typed record. Revalidate a copy: preserve the exact original
    # canonical snapshot and reject inconsistent inventory, identities or evidence.
    verified = validate_record(record.model_copy(deep=True))
    if verified.status not in {"supported", "reviewed"}:
        problems = [f.message for f in verified.findings if f.severity in {"warning", "error"}]
        raise ExportError("Canonical semantic validation requires review: " + "; ".join(problems[:3]))
    _canonical_extension(root, record)
    try:
        xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    except (ValueError, TypeError) as exc:
        raise ExportError(f"Record contains content that cannot be encoded as XML: {exc}") from exc
    validate_xml(xml)
    return xml
