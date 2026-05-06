"""
server.py — FastAPI server for ToolZero-based tool-agents.

Endpoints:
  GET  /health      → liveness + registered tools list
  POST /execute     → direct HTTP tool execution (bypasses PlugOps)
  GET  /tools       → list available tools

The /execute endpoint is the primary interface for direct calls.
PlugOps-routed calls come through the WebSocket bridge instead.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent.tools.registry import execute, list_tools

logger = logging.getLogger(__name__)

app = FastAPI(title="ToolAgent", docs_url="/docs")


# ── Models ────────────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    tool:   str
    params: dict[str, Any] = {}


class ExecuteResponse(BaseModel):
    tool:   str
    result: str
    error:  str | None = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tools":  list_tools(),
    }


@app.get("/tools")
async def tools():
    return {"tools": list_tools()}


@app.post("/execute", response_model=ExecuteResponse)
async def execute_tool(req: ExecuteRequest):
    logger.info(f"[api] execute: {req.tool}({list(req.params.keys())})")
    try:
        result = execute(req.tool, req.params)
        return ExecuteResponse(tool=req.tool, result=result)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except TypeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[api] Tool error: {e}")
        return ExecuteResponse(tool=req.tool, result="", error=str(e))
