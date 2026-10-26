# Limitations

## Documents and extraction

The rules extractor supports labelled English metadata, ruled native PDF tables,
pipe/tab text tables and explicit part/date prose. Free-form prose, nested headers,
row continuations, rotated pages, handwriting and other languages need broader
evaluation. Malformed rows can be omitted; known omissions count as errors and
leave the record requiring review.

Defaults are 10 MiB per file, 100 pages and 60,000 retained characters per page.
Reaching a coverage limit creates a warning. Missing pages can only be detected
when the document supplies an expected page count. Evidence offsets refer to
extracted page text; a matching text slice alone does not establish the correct
part/date association.

OCR always requires review. Tesseract 5.3.4 was tested on eight synthetic raster
variants: clean site-transfer scans recovered 2/2 relationships, while the
identifier-confusion scan recovered 2/6. The [OCR report](../reports/ocr/README.md)
retains recognition errors, geometry mismatches and missing relationships.
Substantial raster regions alongside native text leave coverage incomplete.
Identifiers are kept literally; O/0, I/1 and punctuation are not autocorrected.

Inventory-limited ordering and tentative dates stay uncertain. Suggested
replacement parts require a separate compatibility assessment. The app has no
component catalogue, distributor feed or purchasing workflow.

## XML export

The exporter validates a smartPCN 3.0 XML body against the unmodified COGD XSD
revision 3.08. It does not create a full `.smartPCN` ZIP package. Contact, change,
item and date fields must have source evidence; unsupported revisions, exclusions,
dates or incomplete records may require canonical JSON instead.

NoticeForge stores exceptions, evidence and the full canonical snapshot in its
own extension containers. Other readers may ignore them. Downstream receiver
interoperability still needs testing; [smartPCN](SMARTPCN.md) documents the exact
mapping and blocked cases.

## Models and evaluation

The published corpus is synthetic. The rules baseline and model comparisons
need a new holdout of permitted supplier notices to measure generalization.
All seven pretrained serving profiles recovered 0/19 evidence-valid relationships,
so rules remain the default. Invalid model output is retained as a failed request
or rejected proposal, and valid proposals still need a review decision. See the
[comparison report](../reports/model-verification/comparison.txt).

CPU inference, LoRA training, padded batching and dynamic INT8 quantization were
run. CUDA/QLoRA was not run because the NVIDIA driver was unavailable. Resource
budgets in the configs are planning estimates. Tiny random-weight and classifier
smokes check API and checkpoint behavior separately from pretrained extraction.

No component-engineer review study has been completed. The
[study protocol](EXTERNAL_EVALUATION.md) covers errors, corrections and paired
review timings. Browser tests include desktop/mobile workflows, axe checks and
keyboard navigation; human screen-reader testing and full WCAG assessment remain
separate work.

## Running the app

Use one local serving process per database. There is no login or tenant isolation,
so do not expose the app directly as a public service. A shared deployment would
need authentication, document sandbox workers, durable jobs, backup/restore and
retention controls; see [hosting](GITHUB.md).

Uploads run outside the web event loop, but native PDF parsing, rasterization
and rendering share a process-local lock. This prevents simultaneous calls within
one process; it is not a hostile-document sandbox or a multiworker lock. Shutdown
drains queued model work and waits for active calls instead of forcibly stopping
them. Host and same-origin checks protect browser requests but do not authenticate
users. Identical uploads with conflicting expected page counts return a conflict
and preserve the existing notice and review history.

## Implementation references

The implementation used the official [smartPCN downloads](https://smartpcn.org/downloads/),
[specification 3.01](https://smartpcn.org/wp-content/uploads/2021/01/Specification-smartPCN-3.01-released-20180323.pdf),
[PyMuPDF text/layout](https://pymupdf.readthedocs.io/en/latest/recipes-text.html) and
[OCR documentation](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html), and
[FastAPI upload documentation](https://fastapi.tiangolo.com/tutorial/request-files/).
Pinned Transformers and PEFT references are in [Models](MODELS.md).
