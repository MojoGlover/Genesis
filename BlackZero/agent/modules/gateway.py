"""
Model gateway client — all LLM calls go here.

No direct Ollama, Anthropic, or OpenAI calls in agent code.

Call chain (first success wins):
  1. Cloud primary  — if model.provider is "anthropic" or "openai"
  2. Local gateway  — model_gateway module (port 9109)
  3. Direct Ollama  — if fallback_ollama configured
  4. Cloud fallback — last resort (Anthropic only, from model.cloud_fallback)

Config (config.yaml model section):
  provider:       "ollama"      # ollama | anthropic | openai
  cloud_model:    ""            # e.g. claude-haiku-4-5, gpt-4o-mini (cloud primary)
  primary:        ""            # gateway model_id (ollama path)
  fallback:       ""            # direct ollama model name
  cloud_fallback: ""            # anthropic model for last-resort fallback

Environment:
  ANTHROPIC_API_KEY   — required for provider=anthropic or cloud_fallback
  OPENAI_API_KEY      — required for provider=openai
"""
from __future__ import annotations

import logging
import os
import time
import httpx

logger = logging.getLogger(__name__)

_FALLBACK_TIMEOUT = 120.0

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_OPENAI_URL    = "https://api.openai.com/v1/chat/completions"


class GatewayError(Exception):
    pass


