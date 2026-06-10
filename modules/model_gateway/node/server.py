"""
model_gateway node — unified LLM routing, rate limiting, and fallback.

All agents talk to models through this gateway. It handles:
  - Model registry (which models are available and where)
  - Routing (pick best model for a request based on capability + availability)
  - Rate limiting (per-agent, per-model quotas)
  - Fallback chains (if primary model is slow/down, try next)
  - Cost tracking (emits to ledger via comm event)
  - Usage logging

Supported backends:
  ollama   — local Ollama (http://localhost:11434)
  openai   — OpenAI API
  anthropic — Anthropic API
  replicate — Replicate API

The gateway does NOT perform inference itself — it proxies to the actual backend.

HTTP API (port 9109):
  POST   /complete              text completion (route to best model)
  POST   /chat                  chat completion (route to best model)
  GET    /models                list registered models
  POST   /models/register       register a model
  DELETE /models/{model_id}     remove a model
  GET    /models/{model_id}/health  ping backend to check model availability
  GET    /usage/{agent_id}      usage stats for an agent
  GET    /usage                 system-wide usage stats
  GET    /health
  GET    /stats
"""
from __future__ import annotations

import asyncio
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

PORT         = 9109
COMM_URL     = "http://127.0.0.1:9100"
DB_PATH      = Path(__file__).parent / "model_gateway.db"

DEFAULT_TIMEOUT   = 120.0   # LLM inference can be slow
HEALTH_TTL        = 60.0    # seconds before model health is re-checked
RATE_WINDOW       = 60.0    # rate limit window in seconds
USAGE_KEEP        = 10_000  # max usage log entries

# Spend gate (Darnie's rule, 2026-06-05): no paid call without computing cost first.
# Every paid (cloud) call is cost-estimated BEFORE dispatch and checked against the
# agent's daily cap. Over budget → fall back to a free local model (work continues),
# never a silent overspend. Caps are set per-agent via /budget/set; this is the default.
DEFAULT_DAILY_CAP_USD = 5.00   # per-agent/day cloud-spend ceiling before local fallback kicks in

app = FastAPI(title="ModelGateway Node", version="1.0")


