What this repo does: NoticeForge extracts semiconductor change notices into source-linked records, keeps local review history, matches parts to a BOM, and exports JSON or a restricted smartPCN body. Optional model proposals remain separate until a reviewer accepts them. This audit assumes the documented single-process, single-reviewer local application.

**Audit date:** 28 October 2026. **Method:** Ponytail 5.3.2 and relevant Superpowers 7.0.1 skills. The audit followed input, evidence, review, persistence and browser-response boundaries, reproduced concrete failures, and checked small repairs with failing-then-passing regressions. Final integration review and hosted execution of the revised workflows are pending. The earlier audit is retained below as a dated record.

## Must fix — resolved

1. **Partial identifiers pass model evidence validation** ([providers.py](../noticeforge/providers.py), [proposals.py](../noticeforge/proposals.py)).
   - **What this is:** An accepted proposal must cite the complete literal part identifier before creating or changing a canonical part.
   - **Reproduced problem:** Source `ABC-00123/A | 2027-01-15` supported proposals for both `ABC-00123` and a narrowly quoted `123`. Validation checked the quote's boundary rather than the surrounding source and omitted slash suffixes.
   - **Small fix and outcome:** Match the identifier against the original page and reuse that occurrence when applying it. [Evidence tests](../tests/test_data_models.py) and [acceptance tests](../tests/test_model_review.py) cover suffixes, leading zeros, Unicode boundaries, invalid offsets and clipped context while preserving complete identifiers.
   - **If it regresses:** A citation can appear valid while approval creates a part that never appeared in the notice.

2. **A printed page count can exhaust memory** ([ingest.py](../noticeforge/ingest.py)).
   - **What this is:** Printed page labels contribute to incomplete-source detection.
   - **Reproduced problem:** `Page 1 of 1000000000` allocated the entire expected page-number set; a subprocess capped at 256 MiB raised `MemoryError`.
   - **Small fix and outcome:** Validate counts against the supported 1–10000 range before allocation and catch excessively long integer strings. [Bounded-memory regressions](../tests/test_robustness.py) require explicit incomplete-source warnings, never a fabricated claim of full coverage.
   - **If it regresses:** One malformed upload can stop the local app and interrupt review work.

3. **Reused footnote numbers hide unlinked deadlines** ([extraction.py](../noticeforge/extraction.py)).
   - **What this is:** Footnote definitions belong to a page, with a unique cross-page fallback for references.
   - **Reproduced problem:** Page 1 used `[1]`, while an unreferenced `[1]` on page 2 supplied a different deadline. The second definition was treated as consumed and the record remained supported without a warning.
   - **Small fix and outcome:** Track the actual `(page, marker)` definitions resolved by row references. [Regressions](../tests/test_robustness.py) keep the unused definition visible and preserve legitimate unique cross-page links.
   - **If it regresses:** A missed deadline can be exported as confidently supported extraction.

4. **A late model decision changes a newer review dialog** ([app.js](../noticeforge/static/app.js)).
   - **What this is:** A reviewer can close a pending model decision and open another proposal or reload the notice.
   - **Reproduced problem:** Delaying the first acceptance response, pressing Escape, then opening a rejection dialog let the old response close the new dialog. Late errors could also overwrite its error state.
   - **Small fix and outcome:** Guard success, error and busy-state updates with the request token, workspace generation and decision identity. Four [browser regressions](../scripts/browser-model-review.mjs) cover delayed success and mocked 409 errors across new dialogs and same-notice reloads; all failed before the fix and now pass.
   - **If it regresses:** A completed request discards unrelated in-progress review context.

5. **Ordinary reviews accept blank audit attribution** ([models.py](../noticeforge/models.py)).
   - **What this is:** Every correction or acceptance requires a reviewer and meaningful reason.
   - **Reproduced problem:** Whitespace-only reviewer/reason values advanced the record version and persisted an unusable audit event.
   - **Small fix and outcome:** Apply the existing stripped-text rule used by model decisions. [API regressions](../tests/test_review_api.py) require HTTP 422 and unchanged record version and audit history.
   - **If it regresses:** Accepted facts lose the attribution needed to explain a review decision.

## Should fix — resolved

6. **The optional compatibility fixture loses text on tokenizer reload** ([training.py](../noticeforge/training.py)).
   - **What this is:** A tiny random model exercises the real training and serving APIs after optional dependency updates.
   - **Reproduced problem:** Transformers 5 reinterpreted the old generic toy tokenizer and dropped the prompt, making the smoke fixture unsuitable for checking prompt masking and target supervision.
   - **Small fix and outcome:** Use the matching Qwen2 byte tokenizer. The [optional regression](../tests/test_ml_compatibility.py) checks text round-trip, a nonempty prompt, supervised target positions, changed adapter weights and serving reload. The fresh CPU compatibility run passes.
   - **If it regresses:** A compatibility check can stop exercising the text and labels that real training depends on.

## Verification and process changes

