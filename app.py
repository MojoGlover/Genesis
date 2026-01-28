from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.base import router as base_router
from api.ai import router as ai_router
from api.location import router as location_router
from api.chat import router as chat_router
from api.audio import router as audio_router
from api.delivery import router as delivery_router

app = FastAPI(
    title="GENESIS",
    version="0.6.0",
)

# CORS — allow Tailscale CGNAT range (100.x.x.x) + local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:7860",
        "http://localhost:8000",
    ],
    allow_origin_regex=r"http://100\..*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for mobile PWA
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(base_router)
app.include_router(ai_router)
app.include_router(location_router)
app.include_router(chat_router)
app.include_router(audio_router)
app.include_router(delivery_router)
