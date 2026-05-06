"""
TestMath_B — PlugOps diagnostic stub.

Registers with PlugOps, listens on SSE inbox, solves a+b, replies to sender.

Usage: python math_agent_b.py [plugops_url]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from httpx_sse import aconnect_sse

PLUGOPS = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9000"

ME = "math-agent-b"

REGISTER_URL  = f"{PLUGOPS}/api/v1/agents/register"
HEARTBEAT_URL = f"{PLUGOPS}/api/v1/agents/{ME}/heartbeat"
SEND_URL      = f"{PLUGOPS}/api/v1/sse/send"
INBOX_URL     = f"{PLUGOPS}/api/v1/sse/inbox/{ME}"


async def heartbeat_loop(client: httpx.AsyncClient) -> None:
    while True:
        await asyncio.sleep(25)
        try:
            await client.post(HEARTBEAT_URL)
        except Exception:
            pass


async def main() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(20):
            try:
                r = await client.post(REGISTER_URL, json={
                    "id": ME, "name": "TestMath_B", "type": "diagnostic",
                    "base_dir": str(Path(__file__).parent),
                    "capabilities": ["math_diagnostic"],
                    "metadata": {"role": "solver", "category": "diagnostic"},
                })
                if r.status_code in (200, 201, 409):
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)
        print(f"[{ME}] registered at {PLUGOPS}", flush=True)

        hb_task = asyncio.create_task(heartbeat_loop(client))
        count = 0

        while True:
            try:
                async with aconnect_sse(client, "GET", INBOX_URL) as es:
                    async for sse in es.aiter_sse():
                        if sse.event != "message":
                            continue
                        msg  = json.loads(sse.data)
                        p    = msg["payload"]
                        sender = msg["from"]
                        answer = p["a"] + p["b"]
                        try:
                            await client.post(SEND_URL, json={
                                "from": ME, "to": sender,
                                "payload": {"corr": p["corr"], "answer": answer},
                            })
                            count += 1
                            if count % 200 == 0:
                                print(f"[{ME}] solved={count}", flush=True)
                        except Exception as e:
                            print(f"[{ME}] reply error: {e!r}", flush=True)
            except Exception as e:
                print(f"[{ME}] inbox error: {e!r}; reconnecting", flush=True)
                await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
