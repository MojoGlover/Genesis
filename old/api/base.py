from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from core.memory import log_memory

router = APIRouter(tags=["base"])


class EchoPayload(BaseModel):
    text: str


@router.get("/")
def root() -> Dict[str, Any]:
    return {
        "message": "FastAPI is running on your Mac.",
        "framework": "FastAPI",
    }


@router.get("/status")
def status() -> Dict[str, Any]:
    return {
        "status": "ok",
        "time": time.time(),
        "details": "Backend online.",
    }


@router.post("/json")
def echo(payload: EchoPayload) -> Dict[str, Any]:
    rec = log_memory("json_echo", payload.model_dump())
    return {
        "echo": payload.text,
        "len": len(payload.text),
        "memory_id": rec["id"],
    }
