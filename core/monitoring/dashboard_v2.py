"""
GENESIS Monitoring Dashboard v2

Real-time monitoring dashboard with WebSocket integration.
Shows agent health, metrics, errors, alerts, circuit breakers,
and system resources -- all updating live via WebSocket.

API endpoints for dashboard interactions:
- Agent control (restart, stop, clear errors)
- Metrics queries (time-series, sparklines)
- Alert management (test, configure)
- Error management (clear, filter)
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .monitor import get_health_monitor
from .logger import get_error_logger, ErrorSeverity
from .alerting import get_alert_system, AlertSeverity
from .registry import get_agent_registry, AgentAction
from .metrics import get_metrics_collector, Aggregation
from .circuit_breaker import get_circuit_registry
from .throttle import get_alert_throttle
from core.messaging import get_message_bus

router = APIRouter(prefix="/monitor", tags=["monitoring-v2"])

_TEMPLATE_DIR = Path(__file__).parent / "templates"


# -- Request models --

class AgentActionRequest(BaseModel):
    agent: str
    action: str  # start, stop, restart, clear_errors


class AlertTestRequest(BaseModel):
    message: str = "Test alert from GENESIS dashboard"


class AlertConfigRequest(BaseModel):
    ntfy_topic: Optional[str] = None
    enabled: Optional[bool] = None
    min_severity: Optional[str] = None


# -- Dashboard UI --

def _load_template() -> str:
    path = _TEMPLATE_DIR / "monitor.html"
    if path.exists():
        return path.read_text()
    return "<html><body><h1>GENESIS Monitor</h1><p>Template not found.</p></body></html>"


@router.get("/", response_class=HTMLResponse)
async def realtime_dashboard() -> str:
    """Serve the real-time monitoring dashboard."""
    return _load_template()


# -- Agent Control --

@router.post("/agents/action")
async def agent_action(request: AgentActionRequest) -> Dict[str, Any]:
    """Perform an action on an agent (start, stop, restart, clear_errors)."""
    registry = get_agent_registry()

    try:
        action = AgentAction(request.action)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action: {request.action}. Valid: start, stop, restart, clear_errors",
        )

    result = registry.perform_action(request.agent, action)

    if not result["success"] and "not found" in result.get("message", ""):
        raise HTTPException(status_code=404, detail=result["message"])

    return result


@router.get("/agents")
async def list_agents() -> Dict[str, Any]:
    """List all registered agents with health."""
    monitor = get_health_monitor()
    registry = get_agent_registry()
    return {
        "health": monitor.get_all_health(),
        "registry": registry.get_registry_stats(),
        "recent_actions": registry.get_action_history(limit=20),
    }


# -- Metrics --

@router.get("/metrics/current")
async def get_current_metrics(agent: Optional[str] = None) -> Dict[str, Any]:
    """Get latest values of all metrics, optionally filtered by agent."""
    collector = get_metrics_collector()
    return {
        "metrics": collector.get_current(agent),
        "stats": collector.get_stats(),
    }


@router.get("/metrics/query")
async def query_metrics(
    name: str = Query(..., description="Metric name"),
    agent: Optional[str] = Query(None, description="Filter by agent"),
    hours: float = Query(1.0, description="Time range in hours"),
    aggregation: str = Query("avg", description="Aggregation: avg, sum, min, max, count"),
) -> Dict[str, Any]:
    """Query time-series metric data for sparklines/charts."""
    collector = get_metrics_collector()

    try:
        agg = Aggregation(aggregation)
    except ValueError:
        agg = Aggregation.AVG

    series_list = collector.query(name, agent, hours=hours, aggregation=agg)
    return {
        "name": name,
        "hours": hours,
        "aggregation": aggregation,
        "series": [s.to_dict() for s in series_list],
    }


@router.get("/metrics/names")
async def get_metric_names() -> Dict[str, Any]:
    """List all known metric names and agents."""
    collector = get_metrics_collector()
    current = collector.get_current()
    names = sorted(current.keys())
    agents = set()
    for metric_agents in current.values():
        agents.update(metric_agents.keys())
    return {
        "names": names,
        "agents": sorted(agents),
    }


# -- Errors --

@router.get("/errors")
async def get_errors(
    limit: int = Query(50, ge=1, le=500),
    severity: Optional[str] = Query(None),
    agent: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Get recent errors with optional filters."""
    error_logger = get_error_logger()

    sev = ErrorSeverity(severity) if severity else None

    if agent:
        errors = error_logger.get_agent_errors(agent, limit=limit)
    else:
        errors = error_logger.get_recent_errors(limit=limit, severity=sev)

    return {
        "errors": [e.to_dict() for e in errors],
        "stats": error_logger.get_error_stats(),
    }


@router.delete("/errors")
async def clear_errors(days: int = Query(30, ge=1)) -> Dict[str, Any]:
    """Clear errors older than specified days."""
    error_logger = get_error_logger()
    deleted = error_logger.clear_old_errors(days=days)
    return {"deleted": deleted, "days": days}


# -- Alerts --

@router.get("/alerts")
async def get_alerts(limit: int = Query(20, ge=1, le=200)) -> Dict[str, Any]:
    """Get recent alerts and alert system config."""
    alerts = get_alert_system()
    throttle = get_alert_throttle()
    return {
        "alerts": alerts.get_recent_alerts(limit=limit),
        "config": alerts.get_config(),
        "throttle": throttle.get_stats(),
    }


@router.post("/alerts/test")
async def test_alert(request: AlertTestRequest = None) -> Dict[str, Any]:
    """Send a test alert via ntfy.sh."""
    alerts = get_alert_system()
    success = alerts.test_alert()
    return {"success": success, "message": "Test alert sent" if success else "Failed to send"}


@router.post("/alerts/configure")
async def configure_alerts(request: AlertConfigRequest) -> Dict[str, Any]:
    """Update alert system configuration."""
    alerts = get_alert_system()
    kwargs = {}
    if request.ntfy_topic is not None:
        kwargs["ntfy_topic"] = request.ntfy_topic
    if request.enabled is not None:
        kwargs["enabled"] = request.enabled
    if request.min_severity is not None:
        kwargs["min_severity"] = AlertSeverity(request.min_severity)
    if kwargs:
        alerts.configure(**kwargs)
    return {"config": alerts.get_config()}


# -- Circuit Breakers --

@router.get("/circuits")
async def get_circuits() -> Dict[str, Any]:
    """Get all circuit breaker states."""
    registry = get_circuit_registry()
    return {
        "circuits": registry.get_all_status(),
        "open": [name for name, _ in registry.get_open_circuits()],
    }


@router.post("/circuits/{name}/reset")
async def reset_circuit(name: str) -> Dict[str, Any]:
    """Reset a specific circuit breaker."""
    registry = get_circuit_registry()
    breaker = registry.get(name)
    breaker.reset()
    return {"name": name, "state": breaker.get_status()}


# -- Message Bus --

@router.get("/messages")
async def get_messages(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Get recent message bus activity."""
    bus = get_message_bus()
    return {
        "messages": bus.get_recent_messages(limit=limit),
        "stats": bus.get_stats(),
    }
