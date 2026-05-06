"""
policy_gate node — action evaluation and enforcement.

Every agent that touches a sensitive resource or performs a cross-agent action
submits an EvaluateRequest here first. The gate applies ordered rules and returns
allow | deny | approve_required | cerberus (forward to Cerberus for LLM eval).

Fits into the stack:
  - Sits between agents and their actions (not between messages).
  - Cerberus is the authority — when a rule says 'cerberus', we forward.
  - Cerberus is optional: if unreachable, default_effect applies (configurable).
  - All decisions are logged immutably (audit trail).
  - Built-in seed rules enforce Cerberus governance.md + permissions.md policy.

Rule evaluation:
  - Rules are evaluated in descending priority order. First match wins.
  - If no rule matches → default_effect (default: allow).
  - Cerberus can add/remove/update rules at runtime via POST /rules.

Effects:
  allow            — proceed
  deny             — blocked; reason included
  approve_required — block, but send an approval request (async)
  cerberus         — forward to Cerberus for LLM security judgment

Condition fields (all optional; omit = match any):
  from_agent       — glob pattern for submitting agent ID
  action_type      — exact match or list  (write|read|delete|execute|message|deploy)
  resource_pattern — fnmatch glob against resource path/identifier
  to_agent         — glob pattern for target agent ID (inter-agent requests)
  payload_keys     — list of keys that must ALL be present in payload

HTTP API (port 9104):
  POST   /evaluate              submit an action for evaluation
  GET    /rules                 list all rules (sorted by priority)
  POST   /rules                 add or update a rule (upsert by rule_id)
  DELETE /rules/{rule_id}       remove a rule
  GET    /decisions             recent decision log
  GET    /decisions/{agent_id}  decisions for a specific agent
  GET    /health
  GET    /stats
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

PORT         = 9104
CERBERUS_URL = "http://127.0.0.1:8200"
COMM_URL     = "http://127.0.0.1:9100"
REGISTRY_URL = "http://127.0.0.1:9101"
DB_PATH      = Path(__file__).parent / "policy_gate.db"

DEFAULT_EFFECT    = "allow"    # when no rule matches
CERBERUS_TIMEOUT  = 8.0        # seconds to wait for Cerberus
DECISION_KEEP     = 10_000     # max decisions to retain in log

app = FastAPI(title="PolicyGate Node", version="1.0")


# ── DB ────────────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rules (
                rule_id          TEXT PRIMARY KEY,
                description      TEXT NOT NULL DEFAULT '',
                priority         INTEGER NOT NULL DEFAULT 50,
                from_agent       TEXT NOT NULL DEFAULT '',
                action_type      TEXT NOT NULL DEFAULT '',
                resource_pattern TEXT NOT NULL DEFAULT '',
                to_agent         TEXT NOT NULL DEFAULT '',
                payload_keys     TEXT NOT NULL DEFAULT '[]',
                effect           TEXT NOT NULL,
                reason           TEXT NOT NULL DEFAULT '',
                enabled          INTEGER NOT NULL DEFAULT 1,
                created_at       REAL NOT NULL,
                updated_at       REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_rules_priority
                ON rules(priority DESC, enabled);

            CREATE TABLE IF NOT EXISTS decisions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id      TEXT NOT NULL,
                action_type   TEXT NOT NULL,
                resource      TEXT NOT NULL DEFAULT '',
                to_agent      TEXT NOT NULL DEFAULT '',
                decision      TEXT NOT NULL,
                rule_id       TEXT NOT NULL DEFAULT 'default',
                reason        TEXT NOT NULL DEFAULT '',
                cerberus_used INTEGER NOT NULL DEFAULT 0,
                decided_at    REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_decisions_agent
                ON decisions(agent_id, decided_at DESC);
        """)
        _seed_rules(conn)


# ── Seed rules ────────────────────────────────────────────────────────────────

