"""
GENESIS Monitoring System Startup

Initializes and coordinates all monitoring components:
- Health Monitor (agent health tracking)
- Error Logger (centralized error logging)
- Alert System (ntfy.sh notifications)
- Prometheus Metrics (OpenMetrics export)

Usage:
    from core.monitoring.startup import init_monitoring, shutdown_monitoring

    # In FastAPI app
    @app.on_event("startup")
    async def startup():
        await init_monitoring()

    @app.on_event("shutdown")
    async def shutdown():
        await shutdown_monitoring()
"""

from __future__ import annotations
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI

from .monitor import get_health_monitor, AgentMetrics
from .logger import get_error_logger
from .alerting import get_alert_system, AlertSeverity, alert_degraded, alert_critical
from .metrics import get_metrics_collector
from .websocket import get_connection_manager

logger = logging.getLogger(__name__)

# Global state
_initialized = False
_start_time: Optional[datetime] = None


async def init_monitoring(app: Optional[FastAPI] = None) -> None:
    """
    Initialize all monitoring components.
    
    Call this at application startup to:
    1. Start the health monitor
    2. Initialize error logger
    3. Set up alert system with callbacks
    4. Register service health tracking
    
    Args:
        app: Optional FastAPI app to add shutdown handler
    """
    global _initialized, _start_time
    
    if _initialized:
        logger.warning("Monitoring already initialized")
        return
    
    logger.info("Initializing GENESIS monitoring system...")
    _start_time = datetime.now()
    
    # 1. Start health monitor
    monitor = get_health_monitor()
    monitor.start()
    
    # 2. Initialize error logger
    error_logger = get_error_logger()
    logger.info(f"Error logger initialized: {error_logger}")
    
    # 3. Set up alert system with health monitor callbacks
    alert_system = get_alert_system()
    
    # Connect health monitor to alert system
    def on_degraded(agent_name: str, metrics: AgentMetrics) -> None:
        alert_degraded(
            agent=agent_name,
            message=f"Agent {agent_name} is degraded. Error rate: {metrics.error_rate:.1%}",
            context={
                "error_count": metrics.error_count,
                "success_count": metrics.success_count,
                "last_error": metrics.last_error,
            }
        )
    
    def on_dead(agent_name: str, metrics: AgentMetrics) -> None:
        alert_critical(
            agent=agent_name,
            message=f"Agent {agent_name} is not responding. Last heartbeat: {metrics.time_since_heartbeat:.0f}s ago",
            context={
                "last_heartbeat": metrics.last_heartbeat.isoformat() if metrics.last_heartbeat else None,
                "uptime_seconds": metrics.uptime_seconds,
            }
        )
    
    def on_recovered(agent_name: str, metrics: AgentMetrics) -> None:
        # Log recovery but don't push (avoid alert fatigue)
        alert_system.send_alert(
            severity=AlertSeverity.NORMAL,
            agent=agent_name,
            message=f"Agent {agent_name} has recovered",
            context={"status": metrics.status.value}
        )
    
    monitor.on_agent_degraded(on_degraded)
    monitor.on_agent_dead(on_dead)
    monitor.on_agent_recovered(on_recovered)
    
    # 4. Start metrics collector
    metrics = get_metrics_collector()
    metrics.start()
    logger.info("Metrics collector started")

    # 5. Start WebSocket background broadcasts
    ws_manager = get_connection_manager()
    ws_manager.start_background_broadcasts()
    logger.info("WebSocket broadcasts started")

    # 6. Register core services for monitoring
    _register_core_services(monitor)
    
    _initialized = True
    logger.info("GENESIS monitoring system initialized")


async def shutdown_monitoring() -> None:
    """
    Gracefully shutdown all monitoring components.
    
    Call this at application shutdown to:
    1. Stop health monitor
    2. Flush error logs
    3. Save metrics
    """
    global _initialized
    
    if not _initialized:
        return
    
    logger.info("Shutting down GENESIS monitoring system...")
    
    # Stop health monitor
    monitor = get_health_monitor()
    monitor.stop()
    
    # Stop metrics collector
    metrics = get_metrics_collector()
    metrics.stop()
    
    # Stop WebSocket broadcasts
    ws_manager = get_connection_manager()
    ws_manager.stop_background_broadcasts()
    
    _initialized = False
    logger.info("GENESIS monitoring system shutdown complete")


def _register_core_services(monitor) -> None:
    """Register core services as monitored components."""
    # These will be tracked when they send heartbeats
    # Pre-register known services for visibility
    core_services = [
        "genesis_core",
        "llm_service", 
        "workspace_service",
        "memory_service",
    ]
    
    for service in core_services:
        monitor.register_agent(service)


def get_system_uptime() -> float:
    """Get monitoring system uptime in seconds."""
    if _start_time is None:
        return 0.0
    return (datetime.now() - _start_time).total_seconds()


def is_monitoring_initialized() -> bool:
    """Check if monitoring is initialized."""
    return _initialized


@asynccontextmanager
async def monitoring_lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager for monitoring.
    
    Usage:
        from core.monitoring.startup import monitoring_lifespan
        
        app = FastAPI(lifespan=monitoring_lifespan)
    """
    await init_monitoring(app)
    yield
    await shutdown_monitoring()
