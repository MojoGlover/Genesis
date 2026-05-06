"""
PolicyGate module stress test.

Tests:
  1.  Seed rules — verify all 9 governance rules are present at startup
  2.  Allow — normal, non-sensitive action passes
  3.  Deny — policy file write is denied (seed rule fires)
  4.  Deny — cross-agent memory write is denied
  5.  Deny — direct_message action is denied
  6.  Approve_required — production deploy triggers approval flag
  7.  Cerberus path — action that would forward to Cerberus (offline Cerberus → default)
  8.  Custom rule CRUD — add / override / delete a rule at runtime
  9.  Rule priority — higher-priority rule wins over lower-priority for same resource
  10. Decision log — decisions are recorded with correct fields
  11. Stats consistency — allow+deny+approve+cerberus = total
  12. Concurrent evaluations (flood)

Usage:
  python3 test_policy_gate.py [iterations]   default: 500
"""
from __future__ import annotations

import sys
import time
import uuid
import threading
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

BASE    = "http://127.0.0.1:9104"
TIMEOUT = 10.0

counters = {
    "evaluate_ok":    0,
    "allow_ok":       0,
    "deny_ok":        0,
    "approve_ok":     0,
    "rule_ok":        0,
    "decision_ok":    0,
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

def evaluate(from_agent, action_type, resource="", to_agent="", payload=None, context=None):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/evaluate",
            json={
                "from_agent":  from_agent,
                "action_type": action_type,
                "resource":    resource,
                "to_agent":    to_agent or "",
                "payload":     payload or {},
                "context":     context or {},
            },
            timeout=TIMEOUT,
        ))
        if r.status_code == 200:
            inc("evaluate_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def add_rule(rule_id, effect, priority=50, from_agent="", action_type="",
             resource_pattern="", to_agent="", reason="", enabled=True):
    try:
        r = timed(lambda: httpx.post(
            f"{BASE}/rules",
            json={
                "rule_id":          rule_id,
                "effect":           effect,
                "priority":         priority,
                "from_agent":       from_agent,
                "action_type":      action_type,
                "resource_pattern": resource_pattern,
                "to_agent":         to_agent,
                "reason":           reason,
                "enabled":          enabled,
            },
            timeout=TIMEOUT,
        ))
        if r.status_code == 201:
            inc("rule_ok")
            return r.json()
        inc("errors")
    except Exception:
        inc("errors")
    return None


