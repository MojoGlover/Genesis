"""
GENESIS Resource Monitor

Threshold-based system resource watchdog that triggers alerts when
CPU, memory, disk, or process metrics breach configurable limits.

Complements:
- SystemMetricsAgent: collects raw metrics into time-series storage
- HealthMonitor: tracks agent heartbeats and health status
- ResourceMonitor (this): watches resource levels against thresholds
  and fires alerts through the alert system

Integrates with:
- MetricsCollector: reads current metric values
- AlertSystem + AlertThrottle: sends throttled notifications
- Message bus: publishes WARNING messages on threshold breaches
- HealthMonitor: registered as "resource_monitor" agent
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.framework.agent_base import AgentBase, AgentConfig, AutonomyLevel
from core.messaging.message import MessageType, Message, HealthStatus
from core.monitoring.alerting import AlertSeverity, get_alert_system
from core.monitoring.metrics import get_metrics_collector, record_gauge
from core.monitoring.throttle import get_alert_throttle

logger = logging.getLogger(__name__)

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

AGENT_NAME = "resource_monitor"


class ThresholdLevel(Enum):
    """Severity of a threshold breach."""
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ResourceThreshold:
    """A single threshold definition for a resource metric."""
    metric: str                    # Metric name (e.g., "cpu_percent")
    warning: float                 # Warning threshold value
    critical: float                # Critical threshold value
    comparison: str = ">"          # ">" or "<"
    sustained_seconds: float = 0   # Must breach for this long before alerting
    description: str = ""

    def check(self, value: float) -> Optional[ThresholdLevel]:
        """Check a value against this threshold. Returns level or None."""
        if self.comparison == ">":
            if value >= self.critical:
                return ThresholdLevel.CRITICAL
            if value >= self.warning:
                return ThresholdLevel.WARNING
        elif self.comparison == "<":
            if value <= self.critical:
                return ThresholdLevel.CRITICAL
            if value <= self.warning:
                return ThresholdLevel.WARNING
        return None


@dataclass
class ThresholdBreach:
    """Record of a threshold breach event."""
    metric: str
    level: ThresholdLevel
    value: float
    threshold_value: float
    timestamp: datetime
    sustained: bool = False
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "level": self.level.value,
            "value": round(self.value, 2),
            "threshold": self.threshold_value,
            "timestamp": self.timestamp.isoformat(),
            "sustained": self.sustained,
            "description": self.description,
        }


@dataclass
class ResourceMonitorConfig:
    """Configuration for the resource monitor."""
    check_interval: float = 15.0       # Seconds between checks
    history_size: int = 200            # Max breach records kept in memory
    thresholds: List[ResourceThreshold] = field(default_factory=list)

    def __post_init__(self):
        if not self.thresholds:
            self.thresholds = self._default_thresholds()

    @staticmethod
    def _default_thresholds() -> List[ResourceThreshold]:
        return [
            ResourceThreshold(
                metric="cpu_percent",
                warning=80.0,
                critical=95.0,
                sustained_seconds=30,
                description="Overall CPU usage",
            ),
            ResourceThreshold(
                metric="mem_percent",
                warning=85.0,
                critical=95.0,
                description="System memory usage",
            ),
            ResourceThreshold(
                metric="disk_percent",
                warning=85.0,
                critical=95.0,
                description="Root disk usage",
            ),
            ResourceThreshold(
                metric="swap_percent",
                warning=50.0,
                critical=80.0,
                description="Swap usage",
            ),
            ResourceThreshold(
                metric="proc_memory_mb",
                warning=1024.0,
                critical=2048.0,
                description="GENESIS process memory",
            ),
            ResourceThreshold(
                metric="load_avg_1m_per_core",
                warning=1.5,
                critical=3.0,
                sustained_seconds=60,
                description="Load average per CPU core (1m)",
            ),
            ResourceThreshold(
                metric="disk_available_gb",
                warning=5.0,
                critical=1.0,
                comparison="<",
                description="Available disk space",
            ),
            ResourceThreshold(
                metric="mem_available_mb",
                warning=512.0,
                critical=256.0,
                comparison="<",
                description="Available system memory",
            ),
        ]


def _collect_resource_snapshot() -> Dict[str, float]:
    """Collect current resource values for threshold checking."""
    if not HAS_PSUTIL:
        return {}

    values: Dict[str, float] = {}

    try:
        values["cpu_percent"] = psutil.cpu_percent(interval=0)
    except Exception:
        pass

    try:
        mem = psutil.virtual_memory()
        values["mem_percent"] = mem.percent
        values["mem_available_mb"] = round(mem.available / (1024 ** 2), 1)
    except Exception:
        pass

    try:
        swap = psutil.swap_memory()
        values["swap_percent"] = swap.percent
    except Exception:
        pass

    try:
        disk = psutil.disk_usage("/")
        values["disk_percent"] = disk.percent
        values["disk_available_gb"] = round((disk.total - disk.used) / (1024 ** 3), 2)
    except Exception:
        pass

    try:
        load = os.getloadavg()
        cpu_count = psutil.cpu_count() or 1
        values["load_avg_1m"] = load[0]
        values["load_avg_1m_per_core"] = round(load[0] / cpu_count, 2)
    except Exception:
        pass

    try:
        proc = psutil.Process()
        values["proc_memory_mb"] = round(proc.memory_info().rss / (1024 ** 2), 1)
        values["proc_cpu_percent"] = proc.cpu_percent()
        values["proc_threads"] = float(proc.num_threads())
        try:
            values["proc_open_files"] = float(len(proc.open_files()))
        except (psutil.AccessDenied, OSError):
            pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return values


class ResourceMonitor(AgentBase):
    """
    Watches system resource levels against configurable thresholds
    and fires alerts when breached.

    Runs as an agent on a configurable interval (default 15s). When a
    metric crosses a warning or critical threshold, it sends an alert
    through the AlertSystem (with throttling) and publishes a WARNING
    message on the message bus.

    Usage:
        monitor = get_resource_monitor()
        monitor.start()

        # Check current status
        status = monitor.get_status()

        # Get active breaches
        breaches = monitor.get_active_breaches()
    """

    def __init__(self, config: Optional[ResourceMonitorConfig] = None):
        self._rm_config = config or ResourceMonitorConfig()

        agent_config = AgentConfig(
            agent_name=AGENT_NAME,
            mission="Monitor system resources against thresholds and alert on breaches",
            autonomy_level=AutonomyLevel.FULLY_AUTONOMOUS,
            capabilities={
                "threshold_monitoring": True,
                "alert_integration": True,
                "sustained_breach_detection": True,
            },
            tools=["psutil"],
            heartbeat_interval=self._rm_config.check_interval,
            error_threshold=10,
            alert_on_failure=False,
        )
        super().__init__(agent_config)

        self._check_thread: Optional[threading.Thread] = None
        self._breach_history: List[ThresholdBreach] = []
        self._active_breaches: Dict[str, ThresholdBreach] = {}
        self._sustained_tracker: Dict[str, datetime] = {}  # metric -> first breach time
        self._check_count = 0
        self._on_breach_callbacks: List[Callable[[ThresholdBreach], None]] = []

    # -- Public API --

    def get_status(self) -> Dict[str, Any]:
        """Get current resource monitor status."""
        return {
            "running": self._running,
            "check_count": self._check_count,
            "check_interval": self._rm_config.check_interval,
            "psutil_available": HAS_PSUTIL,
            "active_breaches": {
                k: v.to_dict() for k, v in self._active_breaches.items()
            },
            "thresholds": [
                {
                    "metric": t.metric,
                    "warning": t.warning,
                    "critical": t.critical,
                    "comparison": t.comparison,
                    "sustained_seconds": t.sustained_seconds,
                    "description": t.description,
                }
                for t in self._rm_config.thresholds
            ],
            "breach_count": len(self._breach_history),
        }

    def get_active_breaches(self) -> List[Dict[str, Any]]:
        """Get currently active threshold breaches."""
        return [b.to_dict() for b in self._active_breaches.values()]

    def get_breach_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent breach history."""
        return [b.to_dict() for b in self._breach_history[-limit:]]

    def update_threshold(self, metric: str, warning: Optional[float] = None,
                         critical: Optional[float] = None) -> bool:
        """Update thresholds for a specific metric."""
        for t in self._rm_config.thresholds:
            if t.metric == metric:
                if warning is not None:
                    t.warning = warning
                if critical is not None:
                    t.critical = critical
                logger.info(f"Updated threshold for {metric}: warning={t.warning}, critical={t.critical}")
                return True
        return False

    def add_threshold(self, threshold: ResourceThreshold) -> None:
        """Add a new threshold to monitor."""
        self._rm_config.thresholds = [
            t for t in self._rm_config.thresholds if t.metric != threshold.metric
        ]
        self._rm_config.thresholds.append(threshold)
        logger.info(f"Added threshold for {threshold.metric}")

    def on_breach(self, callback: Callable[[ThresholdBreach], None]) -> None:
        """Register a callback for threshold breaches."""
        self._on_breach_callbacks.append(callback)

    # -- AgentBase implementation --

    def execute_task(self, task: Dict[str, Any]) -> Any:
        task_type = task.get("type", "check")

        if task_type == "check":
            return self._run_check()
        if task_type == "status":
            return self.get_status()
        if task_type == "breaches":
            return self.get_active_breaches()
        if task_type == "history":
            return self.get_breach_history(limit=task.get("limit", 50))

        return {"error": f"Unknown task type: {task_type}"}

    def get_health_details(self) -> Dict[str, Any]:
        details = super().get_health_details()
        details.update({
            "check_count": self._check_count,
            "active_breaches": len(self._active_breaches),
            "breach_history_size": len(self._breach_history),
            "psutil_available": HAS_PSUTIL,
        })
        return details

    # -- Lifecycle --

    def start(self) -> None:
        super().start()
        self._check_thread = threading.Thread(
            target=self._check_loop, daemon=True, name="resource-monitor"
        )
        self._check_thread.start()
        logger.info(
            f"{self.name}: Monitoring {len(self._rm_config.thresholds)} resource thresholds "
            f"every {self._rm_config.check_interval}s"
        )

    def stop(self) -> None:
        super().stop()
        if self._check_thread:
            self._check_thread.join(timeout=2.0)
        logger.info(f"{self.name}: Stopped after {self._check_count} checks")

    # -- Core logic --

    def _check_loop(self) -> None:
        """Background loop that checks resource thresholds."""
        while self._running:
            try:
                self._run_check()
                self._check_count += 1
                self._stats["tasks_completed"] += 1
            except Exception as e:
                self.handle_error(e, {"phase": "resource_check"})

            # Sleep in small increments for responsive shutdown
            deadline = time.monotonic() + self._rm_config.check_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.5)

    def _run_check(self) -> Dict[str, Any]:
        """Run a single resource check cycle."""
        values = _collect_resource_snapshot()
        if not values:
            return {"error": "psutil not available"}

        now = datetime.now()
        new_breaches: List[ThresholdBreach] = []
        cleared: List[str] = []

        for threshold in self._rm_config.thresholds:
            value = values.get(threshold.metric)
            if value is None:
                continue

            level = threshold.check(value)

            if level is not None:
                # Check sustained requirement
                sustained = True
                if threshold.sustained_seconds > 0:
                    first_seen = self._sustained_tracker.get(threshold.metric)
                    if first_seen is None:
                        self._sustained_tracker[threshold.metric] = now
                        sustained = False
                    else:
                        elapsed = (now - first_seen).total_seconds()
                        sustained = elapsed >= threshold.sustained_seconds

                if sustained:
                    threshold_val = (
                        threshold.critical if level == ThresholdLevel.CRITICAL
                        else threshold.warning
                    )
                    breach = ThresholdBreach(
                        metric=threshold.metric,
                        level=level,
                        value=value,
                        threshold_value=threshold_val,
                        timestamp=now,
                        sustained=threshold.sustained_seconds > 0,
                        description=threshold.description,
                    )

                    # Only alert if this is a new breach or escalation
                    existing = self._active_breaches.get(threshold.metric)
                    is_new = existing is None
                    is_escalation = (
                        existing is not None
                        and level == ThresholdLevel.CRITICAL
                        and existing.level == ThresholdLevel.WARNING
                    )

                    self._active_breaches[threshold.metric] = breach

                    if is_new or is_escalation:
                        new_breaches.append(breach)
                        self._record_breach(breach)
            else:
                # Metric is within normal range -- clear any active breach
                if threshold.metric in self._active_breaches:
                    cleared.append(threshold.metric)
                    del self._active_breaches[threshold.metric]
                if threshold.metric in self._sustained_tracker:
                    del self._sustained_tracker[threshold.metric]

        # Record monitoring metrics
        record_gauge("resource_monitor.active_breaches", AGENT_NAME,
                     float(len(self._active_breaches)))
        record_gauge("resource_monitor.checks", AGENT_NAME,
                     float(self._check_count))

        # Fire alerts for new breaches
        for breach in new_breaches:
            self._fire_alert(breach)

        # Broadcast status on message bus if we have breaches
        if self._bus and (new_breaches or cleared):
            health = HealthStatus.HEALTHY
            if any(b.level == ThresholdLevel.CRITICAL for b in self._active_breaches.values()):
                health = HealthStatus.CRITICAL
            elif self._active_breaches:
                health = HealthStatus.DEGRADED

            msg = Message(
                type=MessageType.WARNING if self._active_breaches else MessageType.STATUS_REPORT,
                sender=self.name,
                payload={
                    "status": health.value,
                    "active_breaches": [b.to_dict() for b in self._active_breaches.values()],
                    "new_breaches": [b.to_dict() for b in new_breaches],
                    "cleared": cleared,
                },
            )
            self._bus.publish(msg)

        return {
            "values": values,
            "active_breaches": len(self._active_breaches),
            "new_breaches": len(new_breaches),
            "cleared": cleared,
        }

    def _record_breach(self, breach: ThresholdBreach) -> None:
        """Record a breach in history and notify callbacks."""
        self._breach_history.append(breach)
        if len(self._breach_history) > self._rm_config.history_size:
            self._breach_history = self._breach_history[-self._rm_config.history_size:]

        for callback in self._on_breach_callbacks:
            try:
                callback(breach)
            except Exception as e:
                logger.error(f"Breach callback error: {e}")

    def _fire_alert(self, breach: ThresholdBreach) -> None:
        """Send an alert for a threshold breach, respecting throttling."""
        throttle = get_alert_throttle()
        should_send, reason = throttle.should_send(
            AGENT_NAME, f"{breach.metric}:{breach.level.value}", breach.level.value
        )

        if not should_send:
            logger.debug(f"Alert throttled for {breach.metric}: {reason}")
            return

        severity = (
            AlertSeverity.CRITICAL if breach.level == ThresholdLevel.CRITICAL
            else AlertSeverity.DEGRADED
        )

        sustained_note = " (sustained)" if breach.sustained else ""
        message = (
            f"{breach.description or breach.metric}: "
            f"{breach.value:.1f} {'>' if breach.value >= breach.threshold_value else '<'} "
            f"{breach.threshold_value:.1f} threshold{sustained_note}"
        )

        alert_system = get_alert_system()
        alert_system.send_alert(
            severity=severity,
            agent=AGENT_NAME,
            message=message,
            title=f"Resource {breach.level.value.upper()}: {breach.metric}",
            context={
                "metric": breach.metric,
                "value": breach.value,
                "threshold": breach.threshold_value,
                "level": breach.level.value,
            },
        )


# -- Singleton --

_instance: Optional[ResourceMonitor] = None
_instance_lock = threading.Lock()


def get_resource_monitor(
    config: Optional[ResourceMonitorConfig] = None,
) -> ResourceMonitor:
    """Get the singleton ResourceMonitor."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ResourceMonitor(config=config)
        return _instance
