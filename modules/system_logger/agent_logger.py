"""
AgentLogger — drop-in logging client for every PlugOps agent.

Usage in any agent bridge or service:

    from modules.system_logger.agent_logger import AgentLogger

    log = AgentLogger(agent_id="engineer0", agent_name="Engineer0")

    log.info("Starting task loop")
    log.warning("Model response slow", context={"latency_ms": 4200})
    log.error("Tool call failed", context={"tool": "web_search", "error": str(e)})

All calls are non-blocking (fire-and-forget thread) so they never stall the agent.
Falls back to local stderr if PlugOps is unreachable.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_stdlib_log = logging.getLogger("agent_logger")

DEFAULT_PLUGOPS_URL = "http://localhost:9000"


class AgentLogger:
    def __init__(
        self,
        agent_id:    str,
        agent_name:  str,
        plugops_url: str = DEFAULT_PLUGOPS_URL,
    ):
        self.agent_id    = agent_id
        self.agent_name  = agent_name
        self._url        = f"{plugops_url.rstrip('/')}/logs/ingest"

    # ── Public API ────────────────────────────────────────────────────────────

    def debug(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self._send("debug", message, context)

    def info(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self._send("info", message, context)

    def warning(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self._send("warning", message, context)

    def error(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self._send("error", message, context)

    def critical(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self._send("critical", message, context)

    # ── Send (non-blocking) ───────────────────────────────────────────────────

    def _send(self, level: str, message: str, context: Optional[Dict[str, Any]]) -> None:
        payload = {
            "agent_id":   self.agent_id,
            "agent_name": self.agent_name,
            "level":      level,
            "message":    message,
            "context":    context,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        t = threading.Thread(target=self._post, args=(payload,), daemon=True)
        t.start()

    def _post(self, payload: dict) -> None:
        try:
            data = json.dumps(payload).encode()
            req  = urllib.request.Request(
                self._url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:
            # PlugOps unreachable — fall back to stderr so nothing is lost
            _stdlib_log.warning(
                f"[{self.agent_name}] [{payload['level'].upper()}] "
                f"{payload['message']} (logger offline: {e})"
            )

    # ── Convenience: log an exception with full traceback ─────────────────────

    def exception(self, message: str, exc: Exception) -> None:
        import traceback
        self.error(message, context={
            "exception": type(exc).__name__,
            "detail":    str(exc),
            "traceback": traceback.format_exc(),
        })
