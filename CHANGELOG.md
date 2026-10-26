# Changelog

## 0.1.1 — 2026-10-26 (prepared; release publication pending)

- Lead with source-linked review, corrections, BOM matching and export; preserve
  the negative seven-profile ML result (0/19 evidence-valid relationships).
- Add contribution guidance and an independent notice-review trial protocol;
  no authentic supplier evaluation or component-engineer trial is claimed.
- Consolidate current verification, date the old quality audit, add README/source
  URLs to package metadata and include release/contribution/license notices in
  source builds. Update package/API/compiler version metadata consistently.
- Pin the acceptance runner to Ubuntu 24.04 for the locked Playwright browser
  dependencies. Record the successful ordinary hosted suite and browser checks.

No schema/database migration or extractor change. Existing saved records retain
their compiler version; newly compiled records report 0.1.1. Frozen experiment
reports remain unchanged.

Quality, evaluation, CPU smoke, frontend format and installed-wheel checks passed
locally. The ordinary hosted full suite and browser workflows subsequently passed
at `e7413a11c799b86295f20e01079d9aba87d2f42b`, resolving the restricted local
suite/browser gap. See [exact runs, scope and limits](docs/VERIFICATION.md). The
owner's licensing decision remains a release-publication gate; later source
revisions require their own checks.

## 0.1.0 — initial implementation

Local evidence-linked extraction, review/BOM/export workflow and optional model
experiments. [Historical quality audit](docs/QUALITY_AUDIT.md) records earlier checks;
no GitHub Release publication date is implied by this entry.
