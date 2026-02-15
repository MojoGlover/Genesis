"""
GENESIS Monitoring System Startup

Initializes and coordinates all monitoring components:
- Health Monitor (agent health tracking)
- Error Logger (centralized error logging)
- Alert System (ntfy.sh notifications)
- Metrics Collector (time-series storage)
- Resource Monitor (system thresholds)
- Auto Recovery (graduated agent recovery)
- System Metrics Agent (continuous metric collection)

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
from .resource_monitor import get_resource_monitor
from .auto_recovery import get_auto_recovery
from .system_metrics import get_system_metrics_agent
from .incident_tracker import get_incident_tracker
from .log_aggregator import get_log_aggregator
from .trace import get_tracer

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
    4. Start metrics collector
    5. Start WebSocket broadcasts
    6. Start resource monitor
    7. Start auto-recovery system
    8. Start system metrics agent
    9. Register service health tracking
    
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
        # Log recovery but dont push (avoid alert fatigue)
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

    # 6. Start resource monitor
    resource_monitor = get_resource_monitor()
    resource_monitor.start()
    logger.info("Resource monitor started")

    # 7. Start auto-recovery system
    auto_recovery = get_auto_recovery()
    auto_recovery.start()
    logger.info("Auto-recovery system started")

    # 8. Start system metrics agent
    sys_metrics = get_system_metrics_agent()
    sys_metrics.start()
    logger.info("System metrics agent started")

    # 9. Start incident tracker
    incident_tracker = get_incident_tracker()
    incident_tracker.start()
    logger.info("Incident tracker started")

    # 10. Start log aggregator
    log_aggregator = get_log_aggregator()
    log_aggregator.start()
    logger.info("Log aggregator started")

    # 11. Start distributed tracer
    tracer = get_tracer()
    tracer.start()
    logger.info("Distributed tracer started")

    # 12. Register core services for monitoring
    _register_core_services(monitor)
    
    _initialized = True
    logger.info("GENESIS monitoring system initialized")


async def shutdown_monitoring() -> None:
    """
    Gracefully shutdown all monitoring components.
    
    Call this at application shutdown to:
    1. Stop health monitor
    2. Stop auto-recovery
    3. Stop system metrics agent
    4. Stop resource monitor
    5. Stop WebSocket broadcasts
    6. Flush metrics
    """
    global _initialized
    
    if not _initialized:
        return
    
    logger.info("Shutting down GENESIS monitoring system...")
    
    # Stop system metrics agent
    sys_metrics = get_system_metrics_agent()
    sys_metrics.stop()
    
    # Stop distributed tracer
    tracer = get_tracer()
    tracer.stop()

    # Stop log aggregator
    log_aggregator = get_log_aggregator()
    log_aggregator.stop()
    
    # Stop incident tracker
    incident_tracker = get_incident_tracker()
    incident_tracker.stop()
    
    # Stop auto-recovery
    auto_recovery = get_auto_recovery()
    auto_recovery.stop()
    
    # Stop health monitor
    monitor = get_health_monitor()
    monitor.stop()
    
    # Stop metrics collector
    metrics = get_metrics_collector()
    metrics.stop()
    
    # Stop WebSocket broadcasts
    ws_manager = get_connection_manager()
    ws_manager.stop_background_broadcasts()
    
    # Stop resource monitor
    resource_monitor = get_resource_monitor()
    resource_monitor.stop()
    
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
        "resource_monitor",
        "system_metrics",
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
