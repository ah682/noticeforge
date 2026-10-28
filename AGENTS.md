# Working on NoticeForge

Read [CONTRIBUTING.md](CONTRIBUTING.md), the [architecture](docs/ARCHITECTURE.md),
and the [quality audit](docs/QUALITY_AUDIT.md) for the supported local workflow
and current evidence.

- Reproduce an observed problem before changing behavior. Add the smallest
  regression that fails for the right reason, repair the existing boundary, run
  the relevant checks, then obtain fresh independent review for substantive work.
  Use Ponytail and the relevant Superpowers skills when available; existing user
  authorization governs routine implementation.
- Preserve original source records, immutable review history, version checks and
  meaningful reviewer/reason attribution. Model candidates stay separate until
  explicitly reviewed; never turn rejected evidence into canonical facts.
- Match complete identifiers, including leading zeros and suffixes, against
  page-local source spans. Missing pages, truncated context and unlinked
  footnotes must retain uncertainty rather than imply complete coverage.
- Guard asynchronous UI results by request, workspace and dialog identity.
  Extend the existing browser suites for delayed successes and errors; use
  disposable databases and the offline fixture provider.
- Run `make verify` for Python/runtime changes, `npm run format:check` for
  JavaScript changes, and the relevant browser commands from the audit for UI
  changes. Packaging changes also need `make distribution-check`. Workflow edits
  need actionlint and their affected commands. Documentation-only edits need
  link, command and claim checks, not model training.
- Keep default CPU dependencies separate from the optional ML environment. Use
  [MODELS.md](docs/MODELS.md) for the hashed CPU compatibility profile; record
  exact versions and fresh output paths without overwriting historical reports.
  A tiny-model smoke establishes API compatibility, not extraction performance.
- Use owned synthetic or explicitly permitted inputs. Do not enable remote
  model transfer, download weights, retrain a frozen experiment or reset
  non-disposable data as an incidental maintenance step. Keep the documented
  single-process scope and restricted smartPCN body export claims accurate.
- Preserve [AGPL-3.0-only](LICENSE), [NOTICE](NOTICE), dataset provenance,
  source-linked uncertainty and the historical failed model comparisons. Report
  checks actually run, skips and remaining limits without upgrading old results
  into new evidence.
