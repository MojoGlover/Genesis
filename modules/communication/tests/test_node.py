"""Unit tests for the communication node."""
from __future__ import annotations

import asyncio
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from client import CommClient  # noqa: E402

NODE = os.environ.get("COMM_NODE_URL", "http://127.0.0.1:9100")


@pytest.mark.asyncio
async def test_health():
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{NODE}/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_register_and_send_roundtrip():
    async with CommClient("unit_a", NODE) as a, CommClient("unit_b", NODE) as b:
        received: asyncio.Queue = asyncio.Queue()

        async def listen():
            async for msg in b.inbox():
                await received.put(msg)
                return

        task = asyncio.create_task(listen())
        await asyncio.sleep(0.2)
        await a.send("unit_b", {"ping": 1})
        msg = await asyncio.wait_for(received.get(), timeout=3.0)
        assert msg["from"] == "unit_a"
        assert msg["payload"]["ping"] == 1
        task.cancel()


@pytest.mark.asyncio
async def test_send_to_unknown_returns_404():
    async with CommClient("unit_c", NODE) as c:
        r = await c.send("nonexistent_agent_xyz", {"x": 1})
        assert r.status_code == 404
