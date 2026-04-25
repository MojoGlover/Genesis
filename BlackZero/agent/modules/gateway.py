"""
Model gateway client — all LLM calls go here.

No direct Ollama, Anthropic, or OpenAI calls in agent code.
If the gateway is down, falls back to direct Ollama (if configured).
"""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)

_FALLBACK_TIMEOUT = 120.0


class GatewayError(Exception):
    pass


class GatewayClient:
    def __init__(self, agent_id: str, url: str, model: str = "",
                 enabled: bool = True, fallback_ollama: str = ""):
        self.agent_id        = agent_id
        self.url             = url.rstrip("/")
        self.model           = model   # preferred model_id in the gateway registry
        self.enabled         = enabled
        self.fallback_ollama = fallback_ollama  # e.g. "http://127.0.0.1:11434"

    def chat(self, messages: list[dict], capability: str = "chat",
             max_tokens: int = 2048, timeout: float = _FALLBACK_TIMEOUT) -> dict:
        """
        Send a chat request. Returns dict with content, model_id, cost_usd, latency_ms.
        Raises GatewayError only if both gateway and fallback fail.
        """
        if self.enabled:
            try:
                r = httpx.post(f"{self.url}/chat", json={
                    "agent_id":   self.agent_id,
                    "messages":   messages,
                    "model_id":   self.model,
                    "capability": capability,
                    "max_tokens": max_tokens,
                }, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                logger.warning(f"[gateway] {r.status_code} — trying fallback")
            except Exception as e:
                logger.warning(f"[gateway] unreachable ({e}) — trying fallback")

        # Fallback: direct Ollama
        if self.fallback_ollama and self.model:
            return self._ollama_fallback(messages, max_tokens, timeout)

        raise GatewayError("model_gateway unavailable and no fallback configured")

    def _ollama_fallback(self, messages: list[dict], max_tokens: int,
                         timeout: float) -> dict:
        import time
        t0 = time.time()
        try:
            r = httpx.post(f"{self.fallback_ollama}/api/chat", json={
                "model":   self.model,
                "messages": messages,
                "options": {"num_predict": max_tokens},
                "stream":  False,
            }, timeout=timeout)
            r.raise_for_status()
            data    = r.json()
            content = data.get("message", {}).get("content", "")
            return {
                "ok":           True,
                "model_id":     self.model,
                "backend":      "ollama-direct",
                "content":      content,
                "input_tokens":  len(str(messages)) // 4,
                "output_tokens": len(content) // 4,
                "cost_usd":     0.0,
                "latency_ms":   round((time.time() - t0) * 1000, 1),
            }
        except Exception as e:
            raise GatewayError(f"ollama fallback failed: {e}") from e
