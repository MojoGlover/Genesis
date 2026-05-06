"""Communication client — reusable async helper for agents using the node.

Usage:
    async with CommClient("agent_id", "http://127.0.0.1:9100") as c:
        await c.send("peer_id", {"hello": "world"})
        async for msg in c.inbox():
            ...
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import httpx
from httpx_sse import aconnect_sse


class CommClient:
    def __init__(self, agent_id: str, node_url: str = "http://127.0.0.1:9100"):
        self.agent_id = agent_id
        self.node_url = node_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CommClient":
        self._client = httpx.AsyncClient(timeout=10.0)
        await self.register()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    async def register(self, retries: int = 20, delay: float = 0.25) -> None:
        assert self._client is not None
        last_err: Exception | None = None
        for _ in range(retries):
            try:
                r = await self._client.post(
                    f"{self.node_url}/register", json={"agent_id": self.agent_id}
                )
                r.raise_for_status()
                return
            except Exception as e:
                last_err = e
                await asyncio.sleep(delay)
        raise RuntimeError(f"register failed after {retries} retries: {last_err!r}")

    async def send(self, to: str, payload: dict) -> httpx.Response:
        assert self._client is not None
        return await self._client.post(
            f"{self.node_url}/send",
            json={"from": self.agent_id, "to": to, "payload": payload},
        )

    async def inbox(self) -> AsyncIterator[dict]:
        """Yield messages for this agent. Auto-reconnects on error."""
        assert self._client is not None
        while True:
            try:
                async with aconnect_sse(
                    self._client, "GET", f"{self.node_url}/inbox/{self.agent_id}"
                ) as es:
                    async for sse in es.aiter_sse():
                        if sse.event != "message":
                            continue
                        yield json.loads(sse.data)
            except Exception as e:
                print(f"[CommClient:{self.agent_id}] inbox error: {e!r}; reconnecting", flush=True)
                await asyncio.sleep(1.0)
