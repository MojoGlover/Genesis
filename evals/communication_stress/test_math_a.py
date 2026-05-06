"""TestMath_A — generates a+b problems, sends to TestMath_B via node, verifies replies.

Tracks per-exchange latency and writes final stats to stdout.
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import time
import uuid
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent.parent / "modules" / "communication"
sys.path.insert(0, str(MODULE_DIR))
from client import CommClient  # noqa: E402

NODE = os.environ.get("COMM_NODE_URL", "http://127.0.0.1:9100")
ME = "TestMath_A"
PEER = "TestMath_B"
MAX_ITERS = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
TIMEOUT_S = 5.0

counters = {"sent": 0, "correct": 0, "wrong": 0, "timeout": 0, "errors": 0}
latencies_ms: list[float] = []
pending: dict[str, tuple[asyncio.Future, float]] = {}


async def inbox_reader(client: CommClient) -> None:
    async for msg in client.inbox():
        corr = msg["payload"].get("corr")
        entry = pending.pop(corr, None)
        if entry and not entry[0].done():
            entry[0].set_result((msg["payload"], time.time() - entry[1]))


def pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, int(len(s) * p))
    return s[i]


async def main() -> None:
    async with CommClient(ME, NODE) as client:
        print(f"[{ME}] registered, target iters={MAX_ITERS}", flush=True)
        reader = asyncio.create_task(inbox_reader(client))
        await asyncio.sleep(0.3)

        t0 = time.time()
        for i in range(1, MAX_ITERS + 1):
            a, b = random.randint(0, 20), random.randint(0, 20)
            corr = uuid.uuid4().hex
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            sent_at = time.time()
            pending[corr] = (fut, sent_at)
            try:
                r = await client.send(PEER, {"a": a, "b": b, "corr": corr})
                if r.status_code != 200:
                    counters["errors"] += 1
                    pending.pop(corr, None)
                    continue
                counters["sent"] += 1
                try:
                    reply, latency = await asyncio.wait_for(fut, timeout=TIMEOUT_S)
                    latencies_ms.append(latency * 1000)
                    if reply.get("answer") == a + b:
                        counters["correct"] += 1
                    else:
                        counters["wrong"] += 1
                except asyncio.TimeoutError:
                    counters["timeout"] += 1
                    pending.pop(corr, None)
            except Exception as e:
                counters["errors"] += 1
                print(f"[{ME}] send error: {e!r}", flush=True)
                pending.pop(corr, None)

            if i % 500 == 0:
                dt = time.time() - t0
                rate = i / dt if dt else 0
                print(
                    f"[{ME}] i={i} {counters} rate={rate:.1f}/s "
                    f"p50={pct(latencies_ms,0.5):.1f}ms p95={pct(latencies_ms,0.95):.1f}ms",
                    flush=True,
                )

        dt = time.time() - t0
        print(
            f"[{ME}] DONE iters={MAX_ITERS} elapsed={dt:.1f}s "
            f"counters={counters} "
            f"latency_ms min={min(latencies_ms) if latencies_ms else 0:.1f} "
            f"p50={pct(latencies_ms,0.5):.1f} p95={pct(latencies_ms,0.95):.1f} "
            f"p99={pct(latencies_ms,0.99):.1f} max={max(latencies_ms) if latencies_ms else 0:.1f}",
            flush=True,
        )
        reader.cancel()


if __name__ == "__main__":
    asyncio.run(main())
