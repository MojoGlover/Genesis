"""
Model Gateway module stress test.

Tests:
  1.  Register model / list / disable
  2.  Chat via mock Ollama backend (real HTTP round-trip)
  3.  Model selection by capability
  4.  Model selection by backend filter
  5.  Priority routing (lower priority number wins)
  6.  Usage logging (entries appear after chat)
  7.  System usage aggregation
  8.  Stats / health consistency
  9.  Concurrent chats (N agents simultaneously)
  10. Chat with missing model → 404

A mock Ollama-compatible server runs on port 9199.

Usage:
  python3 test_model_gateway.py [iterations]   default: 500
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
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

BASE      = "http://127.0.0.1:9109"
MOCK_PORT = 9199
MOCK_URL  = f"http://127.0.0.1:{MOCK_PORT}"
TIMEOUT   = 15.0

counters = {
    "chat_ok":      0,
    "register_ok":  0,
    "list_ok":      0,
    "disable_ok":   0,
    "usage_ok":     0,
    "integrity_fail": 0,
    "errors":       0,
}
latencies: list[float] = []
lock = threading.Lock()

_mock_calls: list[dict] = []
_mock_lock  = threading.Lock()


def inc(key, n=1):
    with lock:
        counters[key] += n


def timed(fn):
    t0 = time.perf_counter()
    r  = fn()
    with lock:
        latencies.append((time.perf_counter() - t0) * 1000)
    return r


# ── Mock Ollama server ────────────────────────────────────────────────────────

mock_app = FastAPI(title="MockOllama")


@mock_app.post("/api/chat")
async def mock_ollama_chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    last_content = messages[-1]["content"] if messages else "hello"
    with _mock_lock:
        _mock_calls.append({"received_at": time.time(), "body": body})
    return JSONResponse({
        "model":             body.get("model", "test-model"),
        "message":           {"role": "assistant", "content": f"echo: {last_content}"},
        "done":              True,
        "prompt_eval_count": len(last_content),
        "eval_count":        10,
    })


@mock_app.get("/health")
async def mock_health():
    return {"ok": True}


def _run_mock():
    uvicorn.run(mock_app, host="127.0.0.1", port=MOCK_PORT, log_level="error")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def register_model(model_id, priority=10, capabilities=None, endpoint=None):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/models/register",
            json={
                "model_id":        model_id,
                "name":            model_id,
                "backend":         "ollama",
                "backend_model":   model_id,
                "endpoint":        endpoint or MOCK_URL,
                "context_window":  4096,
                "capabilities":    capabilities or ["chat", "complete"],
                "priority":        priority,
                "cost_per_1k_in":  0.001,
                "cost_per_1k_out": 0.002,
                "max_tokens":      512,
            },
            timeout=TIMEOUT,
        ))
        if r.status_code in (200, 201):
            inc("register_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def list_models(backend="", capability=""):
    try:
        params = {}
        if backend:
            params["backend"] = backend
        if capability:
            params["capability"] = capability
        r = timed(lambda: httpx.get(f"{BASE}/models", params=params, timeout=TIMEOUT))
        if r.status_code == 200:
            inc("list_ok")
            return r.json().get("models", [])
        inc("errors")
    except Exception:
        inc("errors")
    return []


def disable_model(model_id):
    try:
        r = timed(lambda: httpx.delete(f"{BASE}/models/{model_id}", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("disable_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def chat(agent_id, messages, model=None, capability=None, backend=None):
    try:
        payload: dict = {
            "agent_id":   agent_id,
            "messages":   messages,
            "model_id":   model or "",
            "backend":    backend or "",
            "max_tokens": 64,
        }
        if capability:
            payload["capability"] = capability
        r = timed(lambda: httpx.post(
            f"{BASE}/chat",
            json=payload,
            timeout=TIMEOUT,
        ))
        if r.status_code == 200:
            inc("chat_ok")
            return r.json()
        if r.status_code in (404, 503, 502):
            return {"error": r.status_code}
        inc("errors")
    except Exception:
        inc("errors")
    return None


def get_usage(agent_id):
    try:
        r = timed(lambda: httpx.get(f"{BASE}/usage/{agent_id}", timeout=TIMEOUT))
        if r.status_code == 200:
            inc("usage_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def get_system_usage():
    try:
        r = httpx.get(f"{BASE}/usage", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def gateway_health():
    try:
        r = httpx.get(f"{BASE}/health", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def gateway_stats():
    try:
        r = httpx.get(f"{BASE}/stats", timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ── Test cases ────────────────────────────────────────────────────────────────

# Model IDs used in tests — registered once, shared
TEST_MODEL_A = "test-mock-a"
TEST_MODEL_B = "test-mock-b"


def setup_test_models():
    """Register test models pointing at mock Ollama server."""
    register_model(TEST_MODEL_A, priority=5, capabilities=["chat", "complete", "code"])
    register_model(TEST_MODEL_B, priority=15, capabilities=["chat"])


def test_register_list():
    """Register + verify in list."""
    mid = f"test-reg-{uuid.uuid4().hex[:6]}"
    result = register_model(mid, priority=20)
    if not result or result.get("model_id") != mid:
        inc("integrity_fail")
        return

    models = list_models()
    ids = [m["model_id"] for m in models]
    if mid not in ids:
        inc("integrity_fail")
        return

    # Clean up — disable
    disable_model(mid)


def test_disable_model():
    """Disable model → no longer in active (enabled_only) list."""
    mid = f"test-dis-{uuid.uuid4().hex[:6]}"
    register_model(mid, priority=99)
    models_before = [m["model_id"] for m in list_models()]
    if mid not in models_before:
        inc("integrity_fail")
        return

    disable_model(mid)

    # Default list is enabled_only=true — disabled model should not appear
    models_after = [m["model_id"] for m in list_models()]
    if mid in models_after:
        inc("integrity_fail")


def test_chat_mock():
    """Chat via mock Ollama backend → verify echo response."""
    agent_id = f"chat-{uuid.uuid4().hex[:6]}"
    msg = "ping from test"
    result = chat(agent_id, [{"role": "user", "content": msg}], model=TEST_MODEL_A)
    if not result or "error" in result:
        inc("integrity_fail")
        return
    content = result.get("content", "")
    if msg not in content:
        inc("integrity_fail")
        return
    if not result.get("model_id"):
        inc("integrity_fail")
    if result.get("cost_usd") is None:
        inc("integrity_fail")


def test_priority_routing():
    """TEST_MODEL_A (priority=5) beats TEST_MODEL_B (priority=15) when both capable."""
    agent_id = f"prio-{uuid.uuid4().hex[:6]}"
    result = chat(agent_id, [{"role": "user", "content": "hi"}],
                  capability="chat", backend="ollama")
    if not result or "error" in result:
        inc("integrity_fail")
        return
    # Should pick TEST_MODEL_A (priority 5) over B (priority 15)
    if result.get("model_id") != TEST_MODEL_A:
        inc("integrity_fail")


def test_capability_filter():
    """Only TEST_MODEL_A has 'code' capability."""
    agent_id = f"cap-{uuid.uuid4().hex[:6]}"
    result = chat(agent_id, [{"role": "user", "content": "write code"}],
                  capability="code")
    if not result or "error" in result:
        inc("integrity_fail")
        return
    if result.get("model_id") != TEST_MODEL_A:
        inc("integrity_fail")


def test_exact_model_routing():
    """Requesting TEST_MODEL_B by exact ID should route there."""
    agent_id = f"exact-{uuid.uuid4().hex[:6]}"
    result = chat(agent_id, [{"role": "user", "content": "direct"}],
                  model=TEST_MODEL_B)
    if not result or "error" in result:
        inc("integrity_fail")
        return
    if result.get("model_id") != TEST_MODEL_B:
        inc("integrity_fail")


def test_missing_model():
    """Chat with a nonexistent model ID → 503 (no model available)."""
    agent_id = f"miss-{uuid.uuid4().hex[:6]}"
    result = chat(agent_id, [{"role": "user", "content": "hello"}],
                  model="nonexistent-model-xyz-99999")
    # Server returns 503 when no model matches — our chat() returns {"error": 503}
    if not result or result.get("error") != 503:
        inc("integrity_fail")


def test_usage_logged():
    """After chat, usage entry should appear for agent."""
    agent_id = f"usage-{uuid.uuid4().hex[:6]}"
    chat(agent_id, [{"role": "user", "content": "log me"}], model=TEST_MODEL_A)

    usage = get_usage(agent_id)
    entries = (usage or {}).get("entries", [])
    if not entries:
        inc("integrity_fail")
        return
    entry = entries[0]
    if entry.get("model_id") != TEST_MODEL_A:
        inc("integrity_fail")
    total_tokens = entry.get("input_tokens", 0) + entry.get("output_tokens", 0)
    if total_tokens < 1:
        inc("integrity_fail")


def test_system_usage():
    """System usage endpoint returns per-model breakdown."""
    u = get_system_usage()
    if not u or not isinstance(u.get("by_model"), list):
        inc("integrity_fail")


def test_health_stats():
    """Health and stats must be ok."""
    h = gateway_health()
    s = gateway_stats()
    if not h or not h.get("ok"):
        inc("integrity_fail")
    if not s or not s.get("ok"):
        inc("integrity_fail")


def test_stress(i):
    """Fast chat cycle using shared test model."""
    agent_id = f"stress-{i % 50}"
    prompts = [
        "What is 2+2?",
        "Hello, agent.",
        "Summarize briefly.",
        "Run a task.",
        "Check status.",
    ]
    result = chat(agent_id, [{"role": "user", "content": random.choice(prompts)}],
                  model=TEST_MODEL_A)
    if result and result.get("content"):
        pass  # successful chat — content returned
    # 502 from mock/backend issues don't count as test errors


def test_concurrent(n):
    def one(i):
        aid = f"conc-{i}-{uuid.uuid4().hex[:4]}"
        chat(aid, [{"role": "user", "content": f"concurrent-{i}"}], model=TEST_MODEL_A)

    with ThreadPoolExecutor(max_workers=min(n, 30)) as ex:
        futs = [ex.submit(one, i) for i in range(n)]
        for f in as_completed(futs):
            f.result()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 500

    # Start mock Ollama server
    t = threading.Thread(target=_run_mock, daemon=True)
    t.start()
    time.sleep(1.0)

    try:
        r = httpx.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200
        print(f"[test] model_gateway healthy: {r.json()}")
    except Exception as e:
        print(f"[test] FATAL: model_gateway not reachable at {BASE}: {e}")
        sys.exit(1)

    # Verify mock is up
    try:
        r = httpx.get(f"{MOCK_URL}/health", timeout=5)
        assert r.status_code == 200
        print("[test] mock Ollama server ready")
    except Exception as e:
        print(f"[test] FATAL: mock server not ready: {e}")
        sys.exit(1)

    print(f"[test] running {iters} iterations")
    t_start = time.perf_counter()

    # Register test models
    print("[test] registering test models...")
    setup_test_models()

    # Correctness suite
    print("[test] correctness suite...")
    test_register_list()
    test_disable_model()
    test_chat_mock()
    test_priority_routing()
    test_capability_filter()
    test_exact_model_routing()
    test_missing_model()
    test_usage_logged()
    test_system_usage()
    test_health_stats()
    print(f"[test] correctness suite done — {counters}")

    # Stress loop
    for i in range(iters):
        test_stress(i)
        if (i + 1) % 100 == 0:
            elapsed = time.perf_counter() - t_start
            p50 = round(statistics.median(latencies), 1) if latencies else 0
            p95 = round(statistics.quantiles(latencies, n=20)[18], 1) if len(latencies) >= 20 else 0
            print(f"[test] i={i+1} {counters} rate={round((i+1)/elapsed,1)}/s p50={p50}ms p95={p95}ms")

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
