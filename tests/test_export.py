"""Owned synthetic examples; the actual unmodified COGD XSD is the oracle."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from lxml import etree

from noticeforge.exporters import (
    SCHEMA_PATH,
    SCHEMA_SHA256,
    SMARTPCN_NAMESPACE,
    SMARTPCN_VERSION,
    ExportError,
    export_json,
    export_smartpcn,
    validate_xml,
)
from noticeforge.models import (
    Contact,
    CriticalValue,
    DateValue,
    Document,
    Evidence,
    NoticeMetadata,
    NoticeRecord,
    PartRecord,
    Replacement,
    RevisionRelationship,
    SourcePage,
)
from noticeforge.pipeline import compile_notice

NS = {"s": SMARTPCN_NAMESPACE}


@pytest.fixture
def supported_record() -> NoticeRecord:
    """Original test content, not a manufacturer notice or extracted claim."""
    text = """Owned synthetic fixture for NoticeForge exporter tests.
Notice: NF-SITE-2026
Supplier: Owned Semiconductors
Type: PCN
Title: Assembly location transfer
Issue date: 2026-10-01
Revision: B
Revision date: 2026-10-02
Contact type: MANUFACTURER
Company: Owned Semiconductors Ltd
Email: pcn@example.invalid
Street: 1 Fixture Lane
Postal code: CB1 1AA
City: Cambridge
Country: GB
Change title: Assembly location transfer
Change detail: Assembly moves to the owned synthetic facility.
Item category: ACEL
Change category: PSITE
0012-A | Precision controller | Last buy 2027-03-31 | Effective 2027-01-01 | Last delivery 2027-12-31
012-A | Voltage controller | Last buy 2027-06-30 | Effective 2027-02-01 | Last delivery 2028-01-31
Footnote 1: 0012-A last buy is extended to 2027-03-31.
Suggested replacement for 0012-A: 0012-B. Compatibility not assessed.
"""

    def field(value: str) -> CriticalValue:
        start = text.index(value)
        return CriticalValue(
            value=value,
            raw=value,
            evidence=[Evidence(page=1, start=start, end=start + len(value), quote=value)],
        )

    def deadline(kind: str, value: str) -> DateValue:
        return DateValue(**field(value).model_dump(), kind=kind)

    parts = []
    for index, (number, name, last_buy, effective, last_delivery) in enumerate(
        [
            ("0012-A", "Precision controller", "2027-03-31", "2027-01-01", "2027-12-31"),
            ("012-A", "Voltage controller", "2027-06-30", "2027-02-01", "2028-01-31"),
        ]
    ):
        parts.append(
            PartRecord(
                id=f"part-{index}",
                raw_identifier=field(number),
                normalized_identifier=number,
                manufacturer=field("Owned Semiconductors"),
                group=f"Group {index + 1}",
                item_name=field(name),
                item_category=field("ACEL"),
                change_categories=[field("PSITE")],
                dates=[
                    deadline("last_buy", last_buy),
                    deadline("effective_change", effective),
                    deadline("last_delivery", last_delivery),
                ],
            )
        )
    parts[0].exceptions = [field("Footnote 1: 0012-A last buy is extended to 2027-03-31.")]
    parts[0].replacement_suggestions = [Replacement(part_number=field("0012-B"))]
    raw = text.encode()
    return NoticeRecord(
        id="owned-export-fixture",
        provenance="synthetic",
        created_at="2026-10-13T00:00:00Z",
        document=Document(
            sha256=hashlib.sha256(raw).hexdigest(),
            filename="owned-export.txt",
            media_type="text/plain",
            byte_size=len(raw),
            pages=[SourcePage(number=1, text=text)],
        ),
        metadata=NoticeMetadata(
            notice_id=field("NF-SITE-2026"),
            supplier=field("Owned Semiconductors"),
            notice_type=field("PCN"),
            title=field("Assembly location transfer"),
            issue_date=deadline("issue_date", "2026-10-01"),
            revision=field("B"),
            revision_date=deadline("revision_date", "2026-10-02"),
            change_title=field("Assembly location transfer"),
            change_detail=field("Assembly moves to the owned synthetic facility."),
            contact=Contact(
                contact_type=field("MANUFACTURER"),
                company=field("Owned Semiconductors Ltd"),
                email=field("pcn@example.invalid"),
                street=field("1 Fixture Lane"),
                zip_code=field("CB1 1AA"),
                city=field("Cambridge"),
                country=field("GB"),
            ),
        ),
        parts=parts,
    )


def test_original_publisher_schema_hashes():
    manifest = json.loads((SCHEMA_PATH.parent / "SOURCE.json").read_text())
    assert SCHEMA_PATH.name == "PCNbody_V3_08.xsd"
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == SCHEMA_SHA256
    for entry in manifest["files"]:
        assert (
            hashlib.sha256((SCHEMA_PATH.parent / entry["file"]).read_bytes()).hexdigest() == entry["sha256"]
        )
    assert manifest["schema_revision"] == SMARTPCN_VERSION


def test_owned_valid_fixture_passes_actual_xsd(supported_record):
    xml = export_smartpcn(supported_record)
    validate_xml(xml)
    # Independently use the actual on-disk schema, not an exporter self-check.
    original_schema = etree.XMLSchema(etree.parse(str(SCHEMA_PATH)))
    root = etree.fromstring(xml)
    original_schema.assertValid(root)
    assert root.find("s:masterData", NS).get("pcnFormatVersion") == "SmartPCN_3.08"


def test_owned_pdf_compiles_and_exports_without_filling_missing_fields():
    path = Path(__file__).resolve().parents[1] / "fixtures/development/aster-site-transfer.pdf"
    record = compile_notice(path.read_bytes(), path.name)
    xml = export_smartpcn(record)
    validate_xml(xml)
    root = etree.fromstring(xml)
    dates = {
        item.findtext("s:itemMfrNumber", namespaces=NS): item.find("s:itemLifeCycleData", NS).get(
            "itemEOPeffDate"
        )
        for item in root.findall("s:ItemNumbers/s:ItemNumber", NS)
    }
    assert dates == {"AMP-230-A": "2027-01-15", "AMP-230-B": "2027-02-15"}
    # Inspect the actual XML extension contract independently of any importer.
    envelopes = [
        json.loads(node.text)
        for node in root.findall("s:pcnSubStructures/s:pcnSubStructure/s:pcnSubData", NS)
    ]
    reconstructed = base64.b64decode("".join(item["data"] for item in envelopes))
    assert reconstructed == export_json(record)
    restored = NoticeRecord.model_validate_json(reconstructed)
    assert restored.document.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert restored.document.pages == record.document.pages
    for part, restored_part in zip(record.parts, restored.parts, strict=True):
        assert restored_part.raw_identifier.evidence == part.raw_identifier.evidence
        assert restored_part.dates == part.dates
        assert restored_part.raw_identifier.evidence[0].bbox is not None


def test_native_dates_remain_specific_to_exact_part_identifiers(supported_record):
    root = etree.fromstring(export_smartpcn(supported_record))
    actual = {}
    for item in root.findall("s:ItemNumbers/s:ItemNumber", NS):
        actual[item.findtext("s:itemMfrNumber", namespaces=NS)] = dict(
            item.find("s:itemLifeCycleData", NS).attrib
        )
    assert actual == {
        "0012-A": {"itemEOS": "2027-03-31", "itemEOPeffDate": "2027-01-01", "itemLTD": "2027-12-31"},
        "012-A": {"itemEOS": "2027-06-30", "itemEOPeffDate": "2027-02-01", "itemLTD": "2028-01-31"},
    }
    assert root.find("s:pcnLifeCycleData", NS) is None


def test_direct_export_blocks_an_inconsistent_normalized_identity(supported_record):
    supported_record.parts[1].normalized_identifier = "0012-A"
    with pytest.raises(ExportError, match="normalization"):
        export_smartpcn(supported_record)
    assert supported_record.parts[1].raw_identifier.value == "012-A"


@pytest.mark.parametrize(
    "field_path,new_value",
    [
        ("deadline", "2030-01-01"),
        ("supplier", "Invented Manufacturer"),
    ],
)
def test_direct_export_rejects_schema_valid_but_unsupported_mutation(supported_record, field_path, new_value):
    if field_path == "deadline":
        value = supported_record.parts[0].dates[1]
    else:
        value = supported_record.metadata.supplier
    value.value = new_value
    # Pydantic and XSD permit these lexical values; the retained source does not.
    assert value.review_status == "supported"
    assert supported_record.status == "supported"
    with pytest.raises(ExportError, match="not an exact source copy or supported date normalization"):
        export_smartpcn(supported_record)


def test_exception_and_unassessed_suggestion_stay_on_their_part(supported_record):
    root = etree.fromstring(export_smartpcn(supported_record))
    items = root.findall("s:ItemNumbers/s:ItemNumber", NS)
    extensions = [
        json.loads(item.findtext("s:itemSubStructures/s:itemSubStructure/s:itemSubData", namespaces=NS))
        for item in items
    ]
    assert extensions[0]["exceptions"][0]["value"] == supported_record.parts[0].exceptions[0].value
    assert extensions[1]["exceptions"] == []
    assert extensions[0]["supplier_replacement_suggestions"][0]["part_number"]["value"] == "0012-B"
    assert extensions[0]["supplier_replacement_suggestions"][0]["compatibility"] == "not_assessed"
    assert extensions[1]["supplier_replacement_suggestions"] == []
    assert not root.findall(".//s:itemReplacements", NS)


def test_complete_canonical_snapshot_is_lossless_hashed_and_xsd_bounded(supported_record):
    xml = export_smartpcn(supported_record)
    root = etree.fromstring(xml)
    nodes = root.findall("s:pcnSubStructures/s:pcnSubStructure/s:pcnSubData", NS)
    envelopes = [json.loads(node.text) for node in nodes]
    assert all(len(node.text) <= 4096 for node in nodes)
    assert [entry["index"] for entry in envelopes] == list(range(len(envelopes)))
    assert all(entry["total"] == len(envelopes) for entry in envelopes)
    canonical = base64.b64decode("".join(entry["data"] for entry in envelopes))
    assert canonical == export_json(supported_record)
    assert {entry["sha256"] for entry in envelopes} == {hashlib.sha256(canonical).hexdigest()}
    assert json.loads(canonical)["document"]["pages"][0]["text"] == supported_record.document.pages[0].text


@pytest.mark.parametrize("qualifier", ["ambiguous", "tentative", "inventory_limited", "missing"])
def test_nonexact_deadlines_cannot_be_exported_as_exact(supported_record, qualifier):
    supported_record.parts[0].dates[0].qualifier = qualifier
    with pytest.raises(ExportError, match=qualifier):
        export_smartpcn(supported_record)
    assert json.loads(export_json(supported_record))["parts"][0]["dates"][0]["qualifier"] == qualifier


def test_incomplete_record_blocks_xml_but_preserves_json(supported_record):
    supported_record.document.complete = False
    with pytest.raises(ExportError, match="incomplete"):
        export_smartpcn(supported_record)
    assert json.loads(export_json(supported_record))["document"]["complete"] is False


def test_subset_supersession_is_never_flattened(supported_record):
    supported_record.relationships = [
        RevisionRelationship(
            kind="supersedes",
            target_notice_id=supported_record.metadata.notice_id,
            scope="subset",
            parts=["part-0"],
            evidence=supported_record.parts[0].raw_identifier.evidence,
        )
    ]
    with pytest.raises(ExportError, match="subset scope"):
        export_smartpcn(supported_record)
    assert json.loads(export_json(supported_record))["relationships"][0]["parts"] == ["part-0"]


def test_missing_required_metadata_is_not_invented(supported_record):
    supported_record.metadata.contact.email = CriticalValue()
    with pytest.raises(ExportError, match="metadata.contact.email.*missing"):
        export_smartpcn(supported_record)


def test_identifier_change_requires_review_even_with_original_evidence(supported_record):
    supported_record.parts[0].raw_identifier.value = "O012-A"
    with pytest.raises(ExportError, match="identifier change requires explicit review"):
        export_smartpcn(supported_record)


def test_evidence_offsets_are_checked_before_export(supported_record):
    supported_record.parts[0].dates[0].evidence[0].start += 1
    with pytest.raises(ExportError, match="evidence does not match"):
        export_smartpcn(supported_record)


def test_missing_effective_date_cannot_be_replaced_by_last_delivery(supported_record):
    supported_record.parts[0].dates = [
        d for d in supported_record.parts[0].dates if d.kind != "effective_change"
    ]
    with pytest.raises(ExportError, match="explicit effective_change"):
        export_smartpcn(supported_record)


def test_pdn_requires_explicit_production_date(supported_record):
    # A PDN must not relabel a last-buy/last-delivery date as end of production.
    source = supported_record.document.pages[0].text.replace("Type: PCN", "Type: PDN")
    source = source.replace("Effective ", "End of production ")
    source = source.replace("Change category: PSITE", "Change category: PDN")
    supported_record.document.pages[0].text = source
    supported_record.metadata.notice_type.value = "PDN"
    supported_record.metadata.notice_type.raw = "PDN"
    supported_record.metadata.notice_type.evidence[0].quote = "PDN"
    for part in supported_record.parts:
        part.change_categories[0].value = "PDN"
        part.change_categories[0].raw = "PDN"
        part.change_categories[0].evidence[0].quote = "PDN"
        for deadline in part.dates:
            if deadline.kind == "effective_change":
                deadline.kind = "end_of_production"

    data = supported_record.model_dump(mode="json")

    def reposition(value):
        if isinstance(value, dict):
            for evidence in value.get("evidence", []):
                evidence["start"] = source.index(evidence["quote"])
                evidence["end"] = evidence["start"] + len(evidence["quote"])
            for child in value.values():
                reposition(child)
        elif isinstance(value, list):
            for child in value:
                reposition(child)

    reposition(data)
    pdn = NoticeRecord.model_validate(data)
    root = etree.fromstring(export_smartpcn(pdn))
    lifecycle = root.find("s:ItemNumbers/s:ItemNumber/s:itemLifeCycleData", NS)
    assert lifecycle.get("itemEOPeffDate") == "2027-01-01"
    assert lifecycle.get("itemLTD") == "2027-12-31"
    pdn.parts[0].dates = [d for d in pdn.parts[0].dates if d.kind != "end_of_production"]
    with pytest.raises(ExportError, match="explicit end_of_production"):
        export_smartpcn(pdn)


@pytest.mark.parametrize("kind", ["sample_availability", "acknowledgment"])
def test_unsupported_deadline_kind_is_not_silently_dropped(supported_record, kind):
    other = supported_record.parts[0].dates[0].model_copy(deep=True)
    other.kind = kind
    supported_record.parts[0].dates.append(other)
    with pytest.raises(ExportError, match=f"{kind} is unsupported"):
        export_smartpcn(supported_record)


def test_duplicate_deadline_relationship_requires_review(supported_record):
    supported_record.parts[0].dates.append(supported_record.parts[0].dates[0].model_copy(deep=True))
    with pytest.raises(ExportError, match="more than one last_buy"):
        export_smartpcn(supported_record)


def test_exclusion_cannot_disappear_from_xml(supported_record):
    supported_record.parts[0].exclusions = [supported_record.parts[1].raw_identifier]
    with pytest.raises(ExportError, match="exclusions"):
        export_smartpcn(supported_record)


def test_invalid_xml_fails_actual_schema(supported_record):
    xml = export_smartpcn(supported_record)
    root = etree.fromstring(xml)
    lifecycle = root.find("s:ItemNumbers/s:ItemNumber/s:itemLifeCycleData", NS)
    del lifecycle.attrib["itemEOPeffDate"]
    with pytest.raises(ExportError, match="XSD validation failed"):
        validate_xml(etree.tostring(root))
    with pytest.raises(ExportError, match="XSD validation failed"):
        validate_xml(xml.replace(b'itemEOS="2027-03-31"', b'itemEOS="2027-02-30"'))


def test_bad_xml_and_external_entity_declarations_fail_closed():
    with pytest.raises(ExportError, match="XSD validation failed"):
        validate_xml(b"<PCNbody>")
    with pytest.raises(ExportError, match="DTD"):
        validate_xml(
            b'<!DOCTYPE PCNbody [<!ENTITY leak SYSTEM "file:///etc/passwd">]><PCNbody>&leak;</PCNbody>'
        )


def test_oversized_native_field_fails_instead_of_truncating(supported_record):
    replace_evidenced_value(supported_record, supported_record.metadata.title, "A" * 257)
    with pytest.raises(ExportError, match="XSD validation failed"):
        export_smartpcn(supported_record)


def test_xml_forbidden_control_character_is_readable_failure(supported_record):
    replace_evidenced_value(supported_record, supported_record.metadata.title, "Title\x00broken")
    with pytest.raises(ExportError, match="content cannot be represented"):
        export_smartpcn(supported_record)


def replace_evidenced_value(record, field, value):
    page = record.document.pages[0]
    start = len(page.text)
    page.text += value + "\n"
    field.value = field.raw = value
    field.evidence = [Evidence(page=1, start=start, end=start + len(value), quote=value)]


def test_direct_export_cannot_remove_inventory_qualifier_with_stale_status(supported_record):
    exception = supported_record.parts[0].exceptions[0]
    replace_evidenced_value(supported_record, exception, "Orders only while remaining inventory lasts.")
    # This record was never sent through validate_record after the source condition changed.
    assert supported_record.parts[0].dates[0].qualifier == "exact"
    with pytest.raises(ExportError, match="semantic validation requires review"):
        export_smartpcn(supported_record)


def test_direct_export_checks_source_bbox_even_with_correct_offsets(supported_record):
    evidence = supported_record.parts[0].dates[0].evidence[0]
    evidence.bbox = (-1, 0, 10, 10)
    with pytest.raises(ExportError, match="offsets and region"):
        export_smartpcn(supported_record)
