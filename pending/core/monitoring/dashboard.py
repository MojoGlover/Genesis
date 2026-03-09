"""
GENESIS Monitoring Dashboard

FastAPI router providing:
- Real-time agent health status
- Error logs
- Message bus activity
- Manual control buttons (restart, clear queue)
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .monitor import get_health_monitor
from .logger import get_error_logger, ErrorSeverity
from .alerting import get_alert_system, AlertSeverity
from .registry import get_agent_registry, AgentAction
from core.messaging import get_message_bus

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

router = APIRouter(prefix="/dashboard", tags=["monitoring"])


# Request/Response models
class AlertRequest(BaseModel):
    agent: str
    message: str
    severity: str = "degraded"


class AgentActionRequest(BaseModel):
    agent: str
    action: str  # restart, stop, clear_errors


# API Endpoints
@router.get("/health")
async def get_system_health() -> Dict[str, Any]:
    """Get overall system health."""
    monitor = get_health_monitor()
    return monitor.get_all_health()


@router.get("/health/{agent_name}")
async def get_agent_health(agent_name: str) -> Dict[str, Any]:
    """Get health for a specific agent."""
    monitor = get_health_monitor()
    health = monitor.get_agent_health(agent_name)
    if health is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    return health


@router.get("/errors")
async def get_errors(limit: int = 50, severity: str = None) -> Dict[str, Any]:
    """Get recent errors."""
    logger = get_error_logger()

    sev = ErrorSeverity(severity) if severity else None
    errors = logger.get_recent_errors(limit=limit, severity=sev)

    return {
        "errors": [e.to_dict() for e in errors],
        "stats": logger.get_error_stats(),
    }


@router.get("/errors/{agent_name}")
async def get_agent_errors(agent_name: str, limit: int = 20) -> Dict[str, Any]:
    """Get errors for a specific agent."""
    logger = get_error_logger()
    errors = logger.get_agent_errors(agent_name, limit=limit)
    return {"agent": agent_name, "errors": [e.to_dict() for e in errors]}


@router.get("/alerts")
async def get_alerts(limit: int = 20) -> Dict[str, Any]:
    """Get recent alerts."""
    alerts = get_alert_system()
    return {
        "alerts": alerts.get_recent_alerts(limit=limit),
        "config": alerts.get_config(),
    }


@router.post("/alerts/test")
async def test_alert() -> Dict[str, Any]:
    """Send a test alert."""
    alerts = get_alert_system()
    success = alerts.test_alert()
    return {"success": success, "message": "Test alert sent" if success else "Failed to send"}


@router.post("/alerts/send")
async def send_alert(request: AlertRequest) -> Dict[str, Any]:
    """Send a custom alert."""
    alerts = get_alert_system()
    try:
        severity = AlertSeverity(request.severity)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid severity: {request.severity}")

    success = alerts.send_alert(severity, request.agent, request.message)
    return {"success": success}


@router.get("/messages")
async def get_messages(limit: int = 50) -> Dict[str, Any]:
    """Get recent message bus activity."""
    bus = get_message_bus()
    return {
        "messages": bus.get_recent_messages(limit=limit),
        "stats": bus.get_stats(),
    }


@router.post("/agent/action")
async def agent_action(request: AgentActionRequest) -> Dict[str, Any]:
    """
    Perform an action on an agent.
    
    Actions:
    - start: Start a stopped agent
    - stop: Stop a running agent
    - restart: Stop and restart an agent
    - clear_errors: Clear error count and restore healthy status
    """
    registry = get_agent_registry()
    
    try:
        action = AgentAction(request.action)
    except ValueError:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid action: {request.action}. Valid: start, stop, restart, clear_errors"
        )
    
    result = registry.perform_action(request.agent, action)
    
    if not result["success"] and "not found" in result.get("message", ""):
        raise HTTPException(status_code=404, detail=result["message"])
    
    return result


@router.get("/agents/registry")
async def get_registry_info() -> Dict[str, Any]:
    """Get agent registry information."""
    registry = get_agent_registry()
    return {
        "stats": registry.get_registry_stats(),
        "recent_actions": registry.get_action_history(limit=10),
    }


@router.get("/system/resources")
async def get_system_resources() -> Dict[str, Any]:
    """Get system resource usage (CPU, memory, disk)."""
    if not HAS_PSUTIL:
        return {"error": "psutil not installed", "available": False}
    
    from datetime import datetime
    
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count()
    cpu_freq = psutil.cpu_freq()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    process = psutil.Process()
    process_memory = process.memory_info()
    
    return {
        "timestamp": datetime.now().isoformat(),
        "available": True,
        "cpu": {
            "percent": cpu_percent,
            "count": cpu_count,
            "freq_mhz": cpu_freq.current if cpu_freq else None,
        },
        "memory": {
            "total_gb": round(memory.total / (1024**3), 2),
            "available_gb": round(memory.available / (1024**3), 2),
            "used_gb": round(memory.used / (1024**3), 2),
            "percent": memory.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": disk.percent,
        },
        "process": {
            "pid": process.pid,
            "memory_mb": round(process_memory.rss / (1024**2), 2),
            "cpu_percent": process.cpu_percent(),
            "threads": process.num_threads(),
        },
    }


@router.delete("/errors/clear")
async def clear_old_errors(days: int = 30) -> Dict[str, Any]:
    """Clear errors older than specified days."""
    logger = get_error_logger()
    deleted = logger.clear_old_errors(days=days)
    return {"deleted": deleted, "days": days}


@router.get("/", response_class=HTMLResponse)
async def dashboard_ui() -> str:
    """Serve the monitoring dashboard UI."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>GENESIS Dashboard</title>
    <style>
        :root {
            --bg: #0f0f1a;
            --bg-card: #1a1a2e;
            --text: #e8e8f0;
            --text-muted: #8888aa;
            --accent: #4f6df5;
            --success: #34d399;
            --warning: #fbbf24;
            --danger: #f87171;
            --border: #2d2d50;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 20px;
        }
        h1 { margin-bottom: 20px; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }
        .card h2 {
            font-size: 14px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 15px;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .status-healthy { background: var(--success); color: #000; }
        .status-degraded { background: var(--warning); color: #000; }
        .status-critical { background: var(--danger); color: #fff; }
        .agent-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid var(--border);
        }
        .agent-item:last-child { border-bottom: none; }
        .agent-name { font-weight: 600; }
        .agent-meta { font-size: 12px; color: var(--text-muted); }
        .error-item {
            padding: 10px;
            background: rgba(248, 113, 113, 0.1);
            border-left: 3px solid var(--danger);
            margin-bottom: 10px;
            border-radius: 0 8px 8px 0;
        }
        .error-agent { font-weight: 600; font-size: 12px; color: var(--danger); }
        .error-message { margin-top: 5px; font-size: 13px; }
        .error-time { font-size: 11px; color: var(--text-muted); margin-top: 5px; }
        .stat-value {
            font-size: 32px;
            font-weight: 700;
            color: var(--accent);
        }
        .stat-label {
            font-size: 12px;
            color: var(--text-muted);
        }
        .stats-row {
            display: flex;
            gap: 30px;
            margin-bottom: 20px;
        }
        .refresh-btn {
            background: var(--accent);
            color: #fff;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
        }
        .refresh-btn:hover { opacity: 0.9; }
        .empty { color: var(--text-muted); font-style: italic; }
        #last-update { color: var(--text-muted); font-size: 12px; margin-left: 20px; }
    </style>
</head>
<body>
    <div style="display: flex; align-items: center; margin-bottom: 20px;">
        <h1>GENESIS Dashboard</h1>
        <span id="last-update"></span>
        <button class="refresh-btn" onclick="refresh()" style="margin-left: auto;">Refresh</button>
    </div>

    <div class="stats-row" id="summary"></div>

    <div class="grid">
        <div class="card">
            <h2>Agents</h2>
            <div id="agents"><p class="empty">Loading...</p></div>
        </div>

        <div class="card">
            <h2>Recent Errors</h2>
            <div id="errors"><p class="empty">Loading...</p></div>
        </div>

        <div class="card">
            <h2>Message Bus</h2>
            <div id="messages"><p class="empty">Loading...</p></div>
        </div>
    </div>

    <script>
        async function refresh() {
            // Fetch health
            try {
                const health = await fetch('/dashboard/health').then(r => r.json());
                renderHealth(health);
            } catch (e) {
                document.getElementById('agents').innerHTML = '<p class="empty">Error loading health</p>';
            }

            // Fetch errors
            try {
                const errors = await fetch('/dashboard/errors?limit=10').then(r => r.json());
                renderErrors(errors);
            } catch (e) {
                document.getElementById('errors').innerHTML = '<p class="empty">Error loading errors</p>';
            }

            // Fetch messages
            try {
                const msgs = await fetch('/dashboard/messages?limit=10').then(r => r.json());
                renderMessages(msgs);
            } catch (e) {
                document.getElementById('messages').innerHTML = '<p class="empty">Error loading messages</p>';
            }

            document.getElementById('last-update').textContent = 'Updated: ' + new Date().toLocaleTimeString();
        }

        function renderHealth(data) {
            const summary = data.summary;
            document.getElementById('summary').innerHTML = `
                <div><div class="stat-value">${summary.total}</div><div class="stat-label">Total Agents</div></div>
                <div><div class="stat-value" style="color: var(--success)">${summary.healthy}</div><div class="stat-label">Healthy</div></div>
                <div><div class="stat-value" style="color: var(--warning)">${summary.degraded}</div><div class="stat-label">Degraded</div></div>
                <div><div class="stat-value" style="color: var(--danger)">${summary.critical}</div><div class="stat-label">Critical</div></div>
            `;

            const agents = Object.values(data.agents);
            if (agents.length === 0) {
                document.getElementById('agents').innerHTML = '<p class="empty">No agents registered</p>';
                return;
            }

            document.getElementById('agents').innerHTML = agents.map(a => `
                <div class="agent-item">
                    <div>
                        <div class="agent-name">${a.name}</div>
                        <div class="agent-meta">Errors: ${a.error_count} | Success: ${a.success_count}</div>
                    </div>
                    <span class="status-badge status-${a.status}">${a.status}</span>
                </div>
            `).join('');
        }

        function renderErrors(data) {
            if (data.errors.length === 0) {
                document.getElementById('errors').innerHTML = '<p class="empty">No recent errors</p>';
                return;
            }

            document.getElementById('errors').innerHTML = data.errors.slice(0, 5).map(e => `
                <div class="error-item">
                    <div class="error-agent">${e.agent} - ${e.severity}</div>
                    <div class="error-message">${e.message}</div>
                    <div class="error-time">${new Date(e.timestamp).toLocaleString()}</div>
                </div>
            `).join('');
        }

        function renderMessages(data) {
            const stats = data.stats;
            document.getElementById('messages').innerHTML = `
                <div style="margin-bottom: 15px;">
                    <div>Sent: <strong>${stats.messages_sent}</strong></div>
                    <div>Delivered: <strong>${stats.messages_delivered}</strong></div>
                    <div>Queue: <strong>${stats.queue_size}</strong></div>
                </div>
                <div style="font-size: 12px; color: var(--text-muted);">
                    Subscriptions: ${Object.keys(stats.type_subscriptions).length} types,
                    ${stats.agent_subscriptions.length} agents
                </div>
            `;
        }

        // Initial load
        refresh();

        // Auto-refresh every 30 seconds
        setInterval(refresh, 30000);
    </script>
</body>
</html>
"""
