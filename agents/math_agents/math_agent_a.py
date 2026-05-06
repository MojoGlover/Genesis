"""
TestMath_A — PlugOps diagnostic stub.

Registers with PlugOps, sends a+b problems to TestMath_B via PlugOps SSE
transport, verifies replies. Runs N iterations and reports stats.

Usage: python math_agent_a.py [iterations] [plugops_url]
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time
import uuid
from pathlib import Path

import httpx
from httpx_sse import aconnect_sse

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "modules" / "communication"))

PLUGOPS = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:9000"
MAX_ITERS = int(sys.argv[1]) if len(sys.argv) > 1 else 500
TIMEOUT_S = 5.0

ME = "math-agent-a"
PEER = "math-agent-b"

REGISTER_URL  = f"{PLUGOPS}/api/v1/agents/register"
HEARTBEAT_URL = f"{PLUGOPS}/api/v1/agents/{ME}/heartbeat"
SEND_URL      = f"{PLUGOPS}/api/v1/sse/send"
INBOX_URL     = f"{PLUGOPS}/api/v1/sse/inbox/{ME}"

counters = {"sent": 0, "correct": 0, "wrong": 0, "timeout": 0, "errors": 0}
latencies_ms: list[float] = []
pending: dict[str, tuple[asyncio.Future, float]] = {}


def pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * p))]


async def heartbeat_loop(client: httpx.AsyncClient) -> None:
    while True:
        await asyncio.sleep(25)
        try:
            await client.post(HEARTBEAT_URL)
        except Exception:
            pass


async def inbox_reader(client: httpx.AsyncClient) -> None:
    while True:
        try:
            async with aconnect_sse(client, "GET", INBOX_URL) as es:
                async for sse in es.aiter_sse():
                    if sse.event != "message":
                        continue
                    msg = json.loads(sse.data)
                    corr = msg["payload"].get("corr")
                    entry = pending.pop(corr, None)
                    if entry and not entry[0].done():
                        entry[0].set_result((msg["payload"], time.time() - entry[1]))
        except Exception as e:
            print(f"[{ME}] inbox error: {e!r}; reconnecting", flush=True)
            await asyncio.sleep(1.0)


async def main() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Register with PlugOps
        for attempt in range(20):
            try:
                r = await client.post(REGISTER_URL, json={
                    "id": ME, "name": "TestMath_A", "type": "diagnostic",
                    "base_dir": str(Path(__file__).parent),
                    "capabilities": ["math_diagnostic"],
                    "metadata": {"role": "asker", "category": "diagnostic"},
                })
                if r.status_code in (200, 201, 409):
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)
        print(f"[{ME}] registered at {PLUGOPS}, iters={MAX_ITERS}", flush=True)

        hb_task = asyncio.create_task(heartbeat_loop(client))
        reader   = asyncio.create_task(inbox_reader(client))
        await asyncio.sleep(0.5)

        t0 = time.time()
        for i in range(1, MAX_ITERS + 1):
            a, b = random.randint(0, 20), random.randint(0, 20)
            corr = uuid.uuid4().hex
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            pending[corr] = (fut, time.time())
            try:
                r = await client.post(SEND_URL, json={
                    "from": ME, "to": PEER,
                    "payload": {"a": a, "b": b, "corr": corr},
                })
                if r.status_code != 200:
                    counters["errors"] += 1
                    pending.pop(corr, None)
                    continue
                counters["sent"] += 1
                try:
                    reply, lat = await asyncio.wait_for(fut, timeout=TIMEOUT_S)
                    latencies_ms.append(lat * 1000)
                    if reply.get("answer") == a + b:
                        counters["correct"] += 1
                    else:
                        counters["wrong"] += 1
                except asyncio.TimeoutError:
                    counters["timeout"] += 1
                    pending.pop(corr, None)
            except Exception as e:
                counters["errors"] += 1
                pending.pop(corr, None)
                print(f"[{ME}] send error: {e!r}", flush=True)

            if i % 100 == 0:
                dt = time.time() - t0
                print(
                    f"[{ME}] i={i} {counters} "
                    f"rate={i/dt:.1f}/s p50={pct(latencies_ms,0.5):.1f}ms",
                    flush=True,
                )

        dt = time.time() - t0
        print(
            f"[{ME}] DONE iters={MAX_ITERS} elapsed={dt:.1f}s "
            f"counters={counters} "
            f"latency_ms min={min(latencies_ms,default=0):.1f} "
            f"p50={pct(latencies_ms,0.5):.1f} p95={pct(latencies_ms,0.95):.1f} "
            f"p99={pct(latencies_ms,0.99):.1f} max={max(latencies_ms,default=0):.1f}",
            flush=True,
        )
        hb_task.cancel()
        reader.cancel()


if __name__ == "__main__":
    asyncio.run(main())
