# Actual local OCR verification

Owned synthetic development OCR verification; not held-out supplier evaluation.

Executed: 2026-10-14T09:07:49.885990+00:00. Engine: tesseract 5.3.4. Repetitions: 1, concurrency: 1.

| Owned input | Exact parts | Exact part/date/qualifier | Status | Median seconds |
| --- | --- | --- | --- | --- |
| site-transfer-300dpi | 2/2 | 2/2 | review_required | 0.596 |
| site-transfer-144dpi | 2/2 | 2/2 | review_required | 0.506 |
| discontinuation-300dpi | 5/6 | 15/18 | review_required | 0.647 |
| discontinuation-144dpi | 5/6 | 15/18 | review_required | 0.560 |
| literal-identifiers-300dpi | 2/6 | 2/6 | review_required | 0.488 |
| mixed-native-image | 0/2 | 0/2 | incomplete | 0.110 |
| missing-page-scan | 0/0 | 0/0 | incomplete | 0.381 |
| large-blank-page | 0/0 | 0/0 | incomplete | 0.499 |

All raw outcomes, wrong candidates, missing relationships, evidence checks, engine package hashes, and resource observations are in [report.json](report.json). The `.json` files preserve complete canonical results; the evidence PNGs show line-level review regions.

## Reproduce

```sh
.venv/bin/python scripts/verify_ocr.py --bootstrap /tmp/noticeforge-ocr --output reports/ocr --repetitions 3
```

The optional bootstrap verifies package hashes and extracts binaries/data locally; it requires an Ubuntu-compatible x86_64 runtime and does not run package maintainer scripts or change system packages.

## Boundaries

- Development fixtures informed layout changes; these are not held-out scores.
- Clean PDF rasterizations do not represent skew, noise, handwriting, all fonts, or supplier scans.
- Table separation is a wide-gap heuristic for at least three columns; OCR has no general table parser.
- Mixed native/image pages remain incomplete; image regions are not merged automatically.
- The timeout bounds the engine subprocess; there is no hard process-RAM or disk quota here.
- RSS high-water values cover this script or child processes, not concurrent service memory.
- Evidence offset correctness is measured against OCR text; recognition errors can still be localized.
- Every OCR-derived critical value must be reviewed; confidence is not used as a probability.

Safety failures in this run: 0. Recognition errors are recorded separately and are not hidden by that count.

The fixture-generation process high-water values include image buffers and are not engine-only memory. A separate actual Tesseract process was sampled 77 times after exec: observed peak RSS 123824 KiB and 1 thread(s). Sampling every 5 ms can miss brief peaks; this is an observation, not a hard memory ceiling.

## Evidence denominators

The 195 populated OCR-derived critical fields carry 201 evidence entries; some fields cite both a table cell and a footnote, and inherited metadata is cited on multiple parts. Offsets are checked against the retained OCR text and boxes against the received page bounds. These are internal localization checks, not proof that recognized characters are correct.

For comparison with the original native-text PDF, 185/201 OCR quotes occur somewhere in that source, and 180/185 corresponding boxes intersect a native occurrence. Unrecognized source strings have no native comparison; substitutions such as O/0 and an invented colon can match a different native occurrence elsewhere. The report records those mismatches rather than counting them as successful source localization. None of these checks establish authentic scan performance.