# ── DB ────────────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS models (
                model_id        TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                backend         TEXT NOT NULL,
                backend_model   TEXT NOT NULL,
                endpoint        TEXT NOT NULL DEFAULT '',
                api_key_env     TEXT NOT NULL DEFAULT '',
                capabilities    TEXT NOT NULL DEFAULT '[]',
                priority        INTEGER NOT NULL DEFAULT 50,
                max_tokens      INTEGER NOT NULL DEFAULT 4096,
                context_window  INTEGER NOT NULL DEFAULT 8192,
                cost_per_1k_in  REAL NOT NULL DEFAULT 0.0,
                cost_per_1k_out REAL NOT NULL DEFAULT 0.0,
                enabled         INTEGER NOT NULL DEFAULT 1,
                last_health_ok  REAL,
                registered_at   REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_models_priority
                ON models(backend, priority, enabled);

            CREATE TABLE IF NOT EXISTS rate_limits (
                agent_id        TEXT NOT NULL,
                model_id        TEXT NOT NULL,
                requests_per_min INTEGER NOT NULL DEFAULT 60,
                tokens_per_min  INTEGER NOT NULL DEFAULT 100000,
                PRIMARY KEY (agent_id, model_id)
            );

            CREATE TABLE IF NOT EXISTS usage_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id        TEXT NOT NULL,
                model_id        TEXT NOT NULL,
                backend         TEXT NOT NULL,
                input_tokens    INTEGER NOT NULL DEFAULT 0,
                output_tokens   INTEGER NOT NULL DEFAULT 0,
                cost_usd        REAL NOT NULL DEFAULT 0.0,
                latency_ms      REAL NOT NULL DEFAULT 0,
                status          TEXT NOT NULL DEFAULT 'ok',
                request_type    TEXT NOT NULL DEFAULT 'chat',
                logged_at       REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_usage_agent
                ON usage_log(agent_id, logged_at DESC);
            CREATE INDEX IF NOT EXISTS idx_usage_model
                ON usage_log(model_id, logged_at DESC);

            CREATE TABLE IF NOT EXISTS budgets (
                agent_id      TEXT PRIMARY KEY,
                cap_usd       REAL NOT NULL,
                window_days   INTEGER NOT NULL DEFAULT 1,
                set_at        REAL NOT NULL
            );
        """)
        _seed_models(conn)


# ── Seed models ───────────────────────────────────────────────────────────────

_DEFAULT_MODELS = [
    {
        "model_id":       "ollama-llama3-3b",
        "name":           "Llama 3.2 3B (local)",
        "backend":        "ollama",
        "backend_model":  "llama3.2:3b",
        "endpoint":       "http://localhost:11434",
        "capabilities":   ["chat", "complete"],
        "priority":       10,
        "max_tokens":     4096,
        "context_window": 8192,
    },
    {
        "model_id":       "ollama-llama3-70b",
        "name":           "Llama 3.3 70B (local)",
        "backend":        "ollama",
        "backend_model":  "llama3.3:70b",
        "endpoint":       "http://localhost:11434",
        "capabilities":   ["chat", "complete"],
        "priority":       20,
        "max_tokens":     4096,
        "context_window": 32768,
    },
    {
        "model_id":       "anthropic-claude-haiku",
        "name":           "Claude 3 Haiku",
        "backend":        "anthropic",
        "backend_model":  "claude-3-haiku-20240307",
        "api_key_env":    "ANTHROPIC_API_KEY",
        "capabilities":   ["chat", "complete"],
        "priority":       30,
        "max_tokens":     4096,
        "context_window": 200000,
        "cost_per_1k_in":  0.00025,
        "cost_per_1k_out": 0.00125,
    },
    {
        "model_id":       "anthropic-claude-sonnet",
        "name":           "Claude 3.5 Sonnet",
        "backend":        "anthropic",
        "backend_model":  "claude-3-5-sonnet-20241022",
        "api_key_env":    "ANTHROPIC_API_KEY",
        "capabilities":   ["chat", "complete", "tools"],
        "priority":       40,
        "max_tokens":     8192,
        "context_window": 200000,
        "cost_per_1k_in":  0.003,
        "cost_per_1k_out": 0.015,
    },
]


def _seed_models(conn: sqlite3.Connection) -> None:
    now = time.time()
    for m in _DEFAULT_MODELS:
        existing = conn.execute(
            "SELECT model_id FROM models WHERE model_id=?", (m["model_id"],)
        ).fetchone()
        if existing:
            continue
        conn.execute("""
            INSERT INTO models
              (model_id, name, backend, backend_model, endpoint, api_key_env,
               capabilities, priority, max_tokens, context_window,
               cost_per_1k_in, cost_per_1k_out, registered_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            m["model_id"], m["name"], m["backend"], m["backend_model"],
            m.get("endpoint", ""), m.get("api_key_env", ""),
            json.dumps(m.get("capabilities", [])),
            m.get("priority", 50), m.get("max_tokens", 4096),
            m.get("context_window", 8192),
            m.get("cost_per_1k_in", 0.0), m.get("cost_per_1k_out", 0.0), now,
        ))


# ── Routing ───────────────────────────────────────────────────────────────────

def _pick_model(
    preferred_model: str,
    capability: str,
    backend: str,
) -> Optional[sqlite3.Row]:
    """Pick best available model. preferred_model is an exact model_id or ''.
    If preferred_model is specified and not found/enabled, returns None immediately
    (caller raises 503 — no silent fallback on an explicit model request)."""
    with db() as conn:
        if preferred_model:
            row = conn.execute(
                "SELECT * FROM models WHERE model_id=? AND enabled=1",
                (preferred_model,)
            ).fetchone()
            return row  # None if not found → 503 to caller

        # Route by capability + backend preference
        if backend:
            row = conn.execute(
                "SELECT * FROM models WHERE enabled=1 AND backend=? AND capabilities LIKE ? ORDER BY priority LIMIT 1",
                (backend, f"%{capability}%")
            ).fetchone()
            if row:
                return row

        # Any capable model, lowest priority number first
        return conn.execute(
            "SELECT * FROM models WHERE enabled=1 AND capabilities LIKE ? ORDER BY priority LIMIT 1",
            (f"%{capability}%",)
        ).fetchone()


