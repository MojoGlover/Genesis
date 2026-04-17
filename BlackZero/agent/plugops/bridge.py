"""
bridge.py — PlugOps WebSocket connection.

Responsibilities:
- Connect to PlugOps at ws://host:9000/ws/{agent_id}
- Register immediately on connect
- Send heartbeat every 10 seconds (NOT 60)
- Receive messages and call on_message_callback
- Reconnect automatically on disconnect (backoff: 1s, 2s, 4s, 8s, max 30s)
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

HEARTBEAT_INTERVAL = 10   # seconds
BACKOFF_MAX        = 30   # seconds


class PlugOpsBridge:
    def __init__(
        self,
        url: str,
        agent_id: str,
        agent_name: str,
        capabilities: list[str],
        on_message_callback: Callable[[dict], Awaitable[None]],
    ) -> None:
        self.url                  = url
        self.agent_id             = agent_id
        self.agent_name           = agent_name
        self.capabilities         = capabilities
        self.on_message_callback  = on_message_callback
        self._ws                  = None
        self._connected           = False
        self._should_run          = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def _http_register(self) -> None:
        """Register with PlugOps via HTTP so agent appears in the roster."""
        import httpx
        http_url = self.url.replace("ws://", "http://").replace("wss://", "https://")
        # Strip the ws path to get the base URL
        base_url = "/".join(http_url.split("/")[:3])
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(f"{base_url}/api/v1/agents/register", json={
                    "id":           self.agent_id,
                    "name":         self.agent_name,
                    "type":         "autonomous",
                    "base_dir":     f"/agents/{self.agent_id}",
                    "capabilities": self.capabilities,
                    "metadata": {
                        "emoji": "⬛",
                        "role":  "BlackZero template agent",
                    }
                })
                if r.status_code in (200, 201):
                    logger.info(f"[bridge] HTTP registered with PlugOps roster")
                else:
                    logger.warning(f"[bridge] HTTP register returned {r.status_code}")
        except Exception as e:
            logger.warning(f"[bridge] HTTP register failed: {e} (continuing anyway)")

    async def connect(self) -> None:
        """Connect to PlugOps and run forever. Reconnects on disconnect."""
        # Register via HTTP first so agent appears in the roster immediately
        await self._http_register()

        backoff = 1
        while self._should_run:
            try:
                logger.info(f"[bridge] Connecting to {self.url}")
                async with websockets.connect(self.url) as ws:
                    self._ws = ws
                    self._connected = True
                    backoff = 1  # reset on successful connect

                    # Register immediately on WebSocket too
                    await self._register()
                    logger.info(f"[bridge] Registered as {self.agent_name} — online")

                    # Run heartbeat and receive concurrently
                    await asyncio.gather(
                        self._heartbeat_loop(),
                        self._receive_loop(),
                    )

            except ConnectionClosed as e:
                self._connected = False
                logger.warning(f"[bridge] Connection closed: {e}. Reconnecting in {backoff}s")
            except OSError as e:
                self._connected = False
                logger.warning(f"[bridge] Connection failed: {e}. Reconnecting in {backoff}s")
            except Exception as e:
                self._connected = False
                logger.error(f"[bridge] Unexpected error: {e}. Reconnecting in {backoff}s")

            if self._should_run:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)

    async def stop(self) -> None:
        self._should_run = False
        if self._ws:
            await self._ws.close()

    async def send(self, message: dict) -> None:
        if not self._connected or not self._ws:
            logger.warning("[bridge] Not connected — message dropped")
            return
        try:
            await self._ws.send(json.dumps(message))
        except Exception as e:
            logger.error(f"[bridge] Send failed: {e}")
            self._connected = False

    async def send_response(self, to_agent: str, content: str) -> None:
        # PlugOps routes "chat" type messages. "message" type is ignored by the agent WS handler.
        await self.send({
            "type": "chat",
            "message": {
                "from_agent": self.agent_name,
                "to_agent":   to_agent,
                "content":    content,
            }
        })

    async def _register(self) -> None:
        await self.send({
            "type":         "register",
            "agent":        self.agent_name,
            "capabilities": self.capabilities,
            "ts":           time.time(),
        })

    async def _heartbeat_loop(self) -> None:
        while self._connected:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if self._connected:
                await self.send({
                    "type":  "heartbeat",
                    "agent": self.agent_name,
                    "ts":    time.time(),
                })
                logger.debug("[bridge] Heartbeat sent")

    async def _receive_loop(self) -> None:
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"[bridge] Non-JSON message: {raw[:80]}")
                continue

            msg_type = msg.get("type", "")

            if msg_type == "message":
                await self.on_message_callback(msg)
            elif msg_type in ("heartbeat_ack", "register_ack"):
                logger.debug(f"[bridge] {msg_type} received")
            elif msg_type == "ping":
                await self.send({"type": "pong", "agent": self.agent_name, "ts": time.time()})
            else:
                logger.debug(f"[bridge] Unhandled message type: {msg_type}")
