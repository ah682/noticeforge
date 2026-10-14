# Models, training and reproducibility

GitHub source publication includes configurations, checkpoint manifests and measured reports, but
excludes generated model weights/tokenizer copies and private local model caches. The recorded
weights remain in this workspace; a fresh clone must reproduce the documented training steps or
obtain an explicitly distributed checkpoint before running an adapted profile. No pretrained model
or adapter download is part of the default demo.

The useful default extractor is the text/table/rules pipeline. It does not require a model service, model weights, an API key, or training. Optional model output is a proposal with mandatory review; it cannot replace canonical records or bypass source validation. The fixture provider is explicitly labelled `fixture-offline` and returns supplied JSON for tests, not simulated live intelligence.

## Executed CPU training smoke

```bash
.venv/bin/python -m noticeforge.training smoke --output output/smoke
```

This trains a small NumPy softmax classifier on authored synthetic date-label phrases. It performs gradient updates, saves weights and a checksum-bearing checkpoint manifest, reloads them, verifies identical predictions, and measures inference. It is **training/checkpoint/load plumbing**, not a PCN relation extraction model. The synthetic validation classification score must not be reported as notice extraction accuracy. Generated training and validation rows use separate random seeds but share the phrase grammar.

`output/smoke/smoke_report.json` records the complete configuration, seeds, generated-data digest, loss history, weight change, runtime versions, hardware, process high-water RSS, training time, reload equality, and raw benchmark outcomes. The microbenchmark compares a Python dot-product loop, a real NumPy batch, and actual int8 weight storage with float64 dequantization/compute. Features are prepared before timing; quantization is not a native int8 inference kernel. These are smoke classifier measurements and cannot establish GPU or domain-model gains.

## Dataset and annotation contract

Use a JSON manifest with a `documents` list. Every entry requires `id`, relative `path`, `source`, `permission_status`, `license`, `supplier`, `template`, `family`, `classification`, `split`, and `annotation_provenance`. Optional fields include `sha256`, `created_at`, `transformations`, `permission_reference`, `expected_pages`, `annotation_path`, and `expected` gold assertions. Document paths must remain inside the manifest directory. Actual files are local UTF-8 text or PDFs; nothing downloads supplier notices.

Synthetic permission statuses are `owned_synthetic`, `owned`, `authorized`, or `open_license`. Real material requires `authorized`, `licensed`, or `open_license`, plus a nonempty `permission_reference` recording the right to use the material for training/evaluation. The software checks that a record exists; a responsible human must verify that authorization actually covers the planned use. Merely marking public documents as synthetic is not a valid permission process.

```bash
.venv/bin/python -m noticeforge.datasets audit fixtures/evaluation/manifest.json
.venv/bin/python -m noticeforge.datasets import partner/manifest.json partner/annotations.jsonl output/partner-import
.venv/bin/python -m noticeforge.datasets prepare partner/manifest.json partner/prepared.json --seed 17
```

Audits reject cross-split supplier, template, revision-family and near-duplicate-page overlaps, bad checksums, unreadable sources, and missing permission records. Near-duplicate checking uses normalized exact equality, word 5-shingle Jaccard, and token-sequence similarity for pages of at most 2,000 tokens. The default threshold is 0.8 and must be frozen before final evaluation. It is a conservative pilot-corpus screen; common boilerplate can require adjudication, and OCR/paraphrases can evade it. Image-only PDFs need a reviewed text rendition for text-based duplicate checking. Do not override overlaps merely to achieve target split sizes.

Preparation merges connected supplier/template/family/duplicate groups and assigns entire groups by a seeded SHA256 70/15/15 allocation. It does not guarantee nonempty or balanced splits. Small datasets need additional independent groups. When the output moves outside the source directory, preparation copies sources and referenced annotations into a sibling `<manifest-stem>.data` directory so the result remains self-contained. It refuses to overwrite the source manifest or a conflicting copied file. Real training requires both train and validation groups; final-test annotations never enter training. Freeze prompts, thresholds and model choice before an authentic final test. The bundled synthetic developmental evaluation is explicitly **not** that final test.