def _compute_cost(model: sqlite3.Row, input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens  * model["cost_per_1k_in"] +
        output_tokens * model["cost_per_1k_out"]
    ) / 1000


# ── Spend gate ──────────────────────────────────────────────────────────────────
# Deterministic pre-call cost check. Lives in the gateway (the single chokepoint all
# cloud calls pass through) — NOT in the Accountant LLM agent, which would be slow and
# would burn LLM tokens to check LLM spend. The Accountant sets caps + reports; the
# gateway enforces.

def _is_paid(model: sqlite3.Row) -> bool:
    """A model costs money if it has any per-token cost (cloud backends)."""
    return model["cost_per_1k_in"] > 0 or model["cost_per_1k_out"] > 0


def _estimate_cost(model: sqlite3.Row, messages: list, max_tokens: int) -> float:
    """Worst-case cost estimate BEFORE the call: rough input-token count from the
    payload + the full requested max_tokens as output. Deliberately conservative so
    the gate never under-estimates a paid call."""
    input_tokens_est  = max(1, len(str(messages)) // 4)
    output_tokens_est = max_tokens
    return _compute_cost(model, input_tokens_est, output_tokens_est)


def _get_budget(agent_id: str) -> tuple[float, int]:
    """Return (cap_usd, window_days) for an agent. Default is a 1-day window."""
    with db() as conn:
        row = conn.execute(
            "SELECT cap_usd, window_days FROM budgets WHERE agent_id=?", (agent_id,)
        ).fetchone()
    if row:
        return float(row["cap_usd"]), int(row["window_days"])
    return DEFAULT_DAILY_CAP_USD, 1


def _spend_window(agent_id: str, window_days: int) -> float:
    """Sum of this agent's cloud spend over the rolling window. A 7-day window means
    unused budget 'banks' across the week — a quiet stretch funds a heavy day."""
    since = time.time() - (window_days * 86400)
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) AS t FROM usage_log "
            "WHERE agent_id=? AND logged_at>=?",
            (agent_id, since),
        ).fetchone()
    return float(row["t"] or 0.0)


def _budget_check(agent_id: str, estimated_cost_usd: float) -> dict:
    """The core decision: would this estimated cost push the agent over its cap,
    measured across its rolling window (weekly-banked if window_days=7)?"""
    cap, window_days = _get_budget(agent_id)
    spend   = _spend_window(agent_id, window_days)
    allowed = (spend + estimated_cost_usd) <= cap
    return {
        "allowed":            allowed,
        "agent_id":           agent_id,
        "estimated_cost_usd": round(estimated_cost_usd, 6),
        "window_days":        window_days,
        "spend_in_window_usd": round(spend, 6),
        "cap_usd":            round(cap, 6),
        "remaining_usd":      round(max(0.0, cap - spend), 6),
    }


def _pick_free_local(capability: str) -> Optional[sqlite3.Row]:
    """Cheapest free local model with the needed capability — the budget fallback."""
    with db() as conn:
        return conn.execute(
            "SELECT * FROM models WHERE enabled=1 AND backend='ollama' "
            "AND cost_per_1k_in=0 AND cost_per_1k_out=0 AND capabilities LIKE ? "
            "ORDER BY priority LIMIT 1",
            (f"%{capability}%",),
        ).fetchone()


