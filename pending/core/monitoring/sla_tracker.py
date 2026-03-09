"""
GENESIS SLA Tracker

Tracks Service Level Agreement (SLA) compliance and uptime metrics for agents.
Provides detailed uptime calculations, SLA breach detection, and historical reporting.

Key features:
- Per-agent uptime tracking (availability %)
- SLA target management and breach alerts
- Historical availability reports
- Maintenance window support
- Error budget tracking
- Burn rate calculations

Integrates with:
- HealthMonitor: receives health status changes
- AlertSystem: alerts on SLA breaches
- IncidentTracker: correlates downtime with incidents
- Message bus: listens for health events
- Dashboard: API endpoints for SLA visualization
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Set

from core.messaging import Message, MessageType, get_message_bus

logger = logging.getLogger(__name__)


class AvailabilityState(Enum):
    """Agent availability states."""
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class SLABreachType(Enum):
    """Type of SLA breach."""
    AVAILABILITY = "availability"
    ERROR_BUDGET = "error_budget"
    BURN_RATE = "burn_rate"
    RESPONSE_TIME = "response_time"


@dataclass
class StateChange:
    """Record of an availability state change."""
    timestamp: datetime
    previous_state: AvailabilityState
    new_state: AvailabilityState
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "previous_state": self.previous_state.value,
            "new_state": self.new_state.value,
            "reason": self.reason,
        }


@dataclass
class MaintenanceWindow:
    """Scheduled maintenance window (downtime not counted)."""
    window_id: str
    agent: str
    start_time: datetime
    end_time: datetime
    description: str = ""
    created_by: str = "system"

    def is_active(self, at: Optional[datetime] = None) -> bool:
        check_time = at or datetime.now()
        return self.start_time <= check_time <= self.end_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_id": self.window_id,
            "agent": self.agent,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "description": self.description,
            "is_active": self.is_active(),
        }


@dataclass
class SLATarget:
    """SLA target for an agent."""
    agent: str
    availability_target: float = 99.9  # Percentage (e.g., 99.9%)
    max_downtime_minutes_monthly: float = 43.2  # 99.9% = 43.2 min/month
    error_budget_percent: float = 0.1  # 100% - availability_target
    response_time_ms: Optional[float] = None  # Optional response time SLA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "availability_target": self.availability_target,
            "max_downtime_minutes_monthly": self.max_downtime_minutes_monthly,
            "error_budget_percent": self.error_budget_percent,
            "response_time_ms": self.response_time_ms,
        }


@dataclass
class SLABreach:
    """Record of an SLA breach."""
    breach_id: str
    agent: str
    breach_type: SLABreachType
    target_value: float
    actual_value: float
    breach_time: datetime
    message: str
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "breach_id": self.breach_id,
            "agent": self.agent,
            "breach_type": self.breach_type.value,
            "target_value": round(self.target_value, 3),
            "actual_value": round(self.actual_value, 3),
            "breach_time": self.breach_time.isoformat(),
            "message": self.message,
            "context": self.context,
        }


@dataclass
class AgentAvailability:
    """Availability tracking for a single agent."""
    agent: str
    current_state: AvailabilityState = AvailabilityState.UNKNOWN
    state_since: datetime = field(default_factory=datetime.now)
    
    # Time tracking (in seconds)
    total_uptime: float = 0.0
    total_downtime: float = 0.0
    total_degraded: float = 0.0
    total_maintenance: float = 0.0
    tracking_started: datetime = field(default_factory=datetime.now)
    
    # State history
    state_changes: Deque[StateChange] = field(default_factory=lambda: deque(maxlen=500))
    
    # Incident tracking
    current_outage_id: Optional[str] = None
    outage_count: int = 0

    def availability_percent(self, exclude_maintenance: bool = True) -> float:
        """Calculate availability percentage."""
        total = self.total_uptime + self.total_downtime + self.total_degraded
        if exclude_maintenance:
            pass  # Maintenance already excluded
        else:
            total += self.total_maintenance
        
        if total == 0:
            return 100.0
        
        return (self.total_uptime / total) * 100

    def downtime_minutes(self, period_hours: float = 720) -> float:  # 720h = 30 days
        """Get downtime in minutes over period."""
        return self.total_downtime / 60

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "current_state": self.current_state.value,
            "state_since": self.state_since.isoformat(),
            "availability_percent": round(self.availability_percent(), 3),
            "uptime_hours": round(self.total_uptime / 3600, 2),
            "downtime_minutes": round(self.total_downtime / 60, 2),
            "degraded_minutes": round(self.total_degraded / 60, 2),
            "tracking_since": self.tracking_started.isoformat(),
            "outage_count": self.outage_count,
        }


@dataclass
class SLATrackerConfig:
    """Configuration for SLA tracking."""
    default_sla_target: float = 99.9  # Default availability target
    check_interval_seconds: float = 60.0  # How often to check SLAs
    burn_rate_window_hours: float = 1.0  # Window for burn rate calculation
    burn_rate_threshold: float = 2.0  # Alert if burn rate exceeds this
    state_history_max: int = 500
    breach_history_max: int = 200


class SLATracker:
    """
    Tracks SLA compliance and availability metrics for agents.
    
    Usage:
        tracker = get_sla_tracker()
        tracker.start()
        
        # Set SLA target
        tracker.set_sla_target("db_agent", availability_target=99.95)
        
        # Create maintenance window
        tracker.create_maintenance_window("db_agent", start, end, "Planned upgrade")
        
        # Get current SLA status
        status = tracker.get_agent_sla("db_agent")
    """

    def __init__(self, config: Optional[SLATrackerConfig] = None):
        self._config = config or SLATrackerConfig()
        self._agents: Dict[str, AgentAvailability] = {}
        self._sla_targets: Dict[str, SLATarget] = {}
        self._maintenance_windows: Dict[str, MaintenanceWindow] = {}
        self._breaches: Deque[SLABreach] = deque(maxlen=self._config.breach_history_max)
        self._lock = threading.RLock()
        self._running = False
        self._check_thread: Optional[threading.Thread] = None
        self._breach_counter = 0
        self._window_counter = 0
        
        # Callbacks
        self._on_breach: List[Callable[[SLABreach], None]] = []
        self._on_state_change: List[Callable[[str, StateChange], None]] = []

    def start(self) -> None:
        """Start SLA tracking."""
        if self._running:
            return
        
        self._running = True
        
        # Subscribe to health events
        bus = get_message_bus()
        bus.subscribe(MessageType.HEARTBEAT, self._handle_heartbeat)
        bus.subscribe(MessageType.AGENT_STARTED, self._handle_agent_started)
        bus.subscribe(MessageType.AGENT_STOPPED, self._handle_agent_stopped)
        bus.subscribe(MessageType.AGENT_DEGRADED, self._handle_agent_degraded)
        
        # Start SLA check thread
        self._check_thread = threading.Thread(
            target=self._check_loop, daemon=True, name="sla-tracker"
        )
        self._check_thread.start()
        
        logger.info("SLA tracker started")

    def stop(self) -> None:
        """Stop SLA tracking."""
        self._running = False
        if self._check_thread:
            self._check_thread.join(timeout=5.0)
        logger.info("SLA tracker stopped")

    # -- Public API --

    def set_sla_target(
        self,
        agent: str,
        availability_target: float = 99.9,
        response_time_ms: Optional[float] = None,
    ) -> None:
        """Set SLA target for an agent."""
        # Calculate derived values
        error_budget = 100 - availability_target
        # Max downtime per month: (100 - target%) * 30 days * 24 hours * 60 min
        max_downtime = (error_budget / 100) * 30 * 24 * 60
        
        target = SLATarget(
            agent=agent,
            availability_target=availability_target,
            max_downtime_minutes_monthly=max_downtime,
            error_budget_percent=error_budget,
            response_time_ms=response_time_ms,
        )
        
        with self._lock:
            self._sla_targets[agent] = target
        
        logger.info(f"Set SLA target for {agent}: {availability_target}%")

    def get_sla_target(self, agent: str) -> Optional[SLATarget]:
        """Get SLA target for an agent."""
        with self._lock:
            return self._sla_targets.get(agent)

    def create_maintenance_window(
        self,
        agent: str,
        start_time: datetime,
        end_time: datetime,
        description: str = "",
        created_by: str = "user",
    ) -> MaintenanceWindow:
        """Create a scheduled maintenance window."""
        with self._lock:
            self._window_counter += 1
            window_id = f"MW-{self._window_counter:05d}"
            
            window = MaintenanceWindow(
                window_id=window_id,
                agent=agent,
                start_time=start_time,
                end_time=end_time,
                description=description,
                created_by=created_by,
            )
            
            self._maintenance_windows[window_id] = window
        
        logger.info(f"Created maintenance window {window_id} for {agent}")
        return window

    def cancel_maintenance_window(self, window_id: str) -> bool:
        """Cancel a maintenance window."""
        with self._lock:
            if window_id in self._maintenance_windows:
                del self._maintenance_windows[window_id]
                return True
            return False

    def get_maintenance_windows(self, agent: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get maintenance windows, optionally filtered by agent."""
        with self._lock:
            windows = list(self._maintenance_windows.values())
        
        if agent:
            windows = [w for w in windows if w.agent == agent]
        
        return [w.to_dict() for w in windows]

    def get_agent_sla(self, agent: str) -> Dict[str, Any]:
        """Get SLA status for an agent."""
        with self._lock:
            availability = self._agents.get(agent)
            target = self._sla_targets.get(agent)
        
        if not availability:
            return {"agent": agent, "error": "Agent not tracked"}
        
        current_availability = availability.availability_percent()
        target_value = target.availability_target if target else self._config.default_sla_target
        
        return {
            "agent": agent,
            "current_availability": round(current_availability, 3),
            "target_availability": target_value,
            "sla_met": current_availability >= target_value,
            "current_state": availability.current_state.value,
            "state_since": availability.state_since.isoformat(),
            "uptime_hours": round(availability.total_uptime / 3600, 2),
            "downtime_minutes": round(availability.total_downtime / 60, 2),
            "outage_count": availability.outage_count,
            "error_budget_remaining": self._calculate_error_budget(agent),
            "burn_rate": self._calculate_burn_rate(agent),
            "tracking_since": availability.tracking_started.isoformat(),
        }

    def get_all_sla_status(self) -> Dict[str, Any]:
        """Get SLA status for all tracked agents."""
        with self._lock:
            agents = list(self._agents.keys())
        
        statuses = {agent: self.get_agent_sla(agent) for agent in agents}
        
        # Calculate summary
        total = len(statuses)
        meeting_sla = sum(1 for s in statuses.values() if s.get("sla_met", False))
        
        return {
            "agents": statuses,
            "summary": {
                "total_agents": total,
                "meeting_sla": meeting_sla,
                "breaching_sla": total - meeting_sla,
                "compliance_percent": round((meeting_sla / total * 100) if total > 0 else 100, 1),
            },
        }

    def get_recent_breaches(self, limit: int = 50, agent: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent SLA breaches."""
        with self._lock:
            breaches = list(self._breaches)
        
        if agent:
            breaches = [b for b in breaches if b.agent == agent]
        
        breaches.sort(key=lambda b: b.breach_time, reverse=True)
        return [b.to_dict() for b in breaches[:limit]]

    def get_availability_history(self, agent: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get state change history for an agent."""
        with self._lock:
            availability = self._agents.get(agent)
            if not availability:
                return []
            return [sc.to_dict() for sc in list(availability.state_changes)[-limit:]]

    def get_status(self) -> Dict[str, Any]:
        """Get overall SLA tracker status."""
        with self._lock:
            return {
                "running": self._running,
                "tracked_agents": len(self._agents),
                "sla_targets_configured": len(self._sla_targets),
                "active_maintenance_windows": sum(
                    1 for w in self._maintenance_windows.values() if w.is_active()
                ),
                "total_breaches": len(self._breaches),
                "config": {
                    "default_sla_target": self._config.default_sla_target,
                    "check_interval_seconds": self._config.check_interval_seconds,
                    "burn_rate_threshold": self._config.burn_rate_threshold,
                },
            }

    def on_breach(self, callback: Callable[[SLABreach], None]) -> None:
        """Register callback for SLA breaches."""
        self._on_breach.append(callback)

    def on_state_change(self, callback: Callable[[str, StateChange], None]) -> None:
        """Register callback for state changes."""
        self._on_state_change.append(callback)

    # -- Internal: State Management --

    def _update_agent_state(
        self,
        agent: str,
        new_state: AvailabilityState,
        reason: str = "",
    ) -> None:
        """Update agent availability state."""
        now = datetime.now()
        
        with self._lock:
            if agent not in self._agents:
                self._agents[agent] = AgentAvailability(agent=agent)
            
            availability = self._agents[agent]
            old_state = availability.current_state
            
            # Calculate time in previous state
            time_in_state = (now - availability.state_since).total_seconds()
            
            # Add time to appropriate bucket
            if old_state == AvailabilityState.UP:
                availability.total_uptime += time_in_state
            elif old_state == AvailabilityState.DOWN:
                availability.total_downtime += time_in_state
            elif old_state == AvailabilityState.DEGRADED:
                availability.total_degraded += time_in_state
            elif old_state == AvailabilityState.MAINTENANCE:
                availability.total_maintenance += time_in_state
            
            # Record state change
            state_change = StateChange(
                timestamp=now,
                previous_state=old_state,
                new_state=new_state,
                reason=reason,
            )
            availability.state_changes.append(state_change)
            
            # Track outages
            if new_state == AvailabilityState.DOWN and old_state != AvailabilityState.DOWN:
                availability.outage_count += 1
            
            # Update current state
            availability.current_state = new_state
            availability.state_since = now
        
        # Notify callbacks
        for callback in self._on_state_change:
            try:
                callback(agent, state_change)
            except Exception as e:
                logger.error(f"State change callback error: {e}")

    def _is_in_maintenance(self, agent: str, at: Optional[datetime] = None) -> bool:
        """Check if agent is in a maintenance window."""
        check_time = at or datetime.now()
        with self._lock:
            for window in self._maintenance_windows.values():
                if window.agent == agent and window.is_active(check_time):
                    return True
        return False

    def _calculate_error_budget(self, agent: str) -> float:
        """Calculate remaining error budget as percentage."""
        with self._lock:
            availability = self._agents.get(agent)
            target = self._sla_targets.get(agent)
        
        if not availability:
            return 100.0
        
        target_availability = target.availability_target if target else self._config.default_sla_target
        error_budget_total = 100 - target_availability
        
        current_availability = availability.availability_percent()
        error_used = 100 - current_availability
        
        if error_budget_total == 0:
            return 100.0 if error_used == 0 else 0.0
        
        remaining = ((error_budget_total - error_used) / error_budget_total) * 100
        return max(0, min(100, remaining))

    def _calculate_burn_rate(self, agent: str) -> float:
        """Calculate burn rate (how fast error budget is being consumed)."""
        with self._lock:
            availability = self._agents.get(agent)
        
        if not availability:
            return 0.0
        
        # Calculate error rate in recent window
        window_seconds = self._config.burn_rate_window_hours * 3600
        
        # Recent downtime as proportion of window
        recent_downtime = min(availability.total_downtime, window_seconds)
        error_rate = recent_downtime / window_seconds if window_seconds > 0 else 0
        
        # Expected error rate based on SLA
        target = self._sla_targets.get(agent)
        expected_error_rate = (100 - (target.availability_target if target else 99.9)) / 100
        
        if expected_error_rate == 0:
            return float("inf") if error_rate > 0 else 0.0
        
        return error_rate / expected_error_rate

    def _check_sla_compliance(self, agent: str) -> None:
        """Check SLA compliance for an agent."""
        with self._lock:
            availability = self._agents.get(agent)
            target = self._sla_targets.get(agent)
        
        if not availability:
            return
        
        target_value = target.availability_target if target else self._config.default_sla_target
        current = availability.availability_percent()
        
        # Check availability breach
        if current < target_value:
            self._record_breach(
                agent=agent,
                breach_type=SLABreachType.AVAILABILITY,
                target_value=target_value,
                actual_value=current,
                message=f"{agent} availability {current:.2f}% below target {target_value}%",
            )
        
        # Check burn rate
        burn_rate = self._calculate_burn_rate(agent)
        if burn_rate > self._config.burn_rate_threshold:
            self._record_breach(
                agent=agent,
                breach_type=SLABreachType.BURN_RATE,
                target_value=1.0,
                actual_value=burn_rate,
                message=f"{agent} burn rate {burn_rate:.1f}x exceeds threshold {self._config.burn_rate_threshold}x",
            )
        
        # Check error budget
        error_budget = self._calculate_error_budget(agent)
        if error_budget <= 0:
            self._record_breach(
                agent=agent,
                breach_type=SLABreachType.ERROR_BUDGET,
                target_value=0,
                actual_value=error_budget,
                message=f"{agent} error budget exhausted",
            )

    def _record_breach(
        self,
        agent: str,
        breach_type: SLABreachType,
        target_value: float,
        actual_value: float,
        message: str,
    ) -> None:
        """Record an SLA breach."""
        with self._lock:
            self._breach_counter += 1
            breach_id = f"SLA-{self._breach_counter:06d}"
            
            breach = SLABreach(
                breach_id=breach_id,
                agent=agent,
                breach_type=breach_type,
                target_value=target_value,
                actual_value=actual_value,
                breach_time=datetime.now(),
                message=message,
            )
            
            self._breaches.append(breach)
        
        # Notify callbacks
        for callback in self._on_breach:
            try:
                callback(breach)
            except Exception as e:
                logger.error(f"Breach callback error: {e}")
        
        # Broadcast on message bus
        try:
            bus = get_message_bus()
            bus.publish(Message(
                type=MessageType.ALERT,
                sender="sla_tracker",
                payload={
                    "alert_type": "sla_breach",
                    "breach": breach.to_dict(),
                },
            ))
        except Exception as e:
            logger.error(f"Failed to broadcast SLA breach: {e}")

    # -- Internal: Event Handlers --

    def _handle_heartbeat(self, message: Message) -> None:
        """Handle heartbeat messages."""
        agent = message.sender
        status = message.payload.get("status", "unknown")
        
        if self._is_in_maintenance(agent):
            self._update_agent_state(agent, AvailabilityState.MAINTENANCE, "Scheduled maintenance")
        elif status == "healthy":
            self._update_agent_state(agent, AvailabilityState.UP, "Healthy heartbeat")
        elif status == "degraded":
            self._update_agent_state(agent, AvailabilityState.DEGRADED, "Degraded heartbeat")
        else:
            self._update_agent_state(agent, AvailabilityState.DOWN, f"Unhealthy: {status}")

    def _handle_agent_started(self, message: Message) -> None:
        """Handle agent started events."""
        agent = message.sender
        self._update_agent_state(agent, AvailabilityState.UP, "Agent started")

    def _handle_agent_stopped(self, message: Message) -> None:
        """Handle agent stopped events."""
        agent = message.sender
        if self._is_in_maintenance(agent):
            self._update_agent_state(agent, AvailabilityState.MAINTENANCE, "Stopped for maintenance")
        else:
            self._update_agent_state(agent, AvailabilityState.DOWN, "Agent stopped")

    def _handle_agent_degraded(self, message: Message) -> None:
        """Handle agent degraded events."""
        agent = message.sender
        reason = message.payload.get("reason", "Unknown")
        self._update_agent_state(agent, AvailabilityState.DEGRADED, reason)

    def _check_loop(self) -> None:
        """Background loop that checks SLA compliance."""
        while self._running:
            time.sleep(self._config.check_interval_seconds)
            try:
                with self._lock:
                    agents = list(self._agents.keys())
                
                for agent in agents:
                    self._check_sla_compliance(agent)
                    
            except Exception as e:
                logger.error(f"SLA check error: {e}")


# -- Singleton --

_tracker_instance: Optional[SLATracker] = None
_tracker_lock = threading.Lock()


def get_sla_tracker(config: Optional[SLATrackerConfig] = None) -> SLATracker:
    global _tracker_instance
    with _tracker_lock:
        if _tracker_instance is None:
            _tracker_instance = SLATracker(config)
        return _tracker_instance