| Check | Baseline | After repairs |
| --- | --- | --- |
| Default Python suite | 174 passed, one optional OCR skip | 194 passed, two skips after adding the optional ML test: optional ML libraries are not installed and the opt-in real-OCR check was not enabled |
| `make verify` | Existing acceptance command | Passed after runtime repairs: 194 passed, one OCR skip, Ruff/formatting, mypy on 19 modules, JavaScript syntax, rules evaluation and CPU smoke |
| Rules evaluation | 18/19 relationships, 15/16 parts | Unchanged; zero unsupported assertions |
| Actual Chrome workflows | Existing standard/review suites | 20 standard checks, 10 review/BOM races, 23 model checks, five mocked response-state checks and four new model-decision races passed |
| Installed wheel | Existing distribution check | Five demo notices, eight evaluation cases, CPU checkpoint, XSD export and UI assets passed outside the checkout |
| Optional CPU compatibility | Historical record retained separately | 24 LoRA steps: loss 4.1541605 → 3.7332263, exact adapter reload with zero maximum logit difference; actual training/serving path completed two optimizer steps and reloaded the adapter |

The [runtime plan](superpowers/plans/2026-10-28-runtime-audit.md) records the regression commands and runtime verification. The new [CPU compatibility report](../reports/quality/ponytail-ml-compatibility/compatibility_report.json) records its stack and limits. Reproduce the default checks from a disposable checkout when preserving historical generated reports:

```sh
make verify
npm ci
npm run format:check
make distribution-check
```

For browser checks, start a disposable local server in one terminal, then run the checks in another:

```sh
NOTICEFORGE_DATA_DIR=/tmp/noticeforge-browser-check .venv/bin/python -m noticeforge.cli demo
```

```sh
node scripts/browser-qa.mjs --output reports/browser-check
node scripts/browser-qa.mjs --races --output reports/browser-races-check
```

Use a second disposable server for the offline model-review fixtures:

```sh
.venv/bin/python scripts/model_review_demo.py --data-dir /tmp/noticeforge-model-check --port 8878
```

```sh
node scripts/browser-model-review.mjs --base http://127.0.0.1:8878 --output reports/model-browser-check
```

