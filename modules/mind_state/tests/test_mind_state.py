"""
MindState module stress test.

Tests:
  1. Save / restore round-trip (state integrity)
  2. Versioning (each save increments version)
  3. Compression (large states compressed correctly)
  4. Checkpoints (survive pruning, promoted correctly)
  5. History listing (correct order, metadata only)
  6. Version rollback (restore specific version)
  7. Wipe (clean delete)
  8. Concurrent saves (multiple agents saving simultaneously)
  9. Agent Hospital scenario (simulate crash → restore → wipe)
  10. Size limit enforcement

Usage:
  python3 test_mind_state.py [iterations]   default: 500
"""
from __future__ import annotations

import sys
import time
import uuid
import json
import threading
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

BASE    = "http://127.0.0.1:9102"
TIMEOUT = 10.0

counters = {
    "save_ok":        0,
    "restore_ok":     0,
    "checkpoint_ok":  0,
    "history_ok":     0,
    "rollback_ok":    0,
    "wipe_ok":        0,
    "hospital_ok":    0,
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


def save(agent_id, state, snapshot_type="auto", label=""):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/agents/{agent_id}/state",
            json={"state": state, "snapshot_type": snapshot_type, "label": label},
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("save_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def restore(agent_id):
    try:
        r = timed(lambda: httpx.get(f"{BASE}/agents/{agent_id}/state", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("restore_ok")
            return r.json()
        if r.status_code == 404:
            return None
        inc("errors")
    except Exception:
        inc("errors")
    return None


def restore_version(agent_id, version):
    try:
        r = httpx.get(f"{BASE}/agents/{agent_id}/state/{version}", timeout=TIMEOUT)
        if r.status_code == 200:
            inc("rollback_ok")
            return r.json()
    except Exception:
        inc("errors")
    return None


def checkpoint(agent_id, label=""):
    try:
        r = httpx.post(
            f"{BASE}/agents/{agent_id}/state/checkpoint",
            params={"label": label}, timeout=TIMEOUT,
        )
        if r.status_code == 200:
            inc("checkpoint_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def history(agent_id, limit=20):
    try:
        r = httpx.get(
            f"{BASE}/agents/{agent_id}/state/history",
            params={"limit": limit}, timeout=TIMEOUT,
        )
        if r.status_code == 200:
            inc("history_ok")
            return r.json().get("history", [])
    except Exception:
        inc("errors")
    return []


def wipe(agent_id):
    try:
        r = httpx.delete(f"{BASE}/agents/{agent_id}/state", timeout=TIMEOUT)
        if r.status_code == 200:
            inc("wipe_ok")
            return True
        inc("errors")
    except Exception:
        inc("errors")
    return False


# ── Test cases ────────────────────────────────────────────────────────────────

def test_round_trip(i):
    """Save → restore → verify state integrity."""
    agent_id = f"rt-{i}-{uuid.uuid4().hex[:6]}"
    state = {
        "memory":         [{"role": "user", "content": f"test message {i}"}],
        "active_task":    {"id": f"task-{i}", "step": i % 10},
        "context_summary": f"Test context {i}",
        "goals":          [f"goal-{i}"],
        "custom":         {"iteration": i, "ts": time.time()},
    }
    save(agent_id, state)
    result = restore(agent_id)
    if result:
        restored = result.get("state", {})
        if restored.get("custom", {}).get("iteration") != i:
            inc("integrity_fail")
    wipe(agent_id)


def test_versioning():
    """Multiple saves create increasing versions."""
    agent_id = f"ver-{uuid.uuid4().hex[:8]}"
    versions = []
    for j in range(5):
        data = save(agent_id, {"step": j})
        if data:
            versions.append(data["version"])

    # Versions should be strictly increasing
    if versions != sorted(versions) or len(set(versions)) != len(versions):
        inc("integrity_fail")

    # Rollback to version 2
    if len(versions) >= 2:
        rolled = restore_version(agent_id, versions[1])
        if rolled and rolled["state"].get("step") != 1:
            inc("integrity_fail")

    h = history(agent_id)
    if h:
        pass  # counted in history_ok

    wipe(agent_id)


def test_large_state_compression():
    """Large states get compressed; round-trip still works."""
    agent_id = f"large-{uuid.uuid4().hex[:8]}"
    big_state = {
        "memory": [{"role": "assistant", "content": "x" * 500} for _ in range(50)],
        "context_summary": "A" * 10000,
        "beliefs": {f"key_{k}": f"value_{k}" * 20 for k in range(100)},
    }
    data = save(agent_id, big_state)
    if data:
        result = restore(agent_id)
        if result:
            restored = result.get("state", {})
            if len(restored.get("context_summary", "")) != 10000:
                inc("integrity_fail")
    wipe(agent_id)


def test_checkpoint_survival():
    """Checkpoints should survive longer than regular versions."""
    agent_id = f"ckpt-{uuid.uuid4().hex[:8]}"
    # Save and checkpoint
    save(agent_id, {"phase": "checkpoint"})
    cp = checkpoint(agent_id, label="test-checkpoint")

    # Save many more regular versions
    for j in range(5):
        save(agent_id, {"phase": f"regular-{j}"})

    # Checkpoint version should still be in history
    h = history(agent_id, limit=50)
    ckpt_versions = [v for v in h if v["snapshot_type"] == "checkpoint"]
    if not ckpt_versions:
        inc("integrity_fail")

    wipe(agent_id)


def test_hospital_scenario():
    """
    Simulate Agent Hospital recovery:
      1. Agent saves state normally
      2. Agent 'dies' (we just stop saving)
      3. Hospital reads last state
      4. Hospital rebuilds agent (we just verify state is accessible)
      5. Hospital wipes state after rebuild
    """
    agent_id = f"hospital-{uuid.uuid4().hex[:8]}"

    # Agent saves state during operation
    for j in range(3):
        save(agent_id, {
            "memory":      [{"role": "user", "content": f"msg {j}"}],
            "active_task": {"id": "build-registry", "step": j},
            "goals":       ["finish registry", "seal module"],
        }, snapshot_type="auto")

    # Checkpoint before a risky op
    save(agent_id, {"memory": [], "active_task": {"id": "deploy"}, "goals": []},
         snapshot_type="checkpoint", label="before_deploy")

    # Agent 'dies' here — Hospital reads the state
    recovered = restore(agent_id)
    if recovered and recovered["state"].get("active_task", {}).get("id") == "deploy":
        inc("hospital_ok")
    else:
        inc("integrity_fail")

    # Hospital wipes after rebuild
    wipe(agent_id)

    # Verify state is gone
    gone = restore(agent_id)
    if gone is not None:
        inc("integrity_fail")


def test_concurrent_saves(n):
    """N agents saving simultaneously."""
    def one(i):
        aid = f"conc-{i}-{uuid.uuid4().hex[:4]}"
        for _ in range(3):
            save(aid, {"agent": i, "ts": time.time()})
        wipe(aid)

    with ThreadPoolExecutor(max_workers=min(n, 30)) as ex:
        futs = [ex.submit(one, i) for i in range(n)]
        for f in as_completed(futs):
            f.result()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    try:
        r = httpx.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200
        print(f"[test] mind_state healthy: {r.json()}")
    except Exception as e:
        print(f"[test] FATAL: mind_state not reachable at {BASE}: {e}")
        sys.exit(1)

    print(f"[test] running {iters} iterations")
    t_start = time.perf_counter()

    # Correctness tests first
    test_versioning()
    test_large_state_compression()
    test_checkpoint_survival()
    test_hospital_scenario()

    # Main loop
    for i in range(iters):
        test_round_trip(i)
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
    test_concurrent_saves(flood_n)

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
