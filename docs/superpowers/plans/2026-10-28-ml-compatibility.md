# Offline ML Compatibility Repair Plan

> **For agentic workers:** Use superpowers:executing-plans with systematic debugging, test-driven development and verification before completion.

**Goal:** Restore the actual offline CPU training/adapter reload smoke on the security-upgraded ML stack without weakening numerical or checkpoint checks.

**Architecture:** Correct the locally authored compatibility fixture so its tokenizer matches its Qwen2 model family. Keep production training, serving selection, dependency versions and historical reports intact.

**Tech stack:** Python 3.12, CPU Torch, Transformers, PEFT, tokenizers; stdlib unittest for the optional ML regression.

**Spec:** The reproduced root cause and authorized boundaries below.

## Reproduced root cause

Transformers 5.21 `AutoTokenizer` replaces a generic saved tokenizer for the Qwen2 model type with `Qwen2Tokenizer`. The smoke combines Qwen2 with a WordLevel tokenizer, which is then reconstructed as byte BPE without a byte vocabulary. Ordinary input encodes to no tokens, leaving only EOS. Causal shifting leaves zero target positions and produces NaN loss even before LoRA or optimization. The model weights and logits remain finite.

The fixture will instead use a Qwen2 byte tokenizer with a locally authored complete byte vocabulary and no merges. Its model vocabulary will match that tokenizer. The exact fixture needs 1,617 prompt tokens and 1,892 total tokens, so the smoke's input budget increases from 1,600 to 2,048 within its existing 2,048 sequence budget.

## Constraints and review focus

- Only `noticeforge/training.py`, focused compatibility tests and this plan may change unless the provider loader proves faulty.
- Do not change the dependency pins, finite-loss guard, weight-change guard or checkpoint checks.
- Use random tiny offline weights; no downloads, pretrained model, GPU or domain-quality claim.
- Preserve historical reports; put new execution evidence in ignored `output/ponytail-ml-*` directories.
- Verify ordinary text survives save/auto-load and decoding, actual optimization changes adapter weights, and the serving adapter reload succeeds.
- The ML environment has no pytest; use stdlib unittest there, while the ordinary pytest suite may skip the optional ML test.

## Task: repair and verify the real compatibility path

- [x] Add `tests/test_ml_compatibility.py` with one optional unittest covering `_full_profile_compatibility_smoke`, finite losses, two optimizer steps, changed weights, text round-trip and adapter-serving load.
- [x] Run `.venv-ml/bin/python -m unittest discover -s tests -p test_ml_compatibility.py -v` before the fix; expect the reproduced non-finite loss failure.
- [x] Replace only the smoke's mismatched WordLevel tokenizer with Qwen2 byte tokenization, match the tiny model vocabulary and correct the smoke input budget.
- [x] Rerun the focused test and the full compatibility CLI using a fresh `output/ponytail-ml-*` path; require real finite optimization and exact first-stage adapter reload.
- [x] Run the complete default pytest suite and repository lint/format/type checks; report any unrelated failure by name.
- [x] Review and commit only the owned files, then hand the SHA and current reports to root for independent review/publication. Do not push.

## Executed evidence

- The new optional regression first reproduced `RuntimeError: training produced a non-finite loss` in the unmodified full-profile loop. It passes after the fixture correction.
- Full CLI report: `output/ponytail-ml-compatibility-fixed/compatibility_report.json`; additional measured token details: `repair-summary.json` in that directory.
- First-stage 24-step LoRA loss: 4.1541604996 to 3.7332262993; exact adapter reload, maximum logit difference 0.
- Full-profile two-step loss: 5.5505867004 to 5.5494360924; adapter weights changed and serving reload succeeded. The 258-token local tokenizer produces 1,617 prompt tokens, 1,892 sequence tokens and 275 supervised positions after causal shifting.
- Default pytest: 194 passed, 2 skipped (optional ML and explicitly gated real OCR), one existing Starlette/httpx warning. Repository lint, formatting, mypy and JavaScript syntax checks passed.
- The optional bitsandbytes import reports an unavailable CPU 4-bit kernel (`kernels` absent); this FP32 smoke does not use quantization. Torch emits a JIT deprecation warning. Neither message was hidden.
- Historical reports, including their old 309-token fixture count, remain unchanged and dated. No pretrained weights, network downloads, GPU or domain-quality validation ran.
