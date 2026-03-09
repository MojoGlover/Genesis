from __future__ import annotations
from fastapi import FastAPI

from api.base import router as base_router
from api.ai import router as ai_router
from api.memory_routes import router as memory_router

app = FastAPI(
    title="Kris Backend",
    version="0.3.0",
)

# Attach routers
app.include_router(base_router)
app.include_router(ai_router)
app.include_router(memory_router)
