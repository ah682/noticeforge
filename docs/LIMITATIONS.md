# Scope and remaining gates

## Extraction

The baseline is deterministic and grammar-limited. Supported inputs include labelled English
metadata, ruled native PDF tables, pipe/tab text tables and explicit part/date prose. It handles
only evidenced links. Free-form prose, complex nested headers, arbitrary row continuations,
rotated pages, handwritten material and multi-language notices are not validated at scale.
Malformed rows can remain unextracted; the evaluation counts those omissions and the record
requires review. The application does not infer unseen pages when no page total is supplied.

Inputs are limited to 10 MiB, 100 pages and 60,000 retained characters per page by default.
Exceeding retained coverage creates warnings rather than silent success. Evidence offsets refer
to extracted page text, not the PDF byte stream. Text-offset validity alone is not proof of the
semantic correctness of every part/date relationship.

Tesseract is an optional local OCR dependency. Actual Tesseract 5.3.4 was provisioned and tested
on eight owned rasterized fixtures. Clean site-transfer scans recovered 2/2 relationships; the
deliberately confusing identifier scan recovered only 2/6. All OCR critical fields require review.
Internal evidence offsets can be valid despite wrong recognized characters. The measured native
source geometry mismatches and missing relationships remain in [the OCR report](../reports/ocr/README.md).
These are development scans, not authentic supplier quality measurements. Substantial raster
regions alongside native PDF text remain incomplete because embedded content has not been
OCR-verified. No O/0, I/1 or punctuation substitutions are automatically normalized.

Inventory-limited ordering and tentative dates require review and cannot be emitted as guaranteed
exact XML deadlines. Supplier replacement suggestions never establish physical/electrical fit.
There is no external component catalogue, distributor feed, approved substitute workflow or purchasing.

## Standards

The implemented exporter validates a **SmartPCN_3.08 XML body** using unmodified COGD XSDs from
the smartPCN 3.0 release family. It is not a full `.smartPCN` ZIP transport implementation or a
guarantee of interoperability with every downstream application. Required contact/change/item
fields must be supported by source evidence. Revisions, exclusions, unsupported date categories,
incomplete documents and unresolved values can require canonical JSON.

Exceptions, evidence and suggestion semantics may rely on NoticeForge extension containers;
generic readers may ignore those containers. A complete canonical snapshot is retained in them.
Actual XSD validity, extraction correctness and useful downstream behavior are separate gates.

## Models, evaluation and deployment

No authorized authentic manufacturer corpus was supplied. Developmental synthetic scores do not
measure unfamiliar supplier performance. Fine-tuning has not earned deployment; the default
rules baseline remains useful independently of an LLM. Actual pretrained Qwen2.5-0.5B inference
and LoRA optimization ran on the CPU with owned synthetic documents. The frozen comparison
also exercises batching, real CPU dynamic INT8 kernels and a larger prompted Qwen2.5-1.5B model.
Raw malformed, incomplete and evidence-invalid outputs remain failures. Faster JSON generation
does not establish correct relationships. See [the measured comparison](../reports/model-verification/comparison.txt).

Authentic supplier training/evaluation and CUDA/QLoRA remain unexecuted: no authorized real corpus
was provided and the NVIDIA device driver was unavailable. The larger local comparator is not
proof of superior capability or a paid-provider integration. GPU budgets are planning allocations,
not measured claims. Random-weight compatibility and tiny classifier tests are labelled separately.

No engineer review-time improvement, customer validation, production readiness or unique category
position is claimed. The importer/study workflow supports future evidence collection.

Browser verification includes desktop/mobile workflows, automated axe checks and scripted keyboard
navigation. It is not a complete WCAG conformance assessment, human screen-reader test or engineer
usability study. The raw accessibility report retains any checks requiring manual interpretation.

This is a local single-user demonstration. Multi-tenant authentication, document sandbox workers,
robust distributed jobs, encrypted backup/restore and deployment operations are outside scope.
Do not expose the demonstration server as a hosted service without that additional engineering.
PyMuPDF has AGPL/commercial terms; evaluate dependency obligations for any intended redistribution.

Uploads run outside the web event loop. Native PDF parsing, OCR rasterization and rendering share
one process-local lock to prevent simultaneous native PDF calls; this is not a multiworker or
hostile-document sandbox. One serving process must own a database. Graceful shutdown drains
queued model work and waits for results; it does not forcibly terminate an in-progress native call.
Allowed Host names and same-origin checks protect the local browser boundary, but are not user
authentication. Re-uploading identical bytes with a conflicting expected page count returns a
conflict and preserves the existing notice and review history.

## Reference verification

The implementation consulted official [smartPCN downloads](https://smartpcn.org/downloads/),
[specification 3.01](https://smartpcn.org/wp-content/uploads/2021/01/Specification-smartPCN-3.01-released-20180323.pdf),
[PyMuPDF text/layout documentation](https://pymupdf.readthedocs.io/en/latest/recipes-text.html),
[OCR documentation](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html),
[FastAPI upload documentation](https://fastapi.tiangolo.com/tutorial/request-files/), and
[TRL PEFT guidance](https://huggingface.co/docs/trl/peft_integration).
The actual model implementation uses the independently pinned Transformers/PEFT APIs described in MODELS.md.

The supplied [SPARTAN research reference](https://pmc.ncbi.nlm.nih.gov/articles/PMC13168265/)
was identified as table extraction work using OpenCV heuristics/OCR. Its direct page initially
returned a browser challenge; no results from that paper were reproduced or used as our benchmark.
Existing products already provide extraction/BOM/workflow features; this release makes no market-gap claim.
