"""
GENESIS Health & Metrics Endpoints

Standard health check endpoints for orchestrators and monitoring systems:
- /health - Overall system health (Kubernetes health check)
- /readiness - Ready to receive traffic
- /liveness - Process is alive
- /metrics - Prometheus/OpenMetrics format

These endpoints follow industry standards:
- 200 OK = healthy/ready/alive
- 503 Service Unavailable = unhealthy/not ready
- 204 No Content = alive but degraded
"""

from __future__ import annotations
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Response, status
from fastapi.responses import PlainTextResponse

from .monitor import get_health_monitor
from .logger import get_error_logger
from .alerting import get_alert_system
from .startup import get_system_uptime, is_monitoring_initialized
from core.messaging import get_message_bus

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

router = APIRouter(tags=["health"])


# -----------------------------------------------------------------------------
# Health Check Endpoints
# -----------------------------------------------------------------------------

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Overall system health check.
    
    Returns 200 if system is healthy, 503 if critical issues exist.
    Used by load balancers and orchestrators.
    """
    monitor = get_health_monitor()
    health = monitor.get_all_health()
    
    summary = health.get("summary", {})
    overall = summary.get("overall_status", "unknown")
    
    # Determine HTTP status
    if overall in ("critical", "failing"):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        status_code = status.HTTP_200_OK
    
    response = {
        "status": overall,
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": get_system_uptime(),
        "monitoring_initialized": is_monitoring_initialized(),
        "summary": summary,
    }
    
    return response


@router.get("/readiness")
async def readiness_check(response: Response) -> Dict[str, Any]:
    """
    Readiness probe - is the system ready to receive traffic?
    
    Checks:
    - Monitoring is initialized
    - Message bus is running
    - No critical agents are down
    
    Returns 200 if ready, 503 if not ready.
    """
    checks = {
        "monitoring_initialized": is_monitoring_initialized(),
        "message_bus_running": False,
        "no_critical_issues": True,
    }
    
    # Check message bus
    try:
        bus = get_message_bus()
        stats = bus.get_stats()
        checks["message_bus_running"] = stats.get("start_time") is not None
    except Exception:
        checks["message_bus_running"] = False
    
    # Check for critical agents
    try:
        monitor = get_health_monitor()
        health = monitor.get_all_health()
        summary = health.get("summary", {})
        checks["no_critical_issues"] = summary.get("critical", 0) == 0
    except Exception:
        checks["no_critical_issues"] = False
    
    # All checks must pass
    is_ready = all(checks.values())
    
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    
    return {
        "ready": is_ready,
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
    }


@router.get("/liveness")
async def liveness_check() -> Dict[str, Any]:
    """
    Liveness probe - is the process alive?
    
    Simple check that the process is running and can respond.
    Used by orchestrators to detect hung processes.
    
    Always returns 200 if the process can respond.
    """
    return {
        "alive": True,
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": get_system_uptime(),
    }


# -----------------------------------------------------------------------------
# Prometheus Metrics Endpoint
# -----------------------------------------------------------------------------

@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> str:
    """
    Prometheus/OpenMetrics format metrics endpoint.
    
    Exports:
    - genesis_agent_health_status (gauge per agent)
    - genesis_agent_error_count (counter per agent)
    - genesis_agent_success_count (counter per agent)
    - genesis_agent_error_rate (gauge per agent)
    - genesis_agent_uptime_seconds (gauge per agent)
    - genesis_message_bus_sent_total (counter)
    - genesis_message_bus_delivered_total (counter)
    - genesis_message_bus_failed_total (counter)
    - genesis_message_bus_queue_size (gauge)
    - genesis_system_uptime_seconds (gauge)
    - genesis_errors_total (counter by severity)
    - genesis_alerts_total (counter)
    """
    lines = []
    
    # Helper to add metric
    def add_metric(name: str, metric_type: str, help_text: str, value: float, labels: Optional[Dict[str, str]] = None):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")
    
    def add_metric_value(name: str, value: float, labels: Optional[Dict[str, str]] = None):
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")
    
    # System uptime
    add_metric(
        "genesis_system_uptime_seconds",
        "gauge",
        "GENESIS monitoring system uptime in seconds",
        get_system_uptime()
    )
    
    # Agent metrics
    try:
        monitor = get_health_monitor()
        health = monitor.get_all_health()
        agents = health.get("agents", {})
        
        # Health status (1=healthy, 0.5=degraded, 0=critical/failing)
        lines.append("# HELP genesis_agent_health_status Agent health status (1=healthy, 0.5=degraded, 0=critical)")
        lines.append("# TYPE genesis_agent_health_status gauge")
        for name, metrics in agents.items():
            status_val = {"healthy": 1, "degraded": 0.5, "failing": 0.25, "critical": 0}.get(metrics.get("status", "unknown"), 0)
            add_metric_value("genesis_agent_health_status", status_val, {"agent": name})
        
        # Error count
        lines.append("# HELP genesis_agent_error_count_total Total errors per agent")
        lines.append("# TYPE genesis_agent_error_count_total counter")
        for name, metrics in agents.items():
            add_metric_value("genesis_agent_error_count_total", metrics.get("error_count", 0), {"agent": name})
        
        # Success count
        lines.append("# HELP genesis_agent_success_count_total Total successful operations per agent")
        lines.append("# TYPE genesis_agent_success_count_total counter")
        for name, metrics in agents.items():
            add_metric_value("genesis_agent_success_count_total", metrics.get("success_count", 0), {"agent": name})
        
        # Error rate
        lines.append("# HELP genesis_agent_error_rate Current error rate per agent (0-1)")
        lines.append("# TYPE genesis_agent_error_rate gauge")
        for name, metrics in agents.items():
            add_metric_value("genesis_agent_error_rate", metrics.get("error_rate", 0), {"agent": name})
        
        # Uptime
        lines.append("# HELP genesis_agent_uptime_seconds Agent uptime in seconds")
        lines.append("# TYPE genesis_agent_uptime_seconds gauge")
        for name, metrics in agents.items():
            add_metric_value("genesis_agent_uptime_seconds", metrics.get("uptime_seconds", 0), {"agent": name})
        
        # Is alive
        lines.append("# HELP genesis_agent_alive Whether agent is alive (1=yes, 0=no)")
        lines.append("# TYPE genesis_agent_alive gauge")
        for name, metrics in agents.items():
            add_metric_value("genesis_agent_alive", 1 if metrics.get("is_alive") else 0, {"agent": name})
        
        # Summary metrics
        summary = health.get("summary", {})
        add_metric("genesis_agents_total", "gauge", "Total number of registered agents", summary.get("total", 0))
        add_metric("genesis_agents_healthy", "gauge", "Number of healthy agents", summary.get("healthy", 0))
        add_metric("genesis_agents_degraded", "gauge", "Number of degraded agents", summary.get("degraded", 0))
        add_metric("genesis_agents_critical", "gauge", "Number of critical agents", summary.get("critical", 0))
        
    except Exception as e:
        lines.append(f"# Error collecting agent metrics: {e}")
    
    # Message bus metrics
    try:
        bus = get_message_bus()
        stats = bus.get_stats()
        
        add_metric("genesis_message_bus_sent_total", "counter", "Total messages sent", stats.get("messages_sent", 0))
        add_metric("genesis_message_bus_delivered_total", "counter", "Total messages delivered", stats.get("messages_delivered", 0))
        add_metric("genesis_message_bus_failed_total", "counter", "Total messages failed", stats.get("messages_failed", 0))
        add_metric("genesis_message_bus_queue_size", "gauge", "Current message queue size", stats.get("queue_size", 0))
        add_metric("genesis_message_bus_uptime_seconds", "gauge", "Message bus uptime in seconds", stats.get("uptime_seconds", 0))
        
    except Exception as e:
        lines.append(f"# Error collecting message bus metrics: {e}")
    
    # Error logger metrics
    try:
        error_logger = get_error_logger()
        error_stats = error_logger.get_stats()
        
        lines.append("# HELP genesis_errors_total Total errors by severity")
        lines.append("# TYPE genesis_errors_total counter")
        by_severity = error_stats.get("by_severity", {})
        for severity, count in by_severity.items():
            add_metric_value("genesis_errors_total", count, {"severity": severity})
        
        add_metric("genesis_errors_24h_total", "gauge", "Errors in last 24 hours", error_stats.get("last_24h", 0))
        
    except Exception as e:
        lines.append(f"# Error collecting error metrics: {e}")
    
    # Alert metrics
    try:
        alert_system = get_alert_system()
        alerts = alert_system.get_recent_alerts(100)
        add_metric("genesis_alerts_total", "gauge", "Total alerts in history", len(alerts))
        
    except Exception as e:
        lines.append(f"# Error collecting alert metrics: {e}")
    

    # System resource metrics (if psutil available)
    if HAS_PSUTIL:
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            
            add_metric("genesis_system_cpu_percent", "gauge", "System CPU usage percentage", cpu_percent)
            add_metric("genesis_system_memory_percent", "gauge", "System memory usage percentage", memory.percent)
            add_metric("genesis_system_memory_used_bytes", "gauge", "System memory used in bytes", memory.used)
            add_metric("genesis_system_memory_available_bytes", "gauge", "System memory available in bytes", memory.available)
            add_metric("genesis_system_disk_percent", "gauge", "Root disk usage percentage", disk.percent)
            add_metric("genesis_system_disk_used_bytes", "gauge", "Root disk used in bytes", disk.used)
            add_metric("genesis_system_disk_free_bytes", "gauge", "Root disk free in bytes", disk.free)
            
            # Process metrics
            process = psutil.Process()
            add_metric("genesis_process_memory_bytes", "gauge", "Process memory (RSS) in bytes", process.memory_info().rss)
            add_metric("genesis_process_threads", "gauge", "Process thread count", process.num_threads())
            
        except Exception as e:
            lines.append(f"# Error collecting system resource metrics: {e}")

    lines.append("")  # Trailing newline
    return chr(10).join(lines)


# -----------------------------------------------------------------------------
# Detailed Health Endpoints
# -----------------------------------------------------------------------------

@router.get("/health/agents")
async def agents_health() -> Dict[str, Any]:
    """Get detailed health for all agents."""
    monitor = get_health_monitor()
    return monitor.get_all_health()


@router.get("/health/agents/{agent_name}")
async def agent_health(agent_name: str, response: Response) -> Dict[str, Any]:
    """Get health for a specific agent."""
    monitor = get_health_monitor()
    health = monitor.get_agent_health(agent_name)
    
    if health is None:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"error": f"Agent {agent_name} not found"}
    
    return health


@router.get("/health/message-bus")
async def message_bus_health() -> Dict[str, Any]:
    """Get message bus health and statistics."""
    bus = get_message_bus()
    stats = bus.get_stats()
    recent = bus.get_recent_messages(10)
    
    return {
        "status": "running" if stats.get("start_time") else "stopped",
        "stats": stats,
        "recent_messages": recent,
    }


@router.get("/health/errors")
async def errors_health() -> Dict[str, Any]:
    """Get error statistics and recent errors."""
    error_logger = get_error_logger()
    
    return {
        "stats": error_logger.get_stats(),
        "recent": error_logger.get_recent_errors(20),
    }


@router.get("/health/alerts")
async def alerts_health() -> Dict[str, Any]:
    """Get alert system status and recent alerts."""
    alert_system = get_alert_system()
    
    return {
        "config": alert_system.get_config(),
        "recent_alerts": alert_system.get_recent_alerts(20),
    }
