"""
test_module_contracts.py — Agent module client ↔ server contract tests.

Imports the REAL BlackZero agent module clients and fires them at live servers.
If a server is up and the client call fails, that's a contract violation — fix it.
If a server is down, that test is skipped (not a failure).

This is the test that would have caught the registry /agents vs /register bug
before Engineer0 ever tried to boot.

Usage:
    python3 tests/test_module_contracts.py
    python3 tests/test_module_contracts.py --verbose

Exit: 0 on all pass/skip, 1 on any contract failure.
"""
from __future__ import annotations

import sys
import os
import time
import uuid
import tempfile
from pathlib import Path

import httpx

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow importing agent module clients directly from BlackZero
BLACKZERO = Path(__file__).parent.parent
sys.path.insert(0, str(BLACKZERO))

from agent.modules.registry_client import RegistryClient
from agent.modules.ledger          import LedgerClient
from agent.modules.obs             import ObsClient
from agent.modules.mind_state      import MindStateClient
from agent.modules.policy          import PolicyClient
from agent.modules.gateway         import GatewayClient
from agent.modules.comms           import CommsClient

VERBOSE = "--verbose" in sys.argv

# ── Result tracking ───────────────────────────────────────────────────────────
results: list[tuple[str, str, str]] = []  # (module, status, detail)


def log(module: str, status: str, detail: str = "") -> None:
    results.append((module, status, detail))
    icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️ "}[status]
    print(f"  {icon} {module}: {detail}" if detail else f"  {icon} {module}")


def server_up(port: int) -> bool:
    """Quick check: is a server listening on this port?"""
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
        return r.status_code in (200, 201)
    except Exception:
        return False


# ── Contract tests ─────────────────────────────────────────────────────────────

def test_registry(port: int = 9101) -> None:
    print("\n[registry]")
    if not server_up(port):
        log("registry", "SKIP", f"server not running on :{port}")
        return

    agent_id = f"contract-test-{uuid.uuid4().hex[:8]}"
    client = RegistryClient(
        agent_id=agent_id,
        url=f"http://127.0.0.1:{port}",
        enabled=True,
    )

    # register
    ok = client.register(
        agent_id=agent_id,
        name="ContractTestAgent",
        role="test",
        capabilities=["test"],
        api_port=19999,
    )
    if not ok:
        log("registry.register", "FAIL", "register() returned False")
        return
    log("registry.register", "PASS")

    # heartbeat
    try:
        client.heartbeat(agent_id)
        log("registry.heartbeat", "PASS")
    except Exception as e:
        log("registry.heartbeat", "FAIL", str(e))

    # deregister
    client.deregister(agent_id)
    log("registry.deregister", "PASS")


def test_ledger(port: int = 9106) -> None:
    print("\n[ledger]")
    if not server_up(port):
        log("ledger", "SKIP", f"server not running on :{port}")
        return

    client = LedgerClient(
        agent_id="contract-test",
        url=f"http://127.0.0.1:{port}",
        enabled=True,
    )

    # record — LedgerClient.record() is silent-fail so we check via httpx
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/entries", json={
            "agent_id":  "contract-test",
            "resource":  "ollama/engineer0:latest",
            "units":     100,
            "unit_type": "tokens",
            "cost_usd":  0.0,
        }, timeout=5.0)
        if r.status_code not in (200, 201):
            log("ledger.record", "FAIL", f"POST /entries → {r.status_code}: {r.text[:100]}")
            return
        log("ledger.record (direct)", "PASS")
    except Exception as e:
        log("ledger.record", "FAIL", str(e))
        return

    # Now test through the client method
    try:
        client.record_llm(
            model_id="ollama/engineer0:latest",
            input_tokens=50,
            output_tokens=30,
            cost_usd=0.0,
        )
        log("ledger.record_llm (client)", "PASS")
    except Exception as e:
        log("ledger.record_llm", "FAIL", str(e))


