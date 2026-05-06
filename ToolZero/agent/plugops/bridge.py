"""
bridge.py — PlugOps WebSocket bridge for tool-agents.

Same registration/heartbeat pattern as BlackZero, with one addition:
handles `tool_request` message type routed by the Operator.

Tool request protocol (sent by Operator):
    {
        "type": "tool_request",
        "request_id": "uuid",
        "from_agent": "accountant",
        "tool": "fetch_tax_data",
        "params": {...}
    }

Tool response (sent back through bridge):
    {
        "type": "tool_response",
        "request_id": "uuid",
        "to_agent": "accountant",
        "result": "...",
        "error": null
    }
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

HEARTBEAT_INTERVAL = 10
BACKOFF_MAX        = 30


class ToolBridge:
    def __init__(
        self,
        url: str,
        agent_id: str,
        agent_name: str,
        agent_role: str,
        capabilities: list[str],
        on_tool_request: Callable[[dict], Awaitable[dict]],
    ) -> None:
        self.url              = url
        self.agent_id         = agent_id
        self.agent_name       = agent_name
        self.agent_role       = agent_role
        self.capabilities     = capabilities
        self.on_tool_request  = on_tool_request   # async fn: request dict → result dict
        self._ws              = None
        self._connected       = False
        self._should_run      = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def _http_register(self) -> None:
        import httpx
        http_url = self.url.replace("ws://", "http://").replace("wss://", "https://")
        base_url = "/".join(http_url.split("/")[:3])
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(f"{base_url}/api/v1/agents/register", json={
                    "id":           self.agent_id,
                    "name":         self.agent_name,
                    "type":         "tool",
                    "base_dir":     f"/agents/{self.agent_id}",
                    "capabilities": self.capabilities,
                    "metadata": {
                        "emoji": "🔧",
                        "role":  self.agent_role,
                    }
                })
                if r.status_code in (200, 201):
                    logger.info("[bridge] Registered with PlugOps roster")
                else:
                    logger.warning(f"[bridge] HTTP register returned {r.status_code}")
        except Exception as e:
            logger.warning(f"[bridge] HTTP register failed: {e} (continuing anyway)")

    async def connect(self) -> None:
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

                    await asyncio.gather(
                        self._heartbeat_loop(),
                        self._receive_loop(),
                    )

            except ConnectionClosed as e:
                self._connected = False
                logger.warning(f"[bridge] Closed: {e}. Reconnecting in {backoff}s")
            except OSError as e:
                self._connected = False
                logger.warning(f"[bridge] Failed: {e}. Reconnecting in {backoff}s")
            except Exception as e:
                self._connected = False
                logger.error(f"[bridge] Unexpected: {e}. Reconnecting in {backoff}s")

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

    async def _register(self) -> None:
        await self.send({
            "type":         "register",
            "agent":        self.agent_name,
            "agent_type":   "tool",
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

    async def _receive_loop(self) -> None:
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"[bridge] Non-JSON: {raw[:80]}")
                continue

            msg_type = msg.get("type", "")

            if msg_type == "tool_request":
                await self._handle_tool_request(msg)
            elif msg_type in ("heartbeat_ack", "register_ack"):
                logger.debug(f"[bridge] {msg_type}")
            elif msg_type == "ping":
                await self.send({"type": "pong", "agent": self.agent_name, "ts": time.time()})
            else:
                logger.debug(f"[bridge] Unhandled: {msg_type}")

    async def _handle_tool_request(self, msg: dict) -> None:
        """Execute tool request and send response back through PlugOps."""
        request_id = msg.get("request_id", "unknown")
        from_agent = msg.get("from_agent", "unknown")

        logger.info(f"[bridge] Tool request from {from_agent}: {msg.get('tool')} (id={request_id})")

        try:
            result = await self.on_tool_request(msg)
            await self.send({
                "type":       "tool_response",
                "request_id": request_id,
                "to_agent":   from_agent,
                "result":     result.get("result", ""),
                "error":      result.get("error"),
            })
        except Exception as e:
            logger.error(f"[bridge] Tool execution error: {e}")
            await self.send({
                "type":       "tool_response",
                "request_id": request_id,
                "to_agent":   from_agent,
                "result":     "",
                "error":      str(e),
            })
