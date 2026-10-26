# Changelog

## 0.1.1 — 2026-10-26 (prepared; publication pending)

- Lead with source-linked review, corrections, BOM matching and export; preserve
  the negative seven-profile ML result (0/19 evidence-valid relationships).
- Add contribution guidance and an independent notice-review trial protocol;
  no authentic supplier evaluation or component-engineer trial is claimed.
- Consolidate current verification, date the old quality audit, add README/source
  URLs to package metadata and include release/contribution/license notices in
  source builds. Update package/API/compiler version metadata consistently.

No schema/database migration or extractor change. Existing saved records retain
their compiler version; newly compiled records report 0.1.1. Frozen experiment
reports remain unchanged.

Quality, evaluation, CPU smoke, frontend format and installed-wheel checks pass.
The standard full suite and browser runs are blocked by runtime socket restrictions;
See [verification and limits](docs/VERIFICATION.md). An ordinary hosted acceptance
run and the owner's licensing decision remain publication gates.

## 0.1.0 — initial implementation

Local evidence-linked extraction, review/BOM/export workflow and optional model
experiments. [Historical quality audit](docs/QUALITY_AUDIT.md) records earlier checks;
no GitHub Release publication date is implied by this entry.
