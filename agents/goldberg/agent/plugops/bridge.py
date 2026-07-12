"""
bridge.py — PlugOps SSE/HTTP connection.

Replaced WebSocket transport with SSE + HTTP (2026-05-04).
WebSocket was the primary source of agent connection fragility —
it breaks on proxies, Cloud Run timeouts, and network interruptions
with no clean recovery path.

SSE + HTTP is:
- Stateless on the send side (plain HTTP POST)
- Auto-reconnecting on the receive side (SSE EventSource pattern)
- Proxy/Cloud Run friendly
- Identical interface to the old bridge — callers unchanged

Responsibilities:
- HTTP POST /api/v1/agents/register  — register on startup + reconnect
- HTTP POST /api/v1/agents/{id}/heartbeat  — keepalive every N seconds
- GET  /api/v1/sse/inbox/{id}  — SSE stream, auto-reconnects on drop
- HTTP POST /api/v1/sse/send   — deliver message to another agent
- Dispatch inbound messages to on_message_callback
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Awaitable

import httpx
from httpx_sse import aconnect_sse

logger = logging.getLogger(__name__)


class PlugOpsBridge:
    def __init__(
        self,
        url: str,
        agent_id: str,
        agent_name: str,
        capabilities: list[str],
        on_message_callback: Callable[[dict], Awaitable[None]],
        config: dict | None = None,
    ) -> None:
        cfg = config or {}
        # Accept ws:// or http:// — normalise to http://
        self.base_url            = url.replace("ws://", "http://").replace("wss://", "https://")
        # Strip any path — we only want scheme://host:port
        self.base_url            = "/".join(self.base_url.split("/")[:3])
        self.agent_id            = agent_id
        self.agent_name          = agent_name
        self.capabilities        = capabilities
        self.on_message_callback = on_message_callback
        self._heartbeat_secs     = cfg.get("heartbeat_seconds", 25)
        self._backoff_max        = cfg.get("reconnect_max_seconds", 30)
        self._should_run         = True
        self._connected          = False
        self._client: httpx.AsyncClient | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── public API ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Register, then run heartbeat + SSE inbox loops forever."""
        # Short timeout for regular requests; None read timeout for SSE stream
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
        )
        try:
            await self._register()
            await asyncio.gather(
                self._heartbeat_loop(),
                self._inbox_loop(),
            )
        finally:
            await self._client.aclose()

    async def stop(self) -> None:
        self._should_run = False
        self._connected  = False

    async def send(self, message: dict) -> None:
        """Send a message to another agent via PlugOps SSE bus."""
        to_agent = (
            message.get("message", {}).get("to_agent")
            or message.get("to_agent", "")
        )
        if not to_agent:
            logger.warning("[bridge] send() called with no to_agent — dropped")
            return
        payload = {
            "from":    self.agent_id,
            "to":      to_agent,
            "payload": message,
        }
        try:
            assert self._client is not None
            await self._client.post(f"{self.base_url}/api/v1/sse/send", json=payload)
        except Exception as e:
            logger.error(f"[bridge] send failed: {e!r}")

    async def send_response(self, to_agent: str, content: str, request_id: str = "") -> None:
        msg: dict = {
            "from_agent": self.agent_name,
            "to_agent":   to_agent,
            "content":    content,
        }
        if request_id:
            msg["request_id"] = request_id
        await self.send({"type": "chat", "message": msg})

    # ── internals ─────────────────────────────────────────────────────────

    async def _register(self, retries: int = 20, delay: float = 0.5) -> None:
        assert self._client is not None
        for attempt in range(retries):
            try:
                r = await self._client.post(
                    f"{self.base_url}/api/v1/agents/register",
                    json={
                        "id":           self.agent_id,
                        "name":         self.agent_name,
                        "type":         "autonomous",
                        "base_dir":     f"/agents/{self.agent_id}",
                        "capabilities": self.capabilities,
                        "metadata": {
                            "emoji": "⚙️",
                            "role":  "Systems, code & infrastructure",
                        },
                    },
                )
                if r.status_code in (200, 201, 409):
                    self._connected = True
                    logger.info(f"[bridge] HTTP registered with PlugOps — online")
                    return
                logger.warning(f"[bridge] register returned {r.status_code}")
            except Exception as e:
                logger.warning(f"[bridge] register attempt {attempt+1}: {e!r}")
            await asyncio.sleep(delay)
        logger.error("[bridge] Could not register with PlugOps after retries")

    async def _heartbeat_loop(self) -> None:
        assert self._client is not None
        while self._should_run:
            await asyncio.sleep(self._heartbeat_secs)
            if not self._should_run:
                break
            try:
                await self._client.post(
                    f"{self.base_url}/api/v1/agents/{self.agent_id}/heartbeat"
                )
                logger.debug("[bridge] heartbeat sent")
            except Exception as e:
                logger.warning(f"[bridge] heartbeat failed: {e!r}")

    async def _inbox_loop(self) -> None:
        """SSE inbox — auto-reconnects on any error."""
        assert self._client is not None
        backoff = 1
        while self._should_run:
            try:
                async with aconnect_sse(
                    self._client,
                    "GET",
                    f"{self.base_url}/api/v1/sse/inbox/{self.agent_id}",
                ) as es:
                    self._connected = True
                    backoff = 1
                    async for sse in es.aiter_sse():
                        if not self._should_run:
                            return
                        if sse.event != "message":
                            continue
                        try:
                            msg = json.loads(sse.data)
                            inner = msg.get("payload", msg)
                            await self._dispatch(inner)
                        except Exception as e:
                            logger.warning(f"[bridge] dispatch error: {e!r}")
            except Exception as e:
                self._connected = False
                logger.warning(f"[bridge] inbox error: {e!r} — reconnecting in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._backoff_max)
                await self._register()

    async def _dispatch(self, msg: dict) -> None:
        msg_type = msg.get("type", "")
        if msg_type == "message":
            await self.on_message_callback(msg)
        elif msg_type == "learning_package":
            await self._handle_learning_package(msg)
        elif msg_type in ("heartbeat_ack", "register_ack", "ping"):
            logger.debug(f"[bridge] {msg_type} — ok")
        else:
            logger.debug(f"[bridge] unhandled type: {msg_type}")
            await self.on_message_callback(msg)

    async def _handle_learning_package(self, msg: dict) -> None:
        package    = msg.get("package", {})
        package_id = msg.get("package_id", "unknown")
        title      = package.get("metadata", {}).get("title", package_id)
        logger.info(f"[bridge] learning package received: {title}")
        content      = package.get("content", {})
        summary      = content.get("summary", "")
        phases       = content.get("phases", [])
        lessons_text = []
        for phase in phases:
            for module in phase.get("modules", []):
                for lesson in module.get("lessons", []):
                    lessons_text.append(
                        f"## {lesson.get('title','')}\n{lesson.get('content','')}"
                    )
        body = f"Learning package: {title}\n\n{summary}"
        if lessons_text:
            body += "\n\n" + "\n\n".join(lessons_text[:3])
        body += "\n\nAcknowledge receipt."
        await self.on_message_callback({
            "type":    "message",
            "message": {"from_agent": "learning_manager", "content": body},
            "_learning_package_id": package_id,
        })
