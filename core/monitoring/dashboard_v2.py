"""
GENESIS Monitoring Dashboard v2

Real-time monitoring dashboard with WebSocket integration.
Shows agent health, metrics, errors, alerts, circuit breakers,
system resources, and auto-recovery status -- all updating live via WebSocket.

API endpoints for dashboard interactions:
- Agent control (restart, stop, clear errors)
- Metrics queries (time-series, sparklines)
- Alert management (test, configure)
- Error management (clear, filter)
- Auto-recovery control (suppress, reset, status)
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from .resource_monitor import get_resource_monitor
from .auto_recovery import get_auto_recovery
from .system_metrics import get_system_metrics_agent
from .incident_tracker import get_incident_tracker, IncidentSeverity
from .log_aggregator import get_log_aggregator, LogLevel
from .trend_analyzer import get_trend_analyzer, AnomalySeverity as TrendAnomalySeverity
from .sla_tracker import get_sla_tracker
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


class RecoveryAgentRequest(BaseModel):
    agent: str


class IncidentCreateRequest(BaseModel):
    title: str
    primary_agent: str
    severity: Optional[str] = "medium"
    tags: Optional[List[str]] = None


class IncidentActionRequest(BaseModel):
    incident_id: str
    resolution: Optional[str] = None
    note: Optional[str] = None
    author: Optional[str] = "user"


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


# -- Resources --

@router.get("/resources")
async def get_resources() -> Dict[str, Any]:
    """Get resource monitor status including active threshold breaches."""
    rm = get_resource_monitor()
    return rm.get_status()


@router.get("/resources/breaches")
async def get_resource_breaches() -> Dict[str, Any]:
    """Get active and historical resource threshold breaches."""
    rm = get_resource_monitor()
    return {
        "active": rm.get_active_breaches(),
        "history": rm.get_breach_history(limit=50),
    }


class ThresholdUpdateRequest(BaseModel):
    metric: str
    warning: Optional[float] = None
    critical: Optional[float] = None


@router.post("/resources/thresholds")
async def update_threshold(request: ThresholdUpdateRequest) -> Dict[str, Any]:
    """Update warning/critical thresholds for a resource metric."""
    rm = get_resource_monitor()
    updated = rm.update_threshold(
        request.metric,
        warning=request.warning,
        critical=request.critical,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"No threshold found for metric: {request.metric}")
    return {"updated": True, "status": rm.get_status()}


# -- Auto Recovery --

@router.get("/recovery")
async def get_recovery_status() -> Dict[str, Any]:
    """Get auto-recovery system status and agent recovery states."""
    recovery = get_auto_recovery()
    return recovery.get_status()


@router.get("/recovery/history")
async def get_recovery_history(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Get recovery attempt history."""
    recovery = get_auto_recovery()
    return {
        "history": recovery.get_history(limit=limit),
    }


@router.post("/recovery/suppress")
async def suppress_recovery(request: RecoveryAgentRequest) -> Dict[str, Any]:
    """Suppress auto-recovery for an agent (e.g., during maintenance)."""
    recovery = get_auto_recovery()
    recovery.suppress_agent(request.agent)
    return {
        "agent": request.agent,
        "suppressed": True,
        "message": f"Auto-recovery suppressed for {request.agent}",
    }


@router.post("/recovery/unsuppress")
async def unsuppress_recovery(request: RecoveryAgentRequest) -> Dict[str, Any]:
    """Re-enable auto-recovery for an agent."""
    recovery = get_auto_recovery()
    recovery.unsuppress_agent(request.agent)
    return {
        "agent": request.agent,
        "suppressed": False,
        "message": f"Auto-recovery re-enabled for {request.agent}",
    }


@router.post("/recovery/reset")
async def reset_recovery(request: RecoveryAgentRequest) -> Dict[str, Any]:
    """Reset recovery state for an agent (e.g., after manual fix)."""
    recovery = get_auto_recovery()
    recovery.reset_agent(request.agent)
    return {
        "agent": request.agent,
        "reset": True,
        "message": f"Recovery state reset for {request.agent}",
    }


# -- System Metrics --

@router.get("/system")
async def get_system_metrics() -> Dict[str, Any]:
    """Get current system metrics snapshot."""
    agent = get_system_metrics_agent()
    return agent.execute_task({"type": "status"})


@router.post("/system/snapshot")
async def trigger_snapshot() -> Dict[str, Any]:
    """Trigger an immediate system metrics snapshot."""
    agent = get_system_metrics_agent()
    return agent.execute_task({"type": "snapshot"})


