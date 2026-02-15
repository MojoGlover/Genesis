"""Ollama async client for LLM interactions."""

import time
from typing import Any

import httpx

from ai_starter.config.settings import OllamaSettings
from ai_starter.llm.schemas import LLMResponse, Message


class OllamaClient:
    """Async HTTP client for Ollama API."""

    def __init__(self, settings: OllamaSettings):
        self.settings = settings
        self.client = httpx.AsyncClient(base_url=settings.base_url, timeout=120.0)

    async def generate(
        self,
        messages: list[Message],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Call Ollama /api/chat endpoint."""
        start_time = time.perf_counter()

        payload = {
            "model": self.settings.model,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
            "stream": False,
            "options": {
                "temperature": temperature or self.settings.temperature,
                "num_predict": max_tokens or self.settings.max_tokens,
            },
        }

        response = await self.client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            model=data.get("model", self.settings.model),
            latency_ms=latency_ms,
            raw=data,
        )

    async def is_available(self) -> bool:
        """Check if Ollama is running and accessible."""
        try:
            response = await self.client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """Enumerate installed Ollama models."""
        try:
            response = await self.client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except Exception:
            return []

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