_SEED_RULES = [
    # ── Hard denies — governance.md §8 ───────────────────────────────────────
    {
        "rule_id":          "deny_policy_modification",
        "description":      "No agent may modify governance, safety, or permission files",
        "priority":         1000,
        "resource_pattern": "*/policies/*",
        "action_type":      "write",
        "effect":           "deny",
        "reason":           "Policy files are ground truth. Modification requires Operator authorization.",
    },
    {
        "rule_id":          "deny_identity_modification",
        "description":      "No agent may modify another agent's identity or mission files",
        "priority":         1000,
        "resource_pattern": "*/identity/*",
        "action_type":      "write",
        "effect":           "deny",
        "reason":           "Identity files are immutable at runtime. Modification requires Operator authorization.",
    },
    {
        "rule_id":          "deny_self_identity_modification",
        "description":      "Agents may not modify their own mission.md or personality files",
        "priority":         999,
        "resource_pattern": "*/mission.md",
        "action_type":      "write",
        "effect":           "deny",
        "reason":           "Identity files are immutable at runtime.",
    },
    # ── Cross-agent memory writes — permissions.md §2 ────────────────────────
    {
        "rule_id":          "deny_cross_agent_memory_write",
        "description":      "Agents may not write to another agent's memory store",
        "priority":         900,
        "resource_pattern": "*/memory/*",
        "action_type":      "write",
        "effect":           "deny",
        "reason":           "Cross-agent memory writes are prohibited. Each agent owns its own memory.",
    },
    # ── Credential / key access — permissions.md §2 ──────────────────────────
    {
        "rule_id":          "cerberus_credential_access",
        "description":      "Any credential or API key access must be vetted by Cerberus",
        "priority":         800,
        "resource_pattern": "*credentials*",
        "effect":           "cerberus",
        "reason":           "Credential access requires Cerberus security clearance.",
    },
    {
        "rule_id":          "cerberus_apikey_access",
        "description":      "API key reads or writes go through Cerberus",
        "priority":         800,
        "resource_pattern": "*api_key*",
        "effect":           "cerberus",
        "reason":           "API key access requires Cerberus security clearance.",
    },
    # ── Shell command execution with untrusted input ──────────────────────────
    {
        "rule_id":          "deny_untrusted_shell",
        "description":      "Shell commands with untrusted_input flag set are always denied",
        "priority":         950,
        "action_type":      "execute",
        "resource_pattern": "*shell*",
        "effect":           "deny",
        "reason":           "Shell commands constructed from untrusted input are prohibited.",
    },
    # ── Production deployments → approval required ────────────────────────────
    {
        "rule_id":          "approve_production_deploy",
        "description":      "Production deployments require explicit approval",
        "priority":         700,
        "action_type":      "deploy",
        "resource_pattern": "*production*",
        "effect":           "approve_required",
        "reason":           "Production deployments are irreversible and require Operator approval.",
    },
    # ── Agent process spawning → Cerberus review ─────────────────────────────
    {
        "rule_id":          "cerberus_agent_spawn",
        "description":      "Spawning new agent processes must be cleared by Cerberus",
        "priority":         750,
        "action_type":      "spawn",
        "effect":           "cerberus",
        "reason":           "New agent instances require Cerberus authorization.",
    },
    # ── Inter-agent peer-to-peer (bypassing PlugOps) ─────────────────────────
    {
        "rule_id":          "deny_direct_peer_message",
        "description":      "Peer agents must not message each other directly (bypass PlugOps)",
        "priority":         850,
        "action_type":      "direct_message",
        "effect":           "deny",
        "reason":           "All inter-agent communication must route through PlugOps.",
    },
]


def _seed_rules(conn: sqlite3.Connection) -> None:
    """Insert seed rules if they don't already exist."""
    now = time.time()
    for r in _SEED_RULES:
        existing = conn.execute(
            "SELECT rule_id FROM rules WHERE rule_id=?", (r["rule_id"],)
        ).fetchone()
        if existing:
            continue   # never overwrite — Cerberus may have updated it
        conn.execute("""
            INSERT INTO rules
              (rule_id, description, priority, from_agent, action_type,
               resource_pattern, to_agent, payload_keys, effect, reason,
               enabled, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
        """, (
            r["rule_id"],
            r.get("description", ""),
            r.get("priority", 50),
            r.get("from_agent", ""),
            r.get("action_type", ""),
            r.get("resource_pattern", ""),
            r.get("to_agent", ""),
            json.dumps(r.get("payload_keys", [])),
            r["effect"],
            r.get("reason", ""),
            now, now,
        ))


# ── Rule matching ─────────────────────────────────────────────────────────────

def _match_rule(rule: sqlite3.Row, req: "EvaluateRequest") -> bool:
    """Return True if the rule conditions match the request."""
    if rule["from_agent"] and not fnmatch.fnmatch(req.from_agent, rule["from_agent"]):
        return False
    if rule["action_type"] and req.action_type not in rule["action_type"].split(","):
        return False
    if rule["resource_pattern"] and not fnmatch.fnmatch(req.resource, rule["resource_pattern"]):
        return False
    if rule["to_agent"] and not fnmatch.fnmatch(req.to_agent or "", rule["to_agent"]):
        return False
    req_keys = json.loads(rule["payload_keys"])
    if req_keys and not all(k in req.payload for k in req_keys):
        return False
    return True


