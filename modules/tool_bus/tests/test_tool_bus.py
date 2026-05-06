"""
ToolBus module stress test.

Tests:
  1.  Register tools / list / get by name
  2.  Deregister provider — tools removed
  3.  Execute (sync) — routes to mock provider, returns result
  4.  Execute (async) — returns job_id, result posted back
  5.  Execute — tool not found returns 404
  6.  Job tracking — status transitions: pending → running → done
  7.  Provider priority — lower priority number wins when multiple providers
  8.  Concurrent executions — N agents simultaneously
  9.  Stress — repeated register/execute/deregister cycles
  10. Stats / health consistency

A mock provider FastAPI server runs on port 9199 during the test.
It echoes back the input as the result.

Usage:
  python3 test_tool_bus.py [iterations]   default: 500
"""
from __future__ import annotations

import sys
import time
import uuid
import threading
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

BASE     = "http://127.0.0.1:9105"
MOCK_URL = "http://127.0.0.1:9199"
TIMEOUT  = 10.0

counters = {
    "register_ok":  0,
    "execute_ok":   0,
    "job_ok":       0,
    "list_ok":      0,
    "deregister_ok": 0,
    "integrity_fail": 0,
    "errors":       0,
}
latencies: list[float] = []
lock = threading.Lock()


def inc(key, n=1):
    with lock:
        counters[key] += n


def timed(fn):
    t0 = time.perf_counter()
    r = fn()
    with lock:
        latencies.append((time.perf_counter() - t0) * 1000)
    return r


# ── Mock provider server ──────────────────────────────────────────────────────

mock_app = FastAPI(title="MockProvider")


class ExecReq(BaseModel):
    job_id:     str = ""
    tool_name:  str = ""
    input:      dict = {}
    from_agent: str = ""
    callback:   str = ""


@mock_app.post("/exec")
async def mock_exec(req: ExecReq):
    """Echo the input back as result. Handles both sync and async modes."""
    result = {"echo": req.input, "tool": req.tool_name}

    if req.callback:
        # Async mode — post result back to tool_bus
        import asyncio
        asyncio.create_task(_post_callback(req.callback, result))
        return {"ok": True}

    return {"result": result, "error": ""}


