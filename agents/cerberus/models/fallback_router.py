"""
fallback_router.py — Multi-provider fallback chain.

Priority: local Ollama → Anthropic Claude → OpenAI → offline error.

The agent's identity (system prompt) is preserved across all backends.
Switching providers never means switching agents.

Environment variables:
    ANTHROPIC_API_KEY        — enables Claude fallback
    OPENAI_API_KEY           — enables OpenAI fallback
    FALLBACK_MODEL_ANTHROPIC — override (default: claude-haiku-4-5)
    FALLBACK_MODEL_OPENAI    — override (default: gpt-4o-mini)

NOTE: Imports here use non-prefixed paths because this file is designed
to be stamped into a standalone agent with its root on sys.path.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any

from models.model_router import ModelRouter, GenerationConfig
from models.provider_adapter import ProviderAdapter, ProviderError

logger = logging.getLogger(__name__)

# ── Rate limiting ──────────────────────────────────────────────────────────────
_RATE_WINDOW_MS  = 60_000
_RATE_MAX_CALLS  = 30
_MIN_INTERVAL_MS = 300
_call_times: list[float] = []
_last_call: float = 0.0


def _check_rate() -> bool:
    global _last_call
    now = time.time() * 1000
    if now - _last_call < _MIN_INTERVAL_MS:
        return False
    cutoff = now - _RATE_WINDOW_MS
    while _call_times and _call_times[0] < cutoff:
        _call_times.pop(0)
    if len(_call_times) >= _RATE_MAX_CALLS:
        logger.warning("FallbackRouter: rate limit hit")
        return False
    _call_times.append(now)
    _last_call = now
    return True


# ── Retry helper ───────────────────────────────────────────────────────────────

def _with_retry(fn, retries: int = 2, base_delay: float = 0.8):
    last_err = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(base_delay * (attempt + 1))
    raise last_err


# ── Anthropic adapter ──────────────────────────────────────────────────────────

class AnthropicAdapter(ProviderAdapter):
    """Claude via Anthropic API. Model configurable via FALLBACK_MODEL_ANTHROPIC."""

    _API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self) -> None:
        self._key   = os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = os.environ.get("FALLBACK_MODEL_ANTHROPIC", "claude-haiku-4-5")

    @property
    def name(self) -> str:
        return "anthropic"

    def is_available(self) -> bool:
        return bool(self._key)

    def default_model(self) -> str | None:
        return self._model

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if not self._key:
            raise ProviderError("No ANTHROPIC_API_KEY set")

        system     = kwargs.get("system", "")
        model      = kwargs.get("model", self._model)
        max_tokens = kwargs.get("max_tokens", 1024)

        payload = {
            "model":      model,
            "max_tokens": max_tokens,
            "messages":   [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            self._API_URL,
            data=data,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         self._key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                return result["content"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise ProviderError(f"Anthropic {e.code}: {body[:200]}")
        except Exception as e:
            raise ProviderError(f"Anthropic request failed: {e}")


# ── OpenAI adapter ─────────────────────────────────────────────────────────────

class OpenAIAdapter(ProviderAdapter):
    """GPT via OpenAI API. Model configurable via FALLBACK_MODEL_OPENAI."""

    _API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self) -> None:
        self._key   = os.environ.get("OPENAI_API_KEY", "")
        self._model = os.environ.get("FALLBACK_MODEL_OPENAI", "gpt-4o-mini")

    @property
    def name(self) -> str:
        return "openai"

    def is_available(self) -> bool:
        return bool(self._key)

    def default_model(self) -> str | None:
        return self._model

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if not self._key:
            raise ProviderError("No OPENAI_API_KEY set")

        system     = kwargs.get("system", "")
        model      = kwargs.get("model", self._model)
        max_tokens = kwargs.get("max_tokens", 1024)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":      model,
            "messages":   messages,
            "max_tokens": max_tokens,
        }

        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            self._API_URL,
            data=data,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                return result["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise ProviderError(f"OpenAI {e.code}: {body[:200]}")
        except Exception as e:
            raise ProviderError(f"OpenAI request failed: {e}")


# ── Fallback router ────────────────────────────────────────────────────────────

class FallbackRouter(ModelRouter):
    """
    Multi-provider router: Ollama → Anthropic → OpenAI.

    The agent's identity (system prompt) threads through every backend.
    Switching backends never changes who is answering.
    """

    def __init__(self, ollama_router: ModelRouter) -> None:
        self._ollama    = ollama_router
        self._anthropic = AnthropicAdapter()
        self._openai    = OpenAIAdapter()
        self._last_used = "ollama"

    def complete(self, prompt: str, config: GenerationConfig | None = None) -> str:
        if not _check_rate():
            return "Getting too many requests — slow down a bit."

        cfg = config or GenerationConfig()

        # 1. Local Ollama — 2 retries
        try:
            result = _with_retry(lambda: self._ollama.complete(prompt, cfg), retries=2)
            self._last_used = "ollama"
            return result.strip() or self._empty_response_fallback(prompt, cfg)
        except Exception as e:
            logger.warning(f"Ollama failed: {e}. Trying Anthropic...")

        # 2. Anthropic — identity preserved via system prompt
        if self._anthropic.is_available():
            try:
                result = _with_retry(
                    lambda: self._anthropic.generate(
                        prompt,
                        system=cfg.system_prompt or "",
                        max_tokens=cfg.max_tokens,
                    ),
                    retries=1,
                )
                self._last_used = "anthropic"
                logger.info("FallbackRouter: using Anthropic")
                return result.strip()
            except Exception as e:
                logger.warning(f"Anthropic failed: {e}. Trying OpenAI...")

        # 3. OpenAI — identity preserved via system prompt
        if self._openai.is_available():
            try:
                result = _with_retry(
                    lambda: self._openai.generate(
                        prompt,
                        system=cfg.system_prompt or "",
                        max_tokens=cfg.max_tokens,
                    ),
                    retries=1,
                )
                self._last_used = "openai"
                logger.info("FallbackRouter: using OpenAI")
                return result.strip()
            except Exception as e:
                logger.error(f"OpenAI failed: {e}")

        # All failed
        self._last_used = "offline"
        logger.error("FallbackRouter: all providers failed")
        return "All backends offline. Local model, Anthropic, and OpenAI all unreachable."

    def complete_with_system(
        self, system: str, user: str, config: GenerationConfig | None = None
    ) -> str:
        cfg = config or GenerationConfig()
        cfg.system_prompt = system
        return self.complete(user, cfg)

    def list_providers(self) -> list[str]:
        providers = ["ollama"]
        if self._anthropic.is_available():
            providers.append("anthropic")
        if self._openai.is_available():
            providers.append("openai")
        return providers

    @property
    def last_used(self) -> str:
        return self._last_used

    def _empty_response_fallback(self, prompt: str, cfg: GenerationConfig) -> str:
        """Ollama returned empty — try cloud before giving up."""
        logger.warning("Ollama returned empty response, trying cloud fallback")
        if self._anthropic.is_available():
            try:
                return self._anthropic.generate(
                    prompt, system=cfg.system_prompt or "", max_tokens=cfg.max_tokens
                )
            except Exception:
                pass
        return "Got an empty response from the local model. Try again."