# -- Incidents --

@router.get("/incidents")
async def get_incidents(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, description="Filter by status: open, investigating, resolved, closed"),
) -> Dict[str, Any]:
    """Get all incidents with optional status filter."""
    tracker = get_incident_tracker()
    if status == "open":
        incidents = tracker.get_open_incidents()
    else:
        incidents = tracker.get_all_incidents(limit=limit)
    return {
        "incidents": incidents,
        "status": tracker.get_status(),
    }


@router.get("/incidents/{incident_id}")
async def get_incident_details(incident_id: str) -> Dict[str, Any]:
    """Get full incident details including event timeline."""
    tracker = get_incident_tracker()
    details = tracker.get_incident_details(incident_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return details


@router.post("/incidents")
async def create_incident(request: IncidentCreateRequest) -> Dict[str, Any]:
    """Manually create a new incident."""
    tracker = get_incident_tracker()
    try:
        severity = IncidentSeverity(request.severity) if request.severity else IncidentSeverity.MEDIUM
    except ValueError:
        severity = IncidentSeverity.MEDIUM
    
    incident = tracker.create_incident(
        title=request.title,
        primary_agent=request.primary_agent,
        severity=severity,
        tags=request.tags,
    )
    return incident.to_dict()


@router.post("/incidents/{incident_id}/investigate")
async def investigate_incident(incident_id: str) -> Dict[str, Any]:
    """Mark an incident as being investigated."""
    tracker = get_incident_tracker()
    success = tracker.investigate_incident(incident_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return {"incident_id": incident_id, "status": "investigating"}


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: str, request: IncidentActionRequest) -> Dict[str, Any]:
    """Resolve an incident with optional resolution note."""
    tracker = get_incident_tracker()
    success = tracker.resolve_incident(incident_id, request.resolution or "")
    if not success:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return {"incident_id": incident_id, "status": "resolved", "resolution": request.resolution}


@router.post("/incidents/{incident_id}/close")
async def close_incident(incident_id: str) -> Dict[str, Any]:
    """Close an incident (final state)."""
    tracker = get_incident_tracker()
    success = tracker.close_incident(incident_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return {"incident_id": incident_id, "status": "closed"}


@router.post("/incidents/{incident_id}/note")
async def add_incident_note(incident_id: str, request: IncidentActionRequest) -> Dict[str, Any]:
    """Add an investigation note to an incident."""
    tracker = get_incident_tracker()
    if not request.note:
        raise HTTPException(status_code=400, detail="Note content is required")
    success = tracker.add_note(incident_id, request.note, request.author or "user")
    if not success:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return {"incident_id": incident_id, "note_added": True}


@router.get("/incidents/agent/{agent}")
async def get_agent_incidents(agent: str) -> Dict[str, Any]:
    """Get all incidents affecting a specific agent."""
    tracker = get_incident_tracker()
    return {"agent": agent, "incidents": tracker.get_agent_incidents(agent)}

# -- Logs --

@router.get("/logs")
async def get_logs(
    limit: int = Query(100, ge=1, le=500),
    agent: Optional[str] = Query(None),
    level: Optional[str] = Query(None, description="Minimum level: debug, info, warning, error, critical"),
    hours: float = Query(1.0, description="Time range in hours"),
) -> Dict[str, Any]:
    """Get recent aggregated logs with optional filters."""
    aggregator = get_log_aggregator()
    
    min_level = None
    if level:
        try:
            min_level = LogLevel(level)
        except ValueError:
            pass
    
    logs = aggregator.get_recent(limit=limit, agent=agent, min_level=min_level)
    return {
        "logs": logs,
        "stats": aggregator.get_stats(),
    }


@router.get("/logs/search")
async def search_logs(
    q: str = Query(..., description="Search query"),
    agent: Optional[str] = Query(None),
    hours: float = Query(1.0),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Full-text search across logs."""
    aggregator = get_log_aggregator()
    entries = aggregator.search(q, agent=agent, hours=hours, limit=limit)
    return {
        "query": q,
        "results": [e.to_dict() for e in entries],
        "count": len(entries),
    }


@router.get("/logs/agents")
async def get_log_agents() -> Dict[str, Any]:
    """Get list of agents with logs."""
    aggregator = get_log_aggregator()
    return {
        "agents": aggregator.get_agents(),
        "stats": aggregator.get_stats(),
    }


@router.get("/logs/agent/{agent}")
async def get_agent_logs(
    agent: str,
    limit: int = Query(100, ge=1, le=500),
    level: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Get logs for a specific agent."""
    aggregator = get_log_aggregator()
    
    min_level = None
    if level:
        try:
            min_level = LogLevel(level)
        except ValueError:
            pass
    
    return {
        "agent": agent,
        "logs": aggregator.get_agent_logs(agent, limit=limit, min_level=min_level),
    }


@router.delete("/logs")
async def clear_logs(agent: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Clear logs, optionally for a specific agent."""
    aggregator = get_log_aggregator()
    count = aggregator.clear(agent=agent)
    return {"cleared": count, "agent": agent}

# -- Trend Analysis / Anomaly Detection --

@router.get("/trends/status")
async def get_trend_analyzer_status() -> Dict[str, Any]:
    """Get trend analyzer status and configuration."""
    analyzer = get_trend_analyzer()
    return analyzer.get_status()


@router.get("/trends/anomalies")
async def get_anomalies(
    limit: int = Query(50, ge=1, le=200),
    agent: Optional[str] = Query(None),
    metric: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Get recent anomalies with optional filters."""
    analyzer = get_trend_analyzer()
    sev = None
    if severity:
        try:
            sev = TrendAnomalySeverity(severity)
        except ValueError:
            pass
    return {
        "anomalies": analyzer.get_recent_anomalies(
            limit=limit, metric_name=metric, agent=agent, severity=sev
        ),
        "status": analyzer.get_status(),
    }


@router.get("/trends/baselines")
async def get_baselines() -> Dict[str, Any]:
    """Get all calculated metric baselines."""
    analyzer = get_trend_analyzer()
    return {"baselines": analyzer.get_all_baselines()}


@router.get("/trends/analyze/{metric}")
async def analyze_metric_trend(
    metric: str,
    agent: Optional[str] = Query(None, description="Agent name"),
    hours: float = Query(1.0, description="Time window in hours"),
) -> Dict[str, Any]:
    """Analyze trend for a specific metric."""
    analyzer = get_trend_analyzer()
    
    if agent:
        trend = analyzer.get_trend(metric, agent, hours=hours)
        baseline = analyzer.get_baseline(metric, agent)
        return {
            "metric": metric,
            "agent": agent,
            "trend": trend.to_dict() if trend else None,
            "baseline": baseline.to_dict() if baseline else None,
        }
    
    # Analyze across all agents
    from .metrics import get_metrics_collector
    collector = get_metrics_collector()
    current = collector.get_current()
    
    results = {}
    agents_for_metric = current.get(metric, {})
    for ag in agents_for_metric:
        trend = analyzer.get_trend(metric, ag, hours=hours)
        baseline = analyzer.get_baseline(metric, ag)
        results[ag] = {
            "trend": trend.to_dict() if trend else None,
            "baseline": baseline.to_dict() if baseline else None,
        }
    
    return {"metric": metric, "agents": results}


class ThresholdUpdateRequest2(BaseModel):
    metric: str
    warning: Optional[float] = None
    critical: Optional[float] = None


@router.post("/trends/thresholds")
async def set_trend_threshold(request: ThresholdUpdateRequest2) -> Dict[str, Any]:
    """Set predictive alerting thresholds."""
    analyzer = get_trend_analyzer()
    analyzer.set_threshold(request.metric, request.warning, request.critical)
    return {"updated": True, "status": analyzer.get_status()}


# -- SLA Tracking --

@router.get("/sla/status")
async def get_sla_status() -> Dict[str, Any]:
    """Get overall SLA tracker status."""
    tracker = get_sla_tracker()
    return tracker.get_status()


@router.get("/sla/all")
async def get_all_sla() -> Dict[str, Any]:
    """Get SLA status for all agents."""
    tracker = get_sla_tracker()
    return tracker.get_all_sla_status()


@router.get("/sla/agent/{agent}")
async def get_agent_sla(agent: str) -> Dict[str, Any]:
    """Get detailed SLA status for a specific agent."""
    tracker = get_sla_tracker()
    return tracker.get_agent_sla(agent)


class SLATargetRequest(BaseModel):
    agent: str
    availability_target: float = 99.9
    response_time_ms: Optional[float] = None


@router.post("/sla/target")
async def set_sla_target(request: SLATargetRequest) -> Dict[str, Any]:
    """Set SLA target for an agent."""
    tracker = get_sla_tracker()
    tracker.set_sla_target(
        request.agent,
        availability_target=request.availability_target,
        response_time_ms=request.response_time_ms,
    )
    return {
        "agent": request.agent,
        "target": tracker.get_sla_target(request.agent).to_dict()
        if tracker.get_sla_target(request.agent) else None,
    }


@router.get("/sla/breaches")
async def get_sla_breaches(
    limit: int = Query(50, ge=1, le=200),
    agent: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Get recent SLA breaches."""
    tracker = get_sla_tracker()
    return {"breaches": tracker.get_recent_breaches(limit=limit, agent=agent)}


@router.get("/sla/history/{agent}")
async def get_availability_history(
    agent: str,
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Get availability state change history for an agent."""
    tracker = get_sla_tracker()
    return {
        "agent": agent,
        "history": tracker.get_availability_history(agent, limit=limit),
    }


class MaintenanceWindowRequest(BaseModel):
    agent: str
    start_time: str  # ISO format
    end_time: str    # ISO format
    description: str = ""


@router.post("/sla/maintenance")
async def create_maintenance_window(request: MaintenanceWindowRequest) -> Dict[str, Any]:
    """Create a scheduled maintenance window."""
    from datetime import datetime
    
    tracker = get_sla_tracker()
    window = tracker.create_maintenance_window(
        agent=request.agent,
        start_time=datetime.fromisoformat(request.start_time),
        end_time=datetime.fromisoformat(request.end_time),
        description=request.description,
    )
    return window.to_dict()


@router.get("/sla/maintenance")
async def get_maintenance_windows(agent: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Get scheduled maintenance windows."""
    tracker = get_sla_tracker()
    return {"windows": tracker.get_maintenance_windows(agent=agent)}


@router.delete("/sla/maintenance/{window_id}")
async def cancel_maintenance_window(window_id: str) -> Dict[str, Any]:
    """Cancel a maintenance window."""
    tracker = get_sla_tracker()
    success = tracker.cancel_maintenance_window(window_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Window {window_id} not found")
    return {"cancelled": True, "window_id": window_id}



# -- Distributed Tracing --

@router.get("/traces/status")
async def get_tracer_status() -> Dict[str, Any]:
    """Get distributed tracer status and configuration."""
    from .trace import get_tracer
    tracer = get_tracer()
    return tracer.get_status()


@router.get("/traces")
async def get_traces(
    limit: int = Query(50, ge=1, le=200),
    agent: Optional[str] = Query(None),
    has_errors: Optional[bool] = Query(None),
) -> Dict[str, Any]:
    """Get recent completed traces with optional filters."""
    from .trace import get_tracer
    tracer = get_tracer()
    return {
        "traces": tracer.get_recent_traces(limit=limit, agent=agent, has_errors=has_errors),
        "status": tracer.get_status(),
    }


@router.get("/traces/active")
async def get_active_traces() -> Dict[str, Any]:
    """Get currently active (in-progress) traces."""
    from .trace import get_tracer
    tracer = get_tracer()
    return {"active": tracer.get_active_traces()}


@router.get("/traces/search")
async def search_traces(
    q: str = Query(..., description="Search query"),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Search traces by name, tags, or span names."""
    from .trace import get_tracer
    tracer = get_tracer()
    return {
        "query": q,
        "results": tracer.search_traces(q, limit=limit),
    }


@router.get("/traces/{trace_id}")
async def get_trace_details(trace_id: str) -> Dict[str, Any]:
    """Get full details for a specific trace."""
    from .trace import get_tracer
    tracer = get_tracer()
    trace = tracer.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")
    return {
        "trace": trace.to_dict(),
        "tree": trace.to_tree(),
    }


@router.delete("/traces")
async def clear_traces() -> Dict[str, Any]:
    """Clear all completed traces."""
    from .trace import get_tracer
    tracer = get_tracer()
    count = tracer.clear()
    return {"cleared": count}


class TracerConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    sample_rate: Optional[float] = None
    max_traces: Optional[int] = None


@router.post("/traces/configure")
async def configure_tracer(request: TracerConfigRequest) -> Dict[str, Any]:
    """Update tracer configuration."""
    from .trace import get_tracer
    tracer = get_tracer()
    tracer.configure(
        enabled=request.enabled,
        sample_rate=request.sample_rate,
        max_traces=request.max_traces,
    )
    return {"config": tracer.get_status()}
