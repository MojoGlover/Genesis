"""
GENESIS Monitoring System

Components:
- HealthMonitor: Tracks all agent health metrics
- ErrorLogger: Centralized error logging
- AlertSystem: ntfy.sh push notifications
- Dashboard: Web UI for monitoring
- AgentRegistry: Agent lifecycle management
"""

from .monitor import HealthMonitor, get_health_monitor, AgentMetrics
from .logger import ErrorLogger, get_error_logger, ErrorSeverity
from .alerting import AlertSystem, AlertSeverity, get_alert_system
from .startup import init_monitoring, shutdown_monitoring, get_system_uptime, is_monitoring_initialized
from .registry import AgentRegistry, get_agent_registry

__all__ = [
    # Health Monitor
    "HealthMonitor",
    "get_health_monitor",
    "AgentMetrics",
    # Error Logger
    "ErrorLogger",
    "get_error_logger",
    "ErrorSeverity",
    # Alert System
    "AlertSystem",
    "AlertSeverity",
    "get_alert_system",
    # Startup
    "init_monitoring",
    "shutdown_monitoring",
    "get_system_uptime",
    "is_monitoring_initialized",
    # Agent Registry
    "AgentRegistry",
    "get_agent_registry",
]
