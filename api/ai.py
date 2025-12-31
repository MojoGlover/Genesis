from __future__ import annotations
import time
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

from core.providers import route_and_generate

router = APIRouter(prefix="/ai", tags=["ai"])


class AIRequest(BaseModel):
    prompt: str
    model: Optional[str] = None


class AIResponse(BaseModel):
    model: str
    prompt: str
    response: str
    latency_ms: int


@router.post("", response_model=AIResponse)
async def ai_endpoint(req: AIRequest) -> AIResponse:
    result = await route_and_generate(prompt=req.prompt)
    
    return AIResponse(
        model=result["model"],
        prompt=req.prompt,
        response=result["content"],
        latency_ms=result["latency_ms"]
    )
