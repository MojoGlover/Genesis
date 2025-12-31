from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from core.memory import log_memory, read_memory

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryWrite(BaseModel):
    entry_type: str
    payload: Dict[str, Any]


@router.get("")
def memory_read(limit: int = 50) -> Dict[str, Any]:
    items = read_memory(limit=limit)
    return {"count": len(items), "items": items}


@router.post("")
def memory_write(entry: MemoryWrite) -> Dict[str, Any]:
    rec = log_memory(entry.entry_type, entry.payload)
    return {"status": "ok", "record": rec}
