from __future__ import annotations
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
import time

from core.providers import route_and_generate
from core.tools.router import detect_and_route
from core.storage.memory import get_memory

router = APIRouter(prefix="/ai", tags=["ai"])


class AIRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    session_id: Optional[str] = "default"
    conversation_id: Optional[int] = None


class AIResponse(BaseModel):
    model: str
    prompt: str
    response: str
    latency_ms: int
    tool_used: Optional[str] = None
    conversation_id: int


@router.post("", response_model=AIResponse)
async def ai_endpoint(req: AIRequest) -> AIResponse:
    start = time.time()
    memory = get_memory()
    
    # Create or get conversation
    if req.conversation_id is None:
        conv_id = memory.create_conversation(req.session_id)
    else:
        conv_id = req.conversation_id
    
    # Get conversation history for context
    history = memory.get_conversation_history(conv_id, limit=5)
    
    # Build context from history
    context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history[-3:]])
    
    # ASSESS COMPLEXITY ON ORIGINAL PROMPT (before adding context)
    complexity = None
    prompt_words = len(req.prompt.split())
    if prompt_words < 10:  # Simple queries - use fast model
        complexity = "simple"
    
    # Check if tools are needed
    tool_result = detect_and_route(req.prompt)
    
    # Build enhanced prompt with context AFTER determining complexity
    full_prompt = req.prompt
    if context:
        full_prompt = f"Previous conversation:\n{context}\n\nUser: {req.prompt}"
    
    if tool_result:
        full_prompt += f"\n\nTool Results:\n{tool_result.get('results', tool_result)}"
    
    # Generate response with pre-determined complexity
    result = await route_and_generate(
        prompt=full_prompt,
        complexity=complexity
    )
    latency_ms = int((time.time() - start) * 1000)
    
    # Save to memory
    memory.add_message(conv_id, "user", req.prompt)
    memory.add_message(conv_id, "assistant", result["content"], {
        "model": result["model"],
        "latency_ms": latency_ms,
        "tool_used": tool_result.get("tool") if tool_result else None
    })
    
    return AIResponse(
        model=result["model"],
        prompt=req.prompt,
        response=result["content"],
        latency_ms=latency_ms,
        tool_used=tool_result.get("tool") if tool_result else None,
        conversation_id=conv_id
    )
