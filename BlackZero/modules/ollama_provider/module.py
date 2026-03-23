"""
ollama_provider — Ollama model router with cloud fallback.

Provides the model_router slot to the loader.
Wraps OllamaRouter in FallbackRouter if cloud API keys are present in env.

Config keys:
    models.reasoning             — primary model name
    tools.ollama_api             — Ollama base URL
    modules.ollama_provider.timeout — request timeout in seconds (default 120)

Environment:
    OLLAMA_API_URL     — overrides tools.ollama_api (Docker sidecar URL)
    ANTHROPIC_API_KEY  — enables Anthropic Claude fallback
    OPENAI_API_KEY     — enables OpenAI fallback

Returns:
    {"model_router": FallbackRouter | OllamaRouter}
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any

from models.model_router import ModelRouter, GenerationConfig
from models.provider_adapter import ProviderAdapter, ProviderError

logger = logging.getLogger(__name__)

MANIFEST = {
    "name": "ollama_provider",
    "description": "Ollama model router with cloud fallback",
    "requires_credentials": [],
    "requires_config": [],
    "provides": ["model_router"],
    "optional_credentials": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
    "capabilities": ["generation"],
}


def _clean_response(text: str) -> str:
    """Strip wrapper artifacts from model output."""
    if not text:
        return text
    if text.startswith("[{") and "text" in text:
        try:
            data = json.loads(text)
            if isinstance(data, list) and len(data) > 0 and "text" in data[0]:
                return data[0]["text"].strip()
        except Exception:
            pass
    if text.startswith("{'text':") or text.startswith('{"text":'):
        try:
            cleaned = text.replace("'", '"')
            data = json.loads(cleaned)
            if isinstance(data, dict) and "text" in data:
                return data["text"].strip()
        except Exception:
            pass
    return text.strip()


class OllamaAdapter(ProviderAdapter):
    """Concrete Ollama provider using the REST API."""

    def __init__(self, api_url: str, default_model_name: str, timeout: float = 120.0):
        self._api_url       = api_url.rstrip("/")
        self._default_model = default_model_name
        self._timeout       = timeout
        self._available     = None

    @property
    def name(self) -> str:
        return "ollama"

    def generate(self, prompt: str, **kwargs: Any) -> str:
        model       = kwargs.get("model", self._default_model)
        temperature = kwargs.get("temperature", 0.7)
        system      = kwargs.get("system")

        payload = {
            "model":   model,
            "prompt":  prompt,
            "stream":  False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            f"{self._api_url}/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                result = json.loads(resp.read().decode())
                raw = result.get("response", "").strip()
                return _clean_response(raw)
        except Exception as e:
            raise ProviderError(f"Ollama generate failed: {e}")

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            req = urllib.request.Request(f"{self._api_url}/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                self._available = resp.status == 200
        except Exception:
            self._available = False
        return self._available

    def default_model(self) -> str | None:
        return self._default_model

    def reset_availability(self) -> None:
        self._available = None


class OllamaRouter(ModelRouter):
    """Routes all generation to Ollama."""

    def __init__(self, adapter: OllamaAdapter):
        self._adapter = adapter

    def complete(self, prompt: str, config: GenerationConfig | None = None) -> str:
        cfg   = config or GenerationConfig()
        model = cfg.model or self._adapter.default_model()
        kwargs = {"model": model, "temperature": cfg.temperature}
        if cfg.system_prompt:
            kwargs["system"] = cfg.system_prompt
        return self._adapter.generate(prompt, **kwargs)

    def complete_with_system(
        self, system: str, user: str, config: GenerationConfig | None = None
    ) -> str:
        cfg = config or GenerationConfig()
        cfg.system_prompt = system
        return self.complete(user, cfg)

    def list_providers(self) -> list[str]:
        return ["ollama"]

    def is_available(self) -> bool:
        return self._adapter.is_available()


def setup(config: dict) -> dict:
    """Module entry point. Called by the loader."""
    from modules.module_manifest import registry
    registry.register("ollama_provider", MANIFEST, status="active")

    models     = config.get("models", {})
    tools      = config.get("tools", {})
    identity   = config.get("identity", {})
    mod_config = config.get("modules", {}).get("ollama_provider", {})

    # OLLAMA_API_URL wins over config (Docker sidecar)
    api_url = (
        os.environ.get("OLLAMA_API_URL")
        or tools.get("ollama_api", "http://localhost:11434/api")
    )

    # Model: from config, or derive from agent identity if not set
    slug          = identity.get("designation", "agent").lower().replace(" ", "")
    default_model = models.get("reasoning", f"{slug}:latest")
    timeout       = mod_config.get("timeout", 120)

    adapter      = OllamaAdapter(api_url=api_url, default_model_name=default_model, timeout=timeout)
    ollama_router = OllamaRouter(adapter)

    # Wrap in fallback chain if cloud keys are present
    try:
        from models.fallback_router import FallbackRouter
        router    = FallbackRouter(ollama_router)
        providers = router.list_providers()
        logger.info(
            f"ollama_provider: model={default_model}, api={api_url}, "
            f"available={adapter.is_available()}, providers={providers}"
        )
    except ImportError:
        router = ollama_router
        logger.info(
            f"ollama_provider: model={default_model}, api={api_url}, "
            f"available={adapter.is_available()}"
        )

    return {"model_router": router}
