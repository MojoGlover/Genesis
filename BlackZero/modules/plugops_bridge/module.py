"""
plugops_bridge — PlugOps WebSocket bridge.

Connects the agent to the PlugOps message bus on PlugWan.
Handles agent registration, heartbeat, task dispatch, and status reporting.

Agent name is read from config.identity.designation (or PLUGOPS_AGENT env var).
Bridge is a no-op if PLUGOPS_URL is unset and no url is in config — safe by default.

Config keys:
    modules.plugops_bridge.url                  — WebSocket URL
    modules.plugops_bridge.heartbeat_seconds    — (default: 60)
    modules.plugops_bridge.reconnect_max_seconds — (default: 60)

Environment:
    PLUGOPS_URL   — WebSocket URL (overrides config)
    PLUGOPS_AGENT — Agent name to register as (overrides config identity)

Returns:
    {"plugops_client": PlugOpsClient, "sinks": {"plugops": log_fn}}
    or {} if bridge is disabled (no URL configured).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    import websocket  # type: ignore
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False
    logger.warning("plugops_bridge: websocket-client not installed — pip install websocket-client")


class PlugOpsClient:
    """
    WebSocket client for the PlugOps agent message bus.
    Runs its receive loop in a background daemon thread.
    """

    def __init__(
        self,
        url: str,
        agent_name: str = "Agent",
        capabilities: list[str] | None = None,
        heartbeat_seconds: int = 60,
        reconnect_max_seconds: int = 60,
        on_task: Callable[[dict], None] | None = None,
        on_message: Callable[[dict], None] | None = None,
    ) -> None:
        self._url               = url
        self._agent_name        = agent_name
        self._capabilities      = capabilities or []
        self._heartbeat_sec     = heartbeat_seconds
        self._reconnect_max     = reconnect_max_seconds
        self._on_task           = on_task
        self._on_message        = on_message
        self._ws: Any           = None
        self._connected         = False
        self._should_run        = False
        self._thread: threading.Thread | None = None
        self._consecutive_fails = 0
        self._registered_agents: list[str] = []

    # ── Connection management ─────────────────────────────────────────────────

    def start(self) -> None:
        if not _WS_AVAILABLE:
            logger.warning("plugops_bridge: websocket-client missing, bridge disabled")
            return
        self._should_run = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name=f"plugops-{self._agent_name}"
        )
        self._thread.start()
        logger.info(f"PlugOps bridge started → {self._url}")

    def stop(self) -> None:
        self._should_run = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def known_agents(self) -> list[str]:
        return list(self._registered_agents)

    # ── Outbound messages ─────────────────────────────────────────────────────

    def send(self, message: dict) -> bool:
        if not self._connected or not self._ws:
            logger.warning("PlugOps: not connected, message dropped")
            return False
        try:
            self._ws.send(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"PlugOps send failed: {e}")
            self._connected = False
            return False

    def report_status(self, status: str, detail: dict | None = None) -> bool:
        return self.send({
            "type":   "status_report",
            "agent":  self._agent_name,
            "status": status,
            "detail": detail or {},
            "ts":     time.time(),
        })

    def escalate(self, reason: str, context: dict | None = None) -> bool:
        logger.warning(f"PlugOps escalation: {reason}")
        return self.send({
            "type":    "escalation",
            "agent":   self._agent_name,
            "reason":  reason,
            "context": context or {},
            "ts":      time.time(),
        })

    def task_complete(self, task_id: str, result: dict) -> bool:
        return self.send({
            "type":    "task_complete",
            "agent":   self._agent_name,
            "task_id": task_id,
            "result":  result,
            "ts":      time.time(),
        })

    def task_failed(self, task_id: str, error: str) -> bool:
        return self.send({
            "type":    "task_failed",
            "agent":   self._agent_name,
            "task_id": task_id,
            "error":   error,
            "ts":      time.time(),
        })

    # ── Internal loop ─────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        while self._should_run:
            delay = min(2 ** self._consecutive_fails, self._reconnect_max)
            if self._consecutive_fails > 0:
                logger.info(f"PlugOps reconnecting in {delay}s (attempt {self._consecutive_fails})")
                time.sleep(delay)
            try:
                self._connect_once()
                self._consecutive_fails = 0
            except Exception as e:
                self._consecutive_fails += 1
                self._connected = False
                logger.warning(f"PlugOps connection lost: {e}")

    def _connect_once(self) -> None:
        ws = websocket.WebSocketApp(
            self._url,
            on_open=self._on_open,
            on_message=self._on_ws_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws = ws
        ws.run_forever(ping_interval=self._heartbeat_sec, ping_timeout=10)

    def _on_open(self, ws) -> None:
        self._connected = True
        self._consecutive_fails = 0
        logger.info(f"PlugOps connected as {self._agent_name}")
        ws.send(json.dumps({
            "type":         "register",
            "agent":        self._agent_name,
            "capabilities": self._capabilities,
            "ts":           time.time(),
        }))

    def _on_ws_message(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"PlugOps: non-JSON message: {raw[:100]}")
            return

        msg_type = msg.get("type", "")
        logger.debug(f"PlugOps received: {msg_type}")

        if msg_type == "agent_list":
            self._registered_agents = msg.get("agents", [])

        elif msg_type == "task_request":
            if self._on_task:
                try:
                    self._on_task(msg)
                except Exception as e:
                    logger.error(f"PlugOps task handler error: {e}")
                    self.task_failed(msg.get("task_id", "?"), str(e))

        elif msg_type == "ping":
            self.send({"type": "pong", "agent": self._agent_name, "ts": time.time()})

        else:
            if self._on_message:
                try:
                    self._on_message(msg)
                except Exception as e:
                    logger.error(f"PlugOps message handler error: {e}")

    def _on_error(self, ws, error) -> None:
        logger.warning(f"PlugOps WebSocket error: {error}")
        self._connected = False

    def _on_close(self, ws, code, reason) -> None:
        self._connected = False
        logger.info(f"PlugOps disconnected: {code} {reason}")


# ── Module entry point ─────────────────────────────────────────────────────────

def setup(config: dict) -> dict:
    """Module entry point. Called by the loader."""
    identity   = config.get("identity", {})
    mod_config = config.get("modules", {}).get("plugops_bridge", {})

    # Agent name: env var → config identity → generic fallback
    agent_name = (
        os.environ.get("PLUGOPS_AGENT")
        or identity.get("designation", "Agent")
    )

    # URL: env var → config → empty (disabled)
    url = (
        os.environ.get("PLUGOPS_URL")
        or mod_config.get("url", "")
    )

    if not url:
        logger.info("plugops_bridge: no URL configured, bridge disabled")
        return {}

    heartbeat  = mod_config.get("heartbeat_seconds", 60)
    reconnect  = mod_config.get("reconnect_max_seconds", 60)

    # Capabilities come from config if defined, otherwise empty (agent fills in at stamp)
    capabilities = mod_config.get("capabilities", [])

    client = PlugOpsClient(
        url=url,
        agent_name=agent_name,
        capabilities=capabilities,
        heartbeat_seconds=heartbeat,
        reconnect_max_seconds=reconnect,
    )
    client.start()

    logger.info(f"plugops_bridge: connecting to {url} as {agent_name}")

    return {
        "plugops_client": client,
        "sinks": {
            "plugops": lambda msg: client.send({
                "type": "log", "agent": agent_name, "msg": msg
            }),
        },
    }
