"""Bounded, explicit local queue for optional model review. No upload triggers calls."""

import hashlib
import importlib.util
import ipaddress
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from noticeforge.providers import (
    CompactConfig,
    CompatibleProvider,
    FixtureProvider,
    Provider,
    ProviderResult,
    TransformersProvider,
    bound_pages,
    extract_candidates,
)
from noticeforge.repository import Repository, ReviewError


class ModelService:
    def __init__(self, repo: Repository, provider: Provider | None = None):
        self.repo = repo
        self.provider = provider
        self.mode = "injected" if provider else os.getenv("NOTICEFORGE_PROVIDER", "none")
        self.config: dict = {}
        self.configuration_error: str | None = None
        self.remote = False
        self._lock = Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False
        self._token = os.getenv("NOTICEFORGE_MODEL_TOKEN")
        if self.mode == "transformers":
            try:
                self.config = json.loads(Path(os.environ["NOTICEFORGE_MODEL_CONFIG"]).read_text())
                self.config["allow_download"] = False
                self.config = CompactConfig.model_validate(self.config).model_dump()
            except (KeyError, OSError, ValueError, TypeError):
                self.configuration_error = (
                    "Set NOTICEFORGE_MODEL_CONFIG to a valid local model profile and restart the server."
                )
            if importlib.util.find_spec("transformers") is None:
                self.configuration_error = "Install the optional model environment and start this server with its Python interpreter."
        elif self.mode == "compatible":
            self.config = {
                "base_url": os.getenv("NOTICEFORGE_MODEL_BASE_URL", ""),
                "model_id": os.getenv("NOTICEFORGE_MODEL_ID", ""),
                "allow_remote": os.getenv("NOTICEFORGE_ALLOW_REMOTE") == "1",
                "timeout": os.getenv("NOTICEFORGE_MODEL_TIMEOUT", "30"),
            }
            try:
                endpoint = urlparse(self.config["base_url"])
                host = endpoint.hostname or ""
                _ = endpoint.port  # Reject invalid ports before a run is queued.
                try:
                    self.remote = not ipaddress.ip_address(host).is_loopback
                except ValueError:
                    self.remote = host.lower() != "localhost"
            except ValueError:
                self.configuration_error = (
                    "Configure a valid HTTP(S) model endpoint, then restart the server."
                )
            if not self.config["base_url"] or not self.config["model_id"]:
                self.configuration_error = (
                    "Configure the model endpoint and model ID, then restart the server."
                )
            elif self.remote and not self.config["allow_remote"]:
                self.configuration_error = "Remote transfer is disabled. Configure an authorized endpoint and explicit remote opt-in."
            try:
                timeout = float(self.config["timeout"])
                if not 0 < timeout <= 300:
                    raise ValueError()
                self.config["timeout"] = timeout
            except (ValueError, TypeError):
                self.configuration_error = "Model timeout must be a positive number of seconds, at most 300."
            if not self.configuration_error:
                try:
                    # This validates settings without sending a request.
                    self.provider = CompatibleProvider(
                        self.config["base_url"],
                        self.config["model_id"],
                        token=self._token,
                        allow_remote=self.config["allow_remote"],
                        timeout=self.config["timeout"],
                    )
                except ValueError:
                    self.configuration_error = "Use a valid HTTP(S) endpoint without embedded credentials, query, or fragment; remote endpoints require HTTPS."
        elif self.mode == "fixture":
            self.config = {"fixture_path": os.getenv("NOTICEFORGE_FIXTURE_OUTPUT_PATH", "")}
        elif self.mode not in {"none", "injected"}:
            self.configuration_error = (
                "Unknown model provider. Choose a documented local or compatible profile."
            )

    def describe(self) -> dict:
        provider = (
            self.provider.name
            if self.provider
            else {
                "transformers": "local-transformers",
                "compatible": "compatible-http",
                "fixture": "fixture-offline",
            }.get(self.mode, "none")
        )
        model = (
            self.provider.model_id
            if self.provider
            else self.config.get("model_id", "fixture-json-v1" if self.mode == "fixture" else None)
        )
        configured = self.mode != "none"
        return {
            "configured": configured,
            "provider": provider,
            "model": model,
            "remote": self.remote,
            "available": configured and not self.configuration_error,
            "reason": self.configuration_error
            or (
                "No model is configured. Rules extraction remains available. See the local model setup guide."
                if not configured
                else "Model review runs only when explicitly requested; proposals require a decision."
            ),
        }

    def _configuration(self) -> dict:
        description = self.describe()
        config = self.config or getattr(self.provider, "config", {})
        public_keys = {
            "model_id",
            "revision",
            "precision",
            "adapter_path",
            "local_model_path",
            "max_input_tokens",
            "max_new_tokens",
            "max_characters",
            "generation_max_seconds",
            "cpu_threads",
            "attention_implementation",
        }
        public = {key: value for key, value in config.items() if key in public_keys}
        public.update(provider=description["provider"], model=description["model"], remote=self.remote)
        if config.get("base_url"):
            endpoint = urlparse(config["base_url"])
            public["endpoint"] = (
                f"{endpoint.scheme}://{endpoint.hostname or ''}{':' + str(endpoint.port) if endpoint.port else ''}{endpoint.path}"
            )
        if config.get("adapter_path"):
            manifest = Path(config["adapter_path"]) / "checkpoint_manifest.json"
            if manifest.is_file():
                public["adapter_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        public["configuration_sha256"] = hashlib.sha256(
            json.dumps(public, sort_keys=True).encode()
        ).hexdigest()
        return public

    def _provider(self) -> Provider:
        if self.provider is None:
            if self.configuration_error:
                raise ValueError("Model configuration is unavailable")
            if self.mode == "transformers":
                self.provider = TransformersProvider(self.config)
            elif self.mode == "compatible":
                self.provider = CompatibleProvider(
                    self.config["base_url"],
                    self.config["model_id"],
                    token=self._token,
                    allow_remote=self.config["allow_remote"],
                    timeout=float(self.config["timeout"]),
                )
            elif self.mode == "fixture":
                path = self.config["fixture_path"]
                if path and Path(path).stat().st_size > 1048576:
                    raise ValueError("Fixture output exceeds 1 MiB")
                self.provider = FixtureProvider(Path(path).read_text() if path else '{"candidates":[]}')
            else:
                raise ValueError("No model is configured")
        return self.provider

    def start(self, notice_id: str, expected_version: int) -> dict:
        with self._lock:
            if self._closed:
                raise ReviewError(
                    "Model service has shut down; restart the server before requesting proposals"
                )
            if not self.describe()["configured"]:
                raise ReviewError(
                    "No model is configured. Configure a local profile and restart before requesting proposals"
                )
            if self.configuration_error:
                raise ReviewError(self.configuration_error)
            record = self.repo.get(notice_id)
            limit = int(self.config.get("max_characters", 16000))
            bounded = bound_pages(record.document.pages, max_characters=limit)
            run = self.repo.start_model_run(
                notice_id, expected_version, self._configuration(), bounded.input_sha256
            )
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="noticeforge-model")
            self._executor.submit(self._run, run, record.document.pages, limit)
        return run

    def _run(self, run: dict, pages: list, limit: int):
        try:
            self.repo.set_model_run_result(run["id"], None)
            result = extract_candidates(pages, self._provider(), max_characters=limit)
        except Exception as exc:
            result = ProviderResult(
                provider=run["provider"],
                model=run["model"] or "unconfigured",
                status="unavailable",
                errors=[
                    f"{type(exc).__name__}: configured model runtime or weights unavailable. Check the local profile and restart."
                ],
            )
        self.repo.set_model_run_result(run["id"], result)

    def close(self):
        # Admission and shutdown share one lock so a rejected request cannot leave
        # a queued database row after executor shutdown. Drain existing bounded work.
        with self._lock:
            self._closed = True
            executor = self._executor
        if executor:
            executor.shutdown(wait=True)
