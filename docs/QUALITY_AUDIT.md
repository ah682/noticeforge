# Historical quality audit — 14 October 2026

This dated record describes the 14 October local repair pass. See
[VERIFICATION.md](VERIFICATION.md) for current checks. These results do not establish
authentic supplier accuracy, useful learned extraction or engineer time savings.

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
Behavior fixes were tested separately. Existing domain names and module boundaries were retained;
no speculative framework rewrite or generic helper layer was added. Authorship cannot be inferred
reliably from code style; the improvement is readability and maintainability.

`make format`, Python format checks in `make verify`, and `npm run format:check` keep this consistent.

## Fresh verification

| Check | Observed result |
| --- | --- |
| Full workspace verification with actual Tesseract | 175 tests passed, zero skips; Ruff, mypy across 19 modules, JavaScript syntax, evaluation and CPU smoke passed. |
| Fresh source archive in `/tmp/noticeforge-clean-quality/noticeforge-0.1.0` | Locked install; 174 tests passed, one explicitly optional OCR skip; remaining verification checks passed. |
| Built/installed wheel | Five demo notices, eight evaluation cases, CPU checkpoint, genuine COGD-XSD export and all UI assets passed outside the source checkout. |
| Default browser workflow | 22 checks passed; desktop/mobile screenshots inspected; no page overflow or unexpected JavaScript errors. |
| Offline model browser workflow | 22 checks passed plus five explicitly mocked response-state checks. This does not claim live model quality. |
| Delayed-response regressions | Ten passed. Successful responses come from the real API; error responses are explicitly mocked 409s. |
| Keyboard/accessibility | 19 keyboard checks passed; ten axe scans with zero violations. One native-dialog overlap diagnostic remains, with measured contrast and unobscured-point evidence. |
| Actual OCR | Repeated the eight owned raster fixtures once with Tesseract 5.3.4; earlier three-repetition results remain available separately. Recognition errors and incomplete mixed-image coverage remain explicit. |
| CI configuration | YAML and shell syntax checked; equivalent local commands exercised. No hosted GitHub Actions run yet. |

Current detailed browser/OCR reports are in `reports/quality/`. One upstream Starlette/httpx
deprecation warning remains; it does not fail the suite. The benchmark uses 20 small warm native
PDF requests and 30 text requests on the shared host; see `reports/pipeline-benchmark.json` for
measured latency and memory rather than treating those figures as a general service guarantee.

## Completion boundary

The local demonstration uses owned synthetic data and a restricted validated smartPCN body exporter.
Acceptance cases are mapped in [VERIFICATION.md](VERIFICATION.md). Rules still
recover 18/19 exact relationships and 15/16 parts on the eight developmental cases. The ragged-row
omission is a counted failure and requires review; it was not patched to improve the frozen score.

The earlier real pretrained comparison remains negative: all seven profiles recovered 0/19
evidence-valid relationships. It was neither rerun nor retuned during this maintenance pass.
Authentic permitted supplier evaluation, real-corpus adaptation, CUDA/QLoRA, downstream receiver
interoperability and a component-engineer study remain external validation gates.

This audit predates GitHub publication. See the [hosting guide](GITHUB.md) for the repository,
project page, and deployment setup. GitHub Pages cannot run the Python/SQLite backend. A live
shared service additionally needs authentication, authorization, durable storage, and deployment
operations described in that guide. A project-wide application license has not been selected.
