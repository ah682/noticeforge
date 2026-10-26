# Contributing

The [walkthrough](docs/WALKTHROUGH.md) is a useful way to get familiar with notice
review, BOM matching and export. The [architecture](docs/ARCHITECTURE.md) maps those
workflows to the Python modules.

For an extraction bug, include a small notice you can share, the expected
part/date relationships and the actual result. Record the source revision,
Python/OS versions and command. Use fictional identifiers when reproducing a
problem from a private supplier notice, and remove credentials from logs.
Security-sensitive reports belong in private vulnerability reporting when available.

Add a regression case for behavior changes, then run:

```bash
make verify
npm ci
npm run format:check
make distribution-check
```

UI changes should also run the browser workflow and delayed-response checks
listed in the [README](README.md#development). Describe the problem, changes and
check results in the pull request, including anything you could not run.
Documentation edits need working links and accurate commands.

Keep original records and review history intact. New extraction rules must retain
uncertainty and cite the source for each relationship. Use development fixtures
for parser and prompt changes; preserve frozen experiment results and reserve
new holdouts for later model comparisons. The [trial protocol](docs/EXTERNAL_EVALUATION.md)
covers independent engineer reviews.

Original code and documentation use [AGPL-3.0-only](LICENSE). Fixture, schema and
dependency terms are listed in [NOTICE](NOTICE).
