# Restricted smartPCN export

NoticeForge produces a **`PCNbody.xml` body for smartPCN 3.0**, pinned to the
publisher's **`SmartPCN_3.08` XSD** dated 2018-08-09. Every returned XML body is
validated with `lxml.etree.XMLSchema` against the unmodified official XSD. A
successful export has passed that XSD and NoticeForge's field and evidence checks.

The actual COGD schemas, source URLs, SHA-256 hashes, and permission attribution
are in [schemas/smartpcn](../schemas/smartpcn/README.md). The publisher's current
[downloads page](https://smartpcn.org/downloads/) was rechecked on 2026-10-14. The
linked body schema identifies `SmartPCN_3.08`; the specification PDF's `3.01` is a
document revision, distinct from the pinned XSD revision.

The exporter returns the XML body, **not the `.smartPCN` ZIP container**, attachment
manifest, source-file attachments, or a delivery/acknowledgment workflow. Native
smartPCN import and round-trip editing are not implemented.

## Required data

`export_smartpcn(record) -> bytes` requires a complete canonical record without
unresolved review-required values, validation errors, unsupported source fields,
or missing source evidence. Evidence offsets must match the referenced source
page. Automatic extractions must include the original value in their cited evidence.
Audited human corrections may select new evidence; the original remains in `raw`,
the canonical snapshot and the review audit.
The exporter independently checks exact source copying/date normalization and
reruns semantic validation on a copy before returning bytes. Changing a typed
record's date or supplier while retaining its old evidence and `supported` status
cannot bypass these checks. The original canonical snapshot is not rewritten by
that verification. Human-review status/method is trusted review metadata supplied
by the review workflow; this is not a cryptographic review-attestation format.

The original XSD mandates more fields than many ordinary notices provide. The
restricted exporter requires explicit, evidence-backed values for notice ID,
title, literal `PCN`/`PDN` type, supplier, exact issue date, change title/detail,
manufacturer contact type, company, email, street, postal code, city, and country.
Every part needs an exact identifier, manufacturer, manufacturer item name, an
official item category code, at least one official change category code, and the
appropriate effective/end-of-production date. No placeholder contact, invented
item description, inferred category, or substituted deadline is added to satisfy
the schema. Names, emails, lengths and enum values must pass the original XSD.

The supported manufacturer contact type is `MANUFACTURER`. Every item's
manufacturer must exactly match the notice supplier. Mixed manufacturer notices
remain canonical JSON until a broader mapping is implemented. `ACEL` and `PSITE`
are the explicit codes used in the owned manufacturing-transfer fixture. The
exporter accepts official codes present in the pinned XSD; it does not infer them
from free prose.

## Relationship mapping

| Canonical data | XML representation / restriction |
| --- | --- |
| Exact raw part identifier | `ItemNumbers/ItemNumber/itemMfrNumber`; never replaced by the normalized identifier |
| Exact last-buy date | The same item's `itemLifeCycleData/@itemEOS` |
| Exact last-delivery date | The same item's `itemLifeCycleData/@itemLTD` |
| PCN exact effective-change date | The same item's required `@itemEOPeffDate` |
| PDN explicit exact end-of-production date | The same item's required `@itemEOPeffDate` |
| Revision identifier and exact revision date | `pcnRevision` and a revision entry, when provided |
| Part-specific exceptions and supplier suggestions | `NOTICEFORGE_PART` JSON substructure attached to that item |
| Complete canonical record, evidence and provenance | Hashed `NOTICEFORGE_CANONICAL` JSON snapshot in substructures |

The official [specification, sections 3.3 and 4.5](https://smartpcn.org/wp-content/uploads/2021/01/Specification-smartPCN-3.01-released-20180323.pdf)
defines end of sales as the last opportunity to buy, and distinguishes effective
change, end of production and last delivery. NoticeForge therefore never copies
last buy or last delivery into the required effective/end-of-production slot.
It does not emit document-level lifecycle summaries: every deadline stays with
its affected item.

This release supports homogeneous change or discontinuation notices. A PDN must
have an explicit `PDN` change code on every item and an explicit end-of-production
date. PCN items must not contain a `PDN` code. Mixed change/discontinuation cases
need a broader item-level semantic mapping and are blocked.

## Explicitly blocked cases

The exporter raises a readable `ExportError` and leaves canonical JSON available
for incomplete documents; review-required records/values; unsupported source
fields; missing/broken evidence; tentative, ambiguous, inventory-limited or
missing dates; more than one date of a kind for an item; missing mandatory data;
mixed manufacturer scopes; duplicate manufacturer/identifier pairs; and
whitespace-sensitive identifiers that XML normalization could change.

Supersession/cancellation references, including subset revisions, are blocked.
They are not flattened into a notice-wide replacement relationship. Exclusions
are blocked. `CANCN`/`CANDN` change codes are blocked. Generic sample-availability
dates and acknowledgment dates are blocked because the implemented native
mapping cannot preserve their meaning and part scope. Dates or text exceeding
XSD limits are rejected, never truncated.

An exact date already resolved by a source footnote can be exported together with
its part-specific exception text and evidence. A condition such as "while stocks
last" must retain `inventory_limited` as its date qualifier; it cannot be emitted
as an exact guaranteed deadline. The exporter trusts validated canonical date
classification and does not attempt a second natural-language interpretation of
exception text.

## NoticeForge extension contract

The original XSD allows labelled substructures containing text. Their containers
are standard smartPCN fields; **the JSON meanings below are proprietary to this
NoticeForge profile**. A generic reader may ignore them. A consumer that needs
exceptions, suggestions, evidence or provenance must retain and read them, or use
the complete canonical JSON directly. `pcnAddInfo` states this boundary in every
exported body. Schema validation alone cannot confirm that another product will
understand the extensions.

Each item's `itemSubStructure` with `itemSubType="NOTICEFORGE_PART"` and
`itemSubRevision="1.0"` contains JSON with `part_id`, `group`, `manufacturer`,
`exceptions`, `supplier_replacement_suggestions`, and
`compatibility: "not_assessed"`. Exceptions retain their original values,
evidence, methods, and review status. Suggestions are not emitted as native
`itemReplacements`: the exporter makes no suitability or compatibility assertion.
The per-item JSON must fit the XSD's 4096-character limit; otherwise export is
blocked. The complete data still fits the independent canonical JSON export.

`pcnSubStructure` containers with `pcnSubType="NOTICEFORGE_CANONICAL"` and
`pcnSubRevision="1.0"` carry the full result of `export_json(record)`. Each
`pcnSubData` is a JSON envelope:

```json
{"encoding":"base64-utf8-json","index":0,"total":2,"sha256":"...","data":"..."}
```

Require a contiguous zero-based index sequence, identical `total`/`sha256` values,
and the declared number of chunks. Concatenate `data` by index, Base64-decode it,
verify SHA-256 against the decoded bytes, and parse those UTF-8 bytes as JSON.
Chunks contain at most 3000 Base64 characters, keeping each envelope within the
original 4096-character XSD limit. The snapshot includes source-page text and may
be large; XML bodies above 20 MiB are rejected. It is neither a substitute for
native standards mapping nor a claim that third-party readers support this
encoding.

## Validation and verification

`validate_xml(xml) -> None` checks any supplied body against the pinned XSD and
raises `ExportError` for malformed or schema-invalid XML. It rejects DTDs; entity
resolution and network access are disabled. Schema bytes are checked against
the pinned SHA-256 before compiling the schema. This function validates structure
only; `export_smartpcn` performs the additional field and evidence checks.

`export_json(record) -> bytes` validates the canonical model and exports it even
when XML is blocked, preserving unsupported fields, uncertain values, warnings,
and relationships.

Run the exporter acceptance suite from the project root:

```sh
.venv/bin/python -m pytest tests/test_export.py
```

The owned synthetic tests independently compile the original XSD, validate a
supported XML body, verify distinct item-level deadlines and raw identifiers,
verify the exact canonical snapshot, preserve a part-specific footnote and an
unassessed suggestion, test explicit PDN end-of-production mapping, reject
incomplete/ambiguous/unsupported records, and reject invalid XML and external
entity declarations.

### Independent verification executed on 2026-10-14

The 30 exporter tests passed, including independent compilation of the original
publisher XSD, valid owned PCN/PDN bodies, invalid dates/missing required attributes,
lossless canonical reconstruction, exact per-item lifecycle mappings, and direct
export calls with stale `supported` status but unsupported date/supplier values.
The native owned PDF test reconstructs every source page, line, coordinate, exact
identifier and date/evidence relationship from the emitted canonical chunks and
checks the original PDF hash. This tests the NoticeForge extension encoding.

As a separate publisher sanity check, `PCNbody.xml` from the official
[COGD test archive](https://smartpcn.org/wp-content/uploads/2021/03/COG-smartPCN-3.0-Testfile-3.2.zip)
validated against the vendored XSD. The archive's `PCNbody_V3_08.xsd` had the same
SHA-256 as the pinned file. Inspection of the original specification confirmed
that `itemEOS` is last time buy, `itemLTD` is last delivery, and `itemEOPeffDate`
changes meaning with PCN versus PDN. The publisher example was used to check
the schema and mapping.
The executed check is recorded in
[standards-verification.json](../reports/ocr/standards-verification.json), alongside
the [owned XML body](../reports/ocr/owned-PCNbody.xml).

A brief search for a locally executable open-source smartPCN receiver did not
identify one suitable for a reproducible integration test. The publisher's
[format page](https://smartpcn.org/format/) points to a freeware browser editor
and [pcn.inspector](https://om.cockpit.global/inspector/), an online service accepting
`.spcn`/`.zip` containers. Neither was used to upload or process this product's
data. No downstream receiver interoperability test has been executed. Adding a
full transport container and verifying receiver preservation of proprietary
exceptions/evidence remain separate work; the restricted validated XML body is
the supported output here.

Actual OCR verification is recorded separately in
[reports/ocr](../reports/ocr/README.md). All unreviewed OCR and incomplete scan
results were rejected by this exporter, including scans with correctly recovered
dates but incorrectly recognized part identifiers.
