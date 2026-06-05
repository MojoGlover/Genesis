"""
Model gateway client — all LLM calls go here.

No direct Ollama, Anthropic, or OpenAI calls in agent code.

Call chain (first success wins):
  1. Cloud primary  — if model.provider is "anthropic" or "openai"
  2. Local gateway  — model_gateway module (port 9109)
  3. Direct Ollama  — if fallback_ollama configured
  4. Gemini fallback — if GEMINI_API_KEY set and gemini_model configured
  5. Cloud fallback — last resort (Anthropic only, from model.cloud_fallback)

Config (config.yaml model section):
  provider:       "ollama"      # ollama | anthropic | openai
  cloud_model:    ""            # e.g. claude-haiku-4-5, gpt-4o-mini (cloud primary)
  primary:        ""            # gateway model_id (ollama path)
  fallback:       ""            # direct ollama model name
  cloud_fallback: ""            # anthropic model for last-resort fallback
  gemini_model:   ""            # e.g. gemini-2.5-flash (fallback provider)

Environment:
  ANTHROPIC_API_KEY   — required for provider=anthropic or cloud_fallback
  OPENAI_API_KEY      — required for provider=openai
  GEMINI_API_KEY      — required for gemini_model fallback
"""
from __future__ import annotations

import logging
import os
import time
import httpx

logger = logging.getLogger(__name__)

_FALLBACK_TIMEOUT = 120.0
_OLLAMA_PRESSURE_RESET_EVERY = 8  # force model unload every N calls to prevent OOM crash under sustained load

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_OPENAI_URL    = "https://api.openai.com/v1/chat/completions"
_GEMINI_URL    = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GatewayError(Exception):
    pass


