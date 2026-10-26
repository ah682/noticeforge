# Evaluation results

The rules pipeline was evaluated on eight synthetic notices, separate from the
five UI examples. They use different fictional suppliers, templates and revision
families, but follow the grammar used to develop the parser. These results
therefore describe the development corpus; unfamiliar supplier documents need
a separate holdout evaluation.

## Reproduce

```bash
make evaluate
.venv/bin/python scripts/benchmark_pipeline.py
make smoke
.venv/bin/python -m noticeforge.study fixtures/review-study.csv --output reports/review-study
```

`make verify` includes evaluation and CPU smoke. Results below are from 2026-10-14.
[evaluation.json](../reports/evaluation.json) preserves denominators, per-case errors,
supplier/template breakdowns, canonical outputs and raw timed requests;
[evaluation.txt](../reports/evaluation.txt) is its generated readable report.

## Relationship correctness

| Metric | Result | Meaning |
| --- | --- | --- |
| Exact part/date relationship accuracy | **18/19, 94.74%** | Multiset intersection / union of exact `(raw part, date kind, ISO date or null)` tuples. Extras and omissions reduce the score. |
| Affected-part recall | **15/16, 93.75%** | Exact identifiers, preserving zeros, suffixes and punctuation. |
| Critical omissions | **2** | One omitted part plus its omitted date relationship; categories deliberately overlap. |
| Unsupported assertions | **0** | Against this annotated corpus, including extra critical tuples and broken evidence. |
| Evidence localization | **102/102** | Quotes equal the exact page-local Unicode slices; this does not prove semantic row association. |
| Required uncertain-part review flags | **2/2** | Ambiguous and inventory-limited dates remain reviewable. |
| Revision relationship recall | **1/1** | Exact target and subset retained; repository resolution/history is separately API-tested. |
| Annotated exception scope | **1/1** | Inventory condition stays on the named part. |
| Missing-document coverage | **1/1** | Missing advertised pages cause incomplete status. |
| Required document review | **2/2** | Both missing-page and unsupported-row cases are surfaced. |

A review warning does not turn an omission into correct extraction. In `unsupported-ragged-row`,
`TR-002` and its `2028-12-31` last-buy relationship are absent. The compiler returns
`unparsed_part_row` and requires review. Both missing objects remain in the error counts.

| Synthetic supplier / template | Exact relationships | Parts recovered | Material behavior |
| --- | --- | --- | --- |
| Vela Silicon / different-deadlines | 6/6 | 3/3 | Group deadlines and one inventory exception retained. |
| Morrow Micro / row-footnote | 2/2 | 2/2 | Only the marked row's deadline changes. |
| Quarry Logic / ambiguous-ordering | 2/2 | 2/2 | Correct output is unresolved null, with review. |
| Helio Components / partial-revision | 1/1 | 1/1 | Subset supersession retained. |
| Indigo Circuits / literal-identifiers | 4/4 | 4/4 | Zero, letter/digit and suffix variants stay distinct. |
| Juniper Micro / injection-data | 1/1 | 1/1 | Source instructions cannot change the schema. |
| Lumen Analog / missing-attachment | 1/1 | 1/1 | Available relationship retained, document incomplete; unseen content is unknown. |
| Tern Logic / unsupported-ragged-row | 1/2 | 1/2 | Counted omission and review finding. |

Metrics with no applicable examples are null, not perfect scores. Compile exceptions remain
request failures and missing expected relationships. Scorer tests deliberately inject wrong dates,
duplicate predictions, leaked exceptions and broken evidence to verify the corresponding penalties.

## Latency, memory and cost

Hardware: AMD Ryzen 7 9700X, 16 logical CPUs, Linux x86-64, Python 3.12.3, shared host.
Dependencies are pinned in `uv.lock`; parser versions are also recorded in the pipeline report.
Runs use concurrency 1, two warmups and ten measured repetitions per document. Parsing, table
extraction, linking and validation are included; browser rendering, HTTP upload, persistence and
cold process startup are excluded.

| Workload | Requests / lengths | p95 | Process high-water RSS |
| --- | --- | --- | --- |
| Eight evaluation text documents | 80; one page, 200–397 extracted characters | **0.890 ms** | 83,759,104 bytes |
| Two development PDFs | 20; one page each | **22.75 ms** | Shared pipeline process: 89,759,744 bytes |
| Three development text notices | 30; one page each | **0.746 ms** | Same process as PDFs |

The development workload spans 204–3,224 source bytes and 204–1,103 extracted characters.
[pipeline-benchmark.json](../reports/pipeline-benchmark.json) contains all 50 outcomes, hashes
and lengths. RSS is the process-lifetime peak, including interpreter/prior allocations. These
small warm fixtures do not establish performance for scans, large documents or concurrent users.

External spend was zero. The text evaluation recorded 0.0461 seconds of measured extraction work.
Training timers are separate. Energy, depreciation, dedicated utilization and provider prices were
not measured, so no total monetary cost is inferred.

## Training and model comparisons

The NumPy CPU smoke optimizes a tiny softmax classifier and saves/reloads checksummed
weights exactly. In the final run, 300 epochs reduced toy loss from 1.38348 to 0.05949; training took
0.00901 seconds excluding imports/setup, with 86,712,320 bytes peak RSS. Its int8 storage
microbenchmark dequantizes for float64 compute and is not a native int8 domain model. The smoke
report's unexecuted list describes that command alone; later pretrained experiments are separate.

