"""
agent/api/server.py — Direct HTTP interface for BlackZero agents.

Runs on a configurable port (set in config.yaml → api.port, overridable by
AGENT_PORT env var). Allows PlugOps chat.py to reach this agent via HTTP.

Does NOT replace the PlugOps WebSocket bridge — both run concurrently.
The bridge handles real-time push; this handles synchronous request/response.

Endpoints:
    GET  /health     → {"status": "ok"|"starting", "agent": "<agent_id>"}
    POST /api/chat   → ChatRequest → ChatResponse
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent.modules import Modules

# Tool results indicating failure — sets the Tool Bus executor's ok=false flag.
_ERROR_PREFIXES = ("error:", "unknown tool", "tool error", "tool '")

logger = logging.getLogger(__name__)

app = FastAPI(title="BlackZero Agent")

# Module-level state — set once at boot via init(), never mutated after that.
_agent_id:       str  = "blackzero"
_graph                = None
_mods: "Modules | None" = None
_data_dir: Path  = Path("~/.blackzero").expanduser()
_system_prompt:  str  = ""
_ready:          bool = False

MAX_MESSAGE_LEN = 32_000   # ~8K tokens — prevent context explosion
CHAT_TIMEOUT    = 660      # seconds before abandoning a request — must stay > handler.py HANDLER_TIMEOUT (650); long tool chains need room


def init(agent_id: str, graph, system_prompt: str, data_dir: Path,
         mods: "Modules | None" = None, ready: bool = False) -> None:
    """Called from main.py once at boot. Signature matches main.py's call exactly."""
    global _agent_id, _graph, _mods, _data_dir, _system_prompt, _ready
    _agent_id      = agent_id
    _graph         = graph
    _system_prompt = system_prompt
    _data_dir      = data_dir
    _mods          = mods
    _ready         = ready
    logger.info(f"[api] Initialized — {agent_id} on HTTP /api/chat")


def set_ready() -> None:
    global _ready
    _ready = True
    logger.info("[api] Agent marked ready")


# ── Request / Response models ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message:    str = Field(..., max_length=MAX_MESSAGE_LEN)
    from_agent: str = "user"
    session_id: str = "default"


class ToolRequest(BaseModel):
    tool:   str
    params: dict = Field(default_factory=dict)


class ChatResponse(BaseModel):
    agent:    str
    response: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    mod_summary = _mods.summary() if _mods else "modules not initialized"
    return {
        "status":  "ok" if _ready else "starting",
        "agent":   _agent_id,
        "modules": mod_summary,
    }


@app.get("/api/v1/tools")
async def tools():
    """MCP-compatible tool discovery endpoint. Returns JSON Schema descriptors for all tools."""
    from agent.tools.registry import list_tools
    return {"agent": _agent_id, "tools": list_tools()}


@app.post("/api/tools/execute")
async def execute_tool(req: ToolRequest, x_agent_id: str = Header(default="")):
    """
    Tool Bus executor endpoint — lets this agent HOST its tools for the grid.

    Any registered agent (or PlugOps on their behalf) calls this over HTTP;
    PlugOps proxies here via POST /api/v1/tools/execute, resolving this agent's
    URL via GridResolver. This is what makes a specialized agent (e.g. the
    Accountant hosting its financial tools) usable by others — they borrow the
    tool without carrying its code.

    Auth: X-Agent-Id header required (any non-empty registered agent). PlugOps is
    the trust boundary; per-agent tool authorization is added in the auth phase.

    Request:  {"tool": "ledger_stats", "params": {}}
    Response: {"result": "...", "ok": true, "tool": "ledger_stats"}
    """
    if not x_agent_id:
        raise HTTPException(status_code=401, detail="X-Agent-Id header required")

    from agent.tools.registry import build_executor
    execute = build_executor()
    try:
        result = execute(req.tool, req.params)
        ok = not result.lower().startswith(_ERROR_PREFIXES)
        logger.info(f"[api/tools] {x_agent_id} called {req.tool} → ok={ok}")
        return {"result": result, "ok": ok, "tool": req.tool}
    except Exception as e:
        logger.error(f"[api/tools] {req.tool} failed for {x_agent_id}: {e}")
        return {"result": f"error: {e}", "ok": False, "tool": req.tool}


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
        # Cooperative deadline for the think node (see graph.py). asyncio.wait_for
        # below can abandon the HTTP response at CHAT_TIMEOUT, but it cannot kill
        # the executor thread running graph.invoke(). Passing this deadline lets
        # the graph notice (between iterations) that the request has already
        # timed out and stop issuing further LLM calls — bounding how long the
        # orphaned thread keeps the local Ollama runner busy after the response
        # has already gone back to the caller.
        "_deadline":         time.monotonic() + CHAT_TIMEOUT,
    }

    try:
        loop   = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _graph.invoke(state, config={"configurable": {"thread_id": req.session_id}, "recursion_limit": 100}),
            ),
            timeout=CHAT_TIMEOUT,
        )
        response = result.get("response", "").strip()
        if not response:
            response = "I received your message but had nothing to say."
        tools_ran = result.get("_tools_ran", 0)
        from agent.core.graph import _requires_tool_use
        if _requires_tool_use(req.message) and tools_ran == 0:
            logger.warning(f"[api] Hallucination suspected — _tools_ran=0 for action request")
            response = (
                f"⚠️ HALLUCINATION WARNING: Agent described the task but executed 0 tools. "
                f"No real action was taken.\n\nRaw response: {response}"
            )
    except asyncio.TimeoutError:
        logger.error(f"[api] graph.invoke timed out after {CHAT_TIMEOUT}s")
        response = f"Request timed out after {CHAT_TIMEOUT}s."
    except Exception as e:
        logger.error(f"[api] graph.invoke failed: {e}")
        response = f"Error processing message: {e}"

    return ChatResponse(agent=_agent_id, response=response)
