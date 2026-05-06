"""
bridge.py — PlugOps WebSocket connection.

Responsibilities:
- Connect to PlugOps WebSocket (URL from config, overridable by env)
- Register immediately on connect
- Send heartbeat on configurable interval (default 10s)
- Receive messages and dispatch to on_message_callback
- Reconnect automatically on disconnect (exponential backoff, max 30s)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Awaitable

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class PlugOpsBridge:
    def __init__(
        self,
        url: str,
        agent_id: str,
        agent_name: str,
        capabilities: list[str],
        config: dict,                          # plugops section of config.yaml
        on_message_callback: Callable[[dict], Awaitable[None]] | None,
    ) -> None:
        self.url                 = url
        self.agent_id            = agent_id
        self.agent_name          = agent_name
        self.capabilities        = capabilities
        self.on_message_callback = on_message_callback
        self._heartbeat_secs     = config.get("heartbeat_seconds", 10)
        self._backoff_max        = config.get("reconnect_max_seconds", 30)
        self._ws                 = None
        self._connected          = False
        self._should_run         = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def _http_register(self) -> None:
        """Register with PlugOps via HTTP so agent appears in the roster."""
        import httpx
        http_url = self.url.replace("ws://", "http://").replace("wss://", "https://")
        base_url = "/".join(http_url.split("/")[:3])
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(f"{base_url}/api/v1/agents/register", json={
                    "id":           self.agent_id,
                    "name":         self.agent_name,
                    "type":         "autonomous",
                    "base_dir":     f"/agents/{self.agent_id}",
                    "capabilities": self.capabilities,
                    "metadata":     {"emoji": "⬛"},
                })
                if r.status_code in (200, 201):
                    logger.info("[bridge] HTTP registered with PlugOps roster")
                else:
                    logger.warning(f"[bridge] HTTP register returned {r.status_code}")
        except Exception as e:
            logger.warning(f"[bridge] HTTP register failed: {e} (continuing)")

    async def connect(self) -> None:
        """Connect and run forever. Reconnects on disconnect."""
        await self._http_register()
        backoff = 1
        while self._should_run:
            try:
                logger.info(f"[bridge] Connecting to {self.url}")
                async with websockets.connect(self.url) as ws:
                    self._ws = ws
                    self._connected = True
                    backoff = 1
                    await self._register()
                    logger.info(f"[bridge] {self.agent_name} online")
                    await asyncio.gather(self._heartbeat_loop(), self._receive_loop())
            except (ConnectionClosed, OSError) as e:
                self._connected = False
                logger.warning(f"[bridge] Disconnected: {e}. Retry in {backoff}s")
            except Exception as e:
                self._connected = False
                logger.error(f"[bridge] Error: {e}. Retry in {backoff}s")

            if self._should_run:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._backoff_max)

    async def stop(self) -> None:
        self._should_run = False
        if self._ws:
            await self._ws.close()

    async def send(self, message: dict) -> None:
        if not self._connected or not self._ws:
            logger.debug("[bridge] Not connected — message dropped")
            return
        try:
            await self._ws.send(json.dumps(message))
        except Exception as e:
            logger.error(f"[bridge] Send failed: {e}")
            self._connected = False

    async def send_response(self, to_agent: str, content: str) -> None:
        await self.send({
            "type": "chat",
            "message": {"from_agent": self.agent_name,
                        "to_agent": to_agent, "content": content},
        })

    async def _register(self) -> None:
        await self.send({
            "type": "register", "agent": self.agent_name,
            "capabilities": self.capabilities, "ts": time.time(),
        })

    async def _heartbeat_loop(self) -> None:
        while self._connected:
            await asyncio.sleep(self._heartbeat_secs)
            if self._connected:
                await self.send({"type": "heartbeat", "agent": self.agent_name,
                                 "ts": time.time()})

    async def _receive_loop(self) -> None:
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg_type = msg.get("type", "")
            if msg_type == "message" and self.on_message_callback:
                await self.on_message_callback(msg)
            elif msg_type == "ping":
                await self.send({"type": "pong", "agent": self.agent_name, "ts": time.time()})