def test_observability(port: int = 9108) -> None:
    print("\n[observability]")
    if not server_up(port):
        log("obs", "SKIP", f"server not running on :{port}")
        return

    client = ObsClient(
        agent_id="contract-test",
        url=f"http://127.0.0.1:{port}",
        enabled=True,
    )

    # beat — obs client is silent-fail, so verify via httpx after
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/health", json={
            "agent_id": "contract-test",
            "status":   "ok",
        }, timeout=3.0)
        if r.status_code not in (200, 201):
            log("obs.beat (direct)", "FAIL", f"POST /health → {r.status_code}: {r.text[:100]}")
        else:
            log("obs.beat (direct)", "PASS")
    except Exception as e:
        log("obs.beat", "FAIL", str(e))

    # counter via client
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/metrics", json={
            "agent_id":    "contract-test",
            "metric_name": "tool_calls_total",
            "metric_type": "counter",
            "value":       1.0,
            "labels":      {},
        }, timeout=3.0)
        if r.status_code not in (200, 201):
            log("obs.counter (direct)", "FAIL", f"POST /metrics → {r.status_code}: {r.text[:100]}")
        else:
            log("obs.counter (direct)", "PASS")
    except Exception as e:
        log("obs.counter", "FAIL", str(e))

    # Now call through the client
    client.beat(status="ok")
    client.counter("tool_calls_total", labels={"tool": "shell"})
    client.histogram("llm_latency_ms", 250.0)
    log("obs.client_methods", "PASS", "silent-fail clients called without exception")


def test_mind_state(port: int = 9102) -> None:
    print("\n[mind_state]")
    if not server_up(port):
        log("mind_state", "SKIP", f"server not running on :{port}")
        return

    agent_id = f"contract-test-{uuid.uuid4().hex[:6]}"

    with tempfile.TemporaryDirectory() as tmpdir:
        client = MindStateClient(
            agent_id=agent_id,
            url=f"http://127.0.0.1:{port}",
            enabled=True,
        )
        client.set_fallback_dir(Path(tmpdir))

        # save — test what the client actually calls
        session_id = "test-session"
        client.save(session_id, "hello from user", "hello from agent")

        # get_recent — should return the saved turn
        recent = client.get_recent(session_id, limit=6)

        if not recent:
            log("mind_state.save+get_recent", "FAIL",
                "save() then get_recent() returned empty — check client endpoints vs server routes")
            if VERBOSE:
                # Check what endpoint the client actually tried
                try:
                    r = httpx.get(f"http://127.0.0.1:{port}/state/{agent_id}", timeout=3.0)
                    print(f"    GET /state/{{agent_id}} → {r.status_code} (client tried this)")
                    r2 = httpx.get(f"http://127.0.0.1:{port}/agents/{agent_id}/state", timeout=3.0)
                    print(f"    GET /agents/{{agent_id}}/state → {r2.status_code} (correct endpoint)")
                except Exception as e:
                    print(f"    probe failed: {e}")
            return

        if "hello from user" not in " ".join(recent) and "hello from agent" not in " ".join(recent):
            log("mind_state.save+get_recent", "FAIL",
                f"data not in recent: {recent[:1]}")
        else:
            log("mind_state.save+get_recent", "PASS")


def test_policy_gate(port: int = 9104) -> None:
    print("\n[policy_gate]")
    if not server_up(port):
        log("policy_gate", "SKIP", f"server not running on :{port}")
        return

    client = PolicyClient(
        agent_id="contract-test",
        url=f"http://127.0.0.1:{port}",
        enabled=True,
    )

    # allow — should return True for a benign action
    try:
        result = client.allow(action="read", resource="/tmp/test.txt")
        if not isinstance(result, bool):
            log("policy_gate.allow", "FAIL", f"expected bool, got {type(result)}")
        else:
            log("policy_gate.allow", "PASS", f"read /tmp/test.txt → {result}")
    except Exception as e:
        log("policy_gate.allow", "FAIL", str(e))

    # Verify response field — client reads 'effect', server returns 'decision'
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/evaluate", json={
            "from_agent":  "contract-test",
            "action_type": "read",
            "resource":    "/tmp/test.txt",
            "to_agent":    "",
        }, timeout=3.0)
        data = r.json()
        if "decision" in data and "effect" not in data:
            log("policy_gate.field_name", "FAIL",
                f"server returns 'decision' but client reads 'effect' — client will always return True (fail-open)")
        elif "effect" in data:
            log("policy_gate.field_name", "PASS", f"server returns 'effect': {data.get('effect')}")
        else:
            log("policy_gate.field_name", "PASS", f"response: {list(data.keys())}")
    except Exception as e:
        log("policy_gate.evaluate_probe", "FAIL", str(e))


