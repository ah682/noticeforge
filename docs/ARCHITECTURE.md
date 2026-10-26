# Architecture

NoticeForge runs as one local Python process serving a static accessible browser workspace and a
FastAPI API. SQLite stores the source bytes, immutable original canonical record, latest reviewed
record and audit events. No frontend build or external service is required at runtime.

```text
PDF / UTF-8 text
  -> ingest.py      (bounded text, lines, PDF cells, optional OCR, hash, coverage)
  -> extraction.py  (literal parts, typed date candidates, scoped rows/footnotes/revisions)
  -> validation.py  (evidence, date semantics, omissions, uncertainty and conflicts)
  -> models.py      (extra-forbidden canonical v1 record)
  -> repository.py  (SQLite original/current snapshots and atomic review events)
  -> api.py / static (source/evidence review, BOM, history, downloads)
  -> exporters.py   (canonical JSON or restricted original-XSD-validated smartPCN)

parsed pages -> model_service.py / providers.py -> persisted evidence-checked model proposals
reviewer decision -> proposals.py -> atomic canonical change plus model/version provenance
authorized manifest + annotation -> datasets.py -> training.py / evaluation.py
```

## Evidence and identifiers

Evidence stores a one-based page number, zero-based Unicode character offsets with exclusive end,
an exact quote, extraction method and optional PDF rectangle in points with a top-left origin.
Page text is retained as returned by the local layout extraction, so offsets remain reproducible
after saving. Browser JavaScript converts UTF-16 string positions into Unicode positions before
sending a new selection. PDF cell citations select a text occurrence intersecting the cell bounds.

Identifiers keep case, leading zeros, hyphens, slashes and suffixes. Normalization trims surrounding
whitespace only. Manufacturer matching additionally folds case and repeated whitespace; there is
no fuzzy match or alias database. Duplicate rows are retained and flagged, never silently merged.
Every critical wrapper holds original raw text, current value, evidence, method and review status.

## Relationships and uncertainty

Table columns carry typed last-buy, last-delivery, effective-change, sample, acknowledgment and
end-of-production dates separately. Issue/revision dates remain notice metadata. Footnote keys
include their source page; a unique cross-page definition may be used, while conflicting references
remain unresolved. Multi-deadline footnotes are split by date label and named part scope.

ISO dates and supported month-name formats can normalize. Slash dates remain ambiguous. A
tentative deadline remains tentative. Inventory conditions apply only to the named/marked part;
even a stated cutoff is not represented as guaranteed inventory availability. Missing and malformed
rows, duplicate columns, ambiguous scope and conflicting dates become findings. A source page
limit, text limit, failed OCR, mixed raster content or advertised missing page marks coverage incomplete.

`Source-supported` means a rule linked a value to text under the supported grammar.
Human acceptance is recorded separately, and model proposals remain separate until reviewed.

## Persistence and review

Migration 1 creates `schema_migrations`, `notices`, and `audit`. Document SHA256 deduplicates
identical uploads without overwriting review history. Each review transaction uses `BEGIN IMMEDIATE`
and an expected record version to reject stale writes. Failed validation rolls back the entire
transaction. Reviewable paths must resolve to known critical wrappers, so arbitrary schema edits
are refused. The server derives any newly selected quote from its stored source text.

Migration 2 adds `model_runs` without replacing existing records. Uploads always compile with
rules. The Model review tab explicitly queues an optional model request against a record version;
configuration, input/output hashes, validated and rejected candidates, errors and decisions persist.
One worker executes up to four pending requests, with at most one active request per notice.
Restarted pending jobs become interrupted errors and require an explicit new request.

Proposals cannot edit canonical fields until a reviewer accepts one with a reason and identity.
Acceptance rechecks literal source evidence, requires explicit selection when multiple part/date
targets match, preserves conditional deadlines and commits provenance and audit events atomically.
Unrelated intervening edits make acceptance stale. Rejection is also a durable decision. Canonical
JSON retains the model revision, configuration/input/output hashes and any truncated-context flag.

Revisions never mutate an earlier notice. `/history` resolves explicitly named target notice IDs
inside supplier scope, excludes self-links and retains subset membership. Missing or conflicting
targets/scopes remain unresolved. The UI shows incoming revisions beside original affected parts.
There is no inferred global latest-notice overwrite.

## Export and runtime

Canonical JSON preserves incomplete and unsupported findings; schema validation does not erase
uncertainty. The smartPCN exporter has separate no-loss eligibility checks and actual original
COGD XSD validation. Required standard metadata must be evidenced. Some provenance and conditions
use named extension containers; generic consumers may ignore them. See [smartPCN](SMARTPCN.md).

The default listener binds loopback. Cross-origin mutations are rejected, untrusted strings render
as text, credentials are not stored, and XML disables DTD/entity/network loading. Uploaded notices
are data; prompt-like instructions cannot alter the schema or extraction code. Optional remote
model calls require explicit configuration and data-transfer authorization.

PDF parsing occurs locally in the app process, with input/page/character limits and a 30-second
per-page OCR subprocess timeout. Run one local server per database: the app has no
user accounts, tenant isolation, document sandbox or distributed worker infrastructure.
