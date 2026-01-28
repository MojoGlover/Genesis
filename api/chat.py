"""
Chat API — REST endpoints wrapping ChatOrchestrator for the mobile PWA.
POST /chat/message   — send message, get AI response
POST /chat/execute   — run a queued task
POST /chat/select-task — select a task to view
GET  /chat/tasks     — list all tasks
GET  /chat/code      — get latest generated code
POST /chat/reset     — clear conversation + queue
GET  /chat/status    — poll conversation state
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.services.orchestrator import get_orchestrator

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Request models ──────────────────────────────────────────────

class MessageRequest(BaseModel):
    message: str
    voice_input: Optional[str] = None


class ExecuteRequest(BaseModel):
    task_id: Optional[str] = None


class SelectTaskRequest(BaseModel):
    task_choice: str


# ── Helpers ─────────────────────────────────────────────────────

def _voice_path_to_url(result: Dict[str, Any]) -> Dict[str, Any]:
    """Convert voice_audio filesystem path to a servable URL."""
    path = result.get("voice_audio")
    if path and os.path.isfile(path):
        result["voice_audio"] = f"/audio/{os.path.basename(path)}"
    else:
        result["voice_audio"] = None
    return result


# ── Endpoints ───────────────────────────────────────────────────

@router.post("/message")
async def send_message(req: MessageRequest) -> Dict[str, Any]:
    """Send a chat message and receive the orchestrator response."""
    orchestrator = get_orchestrator()
    result = await asyncio.to_thread(
        orchestrator.process_message, req.message, req.voice_input
    )
    return _voice_path_to_url(result)


@router.post("/execute")
async def execute_task(req: ExecuteRequest) -> Dict[str, Any]:
    """Execute a queued task (may take a while)."""
    orchestrator = get_orchestrator()
    result = await asyncio.to_thread(orchestrator.execute_task, req.task_id)
    return result


@router.post("/select-task")
async def select_task(req: SelectTaskRequest) -> Dict[str, Any]:
    """Select a task by its dropdown-choice string."""
    orchestrator = get_orchestrator()
    return orchestrator.select_task(req.task_choice)


@router.get("/tasks")
async def list_tasks() -> Dict[str, Any]:
    """Return all tasks and formatted choice strings."""
    orchestrator = get_orchestrator()
    return {
        "tasks": orchestrator.get_all_tasks(),
        "choices": orchestrator.get_task_choices(),
    }


@router.get("/code")
async def get_code() -> Dict[str, Any]:
    """Return the latest generated code from the workspace."""
    orchestrator = get_orchestrator()
    return orchestrator.get_latest_code()


@router.post("/reset")
async def reset() -> Dict[str, Any]:
    """Reset conversation, task queue, and state."""
    orchestrator = get_orchestrator()
    return orchestrator.reset()


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """Poll the current conversation state."""
    orchestrator = get_orchestrator()
    tasks = orchestrator.get_all_tasks()
    return {
        "state": orchestrator.state.value,
        "task_count": len(tasks),
        "pending_task": orchestrator._pending_task,
    }
