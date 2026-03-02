from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.base import router as base_router
from api.ai import router as ai_router
from api.location import router as location_router
from api.chat import router as chat_router
from api.audio import router as audio_router
from core.monitoring.dashboard import router as dashboard_router
from core.monitoring.dashboard_v2 import router as monitor_router
from core.monitoring.health import router as health_router
from core.monitoring.websocket import router as ws_router
from core.monitoring.startup import init_monitoring, shutdown_monitoring
from core.modules.registry import get_module_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - initialize and cleanup resources."""
    # Startup
    await init_monitoring(app)
    module_registry = get_module_registry()
    await module_registry.mount_all(app)
    yield
    # Shutdown
    await module_registry.shutdown_all()
    await shutdown_monitoring()


app = FastAPI(
    title="GENESIS",
    version="0.6.0",
    lifespan=lifespan,
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
app.include_router(health_router)  # /health, /readiness, /liveness, /metrics
app.include_router(dashboard_router)  # /dashboard/*
app.include_router(monitor_router)  # /monitor/ (real-time dashboard v2)
app.include_router(ws_router)  # /ws/monitor (WebSocket)
