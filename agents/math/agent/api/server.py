"""
agent/api/server.py — HTTP interface for BlackZero agents.

Endpoints:
    GET  /health     → {"status": "ok", "agent": "<id>"}
    POST /api/chat   → ChatRequest → ChatResponse

Per-agent custom endpoints live in routes.py (imported below).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from pydantic import BaseModel

if TYPE_CHECKING:
    from agent.modules import Modules

logger = logging.getLogger(__name__)

app = FastAPI(title="BlackZero Agent")

_agent_id: str       = "blackzero"
_graph               = None
_mods: "Modules | None" = None
_data_dir: Path      = Path("~/.blackzero").expanduser()
_system_prompt: str  = ""


def init(agent_id: str, graph, system_prompt: str, data_dir: Path, mods: "Modules") -> None:
    """Called from main.py once at boot. Sets shared state for all request handlers."""
    global _agent_id, _graph, _system_prompt, _data_dir, _mods
    _agent_id      = agent_id
    _graph         = graph
    _system_prompt = system_prompt
    _data_dir      = data_dir
    _mods          = mods
    logger.info(f"[api] Initialized — {agent_id} on HTTP /api/chat")

    # Mount per-agent custom routes if the agent defines any
    try:
        from agent.api import routes
        app.include_router(routes.router)
        logger.info("[api] Custom routes mounted from routes.py")
    except ImportError:
        pass  # no custom routes — that's fine


# ── Models ────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:    str
    from_agent: str = "user"
    session_id: str = "default"


class ChatResponse(BaseModel):
    agent:    str
    response: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "agent": _agent_id}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if _graph is None:
        return ChatResponse(agent=_agent_id, response="Agent not ready yet.")

    state = {
        "message":           req.message,
        "from_agent":        req.from_agent,
        "session_id":        req.session_id,
        "memory_context":    [],
        "response":          "",
        "tool_history":      [],
        "tool_iterations":   0,
        "tool_call_pending": False,
        "_data_dir":         str(_data_dir),
    }

    try:
        result   = _graph.invoke(state)
        response = result.get("response", "").strip()
        if not response:
            response = "I received your message but had nothing to say."
    except Exception as e:
        logger.error(f"[api] graph.invoke failed: {e}")
        response = f"Error processing message: {e}"

    return ChatResponse(agent=_agent_id, response=response)