The browser scripts need Chrome/Chromium; set `CHROME_PATH` when necessary. Stop the servers after checking. [CI](../.github/workflows/ci.yml) runs these workflows, including the new delayed-decision assertions, and the optional CPU test commands in [MODELS.md](MODELS.md#optional-compact-model).

Default dependency repairs update Pillow to 13.0.0 and certifi to 2026.10.19. The optional CPU profile now has a hashed lock and a separate compatibility check. The [full optional dependency audit](../reports/quality/ponytail-ml-compatibility/dependency-audit.json) checked 54 packages and skipped the non-PyPI `torch` CPU build; the [direct public-release audit](../reports/quality/ponytail-ml-compatibility/direct-dependency-audit.json) checked all eight direct pins, including public Torch 2.13.0. Both reported zero known vulnerabilities in the checked packages. The default audit likewise skips the local NoticeForge package, which is covered by code tests. These are advisory checks at the recorded date, not a guarantee about undiscovered vulnerabilities.

Verification jobs now use pinned action commits, read-only repository permissions, time limits, cancellation of superseded runs, browser checks and actionlint. [Dependency audits](../.github/workflows/dependencies.yml) run on pushes, pull requests and weekly schedules; [Dependabot](../.github/dependabot.yml) proposes action and npm updates. Hosted results for the revised workflows are pending.

Verdict: The five reproduced runtime defects and the optional tokenizer compatibility defect are fixed. Source-linked review, explicit uncertainty and the local deployment scope remain intact. The new compatibility result establishes CPU API behavior only; the historical pretrained comparison still recovered 0/19 evidence-valid relationships in all seven profiles.

Not checked: Authorized real supplier evaluation, new pretrained-model extraction scores, real-corpus adaptation, CUDA/QLoRA, remote-provider integration, hostile-document sandboxing, external smartPCN receiver interoperability, or a new human accessibility study. The exporter remains a restricted smartPCN body implementation, not a complete archive implementation. Frozen experiments were not retuned or relabelled. [AGPL-3.0-only](../LICENSE), synthetic fixture boundaries and [third-party notices](../NOTICE) are preserved.

---

# Historical quality audit — 14 October 2026

This dated record describes the 14 October local repair pass. See
[VERIFICATION.md](VERIFICATION.md) for later checks.

## Fixed findings

| Finding | Change and evidence |
| --- | --- |
| Installed CLI could not find fixtures/configuration | Bundle fixtures, configurations and attributed schemas under the package; centralize their location. The old wheel failed `seed`; the new installed wheel passes seed, evaluation, CPU smoke, XSD export and UI asset checks outside the checkout. |
| Late BOM/review results changed the wrong notice | Capture notice, workspace request and review context before awaiting. Eight browser regressions failed before the fix; ten now pass, including same-notice reload and newer-request ordering. |
| PDF uploads blocked the web event loop | Offload parsing and persistence. Regression tests pause each operation while verifying the event loop remains available. |
| Concurrent worker calls could overlap native PDF operations | Serialize complete native PDF lifetimes across parsing, OCR and rendering. A synchronization test failed before the lock and passes with actual parsed records and a rendered PNG; text ingestion remains available. |
| API import touched an unrelated default database | Remove the module-level app instance. Import no longer interrupts queued work in an unselected database. The supported ASGI entry is the `create_app` factory. |
| Model workers lacked application shutdown cleanup | Recover interrupted jobs at application startup, drain work at shutdown, and reject new submissions after close without persisting orphaned requests. |
| Matching an arbitrary Host and Origin bypassed local request protection | Validate Host against loopback names or explicitly configured names before the same-origin check. IPv4, IPv6, configured-proxy and rejected-origin/host tests pass. |
| Reimport silently discarded conflicting coverage information | Return a conflict for identical bytes with a different expected page count; preserve original/current records and review history. |

Two independent initial reviews reproduced defects. A separate final reviewer inspected the
substantive changes and found no remaining Critical or Important issue within the local scope.
Execution additionally caught an overbroad source-directory guard in the new distribution check:
the uv cache is inside this checkout. The guard now rejects the actual editable package while
allowing an installed wheel in that cache, and `make distribution-check` passes.

## Readability

Applied Ruff formatting to Python and pinned Prettier 3.9.10 to the static UI/browser scripts.
Long compound statements and object literals now have conventional indentation and line breaks.
The 35 Python syntax trees were identical immediately before and after mechanical formatting.
Behavior fixes were tested separately, keeping the existing domain names and
module boundaries.

`make format`, Python format checks in `make verify`, and `npm run format:check` keep this consistent.

## Fresh verification

| Check | Observed result |
| --- | --- |
| Full workspace verification with actual Tesseract | 175 tests passed, zero skips; Ruff, mypy across 19 modules, JavaScript syntax, evaluation and CPU smoke passed. |
| Fresh source archive in `/tmp/noticeforge-clean-quality/noticeforge-0.1.0` | Locked install; 174 tests passed, one explicitly optional OCR skip; remaining verification checks passed. |
| Built/installed wheel | Five demo notices, eight evaluation cases, CPU checkpoint, COGD-XSD export and all UI assets passed outside the source checkout. |
| Default browser workflow | 22 checks passed; desktop/mobile screenshots inspected; no page overflow or unexpected JavaScript errors. |
| Offline model browser workflow | 22 fixture-provider checks passed plus five mocked response-state checks. |
| Delayed-response regressions | Ten passed. Successful responses come from the real API; error responses are explicitly mocked 409s. |
| Keyboard/accessibility | 19 keyboard checks passed; ten axe scans with zero violations. One native-dialog overlap diagnostic remains, with measured contrast and unobscured-point evidence. |
| Actual OCR | Repeated the eight owned raster fixtures once with Tesseract 5.3.4; earlier three-repetition results remain available separately. Recognition errors and incomplete mixed-image coverage remain explicit. |
| CI configuration | YAML and shell syntax checked; equivalent local commands exercised. No hosted GitHub Actions run yet. |

Current detailed browser/OCR reports are in `reports/quality/`. One upstream Starlette/httpx
deprecation warning remains; it does not fail the suite. The benchmark uses 20 small warm native
PDF requests and 30 text requests on the shared host; see `reports/pipeline-benchmark.json` for
the measured latency, memory and workload.

## Evaluation results and follow-up

The local demonstration uses owned synthetic data and a restricted validated smartPCN body exporter.
Acceptance cases are mapped in [VERIFICATION.md](VERIFICATION.md). Rules still
recover 18/19 exact relationships and 15/16 parts on the eight developmental cases. The ragged-row
omission is a counted failure and requires review; it was not patched to improve the frozen score.

The earlier real pretrained comparison remains negative: all seven profiles recovered 0/19
evidence-valid relationships. It was neither rerun nor retuned during this maintenance pass.
Authentic permitted supplier evaluation, real-corpus adaptation, CUDA/QLoRA, downstream receiver
interoperability and a component-engineer study still need separate evaluation.

This audit predates GitHub publication. See the [hosting guide](GITHUB.md) for the repository,
project page, and deployment setup. GitHub Pages cannot run the Python/SQLite backend. A live
shared service additionally needs authentication, authorization, durable storage, and deployment
operations described in that guide. Original code and documentation are now
licensed under [AGPL-3.0-only](../LICENSE); see [NOTICE](../NOTICE) for third-party terms.

## Hosted verification — 28 October 2026

Reviewed implementation and workflow revision: `2f4a6f243d1a214ab0eff66aa6521315a0ca8279`.
[Verification](https://github.com/ah682/noticeforge/actions/runs/40670050784) and
[dependency auditing](https://github.com/ah682/noticeforge/actions/runs/40670050595) both passed.
The run artifacts retain the generated test/browser evidence for 14 days.
Subsequent documentation-only commits do not change this tested implementation.
