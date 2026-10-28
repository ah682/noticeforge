# Verification maintenance plan

> **For agentic workers:** Use superpowers:executing-plans, then independent code review and verification-before-completion.

**Goal:** Make the demonstrated checks repeatable in CI for noticeforge.
**Architecture:** Extend existing GitHub workflows and project commands. Keep the exact experimental environments separate from current tooling.
**Tech stack:** GitHub Actions, actionlint 1.7.12, pip-audit 2.10.1 and the existing project test/browser tools.
**Spec:** README development and evidence contracts; requested Ponytail/Superpowers audit of code, checks and processes.

## Constraints and review focus

- Actions use reviewed release commit hashes and read-only default permissions.
- Hosted jobs have bounded execution time and retain diagnostic evidence on failure.
- Browser checks run against disposable state and include the new delayed-response or missing-evidence regressions.
- Dependency checks fail on known advisories; frozen scientific versions are not silently advanced by an updater.
- Historical reports stay dated; a current passing workflow does not validate real customer data or unsupported hardware.

## Tasks

- [x] Update `.github/workflows/` action versions, permissions, cancellation and evidence retention.
- [x] Run existing browser workflows in CI and validate workflow syntax with actionlint.
- [x] Add `.github/workflows/dependencies.yml` for push/PR and weekly advisory checks; add Actions/npm update proposals in `.github/dependabot.yml` where applicable.
- [x] Verify lock changes through the project suite and dependency audit.
- [x] Document reproducible contributor checks, independent review and exact hosted results.
