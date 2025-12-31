from __future__ import annotations
from fastapi import FastAPI

from api.base import router as base_router
from api.ai import router as ai_router

app = FastAPI(
    title="GENESIS",
    version="0.4.0",
)

# Attach routers
app.include_router(base_router)
app.include_router(ai_router)