def delete_rule(rule_id):
    try:
        r = httpx.delete(f"{BASE}/rules/{rule_id}", timeout=TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


def list_rules():
    try:
        r = httpx.get(f"{BASE}/rules", timeout=TIMEOUT)
        return r.json().get("rules", []) if r.status_code == 200 else []
    except Exception:
        return []


def decisions(limit=20, decision=""):
    try:
        params = {"limit": limit}
        if decision:
            params["decision"] = decision
        r = timed(lambda: httpx.get(f"{BASE}/decisions", params=params, timeout=TIMEOUT))
        if r.status_code == 200:
            inc("decision_ok")
            return r.json().get("decisions", [])
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


# ── Test cases ────────────────────────────────────────────────────────────────

def test_seed_rules_present():
    """All governance seed rules must be present at startup."""
    rules = list_rules()
    rule_ids = {r["rule_id"] for r in rules}

    required = {
        "deny_policy_modification",
        "deny_identity_modification",
        "deny_self_identity_modification",
        "deny_cross_agent_memory_write",
        "cerberus_credential_access",
        "cerberus_apikey_access",
        "deny_untrusted_shell",
        "approve_production_deploy",
        "cerberus_agent_spawn",
        "deny_direct_peer_message",
    }
    missing = required - rule_ids
    if missing:
        print(f"[test] MISSING seed rules: {missing}")
        inc("integrity_fail")


def test_allow_normal():
    """Normal, non-sensitive write action should be allowed by default."""
    result = evaluate("engineer0", "write", resource="/tmp/output.txt")
    if not result or result.get("decision") != "allow":
        inc("integrity_fail")
    else:
        inc("allow_ok")


def test_deny_policy_file():
    """Writing to a policy file must be denied."""
    result = evaluate("engineer0", "write", resource="/home/user/agent/policies/security.md")
    if not result or result.get("decision") != "deny":
        inc("integrity_fail")
    else:
        inc("deny_ok")


def test_deny_identity_file():
    """Writing to an identity file must be denied."""
    result = evaluate("ceo", "write", resource="/ai/agents/madjanet/identity/mission.md")
    if not result or result.get("decision") != "deny":
        inc("integrity_fail")
    else:
        inc("deny_ok")


def test_deny_cross_agent_memory():
    """Writing to another agent's memory must be denied."""
    result = evaluate("ceo", "write", resource="/ai/agents/cerberus/memory/recall.db")
    if not result or result.get("decision") != "deny":
        inc("integrity_fail")
    else:
        inc("deny_ok")


def test_deny_direct_message():
    """Direct (non-PlugOps) peer messages must be denied."""
    result = evaluate("accountant", "direct_message", to_agent="engineer0")
    if not result or result.get("decision") != "deny":
        inc("integrity_fail")
    else:
        inc("deny_ok")


def test_approve_required_deploy():
    """Production deploy must return approve_required."""
    result = evaluate("engineer0", "deploy", resource="production-cloud-run")
    if not result or result.get("decision") != "approve_required":
        inc("integrity_fail")
    else:
        inc("approve_ok")


def test_cerberus_credential():
    """Credential access triggers cerberus effect (Cerberus offline → default allow)."""
    result = evaluate("engineer0", "read", resource="/vault/credentials/openai_key")
    if not result:
        inc("integrity_fail")
        return
    # Cerberus is offline in test — default effect is allow
    if result.get("decision") not in ("allow", "deny", "cerberus"):
        inc("integrity_fail")
    # cerberus_used could be True or False depending on whether Cerberus is reachable


def test_custom_rule_crud(i):
    """Add a high-priority deny rule → verify it fires → delete it → verify reverted."""
    rule_id  = f"test-deny-{i}-{uuid.uuid4().hex[:6]}"
    agent_id = f"test-agent-{i}"

    # Normal allow first
    r1 = evaluate(agent_id, "read", resource="/tmp/test.txt")
    if not r1 or r1.get("decision") != "allow":
        inc("integrity_fail")
        return

    # Add deny rule for this agent
    add_rule(
        rule_id=rule_id,
        effect="deny",
        priority=999,
        from_agent=agent_id,
        action_type="read",
        resource_pattern="/tmp/*",
        reason="Test deny rule",
    )

    # Should now be denied
    r2 = evaluate(agent_id, "read", resource="/tmp/test.txt")
    if not r2 or r2.get("decision") != "deny":
        inc("integrity_fail")
        delete_rule(rule_id)
        return

    # Delete the rule
    delete_rule(rule_id)

    # Should revert to allow
    r3 = evaluate(agent_id, "read", resource="/tmp/test.txt")
    if not r3 or r3.get("decision") != "allow":
        inc("integrity_fail")


def test_rule_priority():
    """Higher-priority rule wins over lower-priority for same condition."""
    agent_id = f"priority-test-{uuid.uuid4().hex[:6]}"
    low_id   = f"low-{uuid.uuid4().hex[:4]}"
    high_id  = f"high-{uuid.uuid4().hex[:4]}"

    # Low priority allow
    add_rule(low_id,  effect="allow", priority=10, from_agent=agent_id,
             action_type="execute", resource_pattern="*/cmd/*")
    # High priority deny
    add_rule(high_id, effect="deny",  priority=900, from_agent=agent_id,
             action_type="execute", resource_pattern="*/cmd/*", reason="High-pri deny")

    result = evaluate(agent_id, "execute", resource="/bin/cmd/run.sh")
    if not result or result.get("decision") != "deny":
        inc("integrity_fail")
    if result and result.get("rule_id") != high_id:
        inc("integrity_fail")

    delete_rule(low_id)
    delete_rule(high_id)


def test_decision_log():
    """Decisions are recorded and retrievable."""
    agent_id = f"log-test-{uuid.uuid4().hex[:6]}"
    evaluate(agent_id, "write", resource="/ai/policies/x.md")  # should deny

    d = decisions()
    # Find our deny decision
    found = [x for x in d if x["agent_id"] == agent_id and x["decision"] == "deny"]
    if not found:
        inc("integrity_fail")


def test_stats_consistency():
    """allow + deny + approve_required should equal total (cerberus_forwarded may overlap)."""
    s = stats()
    if not s or not s.get("ok"):
        inc("integrity_fail")
        return
    total = s.get("total_decisions", 0)
    parts = s.get("allowed", 0) + s.get("denied", 0) + s.get("approve_required", 0)
    if total > 0 and parts != total:
        inc("integrity_fail")


def test_evaluate_stress(i):
    """
    Fast CRUD-style evaluation. Alternates allow/deny to exercise both paths.
    """
    agent_id = f"stress-{i % 20}"  # reuse 20 agent IDs

    if i % 3 == 0:
        # Allow case
        result = evaluate(agent_id, "read", resource="/tmp/data.json")
        if result and result.get("decision") == "allow":
            inc("allow_ok")
        elif result:
            inc("integrity_fail")
        else:
            inc("errors")
    elif i % 3 == 1:
        # Deny case
        result = evaluate(agent_id, "write", resource="/ai/policies/test.md")
        if result and result.get("decision") == "deny":
            inc("deny_ok")
        elif result:
            inc("integrity_fail")
        else:
            inc("errors")
    else:
        # Approve_required case
        result = evaluate(agent_id, "deploy", resource="production-api")
        if result and result.get("decision") == "approve_required":
            inc("approve_ok")
        elif result:
            inc("integrity_fail")
        else:
            inc("errors")


def test_concurrent_evaluations(n):
    """N simultaneous evaluations — no errors, no integrity failures."""
    def one(i):
        agent_id = f"conc-{i}"
        evaluate(agent_id, "read", resource="/tmp/concurrent.txt")
        evaluate(agent_id, "write", resource="/ai/policies/concurrent.md")

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
        print(f"[test] policy_gate healthy: {r.json()}")
    except Exception as e:
        print(f"[test] FATAL: policy_gate not reachable at {BASE}: {e}")
        sys.exit(1)

    print(f"[test] running {iters} iterations")
    t_start = time.perf_counter()

    # Correctness suite
    print("[test] correctness suite...")
    test_seed_rules_present()
    test_allow_normal()
    test_deny_policy_file()
    test_deny_identity_file()
    test_deny_cross_agent_memory()
    test_deny_direct_message()
    test_approve_required_deploy()
    test_cerberus_credential()
    test_rule_priority()
    test_decision_log()
    test_stats_consistency()
    print(f"[test] correctness suite done — {counters}")

    # Main loop — mixed evaluate stress
    for i in range(iters):
        test_evaluate_stress(i)
        if i % 2 == 0:
            test_custom_rule_crud(i)
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
    print(f"[test] concurrent flood: {flood_n} agent pairs")
    test_concurrent_evaluations(flood_n)

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