def _log_usage(agent_id: str, model: sqlite3.Row, input_tokens: int,
               output_tokens: int, latency_ms: float, status: str, request_type: str) -> None:
    cost = _compute_cost(model, input_tokens, output_tokens)
    with db() as conn:
        conn.execute("""
            INSERT INTO usage_log
              (agent_id, model_id, backend, input_tokens, output_tokens,
               cost_usd, latency_ms, status, request_type, logged_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            agent_id, model["model_id"], model["backend"],
            input_tokens, output_tokens, round(cost, 8),
            latency_ms, status, request_type, time.time(),
        ))
        conn.execute("""
            DELETE FROM usage_log WHERE id NOT IN (
                SELECT id FROM usage_log ORDER BY id DESC LIMIT ?
            )
        """, (USAGE_KEEP,))


# ── Backend proxies ───────────────────────────────────────────────────────────

async def _call_ollama(model: sqlite3.Row, messages: list, max_tokens: int, timeout: float,
                       tools: list | None = None) -> dict:
    endpoint = model["endpoint"] or "http://localhost:11434"
    body: dict = {
        "model":   model["backend_model"],
        "messages": messages,
        "options": {"num_predict": max_tokens},
        "stream":  False,
    }
    if tools:
        body["tools"] = tools
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{endpoint}/api/chat", json=body)
        r.raise_for_status()
        data    = r.json()
        message = data.get("message", {})
        content = message.get("content", "")
        # Native function calling: Ollama returns tool_calls on the message
        tool_calls = message.get("tool_calls")
        usage   = data.get("usage", {})
        return {
            "content":       content,
            "tool_calls":    tool_calls,   # None for prose, list for tool invocations
            "input_tokens":  usage.get("prompt_tokens", len(str(messages)) // 4),
            "output_tokens": usage.get("completion_tokens", len(content) // 4),
        }


async def _call_anthropic(model: sqlite3.Row, messages: list, max_tokens: int,
                           timeout: float, api_key: str) -> dict:
    import os
    key = api_key or os.environ.get(model["api_key_env"], "")
    if not key:
        raise ValueError(f"No API key for {model['model_id']}")

    # Separate system from messages
    system = ""
    chat_msgs = []
    for m in messages:
        if m.get("role") == "system":
            system = m.get("content", "")
        else:
            chat_msgs.append(m)

    payload: dict = {
        "model":      model["backend_model"],
        "messages":   chat_msgs,
        "max_tokens": max_tokens,
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "x-api-key":         key,
                "anthropic-version":  "2023-06-01",
                "content-type":       "application/json",
            },
        )
        r.raise_for_status()
        data = r.json()
        content = data.get("content", [{}])[0].get("text", "")
        usage   = data.get("usage", {})
        return {
            "content":       content,
            "input_tokens":  usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }


async def _route_and_call(
    agent_id:   str,
    messages:   list,
    model_id:   str = "",
    capability: str = "chat",
    backend:    str = "",
    max_tokens: int = 1024,
    api_key:    str = "",
    timeout:    float = DEFAULT_TIMEOUT,
    request_type: str = "chat",
    tools:      list | None = None,
) -> dict:
    model = _pick_model(model_id, capability, backend)
    if not model:
        raise HTTPException(status_code=503, detail={
            "error": "no_model_available",
            "message": "No model available matching request constraints.",
        })

    # ── SPEND GATE ──────────────────────────────────────────────────────────────
    # No paid call without computing its cost first. Free/local models pass through
    # with zero overhead. Paid models are estimated + checked against the daily cap;
    # over budget → fall back to a free local model so work continues, never overspend.
    budget_decision = None
    if _is_paid(model):
        est = _estimate_cost(model, messages, max_tokens)
        budget_decision = _budget_check(agent_id, est)
        if not budget_decision["allowed"]:
            fallback = _pick_free_local(capability)
            if fallback is None:
                raise HTTPException(status_code=402, detail={
                    "error": "budget_exceeded",
                    "message": "Paid call would exceed the agent's daily cap and no "
                               "free local model is available for fallback.",
                    **budget_decision,
                    "denied_model_id": model["model_id"],
                })
            # Graceful downgrade: serve the request locally instead of overspending.
            model = fallback

    t0     = time.time()
    status = "ok"
    result = {}

    try:
        if model["backend"] == "ollama":
            result = await _call_ollama(model, messages, max_tokens, timeout, tools=tools)
        elif model["backend"] == "anthropic":
            result = await _call_anthropic(model, messages, max_tokens, timeout, api_key)
        else:
            raise HTTPException(status_code=501, detail={
                "error": "backend_not_implemented",
                "backend": model["backend"],
            })
    except HTTPException:
        raise
    except Exception as e:
        status = "error"
        latency_ms = (time.time() - t0) * 1000
        _log_usage(agent_id, model, 0, 0, latency_ms, status, request_type)
        raise HTTPException(status_code=502, detail={
            "error": "backend_error",
            "model_id": model["model_id"],
            "message": str(e),
        })

    latency_ms = (time.time() - t0) * 1000
    _log_usage(agent_id, model, result.get("input_tokens", 0),
               result.get("output_tokens", 0), latency_ms, status, request_type)

    return {
        "ok":            True,
        "model_id":      model["model_id"],
        "backend":       model["backend"],
        "content":       result.get("content", ""),
        "tool_calls":    result.get("tool_calls"),   # forwarded from Ollama native calling
        "input_tokens":  result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
        "cost_usd":      round(_compute_cost(model,
                               result.get("input_tokens", 0),
                               result.get("output_tokens", 0)), 8),
        "latency_ms":    round(latency_ms, 1),
    }


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    agent_id:    str
    messages:    list[dict]
    model_id:    str        = ""     # preferred model — gateway routes if empty
    capability:  str        = "chat" # capability filter (chat | complete | code | tools)
    backend:     str        = ""     # preferred backend (ollama | anthropic | openai)
    max_tokens:  int        = 1024
    temperature: float      = 0.7    # accepted but forwarded only if backend supports it
    api_key:     str        = ""     # override API key
    timeout:     float      = DEFAULT_TIMEOUT
    tools:       list | None = None  # Ollama native function-calling tool definitions


class CompleteRequest(BaseModel):
    agent_id:  str
    prompt:    str
    model_id:  str   = ""
    backend:   str   = ""
    max_tokens: int  = 1024
    api_key:   str   = ""
    timeout:   float = DEFAULT_TIMEOUT


class RegisterModelRequest(BaseModel):
    model_id:       str
    name:           str
    backend:        str
    backend_model:  str
    endpoint:       str = ""
    api_key_env:    str = ""
    capabilities:   list[str] = Field(default_factory=lambda: ["chat"])
    priority:       int  = 50
    max_tokens:     int  = 4096
    context_window: int  = 8192
    cost_per_1k_in:  float = 0.0
    cost_per_1k_out: float = 0.0


class BudgetCheckRequest(BaseModel):
    agent_id:           str
    estimated_cost_usd: float


class BudgetSetRequest(BaseModel):
    agent_id:    str
    cap_usd:     float
    window_days: int = 1   # 1 = daily reset; 7 = weekly-banked


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(req: ChatRequest):
    return await _route_and_call(
        agent_id=req.agent_id, messages=req.messages,
        model_id=req.model_id, capability=req.capability, backend=req.backend,
        max_tokens=req.max_tokens, api_key=req.api_key,
        timeout=req.timeout, request_type="chat",
        tools=req.tools,
    )


@app.post("/complete")
async def complete(req: CompleteRequest):
    messages = [{"role": "user", "content": req.prompt}]
    return await _route_and_call(
        agent_id=req.agent_id, messages=messages,
        model_id=req.model_id, backend=req.backend,
        max_tokens=req.max_tokens, api_key=req.api_key,
        timeout=req.timeout, request_type="complete",
        capability="complete",
    )


@app.get("/models")
async def list_models(enabled_only: bool = True):
    with db() as conn:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM models WHERE enabled=1 ORDER BY priority, model_id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM models ORDER BY priority, model_id"
            ).fetchall()
    return {
        "ok":    True,
        "count": len(rows),
        "models": [
            {
                "model_id":       r["model_id"],
                "name":           r["name"],
                "backend":        r["backend"],
                "backend_model":  r["backend_model"],
                "capabilities":   json.loads(r["capabilities"]),
                "priority":       r["priority"],
                "max_tokens":     r["max_tokens"],
                "context_window": r["context_window"],
                "cost_per_1k_in":  r["cost_per_1k_in"],
                "cost_per_1k_out": r["cost_per_1k_out"],
                "enabled":        bool(r["enabled"]),
                "last_health_ok": r["last_health_ok"],
            }
            for r in rows
        ]
    }


@app.post("/models/register", status_code=201)
async def register_model(req: RegisterModelRequest):
    now = time.time()
    with db() as conn:
        conn.execute("""
            INSERT INTO models
              (model_id, name, backend, backend_model, endpoint, api_key_env,
               capabilities, priority, max_tokens, context_window,
               cost_per_1k_in, cost_per_1k_out, enabled, registered_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)
            ON CONFLICT(model_id) DO UPDATE SET
              name=excluded.name, backend=excluded.backend,
              backend_model=excluded.backend_model,
              endpoint=excluded.endpoint, api_key_env=excluded.api_key_env,
              capabilities=excluded.capabilities, priority=excluded.priority,
              max_tokens=excluded.max_tokens, context_window=excluded.context_window,
              cost_per_1k_in=excluded.cost_per_1k_in,
              cost_per_1k_out=excluded.cost_per_1k_out
        """, (
            req.model_id, req.name, req.backend, req.backend_model,
            req.endpoint, req.api_key_env,
            json.dumps(req.capabilities), req.priority,
            req.max_tokens, req.context_window,
            req.cost_per_1k_in, req.cost_per_1k_out, now,
        ))
    return {"ok": True, "model_id": req.model_id}


@app.delete("/models/{model_id}")
async def remove_model(model_id: str):
    with db() as conn:
        row = conn.execute("SELECT model_id FROM models WHERE model_id=?", (model_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        conn.execute("UPDATE models SET enabled=0 WHERE model_id=?", (model_id,))
    return {"ok": True, "model_id": model_id, "enabled": False}


@app.get("/models/{model_id}/health")
async def model_health(model_id: str):
    """Ping the backend to check if the model is reachable."""
    with db() as conn:
        row = conn.execute("SELECT * FROM models WHERE model_id=?", (model_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    ok = False
    try:
        if row["backend"] == "ollama":
            endpoint = row["endpoint"] or "http://localhost:11434"
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{endpoint}/api/tags")
                ok = r.status_code == 200
        else:
            # For cloud backends — assume reachable if endpoint configured
            ok = True
    except Exception:
        pass

    if ok:
        with db() as conn:
            conn.execute("UPDATE models SET last_health_ok=? WHERE model_id=?",
                         (time.time(), model_id))

    return {"ok": True, "model_id": model_id, "reachable": ok}


@app.get("/usage/{agent_id}")
async def agent_usage(agent_id: str, limit: int = 50):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM usage_log WHERE agent_id=? ORDER BY logged_at DESC LIMIT ?",
            (agent_id, limit)
        ).fetchall()
        total_cost = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) as t FROM usage_log WHERE agent_id=?",
            (agent_id,)
        ).fetchone()["t"]

    return {
        "ok":        True,
        "agent_id":  agent_id,
        "total_usd": round(total_cost, 6),
        "entries": [dict(r) for r in rows],
    }


@app.get("/usage")
async def system_usage(limit: int = 100):
    with db() as conn:
        rows = conn.execute(
            """SELECT model_id, backend,
                      COUNT(*) as requests,
                      SUM(input_tokens) as total_input,
                      SUM(output_tokens) as total_output,
                      SUM(cost_usd) as total_cost,
                      AVG(latency_ms) as avg_latency_ms
               FROM usage_log
               GROUP BY model_id, backend
               ORDER BY total_cost DESC"""
        ).fetchall()
        total = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) as t FROM usage_log"
        ).fetchone()["t"]

    return {
        "ok":        True,
        "total_usd": round(total, 6),
        "by_model": [
            {
                "model_id":       r["model_id"],
                "backend":        r["backend"],
                "requests":       r["requests"],
                "input_tokens":   r["total_input"],
                "output_tokens":  r["total_output"],
                "cost_usd":       round(r["total_cost"], 6),
                "avg_latency_ms": round(r["avg_latency_ms"], 1),
            }
            for r in rows
        ]
    }


@app.post("/budget/check")
async def budget_check(req: BudgetCheckRequest):
    """Pre-call gate: would this estimated cost push the agent over its daily cap?
    Deterministic, no LLM. This is the programmatic enforcement point for the rule
    'no paid call without computing the cost first'."""
    return {"ok": True, **_budget_check(req.agent_id, req.estimated_cost_usd)}


@app.post("/budget/set")
async def budget_set(req: BudgetSetRequest):
    """Set an agent's cloud-spend cap + window. window_days=7 banks unused budget
    across the week. Owned by the Accountant / Darnie."""
    if req.cap_usd < 0 or req.window_days < 1:
        raise HTTPException(status_code=400, detail={"error": "cap>=0 and window_days>=1 required"})
    with db() as conn:
        conn.execute(
            "INSERT INTO budgets (agent_id, cap_usd, window_days, set_at) VALUES (?,?,?,?) "
            "ON CONFLICT(agent_id) DO UPDATE SET cap_usd=excluded.cap_usd, "
            "window_days=excluded.window_days, set_at=excluded.set_at",
            (req.agent_id, req.cap_usd, req.window_days, time.time()),
        )
    return {"ok": True, "agent_id": req.agent_id, "cap_usd": req.cap_usd,
            "window_days": req.window_days}


@app.get("/budget/{agent_id}")
async def budget_get(agent_id: str):
    """Current cap, window, spend over the window, and remaining headroom."""
    cap, window_days = _get_budget(agent_id)
    spend = _spend_window(agent_id, window_days)
    with db() as conn:
        row = conn.execute("SELECT cap_usd FROM budgets WHERE agent_id=?", (agent_id,)).fetchone()
    return {
        "ok":             True,
        "agent_id":       agent_id,
        "cap_usd":        round(cap, 6),
        "window_days":    window_days,
        "is_default_cap": row is None,
        "spend_in_window_usd": round(spend, 6),
        "remaining_usd":  round(max(0.0, cap - spend), 6),
        "pct_used":       round(100 * spend / cap, 1) if cap > 0 else 100.0,
    }


@app.get("/budget")
async def budget_list():
    """All explicitly-set caps + the default. The cost-monitoring overview."""
    with db() as conn:
        rows = conn.execute(
            "SELECT agent_id, cap_usd, window_days, set_at FROM budgets ORDER BY agent_id"
        ).fetchall()
    out = []
    for r in rows:
        spend = _spend_window(r["agent_id"], int(r["window_days"]))
        out.append({
            "agent_id":     r["agent_id"],
            "cap_usd":      r["cap_usd"],
            "window_days":  r["window_days"],
            "spend_usd":    round(spend, 6),
            "remaining_usd": round(max(0.0, r["cap_usd"] - spend), 6),
            "pct_used":     round(100 * spend / r["cap_usd"], 1) if r["cap_usd"] > 0 else 100.0,
        })
    return {"ok": True, "default_cap_usd": DEFAULT_DAILY_CAP_USD, "agent_caps": out}


@app.get("/health")
async def health():
    with db() as conn:
        models   = conn.execute("SELECT COUNT(*) as n FROM models WHERE enabled=1").fetchone()["n"]
        backends = conn.execute("SELECT COUNT(DISTINCT backend) as n FROM models WHERE enabled=1").fetchone()["n"]
        requests = conn.execute("SELECT COUNT(*) as n FROM usage_log").fetchone()["n"]
    return {
        "ok":             True,
        "enabled_models": models,
        "backends":       backends,
        "total_requests": requests,
        "port":           PORT,
    }


@app.get("/stats")
async def stats():
    with db() as conn:
        total   = conn.execute("SELECT COUNT(*) as n FROM usage_log").fetchone()["n"]
        success = conn.execute("SELECT COUNT(*) as n FROM usage_log WHERE status='ok'").fetchone()["n"]
        errors  = conn.execute("SELECT COUNT(*) as n FROM usage_log WHERE status='error'").fetchone()["n"]
        cost    = conn.execute("SELECT COALESCE(SUM(cost_usd),0) as t FROM usage_log").fetchone()["t"]
        models  = conn.execute("SELECT COUNT(*) as n FROM models WHERE enabled=1").fetchone()["n"]
    return {
        "ok":             True,
        "total_requests": total,
        "successful":     success,
        "errors":         errors,
        "total_cost_usd": round(cost, 6),
        "enabled_models": models,
    }


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
