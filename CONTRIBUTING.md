# Contributing

The [walkthrough](docs/WALKTHROUGH.md) is a useful way to get familiar with notice
review, BOM matching and export. The [architecture](docs/ARCHITECTURE.md) maps those
workflows to the Python modules.

For an extraction bug, include a small notice you can share, the expected
part/date relationships and the actual result. Record the source revision,
Python/OS versions and command. Use fictional identifiers when reproducing a
problem from a private supplier notice, and remove credentials from logs.
Security-sensitive reports belong in private vulnerability reporting when available.

Start with an observed failure and the smallest shareable reproduction. For a
behavior change, add a focused regression and observe it fail, repair the existing
boundary, then run the relevant checks. When Ponytail and Superpowers are
available, use Ponytail's evidence-first audit and the relevant Superpowers
debugging, test-first, planning and verification skills. Seek a fresh independent
review of substantive changes after the checks pass. This process adds no new
approval gate to already-authorized work.

The default acceptance commands are:

```bash
make verify
npm ci
npm run format:check
```

`make verify` writes evaluation and smoke reports. Use a disposable checkout or
fresh explicit output paths when comparing against preserved dated evidence.
Run `make distribution-check` for packaging, resource-loading or release changes;
it exercises the installed wheel outside the source checkout.

UI changes should also run the browser workflow and relevant delayed-response
checks in the [quality audit](docs/QUALITY_AUDIT.md#verification-and-process-changes)
or [README](README.md#development). Use disposable data and include success,
error, notice-switch and same-notice-reload cases when asynchronous state changes.
The offline model suite requires no downloaded model. Changes to optional ML
APIs need the separate CPU compatibility commands in
[MODELS.md](docs/MODELS.md#optional-compact-model); real extraction and GPU results
require their own experiments. Workflow edits need actionlint and the affected
commands from [CI](.github/workflows/ci.yml).

Describe the problem, change and actual check results in the pull request,
including skips and anything not run. Documentation-only edits need accurate
commands, claims and working links; they do not require retraining or the full
browser suite.

Keep original records and review history intact. New extraction rules must retain
uncertainty and cite the complete literal identifier, date and applicable
exception for each relationship. Do not claim full coverage for incomplete or
truncated sources. Model proposals require explicit human decisions; uploads
must not silently call a model or send documents to a remote service. Use
development fixtures for parser and prompt changes; preserve frozen experiment results and reserve
new holdouts for later model comparisons. The [trial protocol](docs/EXTERNAL_EVALUATION.md)
covers independent engineer reviews.

The supported app is one local process per database. Keep demo resets and browser
fixtures in disposable data directories. Preserve the restricted smartPCN body
scope and the recorded failed model results; a compatibility smoke or synthetic
score does not establish supplier-document accuracy.

Original code and documentation use [AGPL-3.0-only](LICENSE). Fixture, schema and
dependency terms are listed in [NOTICE](NOTICE).
