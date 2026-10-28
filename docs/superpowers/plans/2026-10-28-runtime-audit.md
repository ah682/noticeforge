# Runtime Audit Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. The parent owns final independent review and publication; no further agents or plan approval are needed.

**Goal:** Repair the five reproduced source-validation and review failures without changing the documented local application scope.

**Architecture:** Keep the current parser, typed requests, repository transactions, and static UI. Validate identifier spans against original page context, bound printed counts, track resolved footnote definitions, and reuse ordinary-review request guards for model decisions.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, SQLite, JavaScript, pytest, Playwright.

**Spec:** The five reproduced failures and repair contracts below; original audit evidence is in `/tmp/noticeforge-ponytail-audit.md`. Parent authorization dated 2026-10-28 covers implementation and assigns independent final review/publication to the parent.

## Global Constraints

- One local process per database; no hosted multi-tenant infrastructure.
- Preserve AGPL, synthetic data boundaries, and the recorded failed model results.
- No dependency upgrades, live mutations, model downloads, full retraining, or push.
- Root owns `.github`, dependency locks, `CONTRIBUTING.md`, and publication.

## Review Focus

- Narrow identifier quotes must not hide leading zeros, suffixes, slash, or surrounding Unicode letters.
- Exact identifiers at page boundaries remain valid; a clipped model page cannot prove a trailing boundary.
- Huge or malformed printed totals produce incomplete-source diagnostics without unbounded allocation.
- Unique cross-page footnotes stay linked; a same-number definition on another page stays independently accountable.
- A late model response must not change a newer dialog, including errors and reloading the same notice.

### Task 1: Exact identifier evidence

**Files:** `noticeforge/providers.py`, `noticeforge/proposals.py`, `tests/test_data_models.py`, `tests/test_model_review.py`.
**Interfaces:** `validate_output(raw, request)` keeps its accepted/rejected return shape. A shared source-span matcher supplies the exact occurrence to `apply_candidate`.

- [x] Add literal cases for narrow `123` inside `ABC-00123/A`, stripped slash suffix, clipped context, oversized evidence end, and valid whole identifiers. Add a persisted invalid-proposal acceptance test and a valid source-occurrence test.
- [x] Run `.venv/bin/python -m pytest tests/test_data_models.py tests/test_model_review.py`; observe the new assertions fail before code changes.
- [x] Match the original page rather than concatenated quotes; reuse the occurrence for new-part evidence. Keep all existing output schema and human-decision requirements.
- [x] Run the same tests; require all to pass. Commit owned task files.

### Task 2: Bounded printed page counts

**Files:** `noticeforge/ingest.py`, `tests/test_robustness.py`.
**Interfaces:** `extract_document(data, filename, expected_pages)` continues returning a `Document` with explicit coverage warnings.

- [x] Add oversized-count and very-long-digit tests in a subprocess with a 256 MiB memory cap, asserting an incomplete document and readable printed-count warning.
- [x] Run `.venv/bin/python -m pytest tests/test_robustness.py -k printed_page`; require failure against current behavior.
- [x] Enforce the existing 1–10000 page-count range before sequence allocation; keep invalid printed labels incomplete.
- [x] Run `.venv/bin/python -m pytest tests/test_robustness.py`; require all to pass. Commit owned task files.

### Task 3: Footnote definition accounting

**Files:** `noticeforge/extraction.py`, `tests/test_robustness.py`.
**Interfaces:** Existing row references resolve by `(page, marker)` or a unique cross-page definition.

- [x] Add `test_unreferenced_reused_footnote_cannot_be_silently_ignored` expecting review and page-2 evidence, plus a valid unique cross-page case.
- [x] Run `.venv/bin/python -m pytest tests/test_robustness.py -k footnote`; require the unused-definition test to fail.
- [x] Record the definitions actually consumed and report the rest as unlinked.
- [x] Run `.venv/bin/python -m pytest tests/test_robustness.py`; require all to pass. Commit owned task files.

### Task 4: Review attribution

**Files:** `noticeforge/models.py`, `tests/test_review_api.py`.
**Interfaces:** `ReviewRequest` accepts meaningful text exactly as `ModelDecisionRequest` does.

- [x] Add parametrized API cases for blank reviewer, blank reason, and a padded reason shorter than three visible characters; assert HTTP 422 and unchanged version/audit.
- [x] Run `.venv/bin/python -m pytest tests/test_review_api.py`; require those assertions to fail before the fix.
- [x] Reuse the existing stripped-text rule in the ordinary review request validator.
- [x] Run the same file; require all to pass. Commit owned task files.

### Task 5: Model decision response ownership

**Files:** `noticeforge/static/app.js`, `scripts/browser-model-review.mjs`.
**Interfaces:** Model decisions use the existing workspace request counter and a dedicated request token/dialog identity, matching ordinary review behavior.

- [x] Extend the fixture browser suite with delayed success and 409 responses after opening a new proposal dialog and after reloading the same notice. Assert the new dialog, source context, enabled submit button, and error state stay intact.
- [x] Run `node scripts/browser-qa.mjs --model --base http://127.0.0.1:8897 --output /tmp/noticeforge-audit-model-red`; require the new race assertions to fail.
- [x] Guard success, error, completion, and busy-state updates with the captured decision context; invalidate/reset on notice load and opening a new decision.
- [x] Run the same suite to a fresh output directory; require all checks to pass. Commit owned task files.

### Final verification

- [x] Run `make verify`, `npm run format:check`, standard browser workflow, existing review/BOM races, and the extended model suite against disposable data.
- [x] Review the diff and record exact outcomes, skipped work, and any rulings in the execution ledger; parent performs independent final review.
- [x] Commit only owned files and return commit SHAs and evidence. Do not publish.

## Observed verification

- Each of the five defects had a failing regression before implementation. Identifier tests produced nine failures, page labels three, footnotes one, attribution three, and all four browser race scenarios failed.
- Final `make verify` passed in `/tmp/noticeforge-runtime-verify-fp3wavqe` with the refreshed default lock: **194 passed, one optional real-OCR skip**, Ruff and formatting, mypy on 19 modules, JavaScript syntax, rules evaluation, and the CPU smoke. Python imports were asserted to come from the snapshot itself.
- Rules evaluation remains **18/19 exact relationships, 15/16 parts, zero unsupported assertions**. Generated reports stayed in the temporary snapshot; published historical reports were not rewritten.
- The working-tree test suite also passed 194 tests with one skip. `npm run format:check` and `git diff --check` passed.
- Final disposable browser checks: 20 standard workflow checks; 10 existing review/BOM races; 23 model workflow checks, five explicitly mocked state checks, and four model decision races. No unexpected browser errors. Evidence is under `/tmp/noticeforge-audit-{browser,races,model}-final`.
- Initial sandbox DNS blocked the isolated Hatchling build; the approved rerun outside the sandbox passed. One upstream Starlette/httpx deprecation warning remains.
- Parent owns independent review and publication. No live model evaluation, full retraining, real supplier evaluation, CUDA, or external smartPCN receiver testing was done. No deferred runtime findings remain from this scoped audit.