class GatewayClient:
    def __init__(
        self,
        agent_id: str,
        url: str,
        model: str = "",
        enabled: bool = True,
        fallback_ollama: str = "",
        fallback_model: str = "",
        cloud_fallback_model: str = "",
        cloud_provider: str = "ollama",   # "ollama" | "anthropic" | "openai"
        cloud_model: str = "",            # model id for cloud primary
        task_ollama: str = "",            # plugwan Ollama URL for async task execution
        task_model: str = "",             # model to use for tasks (e.g. phi4:14b)
        model_map: dict | None = None,
    ) -> None:
        self.agent_id             = agent_id
        self.url                  = url.rstrip("/")
        self.model                = model
        self.enabled              = enabled
        self.fallback_ollama      = fallback_ollama
        self.fallback_model       = fallback_model or model
        self.cloud_fallback_model = cloud_fallback_model
        self.cloud_provider       = cloud_provider.lower()
        self.cloud_model          = cloud_model
        self.task_ollama          = task_ollama   # e.g. http://100.113.209.66:11434
        self.task_model           = task_model    # e.g. phi4:14b
        self._model_map: dict[str, str] = model_map or {}

    @property
    def _anthropic_key(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def _openai_key(self) -> str:
        return os.environ.get("OPENAI_API_KEY", "")

    def _model_for(self, task_type: str) -> str:
        return self._model_map.get(task_type, self.model)

    def task_chat(self, messages: list[dict], max_tokens: int = 4096,
                  timeout: float = _FALLBACK_TIMEOUT,
                  tools: list[dict] | None = None) -> dict:
        """
        Route a long-running task to the configured inference host (task_ollama).
        Falls back to cloud primary if unreachable.
        Use this from the task loop — not for real-time conversation.
        """
        if self.task_ollama and self.task_model:
            try:
                return self._ollama_chat_at(
                    self.task_ollama, self.task_model,
                    messages, max_tokens, timeout, tools=tools
                )
            except GatewayError as e:
                logger.warning(f"[gateway] task Ollama failed: {e} — falling back to cloud")
        # fallback: use normal chat path
        return self.chat(messages, capability="reasoning",
                         max_tokens=max_tokens, timeout=timeout, tools=tools)

    def chat_for(self, messages: list[dict], task_type: str = "chat",
                 max_tokens: int = 2048, timeout: float = _FALLBACK_TIMEOUT,
                 tools: list[dict] | None = None) -> dict:
        return self.chat(messages, capability=task_type,
                         model_id_override=self._model_for(task_type),
                         max_tokens=max_tokens, timeout=timeout, tools=tools)

    def chat(self, messages: list[dict], capability: str = "chat",
             model_id_override: str = "",
             max_tokens: int = 2048, timeout: float = _FALLBACK_TIMEOUT,
             tools: list[dict] | None = None) -> dict:
        """
        Route a chat request through the configured provider chain.
        Returns dict: content, tool_calls, model_id, backend, cost_usd, latency_ms.
        Raises GatewayError only if every path fails.
        """

        # ── 1. Cloud primary (anthropic or openai) ────────────────────────────
        if self.cloud_provider == "anthropic" and self.cloud_model and self._anthropic_key:
            try:
                return self._anthropic_chat(messages, self.cloud_model, max_tokens, timeout)
            except GatewayError as e:
                logger.warning(f"[gateway] Anthropic primary failed: {e} — trying local")

        elif self.cloud_provider == "openai" and self.cloud_model and self._openai_key:
            try:
                return self._openai_chat(messages, self.cloud_model, max_tokens, timeout)
            except GatewayError as e:
                logger.warning(f"[gateway] OpenAI primary failed: {e} — trying local")

        # ── 2. Local model_gateway ────────────────────────────────────────────
        model_id = model_id_override or self.model
        if self.enabled and model_id:
            try:
                payload: dict = {
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
                if 400 <= r.status_code < 500:
                    raise GatewayError(f"gateway rejected: HTTP {r.status_code} — {r.text[:200]}")
                logger.warning(f"[gateway] {r.status_code} — trying Ollama fallback")
            except GatewayError:
                raise
            except Exception as e:
                logger.warning(f"[gateway] unreachable ({e}) — trying Ollama fallback")

        # ── 3. Direct Ollama ──────────────────────────────────────────────────
        if self.fallback_ollama and self.fallback_model:
            logger.warning(f"[gateway] Direct Ollama fallback ({self.fallback_model})")
            try:
                return self._ollama_chat(messages, max_tokens, timeout, tools=tools)
            except GatewayError as e:
                logger.warning(f"[gateway] Ollama failed: {e} — trying cloud fallback")

        # ── 4. Cloud fallback (Anthropic last resort) ─────────────────────────
        if self.cloud_fallback_model and self._anthropic_key:
            logger.warning(f"[gateway] Anthropic cloud fallback ({self.cloud_fallback_model})")
            return self._anthropic_chat(messages, self.cloud_fallback_model, max_tokens, timeout)

        raise GatewayError("all inference paths failed — no provider available")

    # ── Provider implementations ───────────────────────────────────────────────

    def _anthropic_chat(self, messages: list[dict], model: str,
                        max_tokens: int, timeout: float) -> dict:
        t0 = time.time()
        try:
            clean = _normalize_messages(messages)
            r = httpx.post(
                _ANTHROPIC_URL,
                headers={
                    "x-api-key":         self._anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={"model": model, "max_tokens": max_tokens, "messages": clean},
                timeout=timeout,
            )
            r.raise_for_status()
            data    = r.json()
            content = "".join(b.get("text", "") for b in data.get("content", [])
                              if b.get("type") == "text")
            usage   = data.get("usage", {})
            return {
                "ok":            True,
                "model_id":      model,
                "backend":       "anthropic",
                "content":       content,
                "tool_calls":    None,
                "input_tokens":  usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cost_usd":      0.0,
                "latency_ms":    round((time.time() - t0) * 1000, 1),
            }
        except Exception as e:
            raise GatewayError(f"anthropic failed: {e}") from e

    def _openai_chat(self, messages: list[dict], model: str,
                     max_tokens: int, timeout: float) -> dict:
        t0 = time.time()
        try:
            clean = _normalize_messages(messages)
            r = httpx.post(
                _OPENAI_URL,
                headers={
                    "Authorization": f"Bearer {self._openai_key}",
                    "Content-Type":  "application/json",
                },
                json={"model": model, "max_tokens": max_tokens, "messages": clean},
                timeout=timeout,
            )
            r.raise_for_status()
            data    = r.json()
            choice  = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "") or ""
            usage   = data.get("usage", {})
            return {
                "ok":            True,
                "model_id":      model,
                "backend":       "openai",
                "content":       content,
                "tool_calls":    None,
                "input_tokens":  usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "cost_usd":      0.0,
                "latency_ms":    round((time.time() - t0) * 1000, 1),
            }
        except Exception as e:
            raise GatewayError(f"openai failed: {e}") from e

    def _ollama_chat_at(self, base_url: str, model: str, messages: list[dict],
                        max_tokens: int, timeout: float,
                        tools: list[dict] | None = None) -> dict:
        """Ollama call to an arbitrary URL/model — used for task routing."""
        t0 = time.time()
        try:
            body: dict = {
                "model":    model,
                "messages": messages,
                "options":  {"num_predict": max_tokens},
                "stream":   False,
            }
            if tools:
                body["tools"] = tools
            r = httpx.post(f"{base_url}/api/chat", json=body, timeout=timeout)
            r.raise_for_status()
            data    = r.json()
            msg     = data.get("message", {})
            content = msg.get("content", "")
            # Parse native Ollama tool_calls (list of {function: {name, arguments}})
            raw_tc  = msg.get("tool_calls") or []
            parsed_tc: list[dict] | None = None
            if raw_tc:
                parsed_tc = []
                for tc in raw_tc:
                    fn   = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        import json as _json
                        try:
                            args = _json.loads(args)
                        except Exception:
                            args = {}
                    if name:
                        parsed_tc.append({"name": name, "parameters": args})
            return {
                "ok":            True,
                "model_id":      model,
                "backend":       f"ollama-task:{base_url}",
                "content":       content,
                "tool_calls":    parsed_tc,
                "input_tokens":  len(str(messages)) // 4,
                "output_tokens": len(content) // 4,
                "cost_usd":      0.0,
                "latency_ms":    round((time.time() - t0) * 1000, 1),
            }
        except Exception as e:
            raise GatewayError(f"task ollama at {base_url} failed: {e}") from e

    def _ollama_chat(self, messages: list[dict], max_tokens: int,
                     timeout: float, tools: list[dict] | None = None) -> dict:
        t0 = time.time()
        try:
            body: dict = {
                "model":    self.fallback_model,
                "messages": messages,
                "options":  {"num_predict": max_tokens},
                "stream":   False,
            }
            if tools:
                body["tools"] = tools

            r = httpx.post(f"{self.fallback_ollama}/api/chat", json=body, timeout=timeout)

            if r.status_code == 400 and tools:
                logger.warning("[gateway] Ollama rejected tools — retrying without")
                body.pop("tools")
                r = httpx.post(f"{self.fallback_ollama}/api/chat", json=body, timeout=timeout)

            r.raise_for_status()
            data       = r.json()
            message    = data.get("message", {})
            content    = message.get("content", "")
            tool_calls = message.get("tool_calls")
            if not tool_calls and content:
                from agent.tools.registry import parse_tool_call as _ptc
                parsed = _ptc(content)
                if parsed:
                    tool_calls = [{"function": {"name": parsed["tool"],
                                                "arguments": parsed.get("params", {})}}]
            return {
                "ok":            True,
                "model_id":      self.fallback_model,
                "backend":       "ollama-direct",
                "content":       content,
                "tool_calls":    tool_calls,
                "input_tokens":  len(str(messages)) // 4,
                "output_tokens": len(content) // 4,
                "cost_usd":      0.0,
                "latency_ms":    round((time.time() - t0) * 1000, 1),
            }
        except Exception as e:
            raise GatewayError(f"ollama failed: {e}") from e


def _normalize_messages(messages: list[dict]) -> list[dict]:
    """
    Normalize messages for cloud APIs:
    - Keep only role + content fields
    - Merge consecutive same-role messages (Anthropic requires alternating)
    - Drop empty content
    """
    clean: list[dict] = []
    for m in messages:
        role    = m.get("role", "")
        content = m.get("content") or ""
        if role not in ("user", "assistant") or not content:
            continue
        if clean and clean[-1]["role"] == role:
            clean[-1]["content"] += "\n" + content
        else:
            clean.append({"role": role, "content": content})
    return clean
