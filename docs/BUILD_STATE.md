# Build state

Updated 2026-10-14. The scoped local release and resource-supported verification are complete.
The original prompt explicitly permits owned synthetic evaluation and a restricted validated
smartPCN exporter while preserving authentic supplier and engineer-validation gates.

The follow-up quality audit repaired installed resource packaging, delayed-response UI races,
upload blocking, concurrent native PDF calls, API import side effects, worker lifecycle, Host
validation and conflicting reimport coverage. Python and browser code now use checked formatters.
See [QUALITY_AUDIT.md](QUALITY_AUDIT.md) for reproduced failures and fixes, and
[GITHUB.md](GITHUB.md) for source publication and application-hosting instructions.

## Delivered

- CPU-first PDF/text/table extraction with exact identifiers, part-specific dates, scoped footnotes,
  exceptions, exclusions and subset revision history. Ambiguity and missing coverage stay explicit.
- Typed canonical records and schema, immutable originals, SQLite migrations, audited corrections,
  stale-write protection, manufacturer-aware literal BOM matching and actual-XSD-validated export.
- Persisted optional model queue and source-linked proposal review. Explicit accept/reject decisions
  retain original values, reviewer reasons, model/revision/configuration/input/output hashes and
  truncated-context provenance. Uploads always use rules; the default app has no model configured.
- Actual Tesseract OCR with bounded images, engine timeout, literal identifiers and mandatory review.
  Direct export revalidation now rejects changed values that retain stale evidence/status flags.
- Responsive desktop/mobile UI, corrected contrast and target sizes, modal focus wrapping, keyboard
  navigation, source highlighting, useful failure states, JSON/XML downloads and decision history.
- Owned fixtures, permission-aware partner import/annotation, supplier/template/family/duplicate
  split audits, frozen model comparison inputs, reproducible training/serving and study import.
- Pinned dependencies, one-command demo, isolated reset verification, CI configuration, required
  documentation, walkthrough, machine-readable reports, raw outcomes and inspected screenshots.

## Final executed checks

The current workspace `make verify` passed **175 tests with real OCR enabled, no skips**, Ruff
lint/formatting, mypy (19 modules), JavaScript syntax, synthetic evaluation and CPU
training/checkpoint smoke. A clean source-archive installation passed **174 tests plus one
explicitly optional OCR skip**, with the same remaining checks. Installed-wheel verification and
Prettier checks passed. Hosted GitHub CI includes wheel and browser checks; its current status is
available in [Actions](https://github.com/ah682/noticeforge/actions).

Fresh browser checks passed: **22 default workflow**, **22 fixture-model workflow**, **ten delayed
response regressions**, and **19 keyboard** checks. Five fixture-model response-state checks are
labelled mocks. Ten axe scans reported zero violations; one manual-review diagnostic retains
contrast/visibility evidence. This does not claim full WCAG conformance or human usability validation.
The earlier **13 actual pretrained integration checks** and 56-generation matrix remain historical
evidence; they were not repeated or retuned for this maintenance pass.

Run `make demo` at http://127.0.0.1:8877. The quality audit used disposable databases for browser
mutations and did not reset the user's five retained notices or five audit events.
`reports/quality/user-data-preservation.json` records current preservation checks.

## Measured results and decisions

Rules recovered **18/19 exact relationships** and **15/16 parts** on eight owned developmental cases,
with two overlapping omissions, zero unsupported assertions and 102/102 localized citations. The
unsupported ragged row remains a counted failure and requires review. The current native-PDF p95
was **19.24 ms** over 20 small warm requests on a shared Ryzen 7 host; no general throughput claim follows.

Actual pretrained Qwen2.5-0.5B LoRA trained 24 optimizer steps on 16 owned documents in 75.79 seconds.
Validation loss on four disjoint documents worsened slightly (0.322006 to 0.329228). Seven frozen
model profiles covered untuned/adapted FP32, batch two, real CPU INT8 and a larger prompted 1.5B
comparator. **All recovered 0/19 evidence-valid relationships.** Better JSON validity and faster
abstention do not earn deployment. The rules baseline remains the default; model outputs require
source checks and explicit human decisions. No evaluation-feedback retuning was performed.

Actual OCR recovered 2/2 site-transfer, 15/18 discontinuation and 2/6 adversarial identifier
relationships. All 195 populated OCR critical fields require review. Internal localization and
native-source geometry results use different denominators, with mismatches retained in the report.

## External gates

No authentic permitted supplier corpus or completed component-engineer trials were supplied.
Authentic held-out accuracy, real-corpus adaptation, engineer time/quality gains, CUDA/QLoRA
(driver unavailable), paid-provider integration and downstream smartPCN receiver interoperability
remain unperformed. None is substituted with synthetic results. No paid service or supplier
message was involved. No local implementation blocker remains.

See [GitHub and hosting](GITHUB.md) for the repository and static project-page setup. GitHub Pages
cannot host the backend; a live service requires authentication and persistent storage in addition
to a Python host. A project-wide license has not been selected.

Use `make demo` to run and `make verify` to repeat the fast checks. `make reset` intentionally
removes that demo database and its review history. [VERIFICATION.md](VERIFICATION.md) maps every
requirement to implementation, observed evidence and limits; [EVALUATION.md](EVALUATION.md) reports
measured failures; [MODELS.md](MODELS.md) documents the separate actual-model workflow. New model
improvements require separate development data and a new frozen evaluation, not changes to this run.
