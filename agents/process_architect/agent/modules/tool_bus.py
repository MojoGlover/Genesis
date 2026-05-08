"""
Tool bus client — execute tools registered by other agents/providers.

External API calls (Anthropic, OpenAI, etc.) are routed here as tools.
The provider behind the bus holds the keys and manages rate limits.
PlugOps v2 will be the cloud-side management layer for these providers.
"""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0


class ToolBusError(Exception):
    pass


class ToolBusClient:
    def __init__(self, agent_id: str, url: str, enabled: bool = True):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.enabled  = enabled

    def execute(self, tool_name: str, input: dict,
                timeout: float = _DEFAULT_TIMEOUT) -> dict:
        """
        Execute a tool synchronously. Returns result dict.
        Raises ToolBusError on failure.
        """
        if not self.enabled:
            raise ToolBusError("tool_bus disabled in config")
        try:
            r = httpx.post(f"{self.url}/execute", json={
                "tool_name":  tool_name,
                "input":      input,
                "agent_id":   self.agent_id,
                "mode":       "sync",
            }, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            raise ToolBusError(f"tool_bus returned {r.status_code}: {r.text}")
        except ToolBusError:
            raise
        except Exception as e:
            raise ToolBusError(f"tool_bus unreachable: {e}") from e

    def execute_safe(self, tool_name: str, input: dict,
                     timeout: float = _DEFAULT_TIMEOUT) -> dict | None:
        """Non-raising version — returns None on failure."""
        try:
            return self.execute(tool_name, input, timeout)
        except ToolBusError as e:
            logger.warning(f"[tool_bus] {tool_name} failed: {e}")
            return None

    def list_tools(self) -> list[dict]:
        """List tools available on the bus."""
        if not self.enabled:
            return []
        try:
            r = httpx.get(f"{self.url}/tools", timeout=5.0)
            return r.json().get("tools", []) if r.status_code == 200 else []
        except Exception:
            return []
