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
                 enabled: bool = True, fallback_ollama: str = "",
                 model_map: dict | None = None):
        self.agent_id        = agent_id
        self.url             = url.rstrip("/")
        self.model           = model   # default model_id (used when no task_type given)
        self.enabled         = enabled
        self.fallback_ollama = fallback_ollama  # e.g. "http://127.0.0.1:11434"
        # task_type → gateway model_id  (e.g. {"reasoning": "ollama-llama3-70b", "chat": "engineer0-tools"})
        self._model_map: dict[str, str] = model_map or {}

    def _model_for(self, task_type: str) -> str:
        """Return the gateway model_id for a task type, falling back to the default."""
        return self._model_map.get(task_type, self.model)

    def chat_for(self, messages: list[dict], task_type: str = "chat",
                 max_tokens: int = 2048, timeout: float = _FALLBACK_TIMEOUT,
                 tools: list[dict] | None = None) -> dict:
        """
        Chat with automatic model selection based on task_type.
        Pass tools to enable Ollama native function calling — when present,
        the model outputs structured tool_calls instead of prose.
        """
        return self.chat(messages, capability=task_type,
                         model_id_override=self._model_for(task_type),
                         max_tokens=max_tokens, timeout=timeout,
                         tools=tools)

    def chat(self, messages: list[dict], capability: str = "chat",
             model_id_override: str = "",
             max_tokens: int = 2048, timeout: float = _FALLBACK_TIMEOUT,
             tools: list[dict] | None = None) -> dict:
        """
        Send a chat request. Returns dict with content, tool_calls, model_id,
        cost_usd, latency_ms.

        When tools is provided:
          - Passed to Ollama's native function-calling API
          - Response includes tool_calls list when model invokes a tool
          - content will be empty on tool invocations
          - Use parse_native_tool_call() from registry to extract the call

        Raises GatewayError only if both gateway and fallback fail.
        """
        model_id = model_id_override or self.model
        if self.enabled:
            try:
                payload = {
                    "agent_id":   self.agent_id,
                    "messages":   messages,
                    "model_id":   model_id,
                    "capability": capability,
                    "max_tokens": max_tokens,
                }
                if tools:
                    payload["tools"] = tools
                r = httpx.post(f"{self.url}/chat", json=payload, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                logger.warning(f"[gateway] {r.status_code} — trying fallback")
            except Exception as e:
                logger.warning(f"[gateway] unreachable ({e}) — trying fallback")

        # Fallback: direct Ollama using self.model (the Ollama model name).
        # model_id_override is a gateway model_id (e.g. "phi4-14b") — we can't
        # resolve it to an Ollama name without the gateway, so we fall back to
        # the primary model instead of crashing. This is always better than a
        # hard GatewayError when Ollama is reachable.
        if self.fallback_ollama and self.model:
            logger.warning(
                f"[gateway] Falling back to direct Ollama ({self.model})"
                + (f" instead of {model_id_override}" if model_id_override else "")
            )
            return self._ollama_fallback(messages, max_tokens, timeout, tools=tools)

        raise GatewayError("model_gateway unavailable and no fallback configured")

    def _ollama_fallback(self, messages: list[dict], max_tokens: int,
                         timeout: float, tools: list[dict] | None = None) -> dict:
        import time
        t0 = time.time()
        try:
            body: dict = {
                "model":   self.model,
                "messages": messages,
                "options": {"num_predict": max_tokens},
                "stream":  False,
            }
            if tools:
                body["tools"] = tools

            r = httpx.post(f"{self.fallback_ollama}/api/chat",
                           json=body, timeout=timeout)
            r.raise_for_status()
            data    = r.json()
            message = data.get("message", {})
            content = message.get("content", "")
            # Native tool calls come back on message.tool_calls
            tool_calls = message.get("tool_calls")
            if not tool_calls and content:
                from agent.tools.registry import parse_tool_call as _ptc
                parsed = _ptc(content)
                if parsed:
                    tool_calls = [{"function": {"name": parsed["tool"],
                                                "arguments": parsed.get("params", {})}}]

            return {
                "ok":           True,
                "model_id":     self.model,
                "backend":      "ollama-direct",
                "content":      content,
                "tool_calls":   tool_calls,   # None when prose, list when tool invoked
                "input_tokens":  len(str(messages)) // 4,
                "output_tokens": len(content) // 4,
                "cost_usd":     0.0,
                "latency_ms":   round((time.time() - t0) * 1000, 1),
            }
        except Exception as e:
            raise GatewayError(f"ollama fallback failed: {e}") from e
