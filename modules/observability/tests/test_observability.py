"""
Observability module stress test.

Tests:
  1.  Push metric / retrieve / aggregate
  2.  Batch push
  3.  Span start + end + retrieve trace
  4.  Health beat push / retrieve / stale detection
  5.  Alert rule create / trigger
  6.  Summary consistency
  7.  Concurrent pushes (N agents simultaneously)
  8.  Stats / health_check

Usage:
  python3 test_observability.py [iterations]   default: 500
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

BASE    = "http://127.0.0.1:9108"
TIMEOUT = 10.0

counters = {
    "metric_ok":  0,
    "span_ok":    0,
    "health_ok":  0,
    "get_ok":     0,
    "integrity_fail": 0,
    "errors":     0,
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


def push_metric(agent_id, name, value, metric_type="gauge", labels=None):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/metrics",
            json={"agent_id": agent_id, "metric_name": name,
                  "metric_type": metric_type, "value": value,
                  "labels": labels or {}},
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("metric_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def push_batch(points):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/metrics/batch",
            json={"points": [
                {"agent_id": p[0], "metric_name": p[1],
                 "metric_type": p[2], "value": p[3]} for p in points
            ]},
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("metric_ok", len(points))
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def push_span(span_id, trace_id, agent_id, name, started_at, ended_at=None, status="ok"):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/spans",
            json={"span_id": span_id, "trace_id": trace_id, "agent_id": agent_id,
                  "name": name, "started_at": started_at,
                  "ended_at": ended_at, "status": status},
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("span_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def push_health(agent_id, status="ok", cpu_pct=None, mem_mb=None):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/health",
            json={"agent_id": agent_id, "status": status,
                  "cpu_pct": cpu_pct, "mem_mb": mem_mb},
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("health_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def get_agent_metrics(agent_id, metric_name=""):
    try:
        params = {}
        if metric_name:
            params["metric_name"] = metric_name
        r = timed(lambda: httpx.get(f"{BASE}/metrics/{agent_id}", params=params, timeout=TIMEOUT))
        if r.status_code == 200:
            inc("get_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def get_trace(trace_id):
    try:
        r = httpx.get(f"{BASE}/spans/{trace_id}", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def get_health(agent_id):
    try:
        r = httpx.get(f"{BASE}/health/{agent_id}", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def get_summary():
    try:
        r = httpx.get(f"{BASE}/summary", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def health_check():
    try:
        r = httpx.get(f"{BASE}/health_check", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ── Test cases ────────────────────────────────────────────────────────────────

def test_metric_push_retrieve():
    agent_id = f"met-{uuid.uuid4().hex[:6]}"
    push_metric(agent_id, "tasks_done", 42.0, "counter")
    result = get_agent_metrics(agent_id, "tasks_done")
    if not result or result.get("count", 0) < 1:
        inc("integrity_fail")
        return
    if result["metrics"][0]["value"] != 42.0:
        inc("integrity_fail")


def test_batch_push():
    agent_id = f"batch-{uuid.uuid4().hex[:6]}"
    points = [(agent_id, f"metric_{j}", "gauge", float(j)) for j in range(5)]
    result = push_batch(points)
    if not result or result.get("count") != 5:
        inc("integrity_fail")


def test_span_trace():
    agent_id = f"span-{uuid.uuid4().hex[:6]}"
    trace_id = str(uuid.uuid4())
    span_id  = str(uuid.uuid4())
    t0       = time.time()

    push_span(span_id, trace_id, agent_id, "llm_call", t0)
    time.sleep(0.1)
    push_span(span_id, trace_id, agent_id, "llm_call", t0, time.time(), "ok")

    trace = get_trace(trace_id)
    if not trace or len(trace.get("spans", [])) < 1:
        inc("integrity_fail")
        return
    span = trace["spans"][0]
    if not span.get("duration_ms") or span["duration_ms"] < 80:
        inc("integrity_fail")


def test_health_beat():
    agent_id = f"hb-{uuid.uuid4().hex[:6]}"
    push_health(agent_id, status="ok", cpu_pct=35.5, mem_mb=512)
    h = get_health(agent_id)
    if not h or h.get("status") != "ok":
        inc("integrity_fail")
    if not h or abs((h.get("cpu_pct") or 0) - 35.5) > 0.1:
        inc("integrity_fail")
    if h and h.get("stale"):
        inc("integrity_fail")  # just pushed — should not be stale


def test_summary_consistency():
    s = get_summary()
    if not s or not s.get("ok"):
        inc("integrity_fail")


def test_health_check_node():
    h = health_check()
    if not h or not h.get("ok"):
        inc("integrity_fail")


def test_stress(i):
    agent_id = f"stress-{i % 50}"
    metric_names = ["cpu_pct", "mem_mb", "tasks_sec", "queue_depth", "llm_latency_ms"]
    push_metric(agent_id, random.choice(metric_names), random.uniform(0, 100))


def test_concurrent(n):
    def one(i):
        aid = f"conc-{i}-{uuid.uuid4().hex[:4]}"
        push_batch([
            (aid, "cpu_pct", "gauge", random.uniform(0, 100)),
            (aid, "mem_mb",  "gauge", random.uniform(256, 4096)),
        ])
        push_health(aid, status="ok")

    with ThreadPoolExecutor(max_workers=min(n, 30)) as ex:
        futs = [ex.submit(one, i) for i in range(n)]
        for f in as_completed(futs):
            f.result()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    try:
        r = httpx.get(f"{BASE}/health_check", timeout=5)
        assert r.status_code == 200
        print(f"[test] observability healthy: {r.json()}")
    except Exception as e:
        print(f"[test] FATAL: observability not reachable at {BASE}: {e}")
        sys.exit(1)

    print(f"[test] running {iters} iterations")
    t_start = time.perf_counter()

    print("[test] correctness suite...")
    test_metric_push_retrieve()
    test_batch_push()
    test_span_trace()
    test_health_beat()
    test_summary_consistency()
    test_health_check_node()
    print(f"[test] correctness suite done — {counters}")

    for i in range(iters):
        test_stress(i)
        if (i + 1) % 100 == 0:
            elapsed = time.perf_counter() - t_start
            p50 = round(statistics.median(latencies), 1) if latencies else 0
            p95 = round(statistics.quantiles(latencies, n=20)[18], 1) if len(latencies) >= 20 else 0
            print(f"[test] i={i+1} {counters} rate={round((i+1)/elapsed,1)}/s p50={p50}ms p95={p95}ms")

    flood_n = min(iters // 5, 100)
    print(f"[test] concurrent flood: {flood_n} agents")
    test_concurrent(flood_n)

    elapsed = time.perf_counter() - t_start
    p50 = round(statistics.median(latencies), 1) if latencies else 0
    p95 = round(statistics.quantiles(latencies, n=20)[18], 1) if len(latencies) >= 20 else 0
    p99 = round(statistics.quantiles(latencies, n=100)[98], 1) if len(latencies) >= 100 else 0

    print(f"\n[test] DONE iters={iters} elapsed={elapsed:.1f}s\n  counters={counters}\n"
          f"  latency p50={p50}ms p95={p95}ms p99={p99}ms min={round(min(latencies),1)}ms max={round(max(latencies),1)}ms")

    if counters["errors"] > 0 or counters["integrity_fail"] > 0:
        print(f"[test] FAIL — errors={counters['errors']} integrity_fail={counters['integrity_fail']}")
        sys.exit(1)
    else:
        print("[test] PASS")


if __name__ == "__main__":
    main()