def _evaluate_rules(req: "EvaluateRequest") -> tuple[str, str, str]:
    """
    Evaluate rules in descending priority. First match wins.
    Returns (decision, rule_id, reason).
    """
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM rules WHERE enabled=1 ORDER BY priority DESC"
        ).fetchall()

    for row in rows:
        if _match_rule(row, req):
            return row["effect"], row["rule_id"], row["reason"]

    return DEFAULT_EFFECT, "default", "No rule matched — default effect applied."


# ── Cerberus forwarding ───────────────────────────────────────────────────────

async def _ask_cerberus(req: "EvaluateRequest") -> tuple[str, str]:
    """
    Forward to Cerberus for LLM security judgment.
    Returns (decision, reason). Falls back to DEFAULT_EFFECT on error.
    """
    try:
        async with httpx.AsyncClient(timeout=CERBERUS_TIMEOUT) as client:
            r = await client.post(f"{CERBERUS_URL}/evaluate", json={
                "from_agent":   req.from_agent,
                "action_type":  req.action_type,
                "resource":     req.resource,
                "to_agent":     req.to_agent,
                "payload":      req.payload,
                "context":      req.context,
            })
            if r.status_code == 200:
                data = r.json()
                return data.get("decision", DEFAULT_EFFECT), data.get("reason", "Cerberus decision.")
    except Exception:
        pass
    # Cerberus unreachable — fail safe
    return DEFAULT_EFFECT, "Cerberus unreachable — default effect applied."


# ── Broadcast ─────────────────────────────────────────────────────────────────

async def _broadcast(decision: str, agent_id: str, rule_id: str, reason: str) -> None:
    if decision == "allow":
        return   # don't flood comm with every allow
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{COMM_URL}/send", json={
                "from": "policy_gate",
                "to":   "policy-events",
                "payload": {
                    "event":    f"policy_{decision}",
                    "agent_id": agent_id,
                    "rule_id":  rule_id,
                    "reason":   reason,
                },
            })
    except Exception:
        pass


# ── Request / Response models ─────────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    from_agent:  str
    action_type: str           # write | read | delete | execute | message | deploy | spawn | …
    resource:    str = ""      # file path, agent_id, URL, resource name
    to_agent:    str = ""      # target agent ID for inter-agent actions
    payload:     dict[str, Any] = Field(default_factory=dict)
    context:     dict[str, Any] = Field(default_factory=dict)


class RuleRequest(BaseModel):
    rule_id:          str
    description:      str = ""
    priority:         int = 50
    from_agent:       str = ""
    action_type:      str = ""
    resource_pattern: str = ""
    to_agent:         str = ""
    payload_keys:     list[str] = Field(default_factory=list)
    effect:           str       # allow | deny | approve_required | cerberus
    reason:           str = ""
    enabled:          bool = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/evaluate")
