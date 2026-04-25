"""
agent/api/server.py — Direct HTTP interface for BlackZero agents.

Runs on a configurable port (set in config.yaml → api.port, overridable by
AGENT_PORT env var). Allows PlugOps chat.py to reach this agent via HTTP.

Does NOT replace the PlugOps WebSocket bridge — both run concurrently.
The bridge handles real-time push; this handles synchronous request/response.

Endpoints:
    GET  /health     → {"status": "ok", "agent": "<agent_id>"}
    POST /api/chat   → ChatRequest → ChatResponse
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

# Module-level state — set once at boot via init(), never mutated after that.
_agent_id:        str  = "blackzero"
_graph            = None
_mods:  "Modules | None" = None
_data_dir: Path   = Path("~/.blackzero").expanduser()


def init(agent_id: str, graph, mods: "Modules", data_dir: Path) -> None:
    """
    Called from main.py after the graph is built and before the server starts.
    Sets the shared state this module needs to handle requests.
    """
    global _agent_id, _graph, _mods, _data_dir
    _agent_id  = agent_id
    _graph     = graph
    _mods      = mods
    _data_dir  = data_dir
    logger.info(f"[api] Initialized — {agent_id} on HTTP /api/chat")


# ── Request / Response models ──────────────────────────────────────────────────

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
    connected = _mods.bridge.is_connected if (_mods and _mods.bridge) else False
    return {"status": "ok", "agent": _agent_id, "plugops": connected}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if _graph is None:
        return ChatResponse(agent=_agent_id, response="Agent not ready yet.")

    state = {
        "message":        req.message,
        "from_agent":     req.from_agent,
        "session_id":     req.session_id,
        "memory_context": [],
        "response":       "",
        "tool_history":   [],
        "tool_iterations": 0,
        "tool_call_pending": False,
        "_data_dir":      str(_data_dir),   # recall node uses this for SQLite fallback
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
