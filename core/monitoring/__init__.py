"""
GENESIS Monitoring System

Components:
- HealthMonitor: Tracks all agent health metrics
- ErrorLogger: Centralized error logging
- AlertSystem: ntfy.sh push notifications
- AlertThrottle: Prevents alert fatigue
- Dashboard: Web UI for monitoring
- AgentRegistry: Agent lifecycle management
- MetricsCollector: Time-series metrics storage
- CircuitBreaker: Resilient error handling
- WebSocket: Real-time dashboard updates
"""

# Core imports (no FastAPI dependency)
from .monitor import HealthMonitor, get_health_monitor, AgentMetrics
from .logger import ErrorLogger, get_error_logger, ErrorSeverity
from .alerting import AlertSystem, AlertSeverity, get_alert_system
from .registry import AgentRegistry, get_agent_registry
from .metrics import MetricsCollector, get_metrics_collector, record_metric, record_counter, record_gauge, MetricType
from .circuit_breaker import CircuitBreaker, get_circuit_registry, CircuitConfig, CircuitState, CircuitOpenError, circuit_protected
from .throttle import AlertThrottle, get_alert_throttle, ThrottleConfig, throttled_alert


# Lazy import for FastAPI-dependent modules
def init_monitoring(*args, **kwargs):
    from .startup import init_monitoring as _init
    return _init(*args, **kwargs)

def shutdown_monitoring(*args, **kwargs):
    from .startup import shutdown_monitoring as _shutdown
    return _shutdown(*args, **kwargs)

def get_system_uptime():
    from .startup import get_system_uptime as _uptime
    return _uptime()

def is_monitoring_initialized():
    from .startup import is_monitoring_initialized as _is_init
    return _is_init()


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
    # Alert Throttle
    "AlertThrottle",
    "get_alert_throttle",
    "ThrottleConfig",
    "throttled_alert",
    # Startup
    "init_monitoring",
    "shutdown_monitoring",
    "get_system_uptime",
    "is_monitoring_initialized",
    # Agent Registry
    "AgentRegistry",
    "get_agent_registry",
    # Metrics
    "MetricsCollector",
    "get_metrics_collector",
    "record_metric",
    "record_counter",
    "record_gauge",
    "MetricType",
    # Circuit Breaker
    "CircuitBreaker",
    "get_circuit_registry",
    "CircuitConfig",
    "CircuitState",
    "CircuitOpenError",
    "circuit_protected",
]
