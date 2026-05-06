"""
model_gateway/client.py — Python client for the Model Gateway node.

Usage:
    from model_gateway.client import ModelGatewayClient

    gw = ModelGatewayClient(agent_id="engineer0")

    # Chat (multi-turn)
    reply = gw.chat([
        {"role": "user", "content": "What is 2+2?"}
    ])
    print(reply["content"])

    # Completion (single prompt)
    text = gw.complete("Summarize this in one sentence: ...")
    print(text)

    # List available models
    models = gw.models()

    # Register a custom model
    gw.register_model("my-llm", backend="ollama", endpoint="http://localhost:11434",
                      context_window=8192, input_price=0.0, output_price=0.0)

    # Usage stats
    usage = gw.my_usage()
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("model_gateway.client")

DEFAULT_URL = "http://127.0.0.1:9109"


class ModelGatewayError(Exception):
    pass


class ModelGatewayClient:
    def __init__(self, agent_id: str, url: str = DEFAULT_URL, timeout: float = 60.0):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.timeout  = timeout

    def chat(
        self,
        messages:        list[dict],
        model:           str  | None = None,
        capability:      str  | None = None,
        backend:         str  | None = None,
        max_tokens:      int         = 1024,
        temperature:     float       = 0.7,
        system_prompt:   str  | None = None,
    ) -> dict:
        """
        Send a chat request. Returns dict with content, model_id, usage, cost_usd.
        Raises ModelGatewayError on failure.
        """
        try:
            r = httpx.post(
                f"{self.url}/chat",
                json={
                    "agent_id":      self.agent_id,
                    "messages":      messages,
                    "model":         model,
                    "capability":    capability,
                    "backend":       backend,
                    "max_tokens":    max_tokens,
                    "temperature":   temperature,
                    "system_prompt": system_prompt,
                },
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return r.json()
            raise ModelGatewayError(f"chat failed {r.status_code}: {r.text}")
        except ModelGatewayError:
            raise
        except Exception as e:
            raise ModelGatewayError(f"chat request error: {e}") from e

    def complete(
        self,
        prompt:      str,
        model:       str  | None = None,
        capability:  str  | None = None,
        backend:     str  | None = None,
        max_tokens:  int         = 512,
        temperature: float       = 0.7,
    ) -> str:
        """Simple text completion. Returns content string."""
        result = self.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            capability=capability,
            backend=backend,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return result.get("content", "")

    def models(self, backend: str | None = None, capability: str | None = None) -> list[dict]:
        """List available models."""
        try:
            params: dict[str, str] = {}
            if backend:
                params["backend"] = backend
            if capability:
                params["capability"] = capability
            r = httpx.get(f"{self.url}/models", params=params, timeout=self.timeout)
            if r.status_code == 200:
                return r.json().get("models", [])
            return []
        except Exception:
            return []

    def register_model(
        self,
        model_id:        str,
        backend:         str,
        endpoint:        str,
        model_name:      str  | None = None,
        context_window:  int         = 4096,
        capabilities:    list[str]   | None = None,
        priority:        int         = 50,
        input_price:     float       = 0.0,
        output_price:    float       = 0.0,
        max_tokens:      int         = 1024,
        api_key_env:     str  | None = None,
    ) -> dict:
        """Register a model. Returns created/updated model record."""
        try:
            r = httpx.post(
                f"{self.url}/models/register",
                json={
                    "model_id":       model_id,
                    "model_name":     model_name or model_id,
                    "backend":        backend,
                    "endpoint":       endpoint,
                    "context_window": context_window,
                    "capabilities":   capabilities or ["chat"],
                    "priority":       priority,
                    "cost_per_1k_in": input_price,
                    "cost_per_1k_out": output_price,
                    "max_tokens":     max_tokens,
                    "api_key_env":    api_key_env,
                },
                timeout=self.timeout,
            )
            if r.status_code in (200, 201):
                return r.json()
            raise ModelGatewayError(f"register failed {r.status_code}: {r.text}")
        except ModelGatewayError:
            raise
        except Exception as e:
            raise ModelGatewayError(f"register request error: {e}") from e

    def disable_model(self, model_id: str) -> bool:
        """Soft-disable a model."""
        try:
            r = httpx.delete(f"{self.url}/models/{model_id}", timeout=self.timeout)
            return r.status_code == 200
        except Exception:
            return False

    def model_health(self, model_id: str) -> dict | None:
        """Get health status for a specific model."""
        try:
            r = httpx.get(f"{self.url}/models/{model_id}/health", timeout=self.timeout)
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    def my_usage(self, limit: int = 100) -> dict:
        """Get usage records for this agent."""
        try:
            r = httpx.get(
                f"{self.url}/usage/{self.agent_id}",
                params={"limit": limit},
                timeout=self.timeout,
            )
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    def system_usage(self, limit: int = 100) -> dict:
        """Get system-wide usage records."""
        try:
            r = httpx.get(f"{self.url}/usage", params={"limit": limit}, timeout=self.timeout)
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    def health(self) -> dict | None:
        """Gateway liveness probe."""
        try:
            r = httpx.get(f"{self.url}/health", timeout=5.0)
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    def stats(self) -> dict | None:
        """Gateway internal counters."""
        try:
            r = httpx.get(f"{self.url}/stats", timeout=5.0)
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None
