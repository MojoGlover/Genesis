"""TestMath_B — listens on SSE inbox, returns a+b to sender."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent.parent / "modules" / "communication"
sys.path.insert(0, str(MODULE_DIR))
from client import CommClient  # noqa: E402

NODE = os.environ.get("COMM_NODE_URL", "http://127.0.0.1:9100")
ME = "TestMath_B"


async def main() -> None:
    async with CommClient(ME, NODE) as client:
        print(f"[{ME}] registered", flush=True)
        count = 0
        async for msg in client.inbox():
            sender = msg["from"]
            p = msg["payload"]
            answer = p["a"] + p["b"]
            try:
                await client.send(sender, {"corr": p["corr"], "answer": answer})
                count += 1
                if count % 1000 == 0:
                    print(f"[{ME}] solved={count}", flush=True)
            except Exception as e:
                print(f"[{ME}] reply error: {e!r}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
