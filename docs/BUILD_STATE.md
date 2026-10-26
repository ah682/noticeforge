# Build status

Use [VERIFICATION.md](VERIFICATION.md) for current checks, [CHANGELOG](../CHANGELOG.md)
for release changes and [LIMITATIONS.md](LIMITATIONS.md) for unsupported inputs
and evaluation work.
[QUALITY_AUDIT.md](QUALITY_AUDIT.md) records the 14 October repair pass and
measurements from that run.

The recorded ordinary hosted acceptance workflow passed at source
`e7413a11c799b86295f20e01079d9aba87d2f42b` in
[runs 40291140321](https://github.com/ah682/noticeforge/actions/runs/40291140321)
and [40291147862](https://github.com/ah682/noticeforge/actions/runs/40291147862).
It includes the full suite, quality/evaluation/CPU smoke, installed distribution,
pipeline benchmark, page accessibility and application browser/race checks on
Ubuntu 24.04. The earlier local attempt was blocked by socket restrictions.
Original code and documentation use [AGPL-3.0-only](../LICENSE); third-party
terms are in [NOTICE](../NOTICE).

The working path is local review with deterministic extraction. The published ML
comparison remains negative: all seven profiles recovered 0/19 evidence-valid
relationships. No authentic supplier evaluation or component-engineer trial has
been completed. See the [external evaluation protocol](EXTERNAL_EVALUATION.md).
