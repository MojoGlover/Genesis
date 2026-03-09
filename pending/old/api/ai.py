from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.memory import log_memory

router = APIRouter(prefix="/ai", tags=["ai"])


class AIRequest(BaseModel):
    prompt: str
    model: Optional[str] = "gpt-4o-mini"


class AIResponse(BaseModel):
    model: str
    prompt: str
    response: str
    latency_ms: int


@router.post("", response_model=AIResponse)
def ai_endpoint(req: AIRequest) -> AIResponse:
    start = time.time()
    api_key = os.getenv("OPENAI_API_KEY")

    if api_key:
        try:
            import openai  # type: ignore

            client = openai.OpenAI(api_key=api_key)
            completion = client.chat.completions.create(
                model=req.model or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a concise helper."},
                    {"role": "user", "content": req.prompt},
                ],
                max_tokens=256,
            )
            text = completion.choices[0].message.content or ""
            model_used = req.model or "gpt-4o-mini"
        except Exception as e:  # noqa: BLE001
            text = f"[local fallback due to error: {e}] -> {req.prompt[::-1]}"
            model_used = "local-fallback"
    else:
        text = f"[offline-local] {req.prompt.upper()}"
        model_used = "local-echo"

    latency_ms = int((time.time() - start) * 1000)

    log_memory(
        "ai_call",
        {
            "prompt": req.prompt,
            "response": text,
            "model": model_used,
            "latency_ms": latency_ms,
        },
    )

    return AIResponse(
        model=model_used,
        prompt=req.prompt,
        response=text,
        latency_ms=latency_ms,
    )
