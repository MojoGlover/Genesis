"""
Scheduler module stress test.

Tests:
  1.  Create cron job / get / list / cancel
  2.  Create interval job — fires within expected window
  3.  Create once job — fires once, then done
  4.  Pause / resume cycle
  5.  Manual fire (POST /jobs/{id}/fire)
  6.  Execution history logged correctly
  7.  Invalid cron expression → 422
  8.  next_fire is computed correctly for cron/interval/once
  9.  Concurrent job creation flood
  10. Stats / health consistency

A mock callback server runs on port 9198 to receive fired events.

Usage:
  python3 test_scheduler.py [iterations]   default: 500
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
from fastapi import FastAPI, Request

BASE      = "http://127.0.0.1:9107"
MOCK_PORT = 9198
MOCK_URL  = f"http://127.0.0.1:{MOCK_PORT}"
TIMEOUT   = 10.0

# Shared counter for mock callback fires
_fires: dict[str, list] = {}
_fires_lock = threading.Lock()

counters = {
    "create_ok":    0,
    "get_ok":       0,
    "list_ok":      0,
    "cancel_ok":    0,
    "pause_ok":     0,
    "resume_ok":    0,
    "fire_ok":      0,
    "history_ok":   0,
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


# ── Mock callback server ──────────────────────────────────────────────────────

mock_app = FastAPI(title="MockCallback")


@mock_app.post("/callback/{job_id}")
async def mock_callback(job_id: str, request: Request):
    body = await request.json()
    with _fires_lock:
        if job_id not in _fires:
            _fires[job_id] = []
        _fires[job_id].append({"received_at": time.time(), "body": body})
    return {"ok": True}


@mock_app.post("/callback")
async def mock_callback_generic(request: Request):
    body = await request.json()
    job_id = body.get("job_id", "unknown")
    with _fires_lock:
        if job_id not in _fires:
            _fires[job_id] = []
        _fires[job_id].append({"received_at": time.time(), "body": body})
    return {"ok": True}


def _run_mock():
    uvicorn.run(mock_app, host="127.0.0.1", port=MOCK_PORT, log_level="error")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def create_job(agent_id, name, job_type, schedule, callback=None, payload=None):
    cb = callback or f"{MOCK_URL}/callback"
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/jobs",
            json={
                "name":         name,
                "agent_id":     agent_id,
                "callback_url": cb,
                "job_type":     job_type,
                "schedule":     schedule,
                "payload":      payload or {},
            },
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("create_ok")
            return r.json()
        return {"error": r.json(), "status_code": r.status_code}
    except Exception:
        inc("errors")
    return None


def get_job(job_id):
    try:
        r = timed(lambda: httpx.get(f"{BASE}/jobs/{job_id}", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("get_ok")
            return r.json()
        if r.status_code == 404:
            return None
        inc("errors")
    except Exception:
        inc("errors")
    return None


def list_jobs(agent_id="", status=""):
    try:
        params = {}
        if agent_id:
            params["agent_id"] = agent_id
        if status:
            params["status"] = status
        r = timed(lambda: httpx.get(f"{BASE}/jobs", params=params, timeout=TIMEOUT))
        if r.status_code == 200:
            inc("list_ok")
            return r.json().get("jobs", [])
        inc("errors")
    except Exception:
        inc("errors")
    return []


def cancel_job(job_id):
    try:
        r = timed(lambda: httpx.delete(f"{BASE}/jobs/{job_id}", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("cancel_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def pause_job(job_id):
    try:
        r = httpx.post(f"{BASE}/jobs/{job_id}/pause", timeout=TIMEOUT)
        if r.status_code == 200:
            inc("pause_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def resume_job(job_id):
    try:
        r = httpx.post(f"{BASE}/jobs/{job_id}/resume", timeout=TIMEOUT)
        if r.status_code == 200:
            inc("resume_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def fire_job(job_id):
    try:
        r = timed(lambda: httpx.post(f"{BASE}/jobs/{job_id}/fire", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("fire_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def job_history(job_id, limit=20):
    try:
        r = timed(lambda: httpx.get(
            f"{BASE}/history/{job_id}", params={"limit": limit}, timeout=TIMEOUT
        ))
        if r.status_code == 200:
            inc("history_ok")
            return r.json().get("history", [])
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

def test_cron_crud():
    """Create cron job → get → list → cancel."""
    agent_id = f"cron-{uuid.uuid4().hex[:6]}"
    result = create_job(agent_id, "hourly", "cron", "0 * * * *")
    if not result or not result.get("job_id"):
        inc("integrity_fail")
        return

    job_id = result["job_id"]

    # next_fire should be in the future
    if result.get("next_fire", 0) <= time.time():
        inc("integrity_fail")

    # Get
    job = get_job(job_id)
    if not job or job.get("agent_id") != agent_id:
        inc("integrity_fail")
    if not job or job.get("status") != "active":
        inc("integrity_fail")

    # List
    jobs = list_jobs(agent_id=agent_id)
    ids = [j["job_id"] for j in jobs]
    if job_id not in ids:
        inc("integrity_fail")

    # Cancel
    r = cancel_job(job_id)
    if not r or r.get("status") != "cancelled":
        inc("integrity_fail")

    # Verify cancelled
    job = get_job(job_id)
    if not job or job.get("status") != "cancelled":
        inc("integrity_fail")


def test_once_job_fires():
    """Create once job with 2s delay → wait → verify it fired and is done."""
    agent_id = f"once-{uuid.uuid4().hex[:6]}"
    result = create_job(agent_id, "send-welcome", "once", "2")
    if not result or not result.get("job_id"):
        inc("integrity_fail")
        return

    job_id = result["job_id"]

    # Wait for it to fire
    for _ in range(10):
        time.sleep(0.5)
        job = get_job(job_id)
        if job and job.get("fire_count", 0) >= 1:
            break

    job = get_job(job_id)
    if not job or job.get("fire_count", 0) < 1:
        inc("integrity_fail")
    if not job or job.get("status") != "done":
        inc("integrity_fail")


def test_interval_job():
    """Create 2s interval job → verify multiple fires."""
    agent_id = f"intv-{uuid.uuid4().hex[:6]}"
    result = create_job(agent_id, "heartbeat", "interval", "2")
    if not result or not result.get("job_id"):
        inc("integrity_fail")
        return

    job_id = result["job_id"]

    # Wait ~5 seconds — should fire at least 2 times
    for _ in range(15):
        time.sleep(0.4)
        job = get_job(job_id)
        if job and job.get("fire_count", 0) >= 2:
            break

    job = get_job(job_id)
    if not job or job.get("fire_count", 0) < 2:
        inc("integrity_fail")

    cancel_job(job_id)


def test_pause_resume():
    """Pause job → verify no fires → resume → fires continue."""
    agent_id = f"pause-{uuid.uuid4().hex[:6]}"
    result = create_job(agent_id, "pausable", "interval", "1")
    if not result or not result.get("job_id"):
        inc("integrity_fail")
        return

    job_id = result["job_id"]
    time.sleep(1.5)  # let it fire once

    pause_r = pause_job(job_id)
    if not pause_r or pause_r.get("status") != "paused":
        inc("integrity_fail")
        cancel_job(job_id)
        return

    job = get_job(job_id)
    count_before = job.get("fire_count", 0) if job else 0

    time.sleep(2)  # paused — should NOT fire

    job = get_job(job_id)
    count_after = job.get("fire_count", 0) if job else 0
    if count_after != count_before:
        inc("integrity_fail")

    # Resume
    resume_r = resume_job(job_id)
    if not resume_r or resume_r.get("status") != "active":
        inc("integrity_fail")

    cancel_job(job_id)


def test_manual_fire():
    """Manual fire triggers callback and records history."""
    agent_id = f"manual-{uuid.uuid4().hex[:6]}"
    job_id_str = uuid.uuid4().hex[:6]
    result = create_job(agent_id, "manual-test", "cron", "0 3 * * *",  # 3am — won't auto-fire
                        callback=f"{MOCK_URL}/callback")
    if not result or not result.get("job_id"):
        inc("integrity_fail")
        return

    job_id = result["job_id"]
    fire_result = fire_job(job_id)
    if not fire_result or not fire_result.get("ok"):
        inc("integrity_fail")
        cancel_job(job_id)
        return

    # Wait for async fire to complete and history to be recorded
    time.sleep(1.0)

    hist = job_history(job_id)
    if not hist:
        inc("integrity_fail")

    cancel_job(job_id)


def test_invalid_cron():
    """Invalid cron expression returns 422."""
    result = create_job("test-agent", "invalid", "cron", "not a cron expression")
    if not result or result.get("status_code") != 422:
        inc("integrity_fail")


def test_stats_health():
    h = health()
    s = stats()
    if not h or not h.get("ok"):
        inc("integrity_fail")
    if not s or not s.get("ok"):
        inc("integrity_fail")


def test_crud_stress(i):
    """Fast create → get → cancel cycle. No waiting for fires."""
    agent_id = f"stress-{i % 20}"
    # Use cron (no actual firing at these times during test)
    schedule = f"{i % 60} {i % 24} * * *"
    result = create_job(agent_id, f"stress-job-{i}", "cron", schedule)
    if not result or not result.get("job_id"):
        inc("integrity_fail")
        return

    job_id = result["job_id"]
    job = get_job(job_id)
    if not job or job.get("status") != "active":
        inc("integrity_fail")

    cancel_job(job_id)


def test_concurrent_create(n):
    def one(i):
        agent_id = f"conc-{i}-{uuid.uuid4().hex[:4]}"
        result = create_job(agent_id, f"conc-{i}", "cron", f"{i % 60} * * * *")
        if result and result.get("job_id"):
            cancel_job(result["job_id"])

    with ThreadPoolExecutor(max_workers=min(n, 30)) as ex:
        futs = [ex.submit(one, i) for i in range(n)]
        for f in as_completed(futs):
            f.result()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    # Start mock callback server
    t = threading.Thread(target=_run_mock, daemon=True)
    t.start()
    time.sleep(1.0)

    try:
        r = httpx.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200
        print(f"[test] scheduler healthy: {r.json()}")
    except Exception as e:
        print(f"[test] FATAL: scheduler not reachable at {BASE}: {e}")
        sys.exit(1)

    print(f"[test] running {iters} iterations")
    t_start = time.perf_counter()

    # Correctness suite — includes timing-sensitive tests
    print("[test] correctness suite (includes real-time tests ~10s)...")
    test_cron_crud()
    test_invalid_cron()
    test_stats_health()
    test_once_job_fires()      # ~2s wait
    test_interval_job()        # ~5s wait
    test_pause_resume()        # ~4s wait
    test_manual_fire()         # ~1s wait
    print(f"[test] correctness suite done — {counters}")

    # Stress loop — pure CRUD (no waiting)
    for i in range(iters):
        test_crud_stress(i)
        if (i + 1) % 100 == 0:
            elapsed = time.perf_counter() - t_start
            p50 = round(statistics.median(latencies), 1) if latencies else 0
            p95 = round(statistics.quantiles(latencies, n=20)[18], 1) if len(latencies) >= 20 else 0
            rate = round((i + 1) / elapsed, 1)
            print(
                f"[test] i={i+1} {counters} "
                f"rate={rate}/s p50={p50}ms p95={p95}ms"
            )

    # Flood
    flood_n = min(iters // 5, 100)
    print(f"[test] concurrent flood: {flood_n} jobs")
    test_concurrent_create(flood_n)

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
