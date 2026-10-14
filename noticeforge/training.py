"""Executable tiny CPU training smoke and opt-in PEFT training profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .providers import (
    CandidateOutput,
    CompactConfig,
    bound_pages,
    load_compact_components,
    prompt_messages,
    runtime_versions,
)
from .resources import DATA_ROOT

SMOKE_LABELS = ["last_buy", "last_delivery", "effective_change", "sample_availability"]


def machine_details() -> dict[str, Any]:
    # Linux ru_maxrss is KiB; Darwin reports bytes.
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak = usage.ru_maxrss
    processor = platform.processor()
    if Path("/proc/cpuinfo").exists():
        processor = next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            processor,
        )
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": processor,
        "machine": platform.machine(),
        "logical_cpu_count": __import__("os").cpu_count(),
        "process_peak_rss_bytes": int(peak if platform.system() == "Darwin" else peak * 1024),
        "process_user_cpu_seconds": usage.ru_utime,
        "process_system_cpu_seconds": usage.ru_stime,
        "memory_measurement": "process lifetime high-water RSS; includes interpreter and prior work",
    }


def smoke_examples(count: int, seed: int) -> tuple[list[str], np.ndarray]:
    rng = np.random.default_rng(seed)
    templates = [
        "last buy deadline",
        "last delivery deadline",
        "effective change date",
        "sample availability date",
    ]
    examples, labels = [], []
    for index in range(count):
        label = index % len(templates)
        part = f"S{rng.integers(10000, 99999)}-{rng.choice(['A', 'B', 'C'])}"
        examples.append(f"{part} {templates[label]} 2027-{rng.integers(1, 13):02d}-{rng.integers(1, 28):02d}")
        labels.append(label)
    return examples, np.asarray(labels, dtype=np.int64)


def smoke_features(texts: list[str], dimension: int) -> np.ndarray:
    import re

    x = np.zeros((len(texts), dimension), dtype=np.float64)
    for row, text in enumerate(texts):
        words = re.findall(r"[a-z]+", text.lower())
        features = words + [" ".join(words[i : i + 2]) for i in range(len(words) - 1)]
        for value in features:
            digest = hashlib.sha256(value.encode()).digest()
            x[row, int.from_bytes(digest[:4], "little") % (dimension - 1)] += 1
        x[row, -1] = 1
        x[row] /= max(np.linalg.norm(x[row]), 1)
    return x


class TinySmokeModel:
    """A trained softmax date-label classifier; deliberately not an extractor."""

    def __init__(self, weights: np.ndarray):
        self.weights = np.asarray(weights, dtype=np.float64)
        if (
            self.weights.ndim != 2
            or self.weights.shape[1] != len(SMOKE_LABELS)
            or not np.isfinite(self.weights).all()
        ):
            raise ValueError("invalid smoke checkpoint weight matrix")

    def predict(self, texts: list[str]) -> np.ndarray:
        return np.argmax(smoke_features(texts, self.weights.shape[0]) @ self.weights, axis=1)

    def save(self, folder: Path, manifest: dict[str, Any]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "format": "noticeforge-smoke-softmax-v1",
            "labels": SMOKE_LABELS,
            "weights": self.weights.tolist(),
        }
        data = (json.dumps(checkpoint, sort_keys=True, separators=(",", ":")) + "\n").encode()
        (folder / "weights.json").write_bytes(data)
        (folder / "checkpoint_manifest.json").write_text(
            json.dumps({**manifest, "checkpoint_sha256": hashlib.sha256(data).hexdigest()}, indent=2) + "\n"
        )

    @classmethod
    def load(cls, folder: Path) -> "TinySmokeModel":
        data = (folder / "weights.json").read_bytes()
        manifest = json.loads((folder / "checkpoint_manifest.json").read_text())
        if hashlib.sha256(data).hexdigest() != manifest["checkpoint_sha256"]:
            raise ValueError("smoke checkpoint checksum mismatch")
        checkpoint = json.loads(data)
        if checkpoint["format"] != "noticeforge-smoke-softmax-v1" or checkpoint["labels"] != SMOKE_LABELS:
            raise ValueError("unsupported smoke checkpoint")
        return cls(np.asarray(checkpoint["weights"]))


def _loss(x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> tuple[float, np.ndarray]:
    logits = x @ weights
    logits -= logits.max(axis=1, keepdims=True)
    probabilities = np.exp(logits)
    probabilities /= probabilities.sum(axis=1, keepdims=True)
    value = float(-np.log(probabilities[np.arange(len(y)), y] + 1e-12).mean())
    return value, probabilities


def benchmark_smoke(
    model: TinySmokeModel, texts: list[str], labels: np.ndarray, *, warmup: int = 8
) -> dict[str, Any]:
    """Real timings; INT8 is storage quantization with float dequantization, not a GPU benchmark."""
    for _ in range(warmup):
        model.predict(texts[:1])
    matrix = smoke_features(texts, model.weights.shape[0])
    scale = np.maximum(np.max(np.abs(model.weights), axis=0), 1e-12) / 127
    quantized = np.clip(np.rint(model.weights / scale), -127, 127).astype(np.int8)
    variants = []
    for name in ("unoptimized-python-dot", "numpy-batch", "int8-storage-dequantized-numpy"):
        start = time.perf_counter()
        outcomes: list[dict[str, Any]] = []
        if name == "unoptimized-python-dot":
            predictions = []
            for index, row in enumerate(matrix):
                request_start = time.perf_counter()
                logits = [
                    sum(float(row[k]) * float(model.weights[k, j]) for k in range(len(row)))
                    for j in range(len(SMOKE_LABELS))
                ]
                prediction = int(np.argmax(logits))
                predictions.append(prediction)
                outcomes.append(
                    {
                        "request": index,
                        "latency_seconds": time.perf_counter() - request_start,
                        "predicted": SMOKE_LABELS[prediction],
                        "expected": SMOKE_LABELS[int(labels[index])],
                        "correct": prediction == int(labels[index]),
                        "input_characters": len(texts[index]),
                    }
                )
            weight_bytes = model.weights.nbytes
        else:
            inference_start = time.perf_counter()
            weights = model.weights if name == "numpy-batch" else quantized.astype(np.float64) * scale
            predictions = np.argmax(matrix @ weights, axis=1).tolist()
            batch_time = time.perf_counter() - inference_start
            for index, prediction in enumerate(predictions):
                outcomes.append(
                    {
                        "request": index,
                        "batch_completion_latency_seconds": batch_time,
                        "predicted": SMOKE_LABELS[prediction],
                        "expected": SMOKE_LABELS[int(labels[index])],
                        "correct": prediction == int(labels[index]),
                        "input_characters": len(texts[index]),
                    }
                )
            weight_bytes = model.weights.nbytes if name == "numpy-batch" else quantized.nbytes + scale.nbytes
        elapsed = time.perf_counter() - start
        latency = [
            float(v["latency_seconds"] if "latency_seconds" in v else v["batch_completion_latency_seconds"])
            for v in outcomes
        ]
        variants.append(
            {
                "name": name,
                "concurrency": 1,
                "batch_size": 1 if name == "unoptimized-python-dot" else len(texts),
                "requests": len(texts),
                "warmup_iterations": warmup,
                "feature_extraction_timed": False,
                "precision": "float64"
                if name != "int8-storage-dequantized-numpy"
                else "int8 weights, float64 dequantization/compute",
                "weight_storage_bytes": weight_bytes,
                "elapsed_seconds": elapsed,
                "requests_per_second": len(texts) / elapsed,
                "p95_request_or_batch_completion_seconds": float(np.percentile(latency, 95)),
                "classification_accuracy": float(np.mean(np.asarray(predictions) == labels)),
                "outcomes": outcomes,
            }
        )
    return {
        "purpose": "smoke classifier microbenchmark only; excludes tokenization, document parsing, model loading and real PCN relationship inference",
        "domain_quality_evaluated": False,
        "hardware": machine_details(),
        "runtime_versions": runtime_versions(),
        "variants": variants,
    }


def run_smoke(out_dir: Path, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or json.loads((DATA_ROOT / "configs/smoke.json").read_text())
    seed, dimension = int(config["seed"]), int(config["feature_dimension"])
    if not 8 <= dimension <= 4096 or not 1 <= int(config["epochs"]) <= 10000:
        raise ValueError("invalid smoke dimensions/epochs")
    train, y = smoke_examples(int(config["train_examples"]), seed)
    validation, vy = smoke_examples(int(config["validation_examples"]), seed + 1)
    x = smoke_features(train, dimension)
    rng = np.random.default_rng(seed)
    weights = rng.normal(0, 0.01, (dimension, len(SMOKE_LABELS)))
    initial = weights.copy()
    history = []
    start = time.perf_counter()
    for epoch in range(int(config["epochs"])):
        loss, probabilities = _loss(x, y, weights)
        history.append(loss)
        probabilities[np.arange(len(y)), y] -= 1
        gradient = x.T @ probabilities / len(y)
        weights -= float(config["learning_rate"]) * gradient
    final_loss, _ = _loss(x, y, weights)
    elapsed = time.perf_counter() - start
    model = TinySmokeModel(weights)
    changed = float(np.linalg.norm(weights - initial))
    manifest = {
        "purpose": "genuine tiny CPU training/checkpoint/load SMOKE; not a domain model or real-world validation",
        "status": "executed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "model": "hashed-feature softmax classifier",
        "labels": SMOKE_LABELS,
        "seed": seed,
        "train_examples": len(train),
        "validation_examples": len(validation),
        "data_classification": "owned_synthetic_generated_smoke",
        "data_sha256": hashlib.sha256(
            json.dumps({"train": train, "validation": validation}).encode()
        ).hexdigest(),
        "initial_loss": history[0],
        "final_loss": final_loss,
        "weight_change_l2": changed,
        "epochs": len(history),
        "training_seconds": elapsed,
        "runtime_versions": runtime_versions(),
        "hardware": machine_details(),
        "training_cost": {
            "external_spend": 0,
            "local_compute_seconds": elapsed,
            "currency": None,
            "energy_cost": "not measured",
        },
    }
    model.save(out_dir, manifest)
    loaded = TinySmokeModel.load(out_dir)
    reload_equal = np.array_equal(model.weights, loaded.weights) and np.array_equal(
        model.predict(validation), loaded.predict(validation)
    )
    if not changed > 0 or not final_loss < history[0] or not reload_equal:
        raise RuntimeError("CPU training/checkpoint/load smoke failed")
    texts, labels = smoke_examples(int(config.get("benchmark_requests", 160)), seed + 2)
    report = {
        **manifest,
        "reload_exact": reload_equal,
        "validation_classification_accuracy": float(np.mean(loaded.predict(validation) == vy)),
        "loss_history": history,
        "benchmark": benchmark_smoke(loaded, texts, labels, warmup=int(config.get("benchmark_warmup", 8))),
        "unexecuted": [
            "Qwen model weights training/inference",
            "LoRA and QLoRA real corpus training",
            "GPU batching/quantization relationship comparison",
            "authorized held-out real supplier/template evaluation",
            "component-engineer review-time study",
        ],
    }
    (out_dir / "smoke_report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out_dir / "README.txt").write_text(
        f"CPU TRAINING SMOKE ONLY\nTrained {len(train)} synthetic date-label rows for {len(history)} epochs.\nLoss {history[0]:.6f} -> {final_loss:.6f}; checkpoint reload exact: {reload_equal}.\nThis classifier is not the PCN extraction model. See smoke_report.json for raw outcomes.\n"
    )
    return report


def run_ml_compatibility(out_dir: Path) -> dict[str, Any]:
    """Exercise the pinned real Qwen2/PEFT APIs on random tiny weights, offline.

    This is a library compatibility smoke, not Qwen pretrained inference/training.
    It uses the same architecture and adapter save/load APIs as the real profile.
    """
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, Qwen2Config

    if out_dir.exists():
        raise ValueError("compatibility output already exists")
    torch.set_num_threads(1)
    torch.manual_seed(17)
    architecture = Qwen2Config(
        vocab_size=64,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=1,
        num_attention_heads=2,
        num_key_value_heads=2,
        max_position_embeddings=128,
        tie_word_embeddings=True,
        bos_token_id=1,
        eos_token_id=2,
    )
    base = AutoModelForCausalLM.from_config(architecture, attn_implementation="eager")
    out_dir.mkdir(parents=True)
    base.save_pretrained(out_dir / "base", safe_serialization=True)
    base.config._name_or_path = str(out_dir / "base")
    model = get_peft_model(
        base,
        LoraConfig(
            r=4,
            lora_alpha=8,
            lora_dropout=0,
            target_modules=["q_proj", "v_proj"],
            task_type="CAUSAL_LM",
            bias="none",
        ),
    )
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    before = [parameter.detach().clone() for parameter in trainable]
    inputs = torch.tensor([[1, 8, 12, 19, 23, 2], [1, 9, 13, 20, 24, 2]], dtype=torch.long)
    labels = inputs.clone()
    labels[:, :2] = -100
    optimizer = torch.optim.AdamW(trainable, lr=0.03)
    losses = []
    started = time.perf_counter()
    model.train()
    for _ in range(24):
        optimizer.zero_grad()
        loss = model(input_ids=inputs, labels=labels).loss
        losses.append(float(loss.detach()))
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.inference_mode():
        logits = model(input_ids=inputs).logits
    model.save_pretrained(out_dir / "adapter", safe_serialization=True)
    reloaded_base = AutoModelForCausalLM.from_pretrained(
        out_dir / "base", local_files_only=True, attn_implementation="eager"
    )
    reloaded = PeftModel.from_pretrained(
        reloaded_base, out_dir / "adapter", is_trainable=False, local_files_only=True
    ).eval()
    with torch.inference_mode():
        restored_logits = reloaded(input_ids=inputs).logits
    delta = sum(
        float(torch.linalg.vector_norm(a.detach() - b)) for a, b in zip(trainable, before, strict=True)
    )
    difference = float(torch.max(torch.abs(logits - restored_logits)))
    profile_check = _full_profile_compatibility_smoke(out_dir / "profile-smoke")
    report = {
        "status": "executed",
        "purpose": "offline random tiny Qwen2 architecture + real PEFT LoRA compatibility smoke; no pretrained Qwen weights, no domain performance, no GPU quantization",
        "runtime_versions": runtime_versions(),
        "architecture": architecture.to_dict(),
        "seed": 17,
        "optimizer_steps": 24,
        "initial_loss": losses[0],
        "last_training_loss": losses[-1],
        "losses": losses,
        "trainable_parameters": sum(p.numel() for p in trainable),
        "weight_change_l2_sum": delta,
        "adapter_reload_max_logit_difference": difference,
        "reload_exact": bool(torch.equal(logits, restored_logits)),
        "full_training_profile_probe": profile_check,
        "elapsed_seconds": time.perf_counter() - started,
        "hardware": machine_details(),
        "unexecuted": [
            "pretrained compact model inference",
            "authorized real corpus training",
            "CUDA/bitsandbytes quantization",
            "domain relationship comparison",
        ],
    }
    (out_dir / "compatibility_report.json").write_text(json.dumps(report, indent=2) + "\n")
    if not delta > 0 or not losses[-1] < losses[0] or difference > 1e-6:
        raise RuntimeError("real library LoRA save/load compatibility smoke failed")
    return report


def _full_profile_compatibility_smoke(folder: Path) -> dict[str, Any]:
    """Exercise the actual train_compact and serving load paths with tiny local assets."""
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import AutoModelForCausalLM, PreTrainedTokenizerFast, Qwen2Config

    from .providers import TransformersProvider

    folder.mkdir(parents=True)
    base_path = (folder / "random-tiny-base").resolve()
    vocabulary = {
        "[UNK]": 0,
        "[PAD]": 1,
        "[EOS]": 2,
        "system": 3,
        "user": 4,
        "assistant": 5,
        "candidates": 6,
        "last_buy": 7,
    }
    token_model = Tokenizer(WordLevel(vocabulary, unk_token="[UNK]"))
    token_model.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=token_model, unk_token="[UNK]", pad_token="[PAD]", eos_token="[EOS]"
    )
    tokenizer.chat_template = "{% for message in messages %}{{ message['role'] + '\\n' + message['content'] + '\\n' }}{% endfor %}{% if add_generation_prompt %}{{ 'assistant\\n' }}{% endif %}"
    tokenizer.save_pretrained(base_path)
    base = AutoModelForCausalLM.from_config(
        Qwen2Config(
            vocab_size=64,
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_key_value_heads=2,
            max_position_embeddings=2048,
            tie_word_embeddings=True,
            bos_token_id=1,
            eos_token_id=2,
        ),
        attn_implementation="eager",
    )
    base.save_pretrained(base_path, safe_serialization=True)
    documents, annotations = [], []
    specs = [
        (
            "train-row",
            "train",
            "T-001 last buy 2027-04-30. Copper assembly plant relocation notice with final purchasing deadline.",
            "T-001",
            "2027-04-30",
        ),
        (
            "validation-row",
            "validation",
            "V-999 sample availability 2028-09-15. Ceramic package qualification under a distinct specification.",
            "V-999",
            "2028-09-15",
        ),
    ]
    for identifier, split, text, part, deadline in specs:
        (folder / f"{identifier}.txt").write_text(text)
        documents.append(
            {
                "id": identifier,
                "path": f"{identifier}.txt",
                "source": "owned random-model API smoke fixture",
                "permission_status": "owned_synthetic",
                "license": "CC0-1.0",
                "supplier": identifier,
                "template": identifier,
                "family": identifier,
                "classification": "synthetic",
                "split": split,
                "annotation_provenance": "locally authored literal values for API smoke, not domain validation",
            }
        )
        annotations.append(
            {
                "document_id": identifier,
                "annotator": "NoticeForge smoke author",
                "created_at": "2026-10-13T00:00:00Z",
                "parts": [part],
                "relationships": [
                    {
                        "part_raw": part,
                        "date_type": "last_buy" if split == "train" else "sample_availability",
                        "date": deadline,
                        "date_text": deadline,
                        "exception": None,
                        "evidence": [{"page": 1, "start": 0, "end": len(text), "quote": text}],
                    }
                ],
            }
        )
    manifest_path, annotation_path = folder / "manifest.json", folder / "annotations.jsonl"
    manifest_path.write_text(json.dumps({"documents": documents}, indent=2) + "\n")
    annotation_path.write_text("".join(json.dumps(row) + "\n" for row in annotations))
    config = CompactConfig(
        model_id=str(base_path),
        revision="0" * 40,
        license="random weights authored locally",
        device="cpu",
        precision="float32",
        epochs=2,
        learning_rate=0.003,
        max_input_tokens=1600,
        max_sequence_tokens=2048,
        max_new_tokens=8,
        lora_rank=4,
        lora_alpha=8,
        lora_dropout=0,
        gradient_checkpointing=True,
    ).model_dump()
    config_path = folder / "config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    manifest = train_compact(config_path, manifest_path, annotation_path, folder / "trained-adapter")
    serving = TransformersProvider({**config, "adapter_path": str(folder / "trained-adapter")})
    return {
        "purpose": "actual training loop and adapter-serving loader with random tiny local weights and toy tokenizer",
        "train_compact_executed": True,
        "optimizer_steps": manifest["optimizer_steps"],
        "training_document_ids": manifest["training_document_ids"],
        "input_token_lengths": manifest["training_input_token_lengths"],
        "gradient_checkpointing": True,
        "serving_adapter_loaded": True,
        "loaded_parameter_count": sum(p.numel() for p in serving.model.parameters()),
        "checkpoint_manifest": str(folder / "trained-adapter/checkpoint_manifest.json"),
        "domain_model": False,
    }


def _training_examples(
    manifest_path: Path, annotations_path: Path, config: dict[str, Any], *, split: str = "train"
) -> tuple[list[tuple[str, list[dict[str, str]], str]], dict[str, Any]]:
    from .datasets import (
        PartnerAnnotation,
        audit_manifest,
        load_manifest,
        page_texts,
        resolve_document,
        validate_annotation,
    )

    audit = audit_manifest(manifest_path)
    if not audit["ok"]:
        raise ValueError("training blocked by permission/split/near-duplicate audit")
    entries, _ = load_manifest(manifest_path)
    if split not in {"train", "validation"}:
        raise ValueError("optimizer/validation preparation cannot consume final test documents")
    if not any(item.split == "train" for item in entries) or not any(
        item.split == "validation" for item in entries
    ):
        raise ValueError("training profile requires independent train and validation groups")
    annotations = {}
    for line in annotations_path.read_text().splitlines():
        if line.strip():
            annotation = PartnerAnnotation.model_validate_json(line)
            if annotation.document_id in annotations:
                raise ValueError("duplicate annotation id")
            annotations[annotation.document_id] = annotation
    examples = []
    for item in entries:
        if item.split != split:
            continue  # Final tests and validation never enter optimizer/prompt targets.
        annotation = annotations[item.id]
        pages = page_texts(
            resolve_document(manifest_path.parent, item.path),
            require_complete=True,
            expected_pages=item.expected_pages,
        )
        validate_annotation(annotation, pages)
        request = bound_pages(
            [{"number": i + 1, "text": text} for i, text in enumerate(pages)],
            max_characters=config.get("max_characters", 7000),
        )
        if request.truncated:
            raise ValueError(
                f"training document {item.id} exceeds context budget; annotate bounded page groups explicitly"
            )
        raw = {
            "candidates": [
                {k: v for k, v in relation.model_dump().items() if k != "review_required"}
                for relation in annotation.relationships
            ]
        }
        target = CandidateOutput.model_validate(raw).model_dump_json()
        examples.append((item.id, prompt_messages(request), target))
    return examples, audit


def train_compact(
    config_path: Path,
    manifest_path: Path,
    annotations_path: Path,
    out_dir: Path,
    *,
    allow_download: bool = False,
) -> dict[str, Any]:
    """Train LoRA adapters on authorized, audited training records only.

    Heavy libraries/weights are opt-in. No test-set metric influences training.
    The loss masks prompts and padding; overlong rows fail rather than truncate.
    """
    config = CompactConfig.model_validate_json(config_path.read_text()).model_dump()
    config["allow_download"] = allow_download
    examples, audit = _training_examples(manifest_path, annotations_path, config)
    if out_dir.exists():
        raise ValueError("adapter output already exists; choose a new checkpoint directory")
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    torch.manual_seed(config.get("seed", 17))
    np.random.seed(config.get("seed", 17))
    tokenizer, model = load_compact_components(config, training=True)
    if config["precision"] == "nf4":
        model = prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=config.get("gradient_checkpointing", True)
        )
    elif config.get("gradient_checkpointing", True):
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    model.config.use_cache = False
    model = get_peft_model(
        model,
        LoraConfig(
            r=config["lora_rank"],
            lora_alpha=config["lora_alpha"],
            lora_dropout=config["lora_dropout"],
            target_modules=config["target_modules"],
            bias="none",
            task_type="CAUSAL_LM",
        ),
    )
    rows = []
    for identifier, messages, target in examples:
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        prefix = tokenizer(prompt, add_special_tokens=False)["input_ids"]
        ids = tokenizer(prompt + target + tokenizer.eos_token, add_special_tokens=False)["input_ids"]
        if len(ids) > config["max_sequence_tokens"] or len(prefix) > config["max_input_tokens"]:
            raise ValueError(
                f"training row {identifier} exceeds configured token budget; no truncation performed"
            )
        # Token-boundary consistency is critical for label masking.
        if ids[: len(prefix)] != prefix:
            raise ValueError("chat template token boundary is not stable")
        rows.append({"id": identifier, "input_ids": ids, "labels": [-100] * len(prefix) + ids[len(prefix) :]})

    def collate(batch: list[dict[str, Any]]) -> dict[str, Any]:
        width = max(len(row["input_ids"]) for row in batch)
        return {
            "input_ids": torch.tensor(
                [
                    row["input_ids"] + [tokenizer.pad_token_id] * (width - len(row["input_ids"]))
                    for row in batch
                ],
                dtype=torch.long,
            ),
            "labels": torch.tensor(
                [row["labels"] + [-100] * (width - len(row["labels"])) for row in batch], dtype=torch.long
            ),
            "attention_mask": torch.tensor(
                [[1] * len(row["input_ids"]) + [0] * (width - len(row["input_ids"])) for row in batch],
                dtype=torch.long,
            ),
        }

    generator = torch.Generator().manual_seed(config.get("seed", 17))
    loader = torch.utils.data.DataLoader(
        rows, batch_size=config.get("batch_size", 1), shuffle=True, collate_fn=collate, generator=generator
    )
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=config["learning_rate"])
    accumulation = int(config.get("gradient_accumulation_steps", 1))
    if accumulation < 1:
        raise ValueError("gradient accumulation must be positive")
    model.train()
    losses, steps = [], 0
    initial_trainable_hash = hashlib.sha256(
        b"".join(p.detach().float().cpu().numpy().tobytes() for p in trainable)
    ).hexdigest()
    out_dir.mkdir(parents=True)
    (out_dir / "training_status.json").write_text(
        json.dumps(
            {
                "status": "running",
                "model": config["model_id"],
                "epochs": config["epochs"],
                "training_rows": len(rows),
            }
        )
        + "\n"
    )
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    optimizer.zero_grad()
    for epoch in range(config["epochs"]):
        for index, batch in enumerate(loader):
            batch = {key: value.to(model.device) for key, value in batch.items()}
            output = model(**batch)
            if not torch.isfinite(output.loss):
                raise RuntimeError("training produced a non-finite loss")
            losses.append(float(output.loss.detach().cpu()))
            group_start = (index // accumulation) * accumulation
            group_size = min(accumulation, len(loader) - group_start)
            (output.loss / group_size).backward()
            if (index + 1) % accumulation == 0 or index + 1 == len(loader):
                torch.nn.utils.clip_grad_norm_(trainable, 1.0)
                optimizer.step()
                optimizer.zero_grad()
                steps += 1
                progress = {
                    "epoch": epoch + 1,
                    "optimizer_step": steps,
                    "loss": losses[-1],
                    "elapsed_seconds": time.perf_counter() - started,
                }
                with (out_dir / "training_progress.jsonl").open("a") as stream:
                    stream.write(json.dumps(progress) + "\n")
                print(json.dumps(progress), flush=True)
    elapsed = time.perf_counter() - started
    final_trainable_hash = hashlib.sha256(
        b"".join(p.detach().float().cpu().numpy().tobytes() for p in trainable)
    ).hexdigest()
    if initial_trainable_hash == final_trainable_hash:
        raise RuntimeError("training did not change adapter parameters")
    (out_dir / "training_status.json").write_text(
        json.dumps({"status": "executed", "optimizer_steps": steps}) + "\n"
    )
    model.save_pretrained(out_dir, safe_serialization=True)
    tokenizer.save_pretrained(out_dir)
    artifact_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(out_dir.iterdir())
        if path.is_file()
    }
    manifest = {
        "status": "executed",
        "purpose": "compact model adapter training; deployment requires independent relationship evaluation",
        "model_id": config["model_id"],
        "revision": config["revision"],
        "license": config["license"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "training_document_ids": [row["id"] for row in rows],
        "training_input_token_lengths": [len(row["input_ids"]) for row in rows],
        "dataset_audit": audit,
        "annotations_sha256": hashlib.sha256(annotations_path.read_bytes()).hexdigest(),
        "trainable_parameters": sum(p.numel() for p in trainable),
        "optimizer_steps": steps,
        "losses": losses,
        "training_seconds": elapsed,
        "artifact_hashes": artifact_hashes,
        "runtime_versions": runtime_versions(),
        "hardware": machine_details(),
        "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated() if torch.cuda.is_available() else None,
        "training_cost": {
            "external_spend": 0,
            "local_compute_seconds": elapsed,
            "energy_cost": "not measured",
        },
        "final_test_used": False,
    }
    manifest.update(
        initial_trainable_sha256=initial_trainable_hash,
        final_trainable_sha256=final_trainable_hash,
        adapter_weights_changed=True,
        training_material="owned synthetic only"
        if audit["classification_counts"]["real"] == 0
        else "authorized manifest material",
    )
    (out_dir / "checkpoint_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def validation_loss(
    config_path: Path,
    manifest_path: Path,
    annotations_path: Path,
    output: Path,
    *,
    adapter_path: Path | None = None,
) -> dict[str, Any]:
    """Teacher-forced validation loss only; never chooses hyperparameters or weights."""
    if output.exists():
        raise ValueError("validation output already exists; preserve observations or choose a new path")
    import torch

    from .providers import TransformersProvider

    config = CompactConfig.model_validate_json(config_path.read_text()).model_dump()
    config["allow_download"] = False
    config["adapter_path"] = str(adapter_path) if adapter_path else None
    examples, audit = _training_examples(manifest_path, annotations_path, config, split="validation")
    provider = TransformersProvider(config)
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for identifier, messages, target in examples:
        prompt = provider.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        prefix = provider.tokenizer(prompt, add_special_tokens=False)["input_ids"]
        ids = provider.tokenizer(prompt + target + provider.tokenizer.eos_token, add_special_tokens=False)[
            "input_ids"
        ]
        if (
            ids[: len(prefix)] != prefix
            or len(ids) > config["max_sequence_tokens"]
            or len(prefix) > config["max_input_tokens"]
        ):
            raise ValueError("validation token boundary/budget violation; no truncation")
        labels = [-100] * len(prefix) + ids[len(prefix) :]
        with torch.inference_mode():
            loss = provider.model(
                input_ids=torch.tensor([ids], device=provider.model.device),
                labels=torch.tensor([labels], device=provider.model.device),
                use_cache=False,
            ).loss
        rows.append(
            {
                "document_id": identifier,
                "input_tokens": len(prefix),
                "target_tokens": len(ids) - len(prefix),
                "negative_log_likelihood": float(loss),
            }
        )
    report = {
        "status": "executed",
        "purpose": "owned synthetic validation teacher-forced loss; no final evaluation documents and no model-selection feedback",
        "model_id": config["model_id"],
        "revision": config["revision"],
        "precision": config["precision"],
        "adapter_path": config["adapter_path"],
        "dataset_audit": audit,
        "rows": rows,
        "target_token_weighted_loss": sum(
            row["negative_log_likelihood"] * row["target_tokens"] for row in rows
        )
        / sum(row["target_tokens"] for row in rows),
        "elapsed_seconds": time.perf_counter() - started,
        "hardware": machine_details(),
        "runtime_versions": runtime_versions(),
        "selected_or_updated_weights": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    smoke = commands.add_parser("smoke")
    smoke.add_argument("--output", type=Path, default=Path("output/smoke"))
    smoke.add_argument("--config", type=Path, default=DATA_ROOT / "configs/smoke.json")
    compatibility = commands.add_parser("compatibility")
    compatibility.add_argument("--output", type=Path, required=True)
    train = commands.add_parser("compact")
    train.add_argument("--config", type=Path, default=DATA_ROOT / "configs/compact-lora.json")
    train.add_argument("--manifest", type=Path, required=True)
    train.add_argument("--annotations", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument(
        "--allow-download",
        action="store_true",
        help="explicitly permit model weight download; no private dataset upload",
    )
    args = parser.parse_args()
    if args.command == "smoke":
        report = run_smoke(args.output, json.loads(args.config.read_text()))
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "purpose",
                        "initial_loss",
                        "final_loss",
                        "weight_change_l2",
                        "reload_exact",
                        "validation_classification_accuracy",
                        "training_seconds",
                    )
                },
                indent=2,
            )
        )
    elif args.command == "compatibility":
        report = run_ml_compatibility(args.output)
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "purpose",
                        "initial_loss",
                        "last_training_loss",
                        "reload_exact",
                        "adapter_reload_max_logit_difference",
                        "elapsed_seconds",
                    )
                },
                indent=2,
            )
        )
    else:
        report = train_compact(
            args.config, args.manifest, args.annotations, args.output, allow_download=args.allow_download
        )
        print(
            json.dumps(
                {key: report[key] for key in ("status", "model_id", "optimizer_steps", "training_seconds")},
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
