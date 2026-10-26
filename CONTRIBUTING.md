# Contributing

Start with the [README](README.md), [current verification](docs/VERIFICATION.md)
and [limitations](docs/LIMITATIONS.md). This is a maintained local engineering
demonstration; no response-time or production-support commitment is offered.

For a bug, open an issue with the source revision, Python/OS versions, exact
command, expected/actual result and a minimal permitted synthetic case. Include
relevant errors; remove credentials, private notices and payment/customer data.
Use GitHub's private vulnerability reporting if enabled for security-sensitive
reports; do not publish a working exploit or sensitive data in a public issue.

Keep pull requests focused. For a behavior fix, first add a regression test that
fails on the original source, then run the existing full checks:

```bash
make verify
npm ci
npm run format:check
make distribution-check
```

Describe the failing example, fix, commands/results and any checks you could not
run. Documentation-only edits need accurate commands and working relative links.
Discuss broad parser/model changes before investing in them. Preserve provenance,
unknown outcomes, original records and third-party notices. Do not tune a frozen
evaluation to make a score improve; add development cases and reserve new holdouts.

Independent trials are welcome using the [evaluation protocol](docs/EXTERNAL_EVALUATION.md).
No independent onboarding or user trial is claimed by this guide. Project-wide
licensing is still pending an owner decision; existing third-party terms apply.
