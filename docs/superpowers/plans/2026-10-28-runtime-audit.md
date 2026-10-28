# Runtime Audit Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The parent owns final independent review and publication; no further agents or plan approval are needed.

**Goal:** Repair the five reproduced source-validation and review failures without changing the documented local application scope.

**Architecture:** Keep the current parser, typed requests, repository transactions, and static UI. Validate identifier spans against original page context, bound printed counts, track resolved footnote definitions, and reuse ordinary-review request guards for model decisions.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, SQLite, JavaScript, pytest, Playwright.

**Spec:** `/tmp/noticeforge-ponytail-audit.md`, findings 1–5; parent authorization dated 2026-10-28.

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

- [ ] Add literal cases for narrow `123` inside `ABC-00123/A`, stripped slash suffix, clipped context, oversized evidence end, and valid whole identifiers. Add a persisted invalid-proposal acceptance test and a valid source-occurrence test.
- [ ] Run `.venv/bin/python -m pytest tests/test_data_models.py tests/test_model_review.py`; observe the new assertions fail before code changes.
- [ ] Match the original page rather than concatenated quotes; reuse the occurrence for new-part evidence. Keep all existing output schema and human-decision requirements.
- [ ] Run the same tests; require all to pass. Commit owned task files.

### Task 2: Bounded printed page counts

**Files:** `noticeforge/ingest.py`, `tests/test_robustness.py`.
**Interfaces:** `extract_document(data, filename, expected_pages)` continues returning a `Document` with explicit coverage warnings.

- [ ] Add oversized-count and very-long-digit tests in a subprocess with a 256 MiB memory cap, asserting an incomplete document and readable printed-count warning.
- [ ] Run `.venv/bin/python -m pytest tests/test_robustness.py -k printed_page`; require failure against current behavior.
- [ ] Enforce the existing 1–10000 page-count range before sequence allocation; keep invalid printed labels incomplete.
- [ ] Run `.venv/bin/python -m pytest tests/test_robustness.py`; require all to pass. Commit owned task files.

### Task 3: Footnote definition accounting

**Files:** `noticeforge/extraction.py`, `tests/test_robustness.py`.
**Interfaces:** Existing row references resolve by `(page, marker)` or a unique cross-page definition.

- [ ] Add `test_unreferenced_reused_footnote_cannot_be_silently_ignored` expecting review and page-2 evidence, plus a valid unique cross-page case.
- [ ] Run `.venv/bin/python -m pytest tests/test_robustness.py -k footnote`; require the unused-definition test to fail.
- [ ] Record the definitions actually consumed and report the rest as unlinked.
- [ ] Run `.venv/bin/python -m pytest tests/test_robustness.py`; require all to pass. Commit owned task files.

### Task 4: Review attribution

**Files:** `noticeforge/models.py`, `tests/test_review_api.py`.
**Interfaces:** `ReviewRequest` accepts meaningful text exactly as `ModelDecisionRequest` does.

- [ ] Add parametrized API cases for blank reviewer, blank reason, and a padded reason shorter than three visible characters; assert HTTP 422 and unchanged version/audit.
- [ ] Run `.venv/bin/python -m pytest tests/test_review_api.py`; require those assertions to fail before the fix.
- [ ] Reuse the existing stripped-text rule in the ordinary review request validator.
- [ ] Run the same file; require all to pass. Commit owned task files.

### Task 5: Model decision response ownership

**Files:** `noticeforge/static/app.js`, `scripts/browser-model-review.mjs`.
**Interfaces:** Model decisions use the existing workspace request counter and a dedicated request token/dialog identity, matching ordinary review behavior.

- [ ] Extend the fixture browser suite with delayed success and 409 responses after opening a new proposal dialog and after reloading the same notice. Assert the new dialog, source context, enabled submit button, and error state stay intact.
- [ ] Run `node scripts/browser-qa.mjs --model --base http://127.0.0.1:8897 --output /tmp/noticeforge-audit-model-red`; require the new race assertions to fail.
- [ ] Guard success, error, completion, and busy-state updates with the captured decision context; invalidate/reset on notice load and opening a new decision.
- [ ] Run the same suite to a fresh output directory; require all checks to pass. Commit owned task files.

### Final verification

- [ ] Run `make verify`, `npm run format:check`, standard browser workflow, existing review/BOM races, and the extended model suite against disposable data.
- [ ] Review the diff and record exact outcomes, skipped work, and any rulings in the execution ledger; parent performs independent final review.
- [ ] Commit only owned files and return commit SHAs and evidence. Do not publish.