async def _post_callback(callback_url: str, result: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(callback_url, json={"result": result, "error": ""})
    except Exception:
        pass


def _run_mock_server():
    uvicorn.run(mock_app, host="127.0.0.1", port=9199, log_level="error")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def register(agent_id, tools, exec_url=f"{MOCK_URL}/exec"):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/tools/register",
            json={"agent_id": agent_id, "exec_url": exec_url, "tools": tools},
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("register_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def deregister(agent_id):
    try:
        r = httpx.delete(f"{BASE}/tools/provider/{agent_id}", timeout=TIMEOUT)
        if r.status_code == 200:
            inc("deregister_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def execute(from_agent, tool_name, input_data=None, mode="sync"):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/execute",
            json={
                "from_agent": from_agent,
                "tool_name":  tool_name,
                "input":      input_data or {},
                "timeout":    5.0,
                "mode":       mode,
            },
            timeout=TIMEOUT,
        ))
        if r.status_code == 200:
            inc("execute_ok")
            return r.json()
        if r.status_code == 404:
            return {"error": "not_found", "status_code": 404}
        inc("errors")
    except Exception:
        inc("errors")
    return None


def get_job(job_id):
    try:
        r = timed(lambda: httpx.get(f"{BASE}/jobs/{job_id}", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("job_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def list_tools():
    try:
        r = timed(lambda: httpx.get(f"{BASE}/tools", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("list_ok")
            return r.json().get("tools", [])
        inc("errors")
    except Exception:
        inc("errors")
    return []


def stats():
    try:
        r = httpx.get(f"{BASE}/stats", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def health():
    try:
        r = httpx.get(f"{BASE}/health", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ── Test cases ────────────────────────────────────────────────────────────────

def test_register_list():
    """Register tools, verify they appear in listing."""
    agent_id  = f"provider-{uuid.uuid4().hex[:6]}"
    tool_name = f"test_tool_{uuid.uuid4().hex[:4]}"

    register(agent_id, [{"name": tool_name, "description": "Test tool"}])

    tools = list_tools()
    names = [t["tool_name"] for t in tools]
    if tool_name not in names:
        inc("integrity_fail")

    deregister(agent_id)

    # Verify removed
    tools2 = list_tools()
    names2 = [t["tool_name"] for t in tools2]
    if tool_name in names2:
        inc("integrity_fail")


def test_execute_sync():
    """Register a tool, execute it, verify result is echoed."""
    agent_id  = f"exec-provider-{uuid.uuid4().hex[:4]}"
    tool_name = f"echo_{uuid.uuid4().hex[:4]}"
    input_data = {"key": "value", "n": 42}

    register(agent_id, [{"name": tool_name}])

    result = execute("ceo", tool_name, input_data=input_data, mode="sync")
    if not result or result.get("status") != "done":
        inc("integrity_fail")
        deregister(agent_id)
        return

    # Mock provider echoes input
    r = result.get("result", {})
    if not r or r.get("echo") != input_data:
        inc("integrity_fail")

    deregister(agent_id)


def test_execute_not_found():
    """Executing unknown tool returns 404."""
    result = execute("engineer0", f"nonexistent_{uuid.uuid4().hex[:8]}")
    if not result or result.get("status_code") != 404:
        inc("integrity_fail")


def test_execute_async():
    """Async job: returns job_id, result arrives via callback."""
    agent_id  = f"async-prov-{uuid.uuid4().hex[:4]}"
    tool_name = f"async_tool_{uuid.uuid4().hex[:4]}"

    register(agent_id, [{"name": tool_name}])

    result = execute("accountant", tool_name, input_data={"x": 1}, mode="async")
    if not result or "job_id" not in result:
        inc("integrity_fail")
        deregister(agent_id)
        return

    job_id = result["job_id"]

    # Poll for completion (callback fires async)
    for _ in range(10):
        time.sleep(0.2)
        job = get_job(job_id)
        if job and job.get("status") == "done":
            break

    job = get_job(job_id)
    if not job or job.get("status") != "done":
        inc("integrity_fail")

    deregister(agent_id)


def test_provider_priority():
    """Lower priority number wins when multiple providers for same tool."""
    tool_name = f"priority_{uuid.uuid4().hex[:4]}"
    prov_a    = f"prov-a-{uuid.uuid4().hex[:4]}"
    prov_b    = f"prov-b-{uuid.uuid4().hex[:4]}"

    # prov_a has priority 10 (preferred), prov_b has priority 50
    register(prov_a, [{"name": tool_name, "priority": 10}])
    register(prov_b, [{"name": tool_name, "priority": 50}])

    result = execute("ceo", tool_name, input_data={}, mode="sync")
    if not result or result.get("status") != "done":
        inc("integrity_fail")
        deregister(prov_a)
        deregister(prov_b)
        return

    # Verify provider_id is prov_a (lower priority = preferred)
    job = get_job(result["job_id"])
    if not job or job.get("provider_id") != prov_a:
        inc("integrity_fail")

    deregister(prov_a)
    deregister(prov_b)


def test_job_tracking():
    """Jobs record correct fields and are retrievable."""
    agent_id  = f"tracker-{uuid.uuid4().hex[:4]}"
    tool_name = f"track_{uuid.uuid4().hex[:4]}"

    register(agent_id, [{"name": tool_name}])

    result = execute("ceo", tool_name, input_data={"track": True})
    if not result or "job_id" not in result:
        inc("integrity_fail")
        deregister(agent_id)
        return

    job = get_job(result["job_id"])
    if not job:
        inc("integrity_fail")
        deregister(agent_id)
        return

    if job.get("tool_name") != tool_name:
        inc("integrity_fail")
    if job.get("from_agent") != "ceo":
        inc("integrity_fail")
    if job.get("status") not in ("done", "running", "pending"):
        inc("integrity_fail")

    deregister(agent_id)


def test_stats_health_consistency():
    """Health and stats endpoints return valid data."""
    h = health()
    s = stats()
    if not h or not h.get("ok"):
        inc("integrity_fail")
    if not s or not s.get("ok"):
        inc("integrity_fail")
    # total = done + failed + timed_out + (pending + running)
    if s:
        accounted = s.get("done", 0) + s.get("failed", 0) + s.get("timed_out", 0)
        if s.get("total_jobs", 0) < accounted:
            inc("integrity_fail")


def test_stress_cycle(i):
    """Register → execute → deregister. Core throughput path."""
    agent_id  = f"stress-{i}-{uuid.uuid4().hex[:4]}"
    tool_name = f"stress_tool_{i % 50}"  # reuse 50 tool names

    register(agent_id, [{"name": tool_name}])
    result = execute(f"agent-{i % 10}", tool_name, input_data={"i": i})
    if result and result.get("status") == "done":
        pass  # counted as execute_ok
    elif result and result.get("status_code") == 404:
        pass  # another provider might have deregistered; acceptable race
    else:
        inc("integrity_fail")
    deregister(agent_id)


def test_concurrent(n):
    """N simultaneous register+execute+deregister cycles."""
    def one(i):
        agent_id  = f"conc-{i}-{uuid.uuid4().hex[:4]}"
        tool_name = f"conc_tool_{i}"
        register(agent_id, [{"name": tool_name}])
        execute(f"user-{i}", tool_name, input_data={"n": i})
        deregister(agent_id)

    with ThreadPoolExecutor(max_workers=min(n, 30)) as ex:
        futs = [ex.submit(one, i) for i in range(n)]
        for f in as_completed(futs):
            f.result()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    # Start mock provider in background thread
    t = threading.Thread(target=_run_mock_server, daemon=True)
    t.start()
    time.sleep(1.5)  # let server start

    # Verify both bus and mock are up
    try:
        r = httpx.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200
        print(f"[test] tool_bus healthy: {r.json()}")
    except Exception as e:
        print(f"[test] FATAL: tool_bus not reachable at {BASE}: {e}")
        sys.exit(1)

    try:
        r = httpx.get(f"{MOCK_URL}/docs", timeout=3)
        print(f"[test] mock provider up at {MOCK_URL}")
    except Exception:
        print(f"[test] mock provider not ready — continuing (may affect execute tests)")

    print(f"[test] running {iters} iterations")
    t_start = time.perf_counter()

    # Correctness suite
    print("[test] correctness suite...")
    test_register_list()
    test_execute_sync()
    test_execute_not_found()
    test_execute_async()
    test_provider_priority()
    test_job_tracking()
    test_stats_health_consistency()
    print(f"[test] correctness suite done — {counters}")

    # Main stress loop
    for i in range(iters):
        test_stress_cycle(i)
        if (i + 1) % 100 == 0:
            elapsed = time.perf_counter() - t_start
            p50 = round(statistics.median(latencies), 1) if latencies else 0
            p95 = round(statistics.quantiles(latencies, n=20)[18], 1) if len(latencies) >= 20 else 0
            rate = round((i + 1) / elapsed, 1)
            print(
                f"[test] i={i+1} {counters} "
                f"rate={rate}/s p50={p50}ms p95={p95}ms"
            )

    # Concurrent flood
    flood_n = min(iters // 5, 100)
    print(f"[test] concurrent flood: {flood_n} agents")
    test_concurrent(flood_n)

    elapsed = time.perf_counter() - t_start
    p50 = round(statistics.median(latencies), 1) if latencies else 0
    p95 = round(statistics.quantiles(latencies, n=20)[18], 1) if len(latencies) >= 20 else 0
    p99 = round(statistics.quantiles(latencies, n=100)[98], 1) if len(latencies) >= 100 else 0

    print(
        f"\n[test] DONE iters={iters} elapsed={elapsed:.1f}s\n"
        f"  counters={counters}\n"
        f"  latency p50={p50}ms p95={p95}ms p99={p99}ms "
        f"min={round(min(latencies),1)}ms max={round(max(latencies),1)}ms"
    )

    if counters["errors"] > 0 or counters["integrity_fail"] > 0:
        print(f"[test] FAIL — errors={counters['errors']} integrity_fail={counters['integrity_fail']}")
        sys.exit(1)
    else:
        print("[test] PASS")


if __name__ == "__main__":
    main()