Partner annotations are JSONL, one record per document:

```json
{"document_id":"notice-1","annotator":"engineer-id","created_at":"2026-10-13T00:00:00Z","parts":["001-A"],"relationships":[{"part_raw":"001-A","date_type":"last_buy","date":"2027-04-30","date_text":"2027-04-30","exception":null,"review_required":false,"evidence":[{"page":1,"start":0,"end":25,"quote":"001-A last buy 2027-04-30"}]}],"adjudicator":"second-engineer-id","notes":"Human-checked source and row scope"}
```

Offsets are page-local, zero-based Unicode positions with exclusive ends. Dataset import, training, extraction and serving use the same canonical page parser: PyMuPDF layout lines in sorted order for PDFs, normalized line endings for text, with a newline after each retained line. Annotate the canonical `document.pages[].text`, rather than a separate PDF-to-text conversion. Incomplete extraction, missing expected pages and truncated sources block annotation import and training. Every relationship must cite its exact part, date text and any exception; malformed spans fail the entire import before files are copied. Imports create immutable packages containing source copies, attributed annotations, normalized manifests, and audits. The importer never overwrites an existing package. Gold date normalization and semantic row scope still need human adjudication.

## Optional compact model

The selected model is [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct), pinned to revision `7ae557604adf67be50417f59c2c2f167def9a775` with Apache-2.0 licensing. The official model card identifies the Qwen2 architecture and requires Transformers 4.37 or newer. The selected 0.49B model is a practical compact profile; no claim is made that this size meets domain accuracy requirements. The model card and its [revision history](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/commits/main) were checked during implementation.