class GatewayClient:
    def __init__(
        self,
        agent_id: str,
        url: str,
        model: str = "",
        enabled: bool = True,
        fallback_ollama: str = "http://localhost:11434",
        fallback_model: str = "",
        cloud_fallback_model: str = "",
        cloud_provider: str = "ollama",   # "ollama" | "anthropic" | "openai"
        cloud_model: str = "",            # model id for cloud primary
        task_ollama: str = "",            # plugwan Ollama URL for async task execution
        task_model: str = "",             # model to use for tasks (e.g. phi4:14b)
        gemini_model: str = "",           # Gemini fallback model (e.g. gemini-2.5-flash)
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
        self.gemini_model         = gemini_model  # e.g. gemini-2.5-flash
        self._model_map: dict[str, str] = model_map or {}
        self._ollama_call_count: int = 0

    @property
    def _anthropic_key(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def _openai_key(self) -> str:
        return os.environ.get("OPENAI_API_KEY", "")

    @property
    def _gemini_key(self) -> str:
        return os.environ.get("GEMINI_API_KEY", "")

    def _model_for(self, task_type: str) -> str:
        return self._model_map.get(task_type, self.model)

    def task_chat(self, messages: list[dict], max_tokens: int = 2048,
                  timeout: float = _FALLBACK_TIMEOUT,
                  tools: list[dict] | None = None) -> dict:
        """
        Route a task to the configured task_ollama/task_model.
        Falls back to cloud primary if task_ollama is unreachable.
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

        # ── 1. Direct cloud — ONLY when the gateway is unavailable ─────────────
        # DEFAULT routing goes THROUGH the gated model_gateway (block 2 below) so
        # every paid call is cost-checked before it fires (Darnie's rule, 2026-06-05:
        # "never allow a call without computing the cost"). Direct cloud is a
        # fallback for when the gateway is disabled — never the normal path. The
        # gateway applies per-agent budgets (Accountant-adjustable) and falls back
        # to local on overspend.
        if not self.enabled and self.cloud_provider == "anthropic" and self.cloud_model and self._anthropic_key:
            try:
                return self._anthropic_chat(messages, self.cloud_model, max_tokens, timeout,
                                            tools=tools)
            except GatewayError as e:
                logger.warning(f"[gateway] Anthropic direct failed: {e} — trying local")

        elif not self.enabled and self.cloud_provider == "openai" and self.cloud_model and self._openai_key:
            try:
                return self._openai_chat(messages, self.cloud_model, max_tokens, timeout)
            except GatewayError as e:
                logger.warning(f"[gateway] OpenAI direct failed: {e} — trying local")

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
            except GatewayError as e:
                logger.warning(f"[gateway] model_gateway rejected ({e}) — trying Ollama fallback")
            except Exception as e:
                logger.warning(f"[gateway] unreachable ({e}) — trying Ollama fallback")

        # ── 3. Direct Ollama ──────────────────────────────────────────────────
        if self.fallback_ollama and self.fallback_model:
            logger.warning(f"[gateway] Direct Ollama fallback ({self.fallback_model})")
            try:
                return self._ollama_chat(messages, max_tokens, timeout, tools=tools)
            except GatewayError as e:
                logger.warning(f"[gateway] Ollama failed: {e} — trying cloud fallback")

        # ── 4. Gemini fallback ────────────────────────────────────────────────
        if self.gemini_model and self._gemini_key:
            logger.warning(f"[gateway] Gemini fallback ({self.gemini_model})")
            try:
                return self._gemini_chat(messages, self.gemini_model, max_tokens, timeout,
                                         tools=tools)
            except GatewayError as e:
                logger.warning(f"[gateway] Gemini failed: {e} — trying cloud fallback")

        # ── 5. Cloud fallback (Anthropic last resort) ─────────────────────────
        if self.cloud_fallback_model and self._anthropic_key:
            logger.warning(f"[gateway] Anthropic cloud fallback ({self.cloud_fallback_model})")
            return self._anthropic_chat(messages, self.cloud_fallback_model, max_tokens, timeout,
                                        tools=tools)

        raise GatewayError("all inference paths failed — no provider available")

    # ── Provider implementations ───────────────────────────────────────────────

    def _anthropic_chat(self, messages: list[dict], model: str,
                        max_tokens: int, timeout: float,
                        tools: list[dict] | None = None) -> dict:
        t0 = time.time()
        try:
            # Anthropic uses a top-level "system" param — not a message in the array.
            # Extract system message before normalizing, then pass separately.
            system_text = ""
            for m in messages:
                if m.get("role") == "system":
                    system_text += (m.get("content") or "")
            clean = _normalize_messages(messages)
            payload: dict = {"model": model, "max_tokens": max_tokens, "messages": clean}
            if system_text:
                payload["system"] = system_text
            # Convert Ollama-format tools → Anthropic format.
            # Ollama: [{"type":"function","function":{"name":...,"description":...,"parameters":...}}]
            # Anthropic: [{"name":...,"description":...,"input_schema":{...}}]
            if tools:
                ant_tools = []
                for t in tools:
                    fn = t.get("function", t)
                    schema = fn.get("parameters", fn.get("input_schema", {}))
                    ant_tools.append({
                        "name":         fn.get("name", ""),
                        "description":  fn.get("description", ""),
                        "input_schema": schema if schema else {"type": "object", "properties": {}},
                    })
                if ant_tools:
                    payload["tools"] = ant_tools
            r = httpx.post(
                _ANTHROPIC_URL,
                headers={
                    "x-api-key":         self._anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            r.raise_for_status()
            data    = r.json()
            # Extract text and tool_use blocks from Anthropic content array.
            content    = ""
            tool_calls = None
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content += block.get("text", "")
                elif block.get("type") == "tool_use":
                    # Convert to Ollama-style shape that graph.parse_native_tool_call() understands.
                    if tool_calls is None:
                        tool_calls = []
                    tool_calls.append({"function": {
                        "name":      block.get("name", ""),
                        "arguments": block.get("input", {}),
                    }})
            usage = data.get("usage", {})
            return {
                "ok":            True,
                "model_id":      model,
                "backend":       "anthropic",
                "content":       content,
                "tool_calls":    tool_calls,
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
                        tools: list[dict] | None = None,
                        num_ctx: int = 4096) -> dict:
        """Ollama call to an arbitrary URL/model — used for task routing.

        num_ctx: Ollama KV-cache size. Must match _ollama_chat's default (4096) so
        the model stays loaded between calls — Ollama reloads when num_ctx changes.
        Note: max_tokens (num_predict) caps OUTPUT length, num_ctx caps INPUT window.
        """
        t0 = time.time()
        try:
            self._ollama_call_count += 1
            if self._ollama_call_count >= _OLLAMA_PRESSURE_RESET_EVERY:
                keep_alive = 0
                self._ollama_call_count = 0
                logger.warning(
                    f"[gateway] Ollama memory reset at call {_OLLAMA_PRESSURE_RESET_EVERY} "
                    f"— flushing model from memory (next call will cold-start ~30-60s)"
                )
            else:
                keep_alive = 3600

            body: dict = {
                "model":      model,
                "messages":   messages,
                "options":    {"num_predict": max_tokens, "num_ctx": num_ctx},
                "stream":     False,
                "keep_alive": keep_alive,
            }
            if tools:
                body["tools"] = tools
            r = httpx.post(f"{base_url}/api/chat", json=body, timeout=timeout)
            _tools_stripped = False
            if r.status_code == 400 and tools:
                logger.warning("[gateway] task Ollama rejected tools — retrying without")
                body.pop("tools")
                r = httpx.post(f"{base_url}/api/chat", json=body, timeout=timeout)
                _tools_stripped = True
            r.raise_for_status()
            data    = r.json()
            msg     = data.get("message", {})
            content = msg.get("content", "")
            # Preserve the native Ollama/OpenAI-style shape:
            # [{"function": {"name": "...", "arguments": {...}}}]
            # graph.parse_native_tool_call() already understands this format.
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
                        parsed_tc.append({"function": {"name": name, "arguments": args if isinstance(args, dict) else {}}})
            return {
                "ok":            True,
                "model_id":      model,
                "backend":       f"ollama-task:{base_url}",
                "content":       content,
                "tool_calls":    parsed_tc,
                "tools_stripped": _tools_stripped,
                "input_tokens":  len(str(messages)) // 4,
                "output_tokens": len(content) // 4,
                "cost_usd":      0.0,
                "latency_ms":    round((time.time() - t0) * 1000, 1),
            }
        except Exception as e:
            raise GatewayError(f"task ollama at {base_url} failed: {e}") from e

    def _ollama_chat(self, messages: list[dict], max_tokens: int,
                     timeout: float, tools: list[dict] | None = None,
                     num_ctx: int = 4096) -> dict:
        """Direct Ollama fallback. num_ctx capped at 4096 for local model on plugfoe."""
        t0 = time.time()
        try:
            self._ollama_call_count += 1
            if self._ollama_call_count >= _OLLAMA_PRESSURE_RESET_EVERY:
                keep_alive = 0
                self._ollama_call_count = 0
                logger.warning(
                    f"[gateway] Ollama memory reset at call {_OLLAMA_PRESSURE_RESET_EVERY} "
                    f"— flushing model from memory (next call will cold-start ~30-60s)"
                )
            else:
                keep_alive = 3600

            body: dict = {
                "model":      self.fallback_model,
                "messages":   messages,
                "options":    {"num_predict": max_tokens, "num_ctx": num_ctx},
                "stream":     False,
                "keep_alive": keep_alive,
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


    def _gemini_chat(self, messages: list[dict], model: str,
                     max_tokens: int, timeout: float,
                     tools: list[dict] | None = None) -> dict:
        t0 = time.time()
        try:
            # Extract system prompt — Gemini uses system_instruction separately.
            system_text = ""
            for m in messages:
                if m.get("role") == "system":
                    system_text += (m.get("content") or "")

            # Convert to Gemini contents format (role: user/model, parts: [{text}]).
            contents = []
            for m in messages:
                role = m.get("role", "")
                content = m.get("content") or ""
                if role not in ("user", "assistant") or not content:
                    continue
                gemini_role = "model" if role == "assistant" else "user"
                if contents and contents[-1]["role"] == gemini_role:
                    contents[-1]["parts"][0]["text"] += "\n" + content
                else:
                    contents.append({"role": gemini_role, "parts": [{"text": content}]})

            payload: dict = {
                "contents":          contents,
                "generationConfig":  {"maxOutputTokens": max_tokens},
            }
            if system_text:
                payload["system_instruction"] = {"parts": [{"text": system_text}]}
            if tools:
                fn_decls = []
                for t in tools:
                    fn = t.get("function", t)
                    schema = fn.get("parameters", fn.get("input_schema", {}))
                    fn_decls.append({
                        "name":        fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "parameters":  schema if schema else {"type": "object", "properties": {}},
                    })
                if fn_decls:
                    payload["tools"] = [{"function_declarations": fn_decls}]

            url = _GEMINI_URL.format(model=model)
            r = httpx.post(url, params={"key": self._gemini_key}, json=payload, timeout=timeout)
            r.raise_for_status()
            data = r.json()

            content    = ""
            tool_calls = None
            candidate  = data.get("candidates", [{}])[0]
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    content += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    if tool_calls is None:
                        tool_calls = []
                    tool_calls.append({"function": {
                        "name":      fc.get("name", ""),
                        "arguments": fc.get("args", {}),
                    }})
            usage = data.get("usageMetadata", {})
            return {
                "ok":            True,
                "model_id":      model,
                "backend":       "gemini",
                "content":       content,
                "tool_calls":    tool_calls,
                "input_tokens":  usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
                "cost_usd":      0.0,
                "latency_ms":    round((time.time() - t0) * 1000, 1),
            }
        except Exception as e:
            raise GatewayError(f"gemini failed: {e}") from e


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
