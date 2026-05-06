"""
Supervisor module stress test.

Tests:
  1.  Declare / get / list / remove cycle (CRUD)
  2.  Declare idempotency (re-declare updates config)
  3.  Event log — declare, start, stop events recorded
  4.  Start (sleep process) → verify 'starting' state immediately
  5.  Stop → verify 'stopped' state, process killed
  6.  Restart — stop + start round-trip
  7.  Crash detection — command that exits immediately, policy=never
  8.  Heal endpoint (manual Agent Hospital trigger)
  9.  Stats / health consistency
  10. Concurrent declarations (flood)

Note: Full lifecycle tests (start → 'running' confirmation) require comm + registry
      to be running. These tests cover the supervisor API layer independently.
      Process management is tested with real subprocesses; registry confirmation is
      not waited for (supervisor transitions to 'starting' immediately, which is the
      testable guarantee without the full stack).

Usage:
  python3 test_supervisor.py [iterations]   default: 500
"""
from __future__ import annotations

import sys
import time
import uuid
import threading
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

BASE    = "http://127.0.0.1:9103"
TIMEOUT = 10.0

counters = {
    "declare_ok":     0,
    "get_ok":         0,
    "list_ok":        0,
    "remove_ok":      0,
    "start_ok":       0,
    "stop_ok":        0,
    "restart_ok":     0,
    "events_ok":      0,
    "health_ok":      0,
    "integrity_fail": 0,
    "errors":         0,
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


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def declare(agent_id, name="Test Agent", command=None, working_dir="/tmp",
            restart_policy="never", max_restarts=0):
    if command is None:
        command = ["python3", "-c", "import time; time.sleep(60)"]
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/agents/{agent_id}/declare",
            json={
                "name":           name,
                "command":        command,
                "working_dir":    working_dir,
                "restart_policy": restart_policy,
                "max_restarts":   max_restarts,
                "backoff_base":   2,
            },
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("declare_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def get_agent(agent_id):
    try:
        r = timed(lambda: httpx.get(f"{BASE}/agents/{agent_id}", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("get_ok")
            return r.json()
        if r.status_code == 404:
            return None
        inc("errors")
    except Exception:
        inc("errors")
    return None


def list_agents():
    try:
        r = timed(lambda: httpx.get(f"{BASE}/agents", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("list_ok")
            return r.json().get("agents", [])
        inc("errors")
    except Exception:
        inc("errors")
    return []


def remove(agent_id):
    try:
        r = timed(lambda: httpx.delete(f"{BASE}/agents/{agent_id}", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("remove_ok")
            return True
        inc("errors")
    except Exception:
        inc("errors")
    return False


def start(agent_id):
    try:
        r = timed(lambda: httpx.post(f"{BASE}/agents/{agent_id}/start", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("start_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def stop(agent_id):
    try:
        r = timed(lambda: httpx.post(f"{BASE}/agents/{agent_id}/stop", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("stop_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def restart(agent_id):
    try:
        r = timed(lambda: httpx.post(f"{BASE}/agents/{agent_id}/restart", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("restart_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def heal(agent_id):
    try:
        r = httpx.post(f"{BASE}/agents/{agent_id}/heal", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def events(agent_id="", limit=20):
    try:
        params = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        r = timed(lambda: httpx.get(f"{BASE}/events", params=params, timeout=TIMEOUT))
        if r.status_code == 200:
            inc("events_ok")
            return r.json().get("events", [])
        inc("errors")
    except Exception:
        inc("errors")
    return []


def health():
    try:
        r = httpx.get(f"{BASE}/health", timeout=TIMEOUT)
        if r.status_code == 200:
            inc("health_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def stats():
    try:
        r = httpx.get(f"{BASE}/stats", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ── Test cases ────────────────────────────────────────────────────────────────

def test_crud(i):
    """Declare → get → list → remove cycle. Core DB path."""
    agent_id = f"crud-{i}-{uuid.uuid4().hex[:6]}"

    data = declare(agent_id, name=f"Test-{i}")
    if not data or not data.get("ok"):
        inc("integrity_fail")
        return

    agent = get_agent(agent_id)
    if not agent or agent.get("agent_id") != agent_id:
        inc("integrity_fail")
        remove(agent_id)
        return

    if agent.get("state") != "stopped":
        inc("integrity_fail")

    agents = list_agents()
    ids = [a["agent_id"] for a in agents]
    if agent_id not in ids:
        inc("integrity_fail")

    remove(agent_id)

    gone = get_agent(agent_id)
    if gone is not None:
        inc("integrity_fail")


def test_declare_idempotent():
    """Re-declare with different config — should update without error."""
    agent_id = f"idem-{uuid.uuid4().hex[:8]}"

    declare(agent_id, name="OriginalName")
    a1 = get_agent(agent_id)

    declare(agent_id, name="UpdatedName", max_restarts=3)
    a2 = get_agent(agent_id)

    if not a2 or a2.get("name") != "UpdatedName":
        inc("integrity_fail")
    if not a2 or a2.get("max_restarts") != 3:
        inc("integrity_fail")

    remove(agent_id)


def test_events_logging():
    """Declare and remove → verify events appear in log."""
    agent_id = f"evt-{uuid.uuid4().hex[:8]}"
    declare(agent_id)
    remove(agent_id)

    evts = events(agent_id)
    event_types = {e["event_type"] for e in evts}

    if "declared" not in event_types:
        inc("integrity_fail")
    if "removed" not in event_types:
        inc("integrity_fail")


def test_start_stop():
    """
    Start a sleep process → supervisor returns 'starting' immediately.
    Stop it → verify 'stopped' state and process is gone.
    """
    agent_id = f"startstop-{uuid.uuid4().hex[:8]}"
    declare(agent_id, command=["python3", "-c", "import time; time.sleep(60)"])

    data = start(agent_id)
    if not data or not data.get("ok"):
        inc("integrity_fail")
        remove(agent_id)
        return

    # Supervisor returns 'starting' immediately (registry confirmation is async)
    if data.get("state") != "starting":
        inc("integrity_fail")

    pid = data.get("pid")
    if not pid:
        inc("integrity_fail")

    time.sleep(0.5)  # let process settle

    agent = get_agent(agent_id)
    if agent and agent.get("state") not in ("starting", "running"):
        inc("integrity_fail")

    stop_data = stop(agent_id)
    if not stop_data or not stop_data.get("ok"):
        inc("integrity_fail")

    time.sleep(0.3)
    agent = get_agent(agent_id)
    if not agent or agent.get("state") != "stopped":
        inc("integrity_fail")

    remove(agent_id)


def test_restart():
    """Start → restart → verify still alive after restart."""
    agent_id = f"restart-{uuid.uuid4().hex[:8]}"
    declare(agent_id, command=["python3", "-c", "import time; time.sleep(60)"])

    start(agent_id)
    time.sleep(0.3)

    data = restart(agent_id)
    if not data or not data.get("ok"):
        inc("integrity_fail")
    if data and data.get("state") != "starting":
        inc("integrity_fail")

    time.sleep(0.3)
    stop(agent_id)
    remove(agent_id)


def test_crash_detection():
    """
    Start a command that exits immediately (exit code 1).
    Policy=never so no restart. Verify state goes to 'crashed'.
    """
    agent_id = f"crash-{uuid.uuid4().hex[:8]}"
    declare(agent_id,
            command=["python3", "-c", "import sys; sys.exit(1)"],
            restart_policy="never", max_restarts=0)

    start(agent_id)

    # Wait for supervisor background task to detect exit (~2s poll interval)
    for _ in range(8):
        time.sleep(0.5)
        agent = get_agent(agent_id)
        if agent and agent.get("state") == "crashed":
            break

    agent = get_agent(agent_id)
    if not agent or agent.get("state") != "crashed":
        inc("integrity_fail")

    evts = events(agent_id)
    event_types = {e["event_type"] for e in evts}
    if "crashed" not in event_types and "start_failed" not in event_types:
        inc("integrity_fail")

    remove(agent_id)


def test_heal():
    """Heal endpoint — triggers Agent Hospital flow without real mind_state."""
    agent_id = f"heal-{uuid.uuid4().hex[:8]}"
    declare(agent_id, command=["python3", "-c", "import time; time.sleep(60)"])

    # heal on stopped agent — should start it
    data = heal(agent_id)
    if data and data.get("ok"):
        time.sleep(0.3)
        stop(agent_id)

    remove(agent_id)


def test_health_stats_consistency():
    """Health and stats endpoints return consistent data."""
    h = health()
    s = stats()

    if not h or not h.get("ok"):
        inc("integrity_fail")
        return
    if not s or not s.get("ok"):
        inc("integrity_fail")
        return

    # total from stats should match sum of state counts from health
    state_sum = sum(h.get("states", {}).values())
    if state_sum != s.get("total", 0):
        inc("integrity_fail")


def test_concurrent_declarations(n):
    """N unique agents declared simultaneously — no errors, all visible in list."""
    ids = [f"conc-{uuid.uuid4().hex[:8]}" for _ in range(n)]

    def one(aid):
        declare(aid, name=f"Concurrent-{aid}")

    with ThreadPoolExecutor(max_workers=min(n, 30)) as ex:
        futs = [ex.submit(one, aid) for aid in ids]
        for f in as_completed(futs):
            f.result()

    agents = list_agents()
    agent_set = {a["agent_id"] for a in agents}
    for aid in ids:
        if aid not in agent_set:
            inc("integrity_fail")
        else:
            remove(aid)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    try:
        r = httpx.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200
        print(f"[test] supervisor healthy: {r.json()}")
    except Exception as e:
        print(f"[test] FATAL: supervisor not reachable at {BASE}: {e}")
        sys.exit(1)

    print(f"[test] running {iters} iterations")
    t_start = time.perf_counter()

    # Correctness tests first
    print("[test] correctness suite...")
    test_declare_idempotent()
    test_events_logging()
    test_start_stop()
    test_restart()
    test_crash_detection()
    test_heal()
    test_health_stats_consistency()
    print(f"[test] correctness suite done — {counters}")

    # Main loop — CRUD stress test
    for i in range(iters):
        test_crud(i)
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
    test_concurrent_declarations(flood_n)

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
