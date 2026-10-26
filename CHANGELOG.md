# Changelog

## 0.1.1 — 2026-10-26

- Update the review, BOM and export walkthroughs and document the seven-profile
  model comparison (0/19 evidence-valid relationships).
- Add contribution guidance and a protocol for independent notice-review trials.
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
at `e7413a11c799b86295f20e01079d9aba87d2f42b`, after the local runner could not
open sockets. See the [verification record](docs/VERIFICATION.md). Original code
and documentation now use AGPL-3.0-only, with third-party terms in NOTICE.

## 0.1.0 — initial implementation

Local evidence-linked extraction, review/BOM/export workflow and optional model
experiments. The [14 October quality audit](docs/QUALITY_AUDIT.md) records the
earlier checks.
