# GitHub and hosting

The public source repository is [ah682/noticeforge](https://github.com/ah682/noticeforge). The
[project page](https://ah682.github.io/noticeforge/) contains a workspace preview and local setup
instructions. Its source is in `site/`; `.github/workflows/pages.yml` deploys that directory after
changes are pushed to `main`.

GitHub Pages serves static files. It cannot run the FastAPI backend or store uploaded notices in
SQLite. Run `make demo` locally to use uploads, review decisions, BOM matching, and exports.
See [GitHub's Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages).

## Maintaining the repository

The `local-acceptance` Actions workflow runs the Python checks, installed-wheel verification,
pipeline benchmark, application browser tests, and project-page accessibility checks. Results and
screenshots are attached to each run for 14 days.

Before pushing changes:

```bash
make verify
npm ci
npm run format:check
make distribution-check
```

To check the project page locally, run `npm run test:pages`. Browser checks use Chrome at
`/usr/bin/google-chrome` unless `CHROME_PATH` is set. Pages deployment can also be started from
the **GitHub Pages** workflow's **Run workflow** button. The repository's **Settings → Pages**
publishing source must be **GitHub Actions**.

Keep databases, private notices, `.env` files, credentials, model weights, and caches out of Git.
Reports are ignored by default, with specific exceptions for fictional fixtures and recorded
verification evidence. Review new artifacts before adding them.

## Hosting the full application

A server deployment needs Python 3.12 and persistent storage. The current app has no login or
tenant isolation, so keep it local or behind an enforced private access gateway. Review labels
are not authenticated identities.

The runtime contract is:

- Install with `uv sync --frozen --no-dev`.
- Set `NOTICEFORGE_DATA_DIR` to a persistent directory and run one serving process per database.
- Start with `.venv/bin/uvicorn noticeforge.api:create_app --factory --host 0.0.0.0 --port "$PORT" --workers 1`.
- Set `NOTICEFORGE_ALLOWED_HOSTS` to the exact external hostname. The reverse proxy must preserve
  Host and the HTTPS scheme for same-origin checks.
- Use `/api/health` for readiness. Back up SQLite using its backup API or while the service is stopped.

A public service would also need authentication, authorization, upload/rate limits, backup and
restore checks, document-retention rules, and stronger process isolation for untrusted PDF input.
Those controls are not part of this local release.

Original code and documentation use [AGPL-3.0-only](../LICENSE). Fixtures, COGD schemas
and dependencies retain their own terms, recorded in [NOTICE](../NOTICE).
