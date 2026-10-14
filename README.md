# NoticeForge

NoticeForge is a local review tool for semiconductor product-change and discontinuance notices. It reads PDF or text notices, connects affected parts to their deadlines, and keeps the source evidence beside the extracted records.

[Project page](https://ah682.github.io/noticeforge/) · [Walkthrough](docs/WALKTHROUGH.md)

![NoticeForge review workspace](docs/images/review.png)

## Run it locally

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ah682/noticeforge.git
cd noticeforge
make demo
```

Open **http://127.0.0.1:8877**. The command installs the locked dependencies, adds five example notices, and starts the app. No API key, GPU, model download, or paid service is needed.

The examples are fictional. Your uploaded notices and review history stay in a local SQLite database. Set `NOTICEFORGE_DATA_DIR` to use a different storage directory, or `NOTICEFORGE_PORT` to change the port. Other settings are listed in [`.env.example`](.env.example); export them in your shell before starting the app.

## What it does

- Keeps exact part identifiers and manufacturer context, including leading zeros and suffixes.
- Assigns dates to the right parts instead of using one deadline for the whole notice.
- Preserves footnotes, inventory conditions, exclusions, and partial revisions.
- Links extracted values to source text and PDF regions.
- Records review decisions, corrections, and original values.
- Matches BOM rows by literal identifier and manufacturer.
- Exports canonical JSON and a restricted smartPCN XML body validated against the original COGD XSD.

Try **AST-PDN-2026-041** for grouped deadlines and a row-specific footnote. **BRS-PDN-2026-018** shows an ambiguous date that needs review. **AST-PCN-2026-052** supports the XML export. The [walkthrough](docs/WALKTHROUGH.md) covers these examples.

## How it works

The default extractor uses text, table layout, and deterministic rules. Optional local or compatible model providers can propose changes, but nothing is applied without an explicit review decision. OCR is optional and its output always needs review.

The backend is FastAPI with SQLite. The interface uses plain JavaScript and CSS. See [Architecture](docs/ARCHITECTURE.md) for the data flow and module boundaries.

## Development

```bash
make verify                 # tests, lint, types, evaluation, and CPU training smoke
npm ci
npm run format:check
make distribution-check     # build and exercise an installed wheel
```

Node 24 is used for the development checks. To run browser tests, start a disposable demo in another terminal:

```bash
NOTICEFORGE_DATA_DIR=/tmp/noticeforge-browser-check make demo
npm run test:browser
npm run test:races
```

Browser checks use Chrome; set `CHROME_PATH` if it is installed elsewhere. `make format` runs the Python and frontend formatters.

`make reset` deletes the selected demo database and its review history, then restores the example notices. Keep retained work in a separate data directory.

## Current limits

This is a single-user local application. It has no login or tenant isolation, so it should not be exposed directly as a public service. GitHub Pages can show a project page; it cannot run the Python backend or SQLite storage.

The rules baseline recovered **18 of 19 exact part/date relationships** on eight synthetic development cases. One unsupported table row remains a counted omission. Those results do not establish accuracy on unfamiliar supplier notices. Experimental model profiles did not recover evidence-valid relationships on the comparison set and are not enabled by default.

The XML export is a restricted **smartPCN 3.0 body using XSD revision 3.08**, not a complete `.smartPCN` archive. Suggested replacement parts are never treated as approved substitutes.

## Further reading

- [Verification](docs/VERIFICATION.md) — checks, results, and acceptance cases.
- [Data](docs/DATA.md) — fixture permissions, annotations, and split rules.
- [Models](docs/MODELS.md) — optional training, inference, and measured comparisons.
- [Evaluation](docs/EVALUATION.md) — metrics and known failures.
- [smartPCN](docs/SMARTPCN.md) — supported mappings and export boundaries.
- [Limitations](docs/LIMITATIONS.md) — unsupported inputs and remaining validation work.

The fictional fixtures are CC0. Vendored schema material belongs to COGD and retains its [source and permission record](schemas/smartpcn/SOURCE.json). PyMuPDF has AGPL/commercial licensing terms. A project-wide license has not yet been selected.
