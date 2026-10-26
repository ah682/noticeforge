# Verification

Software behavior, extraction accuracy, XML validity and usefulness to component
engineers are measured separately.

## Local maintenance checks — 26 October 2026, v0.1.1

Fresh checkout; Python 3.12.3, uv 0.11.28, Node 24.16.0. A network `uv sync`
failed DNS. Copying public package caches into this checkout then running
`uv sync --frozen --offline` installed the locked environment. `npm ci --offline`
likewise used copied exact-integrity public package blobs. No reference source
or environment was changed. This is cached installation evidence, not an
independent unaided trial or a new network-install result.

| Command/check | Observed result |
| --- | --- |
| Standard `make verify` | **Incomplete**: stopped during the threadpool lifecycle test; runtime denies asyncio socketpair wakeup sends (`EPERM`). A dependency-free cross-thread callback probe reproduced the restriction. |
| `make check evaluate smoke` | Ruff lint/format, mypy (19 files), JS syntax, eight-case synthetic evaluation and CPU checkpoint smoke passed. |
| `npm run format:check` | Passed. |
| `UV_OFFLINE=1 make distribution-check` | Built wheel/source archive; installed wheel passed five-notice seed, eight-case evaluation, CPU checkpoint, genuine XSD export and UI asset checks outside source. |
| Wheel/source archive inspection | README and source URLs present; fixture CC0 records and original schema hashes retained; generated data/caches absent. |
| `npm run test:pages` | Blocked before browser checks: loopback listener returns `EPERM`. Browser workflows/races were not rerun in this environment. |

The ordinary full suite and browser checks remain release gates for an unrestricted
runner; the Actions workflow already runs them. The optional real OCR engine was
not installed here. Pretrained inference, LoRA/CUDA, remote model APIs and user
trials were not rerun. The CPU smoke trains a tiny compatibility classifier,
not the pretrained domain model. No new hosted run or published release is claimed.

The results below are **historical 14 October evidence**, not new v0.1.1 tests.

## Reproduce the checks

```bash
make verify
npm ci
npm run format:check
make distribution-check
```

`make verify` runs tests, Ruff, mypy, JavaScript syntax checks, the frozen evaluation, and the
CPU training smoke. `make distribution-check` builds an archive and wheel, then exercises the
installed package outside the checkout, including fixture loading, evaluation, training, XML
export, and UI assets.

For browser checks, start a disposable demo in another terminal:

```bash
NOTICEFORGE_DATA_DIR=/tmp/noticeforge-browser-check make demo
# In another terminal:
npm run test:browser
npm run test:races
npm run test:pages
```

Use `CHROME_PATH` to select a Chrome installation. The Actions workflow installs its own
Playwright Chromium and stores the reports with the run.

## Historical local results — 14 October 2026

| Check | Result |
| --- | --- |
| Python suite with the real OCR engine configured | 175 passed, no skips |
| Clean source-archive environment without optional OCR | 174 passed, one OCR skip |
| Ruff formatting and lint, mypy, JavaScript syntax, Prettier | Passed |
| Installed-wheel acceptance | Five demo notices, eight evaluation cases, CPU checkpoint, XSD export, and UI assets verified |
| Application browser workflow | 22 checks passed |
| Delayed-response browser regressions | Ten checks passed |
| Offline model review workflow | 22 checks passed; five additional response states explicitly mocked |
| Keyboard and automated accessibility | 19 keyboard checks; no axe violations in ten states |

The accessibility run retained one manual-review diagnostic. Sampled evidence text had 5.38:1
contrast and nine unobscured points; this is not a claim of complete WCAG conformance.

Evidence is in [the quality audit](QUALITY_AUDIT.md), [the machine-readable summary](../reports/verification.json),
and `reports/quality/`. The pretrained model matrix and actual-model browser run are earlier
experiments; they were not rerun for the maintenance fixes. Current hosted checks are visible in
[GitHub Actions](https://github.com/ah682/noticeforge/actions).

## Acceptance cases

| Case | Verified behavior |
| --- | --- |
| Two groups with different last-buy dates | Each deadline stays attached to its own parts. |
| Inventory exception for one part | Condition stays on that part; an exact XML deadline remains blocked. |
| Row footnote changes a deadline | Only the marked part/date changes. |
| Revision supersedes a subset | Earlier parts outside its scope survive; originals remain immutable. |
| Ambiguous slash date | Acceptance is blocked until a sourced correction is recorded. |
| Leading zeros, suffixes, and OCR confusion | Literal identifiers are not merged; uncertain OCR values require review. |
| Missing pages or truncated context | Incomplete coverage stays visible after review and export. |
| Evidence links | Text offsets and PDF regions are checked; invented values are rejected. |
| Replacement suggestions | Compatibility is explicitly not assessed. |
| BOM matching | Identifier and manufacturer determine literal, ambiguous, and unmatched results. |
| XML export | Supported bodies pass the pinned COGD XSD 3.08; invalid bodies fail. |
| Dataset leakage | Split overlap, changed hashes, incomplete annotations, and missing permission references fail validation. |
| Instructions inside notices | Uploaded text cannot change the schema; markup is rendered as text. |

Tests also cover database migrations and rollback, stale edits, queued model work, provider
timeouts, host/origin checks, native PDF serialization, duplicate uploads, and application shutdown.

## Extraction and model results

The rules baseline recovered **18/19 exact part/date relationships** and **15/16 exact parts**
across eight fictional development cases, with zero unsupported assertions. A ragged table row
remains a counted omission. All 102 native evaluation citations localized, which does not by
itself prove semantic accuracy. See [Evaluation](EVALUATION.md).

Actual Tesseract 5.3.4 runs cover eight owned scan variants. All 195 populated critical OCR fields
require review. Internal bounds/offset checks passed for 201/201 evidence entries; 180/185
native-comparable regions intersected their matching text. The different denominators measure
different properties. Recognition errors and omitted relationships remain in the [OCR report](../reports/ocr/report.json).

Pretrained LoRA training changed adapter weights, but all seven measured model profiles recovered
**0/19 evidence-valid relationships**. Those models are not the default. Raw outcomes, latency,
memory, batch, and quantization results are retained in the [comparison](../reports/model-verification/comparison.txt).
An actual-model browser run exercised queue, review, history, and export behavior and rejected an
invalid-evidence proposal; it did not demonstrate useful extraction accuracy.

No authentic authorized supplier corpus or completed component-engineer trials were supplied.
Real supplier holdout accuracy, real-corpus adaptation, engineer time savings, GPU/QLoRA runs,
and downstream smartPCN receiver interoperability remain unverified. The review-study report
contains zero trials and no time-saving estimate.
