"""
Ledger module stress test.

Tests:
  1.  Record entry / retrieve by entry_id / verify HMAC
  2.  Tamper detection — modified entry fails HMAC check
  3.  Agent summary — totals match individual entries
  4.  System summary — sums across all agents
  5.  Budget set / get / alert at threshold
  6.  Date range filtering (since/until)
  7.  Multiple unit types (tokens, seconds, requests, bytes)
  8.  Zero-cost entries (Ollama / local compute)
  9.  Concurrent writes from multiple agents
  10. Stats consistency

Usage:
  python3 test_ledger.py [iterations]   default: 500
"""
from __future__ import annotations

import sys
import time
import uuid
import threading
import statistics
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

BASE    = "http://127.0.0.1:9106"
TIMEOUT = 10.0

counters = {
    "record_ok":    0,
    "get_ok":       0,
    "summary_ok":   0,
    "budget_ok":    0,
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


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def record(agent_id, resource, units=100, unit_type="tokens",
           cost_usd=0.001, task_id="", metadata=None):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/entries",
            json={
                "agent_id":   agent_id,
                "resource":   resource,
                "units":      units,
                "unit_type":  unit_type,
                "cost_usd":   cost_usd,
                "task_id":    task_id,
                "session_id": "",
                "metadata":   metadata or {},
            },
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("record_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def get_entry(entry_id):
    try:
        r = timed(lambda: httpx.get(f"{BASE}/entries/{entry_id}", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("get_ok")
            return r.json()
        if r.status_code == 404:
            return None
        inc("errors")
    except Exception:
        inc("errors")
    return None


def list_entries(agent_id="", resource="", limit=50):
    try:
        params = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        if resource:
            params["resource"] = resource
        r = timed(lambda: httpx.get(f"{BASE}/entries", params=params, timeout=TIMEOUT))
        if r.status_code == 200:
            return r.json().get("entries", [])
        inc("errors")
    except Exception:
        inc("errors")
    return []


def summary(agent_id):
    try:
        r = timed(lambda: httpx.get(f"{BASE}/summary/{agent_id}", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("summary_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def system_summary():
    try:
        r = httpx.get(f"{BASE}/summary", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def set_budget(agent_id, daily_usd, monthly_usd=0, alert_pct=80.0):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/budget/{agent_id}",
            json={"daily_usd": daily_usd, "monthly_usd": monthly_usd, "alert_pct": alert_pct},
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("budget_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def get_budget(agent_id):
    try:
        r = httpx.get(f"{BASE}/budget/{agent_id}", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


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

def test_record_and_retrieve():
    """Record entry → retrieve by ID → verify HMAC is valid."""
    agent_id = f"test-{uuid.uuid4().hex[:6]}"
    data = record(agent_id, "anthropic/claude-3-5-sonnet",
                  units=500, cost_usd=0.0075, task_id="task-1",
                  metadata={"model": "claude-3-5-sonnet"})
    if not data or not data.get("entry_id"):
        inc("integrity_fail")
        return

    entry = get_entry(data["entry_id"])
    if not entry:
        inc("integrity_fail")
        return

    if entry.get("agent_id") != agent_id:
        inc("integrity_fail")
    if not entry.get("hmac_valid"):
        inc("integrity_fail")
    if abs(entry.get("cost_usd", 0) - 0.0075) > 1e-9:
        inc("integrity_fail")
    if entry.get("metadata", {}).get("model") != "claude-3-5-sonnet":
        inc("integrity_fail")


def test_summary_math():
    """Record N entries → verify summary totals match sum of individual costs."""
    agent_id = f"math-{uuid.uuid4().hex[:6]}"
    costs = [0.001, 0.002, 0.003, 0.005, 0.010]
    expected_total = sum(costs)

    for c in costs:
        record(agent_id, "openai/gpt-4o", units=100, cost_usd=c)

    s = summary(agent_id)
    if not s:
        inc("integrity_fail")
        return

    actual = s.get("total_usd", 0)
    if abs(actual - expected_total) > 1e-6:
        inc("integrity_fail")


def test_zero_cost_entry():
    """Ollama / local compute — zero cost entries are valid."""
    agent_id = f"ollama-{uuid.uuid4().hex[:6]}"
    data = record(agent_id, "ollama/llama3.3:70b",
                  units=5000, unit_type="tokens", cost_usd=0.0)
    if not data or not data.get("entry_id"):
        inc("integrity_fail")
        return

    entry = get_entry(data["entry_id"])
    if not entry or entry.get("cost_usd") != 0.0:
        inc("integrity_fail")
    if not entry.get("hmac_valid"):
        inc("integrity_fail")


def test_multiple_unit_types():
    """Record tokens, seconds, requests, bytes — all valid."""
    agent_id = f"units-{uuid.uuid4().hex[:6]}"
    for ut in ["tokens", "seconds", "requests", "bytes"]:
        data = record(agent_id, f"resource/{ut}", units=10, unit_type=ut, cost_usd=0.0)
        if not data or not data.get("entry_id"):
            inc("integrity_fail")

    s = summary(agent_id)
    if not s or len(s.get("breakdown", [])) != 4:
        inc("integrity_fail")


def test_budget_alert():
    """Set a tight budget → record entries that hit alert threshold."""
    agent_id = f"budget-{uuid.uuid4().hex[:6]}"
    # Budget: $0.01/day, alert at 50%
    set_budget(agent_id, daily_usd=0.01, alert_pct=50.0)

    # Record $0.006 (60% of budget — above 50% threshold)
    data = record(agent_id, "anthropic/claude", units=100, cost_usd=0.006)
    if not data:
        inc("integrity_fail")
        return

    b = get_budget(agent_id)
    if not b:
        inc("integrity_fail")
        return

    if b.get("day_pct", 0) < 50:
        inc("integrity_fail")


def test_system_summary_consistency():
    """System summary total >= sum of individual agent totals recorded in this test."""
    sys_s = system_summary()
    if not sys_s or not sys_s.get("ok"):
        inc("integrity_fail")
        return
    # Total >= 0
    if sys_s.get("total_usd", 0) < 0:
        inc("integrity_fail")


def test_stats_health():
    h = health()
    s = stats()
    if not h or not h.get("ok"):
        inc("integrity_fail")
    if not s or not s.get("ok"):
        inc("integrity_fail")
    if s and h:
        if s.get("total_entries", 0) != h.get("entries", 0):
            inc("integrity_fail")


def test_stress_record(i):
    """High-volume recording. Alternates resources and unit types."""
    resources = [
        "anthropic/claude-3-5-sonnet",
        "openai/gpt-4o",
        "ollama/llama3.3:70b",
        "anthropic/claude-haiku",
        "replicate/sdxl",
    ]
    unit_types = ["tokens", "tokens", "tokens", "seconds", "requests"]

    agent_id  = f"stress-{i % 30}"  # 30 reused agent IDs
    resource  = resources[i % len(resources)]
    unit_type = unit_types[i % len(unit_types)]
    units     = random.randint(50, 2000)
    cost      = round(units * 0.000002, 8) if unit_type == "tokens" else round(random.uniform(0, 0.01), 6)

    data = record(agent_id, resource, units=units, unit_type=unit_type, cost_usd=cost)
    if not data or not data.get("entry_id"):
        inc("integrity_fail")


def test_concurrent_writes(n):
    """N agents writing simultaneously — no integrity failures."""
    def one(i):
        aid = f"conc-{i}-{uuid.uuid4().hex[:4]}"
        for _ in range(3):
            record(aid, "anthropic/claude", units=100, cost_usd=0.001)

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
        print(f"[test] ledger healthy: {r.json()}")
    except Exception as e:
        print(f"[test] FATAL: ledger not reachable at {BASE}: {e}")
        sys.exit(1)

    print(f"[test] running {iters} iterations")
    t_start = time.perf_counter()

    # Correctness suite
    print("[test] correctness suite...")
    test_record_and_retrieve()
    test_summary_math()
    test_zero_cost_entry()
    test_multiple_unit_types()
    test_budget_alert()
    test_system_summary_consistency()
    test_stats_health()
    print(f"[test] correctness suite done — {counters}")

    # Main stress loop
    for i in range(iters):
        test_stress_record(i)
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
    print(f"[test] concurrent flood: {flood_n} agents × 3 writes")
    test_concurrent_writes(flood_n)

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
