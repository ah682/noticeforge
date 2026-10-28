"""Optional real-library compatibility checks; no downloaded model or GPU required."""

import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(
    all(importlib.util.find_spec(name) for name in ("torch", "transformers", "peft", "tokenizers")),
    "optional ML environment is not installed",
)
class MLCompatibilityTest(unittest.TestCase):
    def test_training_profile_preserves_text_and_reloads_changed_adapter(self):
        from noticeforge.providers import load_compact_components
        from noticeforge.training import _full_profile_compatibility_smoke, _training_examples

        with tempfile.TemporaryDirectory(prefix="noticeforge-ml-compatibility-") as temporary:
            folder = Path(temporary) / "profile"
            report = _full_profile_compatibility_smoke(folder)
            manifest = json.loads(Path(report["checkpoint_manifest"]).read_text())
            self.assertEqual(report["optimizer_steps"], 2)
            self.assertTrue(report["serving_adapter_loaded"])
            self.assertEqual(len(manifest["losses"]), 2)
            self.assertTrue(all(math.isfinite(loss) for loss in manifest["losses"]))
            self.assertNotEqual(manifest["initial_trainable_sha256"], manifest["final_trainable_sha256"])
            config = json.loads((folder / "config.json").read_text())
            tokenizer, _ = load_compact_components(config)
            text = "system last_buy 2027-04-30"
            tokens = tokenizer(text, add_special_tokens=False)["input_ids"]
            self.assertGreater(len(tokens), 1)
            self.assertEqual(tokenizer.decode(tokens), text)
            examples, _ = _training_examples(folder / "manifest.json", folder / "annotations.jsonl", config)
            _, messages, target = examples[0]
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            prefix = tokenizer(prompt, add_special_tokens=False)["input_ids"]
            ids = tokenizer(prompt + target + tokenizer.eos_token, add_special_tokens=False)["input_ids"]
            self.assertGreater(len(prefix), 0)
            self.assertEqual(ids[: len(prefix)], prefix)
            labels = [-100] * len(prefix) + ids[len(prefix) :]
            self.assertTrue(any(token != -100 for token in labels[1:]))


if __name__ == "__main__":
    unittest.main()
