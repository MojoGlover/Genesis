"""
GENESIS Health Monitor

Tracks all agent health metrics and provides aggregated dashboard data.
"""

from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

from core.messaging import Message, MessageType, get_message_bus
from core.messaging.message import HealthStatus

logger = logging.getLogger(__name__)


@dataclass
class AgentMetrics:
    """Health metrics for a single agent."""
    name: str
    status: HealthStatus = HealthStatus.HEALTHY
    last_heartbeat: Optional[datetime] = None
    error_count: int = 0
    error_rate: float = 0.0
    success_count: int = 0
    queue_depth: int = 0
    uptime_seconds: float = 0.0
    custom_metrics: Dict[str, Any] = field(default_factory=dict)
    last_error: Optional[str] = None
    registered_at: datetime = field(default_factory=datetime.now)

    @property
    def is_alive(self) -> bool:
        """Check if agent is considered alive (heartbeat within 30s)."""
        if self.last_heartbeat is None:
            return False
        return datetime.now() - self.last_heartbeat < timedelta(seconds=30)

    @property
    def time_since_heartbeat(self) -> Optional[float]:
        """Seconds since last heartbeat."""
        if self.last_heartbeat is None:
            return None
        return (datetime.now() - self.last_heartbeat).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API/dashboard."""
        return {
            "name": self.name,
            "status": self.status.value,
            "is_alive": self.is_alive,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "time_since_heartbeat": self.time_since_heartbeat,
            "error_count": self.error_count,
            "error_rate": round(self.error_rate, 4),
            "success_count": self.success_count,
            "queue_depth": self.queue_depth,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "last_error": self.last_error,
            "custom_metrics": self.custom_metrics,
        }


class HealthMonitor:
    """
    Central health monitoring for all GENESIS agents.

    Subscribes to message bus for heartbeats, status reports, and errors.
    Provides aggregated health data for dashboard.

    Usage:
        monitor = get_health_monitor()
        monitor.start()

        # Get all agent health
        health = monitor.get_all_health()

        # Get specific agent
        agent_health = monitor.get_agent_health("route_optimizer")
    """

    def __init__(self, heartbeat_timeout: float = 30.0):
        """
        Initialize the health monitor.

        Args:
            heartbeat_timeout: Seconds after which an agent is considered dead
        """
        self._agents: Dict[str, AgentMetrics] = {}
        self._heartbeat_timeout = heartbeat_timeout
        self._running = False
        self._check_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._start_time: Optional[datetime] = None

        # Callbacks for status changes
        self._on_agent_degraded: List[Callable[[str, AgentMetrics], None]] = []
        self._on_agent_dead: List[Callable[[str, AgentMetrics], None]] = []
        self._on_agent_recovered: List[Callable[[str, AgentMetrics], None]] = []

    def start(self) -> None:
        """Start the health monitor."""
        if self._running:
            return

        self._running = True
        self._start_time = datetime.now()

        # Subscribe to relevant messages
        bus = get_message_bus()
        bus.subscribe(MessageType.HEARTBEAT, self._handle_heartbeat)
        bus.subscribe(MessageType.STATUS_REPORT, self._handle_status_report)
        bus.subscribe(MessageType.ERROR_REPORT, self._handle_error_report)
        bus.subscribe(MessageType.AGENT_STARTED, self._handle_agent_started)
        bus.subscribe(MessageType.AGENT_STOPPED, self._handle_agent_stopped)
        bus.subscribe(MessageType.AGENT_DEGRADED, self._handle_agent_degraded)
        bus.subscribe(MessageType.TASK_COMPLETE, self._handle_task_complete)

        # Start periodic health check
        self._check_thread = threading.Thread(target=self._periodic_check, daemon=True)
        self._check_thread.start()

        logger.info("Health monitor started")

    def stop(self) -> None:
        """Stop the health monitor."""
        self._running = False
        if self._check_thread:
            self._check_thread.join(timeout=2.0)
        logger.info("Health monitor stopped")

    def register_agent(self, name: str) -> None:
        """Register a new agent for monitoring."""
        with self._lock:
            if name not in self._agents:
                self._agents[name] = AgentMetrics(name=name)
                logger.info(f"Registered agent: {name}")

    def unregister_agent(self, name: str) -> None:
        """Unregister an agent."""
        with self._lock:
            if name in self._agents:
                del self._agents[name]
                logger.info(f"Unregistered agent: {name}")

    def get_agent_health(self, name: str) -> Optional[Dict[str, Any]]:
        """Get health metrics for a specific agent."""
        with self._lock:
            if name in self._agents:
                return self._agents[name].to_dict()
        return None

    def get_all_health(self) -> Dict[str, Any]:
        """Get aggregated health data for all agents."""
        with self._lock:
            agents = {name: metrics.to_dict() for name, metrics in self._agents.items()}

            # Calculate summary
            total = len(agents)
            healthy = sum(1 for m in self._agents.values() if m.status == HealthStatus.HEALTHY and m.is_alive)
            degraded = sum(1 for m in self._agents.values() if m.status == HealthStatus.DEGRADED)
            failing = sum(1 for m in self._agents.values() if m.status == HealthStatus.FAILING)
            critical = sum(1 for m in self._agents.values() if m.status == HealthStatus.CRITICAL or not m.is_alive)

            return {
                "timestamp": datetime.now().isoformat(),
                "uptime_seconds": (datetime.now() - self._start_time).total_seconds() if self._start_time else 0,
                "summary": {
                    "total": total,
                    "healthy": healthy,
                    "degraded": degraded,
                    "failing": failing,
                    "critical": critical,
                    "overall_status": self._calculate_overall_status(healthy, degraded, failing, critical, total),
                },
                "agents": agents,
            }

    def _calculate_overall_status(self, healthy: int, degraded: int, failing: int, critical: int, total: int) -> str:
        """Calculate overall system status."""
        if total == 0:
            return "unknown"
        if critical > 0:
            return "critical"
        if failing > 0:
            return "failing"
        if degraded > 0:
            return "degraded"
        if healthy == total:
            return "healthy"
        return "unknown"

    def _handle_heartbeat(self, message: Message) -> None:
        """Handle heartbeat message from agent."""
        sender = message.sender
        status_str = message.payload.get("status", "healthy")

        with self._lock:
            if sender not in self._agents:
                self._agents[sender] = AgentMetrics(name=sender)

            metrics = self._agents[sender]
            old_status = metrics.status
            was_dead = not metrics.is_alive

            metrics.last_heartbeat = datetime.now()
            metrics.status = HealthStatus(status_str)

            # Check for recovery
            if was_dead and metrics.is_alive:
                self._trigger_recovered(sender, metrics)
            elif old_status != HealthStatus.HEALTHY and metrics.status == HealthStatus.HEALTHY:
                self._trigger_recovered(sender, metrics)

    def _handle_status_report(self, message: Message) -> None:
        """Handle detailed status report from agent."""
        sender = message.sender
        payload = message.payload

        with self._lock:
            if sender not in self._agents:
                self._agents[sender] = AgentMetrics(name=sender)

            metrics = self._agents[sender]
            metrics.status = HealthStatus(payload.get("status", "healthy"))
            metrics.last_heartbeat = datetime.now()

            details = payload.get("details", {})
            metrics.error_rate = details.get("error_rate", 0.0)
            metrics.uptime_seconds = details.get("uptime_seconds", 0.0)
            metrics.custom_metrics.update(details)

    def _handle_error_report(self, message: Message) -> None:
        """Handle error report from agent."""
        sender = message.sender
        error = message.payload.get("error", "Unknown error")

        with self._lock:
            if sender not in self._agents:
                self._agents[sender] = AgentMetrics(name=sender)

            metrics = self._agents[sender]
            metrics.error_count += 1
            metrics.last_error = error
            metrics.error_rate = metrics.error_count / max(1, metrics.success_count + metrics.error_count)

    def _handle_agent_started(self, message: Message) -> None:
        """Handle agent started notification."""
        sender = message.sender
        self.register_agent(sender)

        with self._lock:
            if sender in self._agents:
                self._agents[sender].status = HealthStatus.HEALTHY
                self._agents[sender].last_heartbeat = datetime.now()

    def _handle_agent_stopped(self, message: Message) -> None:
        """Handle agent stopped notification."""
        sender = message.sender
        with self._lock:
            if sender in self._agents:
                self._agents[sender].status = HealthStatus.CRITICAL

    def _handle_agent_degraded(self, message: Message) -> None:
        """Handle agent degraded notification."""
        sender = message.sender
        with self._lock:
            if sender in self._agents:
                self._agents[sender].status = HealthStatus.DEGRADED
                self._trigger_degraded(sender, self._agents[sender])

    def _handle_task_complete(self, message: Message) -> None:
        """Handle task completion to track success/failure."""
        sender = message.sender
        success = message.payload.get("success", True)

        with self._lock:
            if sender not in self._agents:
                self._agents[sender] = AgentMetrics(name=sender)

            metrics = self._agents[sender]
            if success:
                metrics.success_count += 1
            else:
                metrics.error_count += 1

            total = metrics.success_count + metrics.error_count
            metrics.error_rate = metrics.error_count / max(1, total)

    def _periodic_check(self) -> None:
        """Periodically check for dead agents."""
        while self._running:
            time.sleep(10)  # Check every 10 seconds

            with self._lock:
                for name, metrics in self._agents.items():
                    if not metrics.is_alive and metrics.status != HealthStatus.CRITICAL:
                        metrics.status = HealthStatus.CRITICAL
                        self._trigger_dead(name, metrics)

    def _trigger_degraded(self, name: str, metrics: AgentMetrics) -> None:
        """Trigger degraded callbacks."""
        for callback in self._on_agent_degraded:
            try:
                callback(name, metrics)
            except Exception as e:
                logger.error(f"Degraded callback error: {e}")

    def _trigger_dead(self, name: str, metrics: AgentMetrics) -> None:
        """Trigger dead callbacks."""
        for callback in self._on_agent_dead:
            try:
                callback(name, metrics)
            except Exception as e:
                logger.error(f"Dead callback error: {e}")

    def _trigger_recovered(self, name: str, metrics: AgentMetrics) -> None:
        """Trigger recovered callbacks."""
        for callback in self._on_agent_recovered:
            try:
                callback(name, metrics)
            except Exception as e:
                logger.error(f"Recovered callback error: {e}")

    def on_agent_degraded(self, callback: Callable[[str, AgentMetrics], None]) -> None:
        """Register callback for when agent becomes degraded."""
        self._on_agent_degraded.append(callback)

    def on_agent_dead(self, callback: Callable[[str, AgentMetrics], None]) -> None:
        """Register callback for when agent is considered dead."""
        self._on_agent_dead.append(callback)

    def on_agent_recovered(self, callback: Callable[[str, AgentMetrics], None]) -> None:
        """Register callback for when agent recovers."""
        self._on_agent_recovered.append(callback)


# Singleton
_monitor_instance: Optional[HealthMonitor] = None
_monitor_lock = threading.Lock()


def get_health_monitor() -> HealthMonitor:
    """Get the singleton health monitor instance."""
    global _monitor_instance
    with _monitor_lock:
        if _monitor_instance is None:
            _monitor_instance = HealthMonitor()
        return _monitor_instance