The earlier random-weight Transformers/PEFT compatibility test trained/saved/reloaded a tiny
Qwen2 adapter with exact restored logits. That establishes API compatibility only. The subsequent
experiment loaded pinned Apache-2.0 Qwen2.5 pretrained weights and trained a rank 8
q/v LoRA adapter on 16 owned synthetic documents: three epochs, 48 microbatches, 24 optimizer steps,
540,672 trainable parameters and 75.792 seconds of timed CPU training. Adapter weight hashes changed.
The training process peaked at 2,906,468,352 bytes RSS. Separate validation on four disjoint documents
returned teacher-forced loss 0.322006 for the base and 0.329228 for the adapter (slightly worse).
Validation did not update weights or select hyperparameters; lower training loss did not establish
held-out relationship quality.

The evaluation prompt, profiles, annotations, document hashes and parsed inputs were frozen before
model evaluation. All seven profiles used the same eight developmental documents and the same
parsed-input digest. They ran sequentially in separate processes on the shared Ryzen 7 host, four
CPU threads, concurrency 1, one excluded warmup and one measured request per document. Inputs were
409–521 tokens, bounded to 2,048 input/1,024 generated tokens with a 120-second soft generation bound.
The four batch completions each include two requests. With n=8, nearest-rank p95 is the slowest
request; batch rows show batch-completion latency, not isolated per-request latency.

| Executed model profile | Strict JSON validity | Evidence-valid relationships | p95 completion | Process peak RSS |
| --- | --- | --- | --- | --- |
| Untuned 0.5B, FP32 | 1/8 | 0/19 | 95.660 s | 3209.2 MiB |
| LoRA 0.5B, FP32 | 7/8 | 0/19 | 10.037 s | 3209.4 MiB |
| Untuned 0.5B, batch 2 | 1/8 | 0/19 | 115.485 s | 3209.4 MiB |
| Untuned 0.5B, CPU INT8 | 0/8 | 0/19 | 23.165 s | 3209.7 MiB |
| LoRA 0.5B, batch 2 | 7/8 | 0/19 | 12.292 s | 3209.4 MiB |
| LoRA 0.5B, CPU INT8 | 0/8 | 0/19 | 23.095 s | 3213.9 MiB |
| Larger prompted 1.5B, BF16 | 8/8 | 0/19 | 1.354 s | 3418.8 MiB |

**The rules pipeline remains the default.** Every model profile recovered 0/19 evidence-valid
relationships and 0/16 exact parts. The full proposal scorer also counts the missing annotated
exception, giving 36 overlapping omissions (16 parts, 19 relationships, one exception). Accepted-set
unsupported assertions are zero because the accepted set is empty; that is not a raw-model safety
score. LoRA produced five wrong raw tuples in schema-valid output and seven evidence-rejected
candidates. Assertions inside invalid JSON are explicitly uncountable, not assigned zero.

LoRA improved JSON validity from 1/8 to 7/8 and shortened generation, but source offsets remained
wrong. The larger 1.5B model returned an empty candidate list for every document; its 1.354-second
p95 measures abstention. CPU dynamic INT8 converted 169 Linear layers to actual x86 quantized
kernels, retaining FP32 embeddings/attention, but both INT8 variants had 0/8 valid JSON outputs.
All-request throughput includes errors;
separate schema-valid and evidence-accepted rates appear in the comparison report. Peak RSS includes
loading and conversion and therefore does not demonstrate lower steady-state quantized memory.
The 1.5B profile used BF16, so this is not a precision-controlled model-size ablation.

[comparison.json](../reports/model-verification/comparison.json) and
[comparison.txt](../reports/model-verification/comparison.txt) preserve the decision and link raw
strings, per-request outcomes, token counts, elapsed time, precision, memory, exception/review
coverage and supplier/template breakdowns. [MODELS.md](MODELS.md) provides the exact pinned setup
and replay commands. Energy, depreciation, dedicated utilization and provider prices were not
measured; external spend was zero. Training and serving timers remain separate.

Actual integration also ran the saved pretrained adapter through the browser, async queue and
SQLite: 93 output tokens, one evidence-invalid proposal, no canonical mutation and working JSON/XSD
exports. All 13 integration checks passed. This development check is separate from the frozen
quality matrix; see [the integration result](../reports/browser-real-model/result.json).

## OCR baseline

Tesseract 5.3.4 ran across eight owned rasterized development inputs, three repetitions at
concurrency 1. Both site-transfer resolutions recovered 2/2 relationships; both discontinuation
resolutions recovered 15/18; the deliberate identifier-confusion case recovered 2/6. Recognition
errors such as O/0 substitution remain separate review-required records. No automatic repair is
credited as literal accuracy. Mixed image/native content, missing pages and blank scans remain
incomplete, and an actual engine-timeout probe returns an explicit coverage warning.

All 195 populated OCR critical fields require review. All 201 OCR-internal evidence offsets/page
bounds pass, while only 180/185 native-comparable regions intersect a matching native quote;
16 evidence strings had no native match. Internal localization is not proof of correct characters.
Ordinary scan medians range 0.548–0.711 seconds. A separately sampled engine process showed one thread
and 124,052 KiB observed peak RSS; sampling can miss brief peaks and there is no hard process-RAM
limit. Raw results, wrong candidates, raster PDFs and evidence overlays are in
[the OCR report](../reports/ocr/README.md). These clean owned rasterizations are not supplier scans.

## Engineer review study

The study importer ran on the empty template and reported zero trials and no
time-gain value. A review study is still needed; [DATA.md](DATA.md) describes how
to record paired timings and independently assessed errors.

Obtain permitted notices and adjudicated annotations; audit entire supplier/template/revision-family
holdouts and near duplicates; freeze model/prompt/threshold selection before an authentic final
test. XSD validity, relationship accuracy and engineer usefulness remain independent checks.