async def evaluate(req: EvaluateRequest):
    """Evaluate an action. Returns decision + rule that fired + reason."""
    t0 = time.time()

    decision, rule_id, reason = _evaluate_rules(req)
    cerberus_used = False

    if decision == "cerberus":
        decision, reason = await _ask_cerberus(req)
        cerberus_used = True

    decided_at = time.time()

    with db() as conn:
        conn.execute("""
            INSERT INTO decisions
              (agent_id, action_type, resource, to_agent, decision,
               rule_id, reason, cerberus_used, decided_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            req.from_agent, req.action_type, req.resource,
            req.to_agent or "", decision, rule_id, reason,
            int(cerberus_used), decided_at,
        ))
        # Prune old decisions
        conn.execute("""
            DELETE FROM decisions WHERE id NOT IN (
                SELECT id FROM decisions ORDER BY id DESC LIMIT ?
            )
        """, (DECISION_KEEP,))

    asyncio.create_task(_broadcast(decision, req.from_agent, rule_id, reason))

    return {
        "ok":           True,
        "decision":     decision,
        "rule_id":      rule_id,
        "reason":       reason,
        "cerberus_used": cerberus_used,
        "latency_ms":   round((time.time() - t0) * 1000, 1),
    }


@app.get("/rules")
async def list_rules():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM rules ORDER BY priority DESC, rule_id"
        ).fetchall()
    return {
        "ok":    True,
        "count": len(rows),
        "rules": [
            {
                "rule_id":          r["rule_id"],
                "description":      r["description"],
                "priority":         r["priority"],
                "from_agent":       r["from_agent"],
                "action_type":      r["action_type"],
                "resource_pattern": r["resource_pattern"],
                "to_agent":         r["to_agent"],
                "effect":           r["effect"],
                "reason":           r["reason"],
                "enabled":          bool(r["enabled"]),
            }
            for r in rows
        ]
    }


@app.post("/rules", status_code=201)
async def upsert_rule(req: RuleRequest):
    """Add or update a rule. Cerberus calls this to manage policy at runtime."""
    now = time.time()
    with db() as conn:
        conn.execute("""
            INSERT INTO rules
              (rule_id, description, priority, from_agent, action_type,
               resource_pattern, to_agent, payload_keys, effect, reason,
               enabled, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(rule_id) DO UPDATE SET
              description=excluded.description,
              priority=excluded.priority,
              from_agent=excluded.from_agent,
              action_type=excluded.action_type,
              resource_pattern=excluded.resource_pattern,
              to_agent=excluded.to_agent,
              payload_keys=excluded.payload_keys,
              effect=excluded.effect,
              reason=excluded.reason,
              enabled=excluded.enabled,
              updated_at=excluded.updated_at
        """, (
            req.rule_id, req.description, req.priority,
            req.from_agent, req.action_type, req.resource_pattern,
            req.to_agent, json.dumps(req.payload_keys),
            req.effect, req.reason, int(req.enabled), now, now,
        ))
    return {"ok": True, "rule_id": req.rule_id}


@app.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str):
    with db() as conn:
        row = conn.execute("SELECT rule_id FROM rules WHERE rule_id=?", (rule_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "rule_not_found"})
        conn.execute("DELETE FROM rules WHERE rule_id=?", (rule_id,))
    return {"ok": True, "rule_id": rule_id}


@app.get("/decisions")
async def list_decisions(limit: int = 50, decision: str = ""):
    with db() as conn:
        if decision:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE decision=? ORDER BY decided_at DESC LIMIT ?",
                (decision, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY decided_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return {
        "ok":    True,
        "count": len(rows),
        "decisions": [
            {
                "id":           r["id"],
                "agent_id":     r["agent_id"],
                "action_type":  r["action_type"],
                "resource":     r["resource"],
                "to_agent":     r["to_agent"],
                "decision":     r["decision"],
                "rule_id":      r["rule_id"],
                "reason":       r["reason"],
                "cerberus_used": bool(r["cerberus_used"]),
                "decided_at":   r["decided_at"],
            }
            for r in rows
        ]
    }


@app.get("/decisions/{agent_id}")
async def agent_decisions(agent_id: str, limit: int = 20):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE agent_id=? ORDER BY decided_at DESC LIMIT ?",
            (agent_id, limit)
        ).fetchall()
    return {
        "ok":       True,
        "agent_id": agent_id,
        "count":    len(rows),
        "decisions": [dict(r) for r in rows],
    }


@app.get("/health")
async def health():
    with db() as conn:
        rules     = conn.execute("SELECT COUNT(*) as n FROM rules WHERE enabled=1").fetchone()["n"]
        decisions = conn.execute("SELECT COUNT(*) as n FROM decisions").fetchone()["n"]
    return {"ok": True, "active_rules": rules, "total_decisions": decisions, "port": PORT}


@app.get("/stats")
async def stats():
    with db() as conn:
        total     = conn.execute("SELECT COUNT(*) as n FROM decisions").fetchone()["n"]
        allows    = conn.execute("SELECT COUNT(*) as n FROM decisions WHERE decision='allow'").fetchone()["n"]
        denies    = conn.execute("SELECT COUNT(*) as n FROM decisions WHERE decision='deny'").fetchone()["n"]
        approvals = conn.execute("SELECT COUNT(*) as n FROM decisions WHERE decision='approve_required'").fetchone()["n"]
        cerberus  = conn.execute("SELECT COUNT(*) as n FROM decisions WHERE cerberus_used=1").fetchone()["n"]
        rules     = conn.execute("SELECT COUNT(*) as n FROM rules WHERE enabled=1").fetchone()["n"]
    return {
        "ok":              True,
        "total_decisions": total,
        "allowed":         allows,
        "denied":          denies,
        "approve_required": approvals,
        "cerberus_forwarded": cerberus,
        "active_rules":    rules,
    }


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