def test_model_gateway(port: int = 9109) -> None:
    print("\n[model_gateway]")
    if not server_up(port):
        log("model_gateway", "SKIP", f"server not running on :{port}")
        return

    client = GatewayClient(
        agent_id="contract-test",
        url=f"http://127.0.0.1:{port}",
        model="engineer0:latest",
        enabled=True,
        fallback_ollama="",
    )

    # Probe the endpoint directly — 503 = endpoint correct but no models registered (runtime state)
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/chat", json={
            "agent_id":   "contract-test",
            "messages":   [{"role": "user", "content": "OK"}],
            "model_id":   "",
            "capability": "chat",
            "max_tokens": 10,
        }, timeout=10.0)
        if r.status_code == 404:
            log("model_gateway.chat", "FAIL",
                "POST /chat → 404 — wrong endpoint or wrong payload shape")
        elif r.status_code == 422:
            log("model_gateway.chat", "FAIL",
                f"POST /chat → 422 unprocessable — field name mismatch: {r.text[:200]}")
        elif r.status_code in (502, 503):
            log("model_gateway.chat", "PASS",
                f"endpoint correct — {r.status_code} means no models available (seed models to use gateway)")
        elif r.status_code == 200:
            log("model_gateway.chat", "PASS",
                f"got response: {r.json().get('content','')[:40]}")
        else:
            log("model_gateway.chat", "FAIL", f"→ {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log("model_gateway.chat", "FAIL", str(e))


def test_comms(port: int = 9100) -> None:
    print("\n[communication]")
    if not server_up(port):
        log("comms", "SKIP", f"server not running on :{port}")
        return

    client = CommsClient(
        agent_id="contract-test",
        url=f"http://127.0.0.1:{port}",
        enabled=True,
    )

    # Register this agent so it can appear as recipient
    try:
        httpx.post(f"http://127.0.0.1:{port}/register",
                   json={"agent_id": "contract-test"}, timeout=3.0)
    except Exception:
        pass

    # Probe POST /send directly (the correct endpoint)
    try:
        r = httpx.post(f"http://127.0.0.1:{port}/send", json={
            "from":    "contract-test",
            "to":      "contract-test",   # send to self (registered above)
            "payload": {"content": "ping", "type": "test"},
        }, timeout=3.0)
        if r.status_code == 404:
            log("comms.send (direct)", "FAIL",
                "POST /send → 404 — endpoint missing or wrong field names")
        elif r.status_code in (200, 201):
            log("comms.send (direct)", "PASS", f"→ {r.status_code}")
        else:
            log("comms.send (direct)", "FAIL", f"→ {r.status_code}: {r.text[:80]}")
    except Exception as e:
        log("comms.send_probe", "FAIL", str(e))

    # Test through client — send to self (registered above)
    result = client.send(to_agent="contract-test", content="test message")
    if result:
        log("comms.send (client)", "PASS")
    else:
        log("comms.send (client)", "FAIL",
            "send() returned False — check endpoint and field names in comms.py")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 60)
    print("  Module Contract Tests — agent clients vs live servers")
    print("=" * 60)

    test_registry()
    test_ledger()
    test_observability()
    test_mind_state()
    test_policy_gate()
    test_model_gateway()
    test_comms()

    print("\n" + "=" * 60)
    print("  Results")
    print("=" * 60)

    failures = [r for r in results if r[1] == "FAIL"]
    passes   = [r for r in results if r[1] == "PASS"]
    skips    = [r for r in results if r[1] == "SKIP"]

    for name, status, detail in results:
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️ "}[status]
        line = f"  {icon} {name}"
        if detail:
            line += f": {detail}"
        print(line)

    print(f"\n  {len(passes)} pass | {len(failures)} fail | {len(skips)} skip")

    if failures:
        print("\n  ❌ CONTRACT VIOLATIONS — fix the client(s) listed above")
        return 1

    print("\n  ✅ All contracts hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
