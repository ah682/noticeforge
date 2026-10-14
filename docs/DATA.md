# Data provenance and permitted use

All bundled notices and expected annotations were authored for NoticeForge. Supplier names,
identifiers, addresses and dates are fictional. No manufacturer notices were downloaded for
training/evaluation. `fixtures/development/manifest.json` describes five UI examples;
`fixtures/evaluation/manifest.json` describes separate developmental measurement cases.
`scripts/build_fixtures.py` regenerates the source material and SHA256 manifest entries.
PDF generation uses invariant metadata to produce reproducible files.

Manifest fields record source, permission/license status, supplier, template, complete notice/revision
family, synthetic/real classification, source hash, creation timestamp, transformations and annotation
provenance. Owned fixture content is CC0-1.0. Schema implementation material has separate COGD
ownership and attribution; see `schemas/smartpcn/SOURCE.json`.

The evaluation fixtures use different synthetic suppliers/templates/families from the UI examples.
They still use the documented parser grammar and are developmental cases, not a frozen real-world
test set. The malformed-row case deliberately measures a known unsupported layout and its omission.

`fixtures/model-training/` adds 16 owned synthetic training documents and four separate validation
documents. A combined audit covers those and the eight evaluation cases, holding out suppliers,
templates and complete families and screening near duplicates. Before pretrained-model evaluation,
`reports/model-verification/freeze.json` recorded source, parsed-input, prompt and configuration
hashes. No evaluation feedback changed that matrix. This frozen model comparison still uses
developmental synthetic grammar cases; it does not turn them into an authentic supplier holdout.

## Authorized partner data

Public readability does not establish permission for training or evaluation. TI's
[notice information](https://www.ti.com/quality-reliability/quality/product-change-notification.html)
and [terms of use](https://www.ti.com/legal/terms-conditions/terms-of-use.html) were inspected as
context; no reuse entitlement is inferred from access. A responsible owner must verify the scope
of authorization before importing real notices.

`noticeforge.datasets` implements a typed manifest and JSONL partner annotation format, validates
page-local evidence spans, checks attribution/permissions and imports a contained source package
without overwriting existing material. Real entries require an explicit permission reference.
The full schema and executable commands are in [MODELS.md](MODELS.md).

Hold out whole suppliers/templates and whole revision families. Preparation groups connected
supplier, template, family and near-duplicate pages before assigning splits. Audits reject overlaps
between splits and changed source hashes. Exact normalized equality, word-shingle Jaccard and
bounded token-sequence comparison identify near-duplicate pages; this is a pilot-corpus screen,
not proof against all OCR/paraphrase duplication. Image-only pages need a checked text rendition.

Do not tune prompts, thresholds, model selection or normalization using final-test documents.
Freeze the training and validation configuration before an authentic final test. Training only
consumes explicitly audited `train` annotations; separate validation and final evaluation remain
required. A successful software import cannot validate the legal scope or human annotation quality.

## Engineer review-time workflow

`fixtures/review-study.csv` is an empty trial template. Record pseudonymous participant ID,
document hash, manual/NoticeForge arm, timezone-aware start/end, independently adjudicated critical
errors/omissions and adjudicator ID. Then run:

```bash
.venv/bin/python -m noticeforge.study fixtures/review-study.csv --output reports/review-study
```

The importer validates durations and duplicates, preserves individual trials, and reports only
available paired observations. Empty input reports `unexecuted` and no time-gain statistic. Use
real component engineers, consent for study records, balanced task difficulty and randomized order.
For a same-document crossover, learning is a material confound; use a counterbalanced design and
report quality alongside elapsed time. No such study has been performed for this release.