`requirements-ml.txt` pins Torch 2.8.0, Transformers 4.56.2, PEFT 0.17.1, Accelerate 1.10.1, bitsandbytes 0.47.0, tokenizers 0.22.0, safetensors 0.6.2 and huggingface-hub 0.34.4. The implementation follows the official [Transformers 4.56.2 quantization API](https://huggingface.co/docs/transformers/v4.56.2/en/quantization/bitsandbytes), [PEFT quantization guide](https://huggingface.co/docs/peft/v0.17.0/en/developer_guides/quantization), [adapter loading API](https://huggingface.co/docs/peft/v0.17.0/en/package_reference/peft_model), and [PEFT 0.17.1 package requirements](https://github.com/huggingface/peft/blob/v0.17.1/setup.py). PEFT publishes the 0.17.0 documentation for this minor-version API. These deliberately pinned versions are not described as the latest releases.

Install in a separate environment; the standard demo never installs Torch:

```bash
uv venv --python 3.12 .venv-ml
# CPU-only API compatibility check (install this first to avoid CUDA dependency downloads).
uv pip install --python .venv-ml/bin/python --index-url https://download.pytorch.org/whl/cpu torch==2.8.0
uv pip install --python .venv-ml/bin/python -e . -r requirements-ml.txt
.venv-ml/bin/python -m noticeforge.training compatibility --output output/ml-api-smoke
```

The compatibility command constructs random tiny Qwen2 weights locally, applies real PEFT LoRA, updates parameters, saves both safe base weights and adapter, reloads the adapter, and compares logits. It downloads no pretrained weights. Its result establishes compatibility of the exercised CPU APIs only. It does not establish CUDA kernels, QLoRA, pretrained generation quality, or data sufficiency.

The [recorded compatibility run](../reports/ml-compatibility/compatibility_report.json) used Torch `2.8.0+cpu` with the pinned stack above on Python 3.12.3. Twenty-four LoRA optimizer steps reduced the toy loss from 4.1541605 to 3.7332263, and the restored adapter produced exactly equal logits. A second probe exercised the actual `train_compact` path with a local toy tokenizer, 309-token training example, prompt-label masking, gradient checkpointing, two optimizer steps, checkpoint checksums, and the serving adapter loader. It loaded a 12,992-parameter random model. Process high-water RSS was 485,339,136 bytes. All of these numbers describe tiny compatibility assets; none describes the 0.49B pretrained model. [Exact observed packages](../reports/ml-compatibility/requirements-observed.txt) are included with the report. The generated tiny base/adapter weights are excluded from Git; rerun the compatibility command to create them locally.

For a genuine run, install a Torch build compatible with the machine's CUDA installation in a separate environment, obtain authorized annotated documents, and provide enough compute. `configs/compact-lora.json` requests bfloat16 CUDA LoRA; `configs/compact-qlora.json` requests NF4 CUDA QLoRA with double quantization and bfloat16 compute. Planning allocations are 8 GiB GPU / 8 GiB host for LoRA and 6 GiB GPU / 8 GiB host for QLoRA, plus 4 GiB disk. These are configurable planning budgets, not measured guarantees. Actual allocated GPU memory and host high-water RSS are recorded only on execution. CPU float32 LoRA can be selected by editing `device` and `precision`; it may be slow.

```bash
.venv-ml/bin/python -m noticeforge.training compact \
  --config configs/compact-lora.json \
  --manifest output/partner-import/manifest.json \
  --annotations output/partner-import/annotations.jsonl \
  --output output/adapter-run-001 --allow-download
```

The explicit `--allow-download` permits fetching this pinned model snapshot. It does not upload training documents. Without the flag, model loading uses local files/cache only. `trust_remote_code=False` is fixed. Training uses only audited `train` documents, masks prompt/padding labels, applies gradient accumulation, and rejects overlong rows instead of dropping their parts or labels. Validation/test records do not enter the optimizer. Evaluate the saved adapter separately on permitted validation data; conduct a frozen final test only after model selection.

The adapter checkpoint manifest records exact base model/revision, input document IDs and token lengths, annotation/manifest hashes, configuration, parameter count, optimizer steps/losses, runtime versions, actual memory/time and hashes of saved artifacts. Serving validates the base revision and artifact checksums before `PeftModel.from_pretrained` loads an adapter. Optional `adapter_path` in a copied serving config selects the adapter; omitting it runs the untuned base.

## Provider boundary and serving measurements

`noticeforge.providers.extract_candidates(pages, provider)` accepts the same parsed page texts as the rules baseline. JSON output must satisfy an extra-forbidden typed schema. It then checks page offsets and exact quotes, identifier boundaries, unambiguous literal date normalization, and quoted exceptions. Dates like `04/05/2027` cannot become an invented exact value. Text inside the document has no authority to change the schema. These checks localize evidence; they cannot prove semantic row associations. Every surviving candidate still requires review, and rejected candidates/errors remain separate.

Input pages/characters are bounded with original/included character counts, clipped/omitted page identifiers and an incomplete-context warning. The local model also enforces a token budget and refuses overlong input. It never silently truncates tokens. Output and response sizes are capped. Local generation has token/time stopping bounds, but Transformers' `max_time` is a soft generation bound, not a hard process deadline. HTTP requests have transport timeouts and up to two bounded retries for transient failures, with redirects disabled and credentials omitted from errors.

The application `ModelService` defaults to no model provider: its UI is unconfigured, with no automatic fixture fallback or model calls. The lower-level `provider_from_environment` helper used by explicit callers defaults to `fixture`; those outputs are labelled offline fixtures. `NOTICEFORGE_PROVIDER=transformers` requires a `NOTICEFORGE_MODEL_CONFIG` file and cached local weights. `NOTICEFORGE_PROVIDER=compatible` requires `NOTICEFORGE_MODEL_BASE_URL` ending at `/v1` and `NOTICEFORGE_MODEL_ID`; `NOTICEFORGE_MODEL_TOKEN` is optional. A nonloopback endpoint additionally requires `NOTICEFORGE_ALLOW_REMOTE=1`, HTTPS, and authorization to transfer the input. The adapter uses a Chat Completions JSON-schema contract, documented by [vLLM's structured output interface](https://docs.vllm.ai/en/v0.11.2/features/structured_outputs/). Endpoint compatibility still needs an actual integration test. The local app does not automatically send uploads to a configured service.

After the real-model experiment below has created the local checkpoint and adapted profile, start a separate optional model-enabled app with the ML environment:

```bash
NOTICEFORGE_PROVIDER=transformers \
NOTICEFORGE_MODEL_CONFIG=output/model-run-001/profiles/adapted.json \
.venv-ml/bin/python -m noticeforge.cli demo \
  --data-dir var/model-demo --host 127.0.0.1 --port 8876
```

For a different checkpoint, copy the serving profile and set its `local_model_path` and `adapter_path` to the downloaded base snapshot and trained checkpoint. Use the optional ML interpreter; the default `.venv` intentionally has no Torch. The reviewer explicitly requests a model proposal; an invalid schema, incomplete generation or unsupported citation is saved as an error/rejection and cannot overwrite canonical findings. The model result retains safe output hashes and token usage even on schema errors. Serving this experimental adapter demonstrates the integration; the measured negative result below does not qualify it for automatic extraction.

```bash
# Baseline model serving: cached weights, untuned unless adapter_path is configured.
.venv-ml/bin/python -m noticeforge.evaluation --model-config configs/compact-lora.json \
  --manifest partner/validation-manifest.json --output output/serve-unbatched \
  --batch-size 1 --warmup 2 --repetitions 10
# True padded local-model batch with identical parsing, context and gold targets.
.venv-ml/bin/python -m noticeforge.evaluation --model-config configs/compact-lora.json \
  --manifest partner/validation-manifest.json --output output/serve-batched \
  --batch-size 4 --warmup 2 --repetitions 10
```

For quantization, copy the same serving profile and change precision to `int8` or `nf4` on supported CUDA hardware. Keep the same model revision, adapter, data, context budgets, warmup and repetitions; record that configuration alongside both runs. HTTP concurrency is available with `--concurrency N`, while local model concurrency uses real padded batching. Do not compare batch completion latency with single-request latency without their recorded workload context.

Each real serving report includes raw outputs and request outcomes, actual input lengths/token usage, batch/concurrency/warmup settings, p95 latency, wall time, memory, runtime versions, precision, candidate validation failures and exact relationship errors against the same gold targets. Failed/unavailable runs are explicitly `unexecuted` with no latency or quality estimates. Reject an optimization if it worsens critical relationship errors or supported coverage; throughput alone does not authorize deployment. External provider price is not inferred. Serving wall time and training time/cost remain separate, with utilization assumptions stated.

The default demo remains independent of pretrained weights. The separate real-model verification workflow below executes pretrained CPU generation, owned-synthetic LoRA adaptation, and CPU serving comparisons. Authentic manufacturer evaluation, GPU/QLoRA, paid external providers, and component-engineer time studies remain distinct gates. Synthetic experiments and compatibility smokes do not substitute for those measurements.

## Real pretrained CPU verification

`scripts/model_verification.py` is the explicit, reproducible model experiment. It downloads the selected Apache-2.0 snapshots from official Hugging Face repositories, verifies pretrained weight SHA256 values against pinned official LFS metadata, and never uploads notice documents. The larger local comparator is [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct), pinned to `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`; it is a larger prompted local comparator, not a paid provider or a proven superior PCN model.

```bash
# Use the separately installed ML environment described above.
.venv-ml/bin/python scripts/model_verification.py all \
  --model-root /tmp/noticeforge-models \
  --reports output/model-run-001
```

Use a new output directory for each experiment. `reports/model-verification` contains the published
results and checkpoint metadata, not a resumable local model installation. Reusing it skips model
downloads and conflicts with the existing checkpoint directory. The command above creates the
profile used by the optional app launch example.


The script also exposes `prepare`, `baseline`, `train`, `validation-base`, `validation-adapted`, `untuned`, `adapted`, `batched`, `quantized`, `adapted-batched`, `adapted-quantized`, `stronger`, and `summarize` stages. Completed checkpoints/benchmarks are preserved; use a fresh report directory for an independent rerun. Model files may be reused after checksum verification. Downloads total roughly 4 GB; allow additional disk for cached libraries and adapters. The report records actual process memory rather than claiming a universal RAM requirement.

Preparation creates 16 new owned synthetic training notices and four supplier/template/family-separated validation notices in `fixtures/model-training`. These do not contain copied manufacturer material. A combined leakage audit also includes the frozen developmental evaluation. The script freezes source and manifest hashes, parsed page texts, prompt, annotation hashes, and every model/training configuration **before** any evaluation-model score is measured. Changing a frozen input blocks subsequent stages. The parser's synthetic development suite remains a development suite, even when frozen for this experiment; it is not authentic manufacturer generalization evidence.

The fixed LoRA experiment uses the pretrained 0.5B model, CPU bfloat16, rank 8 q/v adapters, three epochs, 48 microbatches, and 24 accumulated optimizer steps. Prompts and padding are masked from loss. Training journals every step and records before/after trainable-weight hashes, full checkpoint artifacts, input lengths, runtime versions and actual memory/time. Separate teacher-forced loss stages use only the four disjoint validation documents, never update weights, and do not select hyperparameters. Hyperparameters are not selected from the frozen evaluation scores.

The standard single-request FP32 model, true padded batches of two requests, and [PyTorch 2.8 dynamic INT8 Linear quantization](https://docs.pytorch.org/docs/2.8/generated/torch.ao.quantization.quantize_dynamic.html) use the same pretrained weights and frozen parsed inputs. Adapter versions use the identical saved LoRA checkpoint; the INT8 adapter profile merges those adapter weights before quantizing. Quantized-module counts are checked after conversion. These are actual CPU quantized Linear kernels, separate from the earlier NumPy storage-quantization smoke. Embeddings and attention remain FP32. The larger 1.5B comparator uses CPU bfloat16, so its measurements are not a precision-controlled model-size ablation.

Each model stage runs in a separate process to release prior model memory. The fixed workload uses four CPU threads, one excluded warmup, eight frozen synthetic documents, one measured request per document, maximum 2,048 input tokens and 1,024 generated tokens, and a 120-second soft generation bound. With only eight requests, nearest-rank p95 equals the slowest request; batches have only four completion observations, shared by their members. Runs used a shared development host with other processes, not an isolated machine. These measurements describe this workload, not a production capacity guarantee. Batch reports clearly label batch-completion latency. Local generation that hits its token/time limit retains its raw output and usage, returns an error, and applies no candidate.

The [comparison report](../reports/model-verification/comparison.json) and readable [comparison table](../reports/model-verification/comparison.txt) link the actual executions. Every profile retains raw model strings, output tokens, schema errors, evidence rejections, omissions, per-supplier results and resource measurements. Each `proposal_quality.json` is a further calculation from those same preserved outputs: affected-part recall, exception scope, evidence localization, review coverage, and supplier/template breakdown. The candidate interface does not predict revisions or source completeness; those remain measured deterministic pipeline responsibilities. Invalid-schema output does not receive an invented zero unsupported-assertion count: the report says those assertions are uncountable without inspecting the raw string. Exact relationship metrics on accepted candidates remain separate. All-request throughput includes failures; the comparison separately counts schema-valid and evidence-accepted throughput. All candidates still need review, and a negative adaptation or quantization result is retained without retuning on the evaluation corpus.

### Observed CPU results, 14 October 2026

The complete matrix ran on an AMD Ryzen 7 9700X (16 logical CPUs, four model threads), Python 3.12.3 and Torch `2.8.0+cpu`. No GPU or QLoRA run occurred. The two official pretrained snapshots and their hashes are recorded in [model-artifacts.json](../reports/model-verification/model-artifacts.json); [requirements-observed.txt](../reports/model-verification/requirements-observed.txt) records the actual installed stack. Each model received the same frozen parsed pages, with 409–521 input tokens per request. The recorded optional environment was `/tmp/noticeforge-ml-probe`; `.venv-ml` in the setup instructions is a reproducible alternative location.

| Executed profile | Schema-valid outputs | Accepted exact tuples | p95 completion, seconds | Peak RSS, MiB |
| --- | ---: | ---: | ---: | ---: |
| Untuned 0.5B FP32 | 1/8 | 0/19 | 95.660 | 3209.2 |
| LoRA 0.5B FP32 | 7/8 | 0/19 | 10.037 | 3209.4 |
| Untuned, batch size 2 | 1/8 | 0/19 | 115.485 | 3209.4 |
| Untuned, CPU dynamic INT8 | 0/8 | 0/19 | 23.165 | 3209.7 |
| LoRA, batch size 2 | 7/8 | 0/19 | 12.292 | 3209.4 |
| LoRA merged, CPU dynamic INT8 | 0/8 | 0/19 | 23.095 | 3213.9 |
| Larger prompted 1.5B BF16 | 8/8 | 0/19 | 1.354 | 3418.8 |

All seven variants completed real generation. The larger model returned empty candidate lists on all eight cases; its low latency reflects abstention. LoRA improved JSON formatting and stopped the untuned model's long unfinished generations, but seven candidates failed source evidence checks, and the eighth response violated the schema. Five raw part/date assertions in its schema-valid outputs were wrong against gold. Offset validation prevented those proposals from becoming canonical facts. No accepted candidates means accepted-evidence localization is **not applicable**, not 100% success.

The INT8 runs converted and checked 169 actual Linear modules using the `x86` dynamic qint8 backend. Both produced zero schema-valid responses. Process high-water RSS includes loading the FP32 base and quantization conversion; these readings do not establish lower steady serving memory. Batching improved total completed-request throughput (untuned 0.0203 to 0.0235 requests/s; adapted 0.1155 to 0.1780 requests/s), while every profile's supported-relationship throughput remained zero. Neither faster invalid output nor faster abstention earns deployment.

The real pretrained LoRA training changed 540,672 parameters over 24 optimizer steps in 75.79 seconds; training peak RSS was 2771.8 MiB. The four independent synthetic validation documents had target-token-weighted loss **0.322006 before** and **0.329228 after** adaptation, a slight worsening. These teacher-forced losses are separate from extraction correctness. The checksum-bearing [checkpoint manifest](../reports/model-verification/adapter/checkpoint_manifest.json) is published; adapter weights are excluded from Git and must be regenerated locally; the experiment used no final-evaluation feedback to adjust training, prompts or thresholds.

The deterministic text/table/rules baseline returned **18/19 relationships and 15/16 parts**, one correctly scoped exception, one partial revision relationship, both required uncertainty flags, and the expected incomplete-source flag. It recorded two overlapping critical omissions (one missing part and its date in the unsupported ragged row), zero unsupported assertions, and 102/102 localized evidence spans. Its p95 was 0.595 ms across 80 serial extractions of these eight short text fixtures, with 80.1 MiB peak RSS; that timing does not represent OCR or large PDF workloads. All local model download/training/serving used zero paid external spend; energy and dedicated-host capacity costs were not measured.

The decision from this experiment is to retain the deterministic default. These small synthetic runs provide reproducible negative adaptation/quantization evidence, not authentic manufacturer validation. An additional [real-model browser/API report](../reports/browser-real-model/result.json) verifies the live integration: one explicit browser request generated 93 tokens with the saved adapter, retained output hash/usage/revision provenance, rejected a bad-offset candidate, preserved canonical facts, and left validated exports usable. All 13 integration checks passed. That development-fixture test establishes the actual request-to-persistence path, not model quality or engineer review-time gains.
