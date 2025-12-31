from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryWrite(BaseModel):
    entry_type: str
    payload: Dict[str, Any]


@router.get("")
def memory_read(limit: int = 50) -> Dict[str, Any]:
    return {"count": 0, "items": [], "message": "Memory system placeholder"}


@router.post("")
def memory_write(entry: MemoryWrite) -> Dict[str, Any]:
    return {"status": "ok", "message": "Memory write placeholder"}
