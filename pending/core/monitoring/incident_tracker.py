"""
GENESIS Incident Tracker

Correlates related errors, alerts, and health events into unified incidents.
Provides a single view for troubleshooting cascading failures and related issues.

Key features:
- Automatic incident creation from alerts and errors
- Correlation by agent, time window, and error patterns
- Incident lifecycle: OPEN -> INVESTIGATING -> RESOLVED -> CLOSED
- Timeline of all related events within an incident
- Integration with auto-recovery for tracking recovery attempts

Integrates with:
- AlertSystem: receives alerts and groups them
- ErrorLogger: correlates errors into incidents
- AutoRecovery: tracks recovery attempts per incident
- Message bus: listens for health/error events
- Dashboard: API endpoints for incident management
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from core.messaging import Message, MessageType, get_message_bus

logger = logging.getLogger(__name__)


class IncidentStatus(Enum):
    """Incident lifecycle states."""
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentSeverity(Enum):
    """Incident severity levels."""
    LOW = "low"          # Single warning, minor issue
    MEDIUM = "medium"    # Multiple warnings or single critical
    HIGH = "high"        # Multiple criticals or cascading failures
    CRITICAL = "critical"  # System-wide impact


class EventType(Enum):
    """Types of events that can be part of an incident."""
    ALERT = "alert"
    ERROR = "error"
    HEALTH_CHANGE = "health_change"
    RECOVERY_ATTEMPT = "recovery_attempt"
    RECOVERY_SUCCESS = "recovery_success"
    RECOVERY_FAILED = "recovery_failed"
    MANUAL_NOTE = "manual_note"
    STATUS_CHANGE = "status_change"


@dataclass
class IncidentEvent:
    """A single event within an incident timeline."""
    event_type: EventType
    timestamp: datetime
    agent: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    event_id: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = self._generate_id()

    def _generate_id(self) -> str:
        data = f"{self.event_type.value}:{self.agent}:{self.timestamp.isoformat()}:{self.message[:50]}"
        return hashlib.md5(data.encode()).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "agent": self.agent,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class Incident:
    """A correlated group of related events representing a single incident."""
    incident_id: str
    title: str
    status: IncidentStatus = IncidentStatus.OPEN
    severity: IncidentSeverity = IncidentSeverity.MEDIUM
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    # Affected agents
    agents: Set[str] = field(default_factory=set)
    primary_agent: str = ""
    
    # Timeline of events
    events: List[IncidentEvent] = field(default_factory=list)
    
    # Correlation metadata
    error_fingerprints: Set[str] = field(default_factory=set)
    alert_ids: Set[str] = field(default_factory=set)
    recovery_attempts: int = 0
    
    # Investigation notes
    notes: List[str] = field(default_factory=list)
    resolution: str = ""
    
    # Tags for filtering
    tags: Set[str] = field(default_factory=set)

    def add_event(self, event: IncidentEvent) -> None:
        """Add an event to the incident timeline."""
        self.events.append(event)
        self.agents.add(event.agent)
        self.updated_at = datetime.now()
        self._recalculate_severity()

    def _recalculate_severity(self) -> None:
        """Recalculate severity based on events and agents."""
        critical_count = sum(
            1 for e in self.events 
            if e.details.get("severity") in ("critical", "CRITICAL")
        )
        error_count = sum(
            1 for e in self.events 
            if e.event_type in (EventType.ERROR, EventType.ALERT)
        )
        agent_count = len(self.agents)
        
        if critical_count >= 3 or agent_count >= 3:
            self.severity = IncidentSeverity.CRITICAL
        elif critical_count >= 1 or error_count >= 5:
            self.severity = IncidentSeverity.HIGH
        elif error_count >= 2:
            self.severity = IncidentSeverity.MEDIUM
        else:
            self.severity = IncidentSeverity.LOW

    def resolve(self, resolution: str = "") -> None:
        """Mark incident as resolved."""
        self.status = IncidentStatus.RESOLVED
        self.resolved_at = datetime.now()
        self.updated_at = datetime.now()
        if resolution:
            self.resolution = resolution
        self.add_event(IncidentEvent(
            event_type=EventType.STATUS_CHANGE,
            timestamp=datetime.now(),
            agent="system",
            message=f"Incident resolved: {resolution or 'No details provided'}",
        ))

    def close(self) -> None:
        """Close the incident (final state)."""
        self.status = IncidentStatus.CLOSED
        self.closed_at = datetime.now()
        self.updated_at = datetime.now()
        self.add_event(IncidentEvent(
            event_type=EventType.STATUS_CHANGE,
            timestamp=datetime.now(),
            agent="system",
            message="Incident closed",
        ))

    def investigate(self) -> None:
        """Mark incident as being investigated."""
        self.status = IncidentStatus.INVESTIGATING
        self.updated_at = datetime.now()
        self.add_event(IncidentEvent(
            event_type=EventType.STATUS_CHANGE,
            timestamp=datetime.now(),
            agent="system",
            message="Investigation started",
        ))

    def add_note(self, note: str, author: str = "system") -> None:
        """Add an investigation note."""
        self.notes.append(f"[{datetime.now().isoformat()}] {author}: {note}")
        self.add_event(IncidentEvent(
            event_type=EventType.MANUAL_NOTE,
            timestamp=datetime.now(),
            agent=author,
            message=note,
        ))

    def duration_seconds(self) -> float:
        """Get incident duration in seconds."""
        end = self.resolved_at or self.closed_at or datetime.now()
        return (end - self.created_at).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "status": self.status.value,
            "severity": self.severity.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "agents": list(self.agents),
            "primary_agent": self.primary_agent,
            "event_count": len(self.events),
            "events": [e.to_dict() for e in self.events[-20:]],  # Last 20 events
            "recovery_attempts": self.recovery_attempts,
            "notes": self.notes,
            "resolution": self.resolution,
            "tags": list(self.tags),
            "duration_seconds": round(self.duration_seconds(), 1),
        }

    def summary(self) -> Dict[str, Any]:
        """Get a summary without full event timeline."""
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "status": self.status.value,
            "severity": self.severity.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "agents": list(self.agents),
            "primary_agent": self.primary_agent,
            "event_count": len(self.events),
            "recovery_attempts": self.recovery_attempts,
            "duration_seconds": round(self.duration_seconds(), 1),
        }


@dataclass
class IncidentTrackerConfig:
    """Configuration for incident tracking."""
    # Correlation settings
    correlation_window_seconds: float = 300.0  # 5 minutes
    auto_resolve_after_healthy_seconds: float = 600.0  # 10 minutes
    auto_close_resolved_after_hours: float = 24.0
    
    # Capacity limits
    max_open_incidents: int = 100
    max_events_per_incident: int = 500
    max_incident_history: int = 500
    
    # Behavior
    auto_create_from_alerts: bool = True
    auto_create_from_errors: bool = True
    auto_resolve_on_recovery: bool = True
    
    # Fingerprinting
    fingerprint_patterns: List[str] = field(default_factory=list)


def _generate_error_fingerprint(agent: str, message: str) -> str:
    """Generate a fingerprint for error correlation."""
    # Normalize the message by removing variable parts
    normalized = re.sub(r'\d+', 'N', message)
    normalized = re.sub(r'0x[0-9a-fA-F]+', 'ADDR', normalized)
    normalized = re.sub(r'["\'][^"\']*["\']', 'STR', normalized)
    normalized = normalized[:100]
    
    data = f"{agent}:{normalized}"
    return hashlib.md5(data.encode()).hexdigest()[:16]


class IncidentTracker:
    """
    Tracks and correlates system incidents from alerts, errors, and health events.
    
    Key responsibilities:
    - Create incidents from alerts and errors
    - Correlate related events by agent, time, and error fingerprint
    - Track incident lifecycle (open -> investigating -> resolved -> closed)
    - Auto-resolve when agents recover
    - Provide API for incident management
    
    Usage:
        tracker = get_incident_tracker()
        tracker.start()
        
        # Events are automatically tracked from message bus
        # Or manually:
        incident = tracker.create_incident("Database connection failures", "db_agent")
        tracker.add_error(incident.incident_id, agent, error_message, {...})
        tracker.resolve_incident(incident.incident_id, "Connection pool resized")
    """

    def __init__(self, config: Optional[IncidentTrackerConfig] = None):
        self._config = config or IncidentTrackerConfig()
        self._incidents: Dict[str, Incident] = {}
        self._closed_incidents: List[Incident] = []
        self._lock = threading.RLock()
        self._running = False
        self._maintenance_thread: Optional[threading.Thread] = None
        self._incident_counter = 0
        
        # Correlation indexes
        self._agent_to_incidents: Dict[str, Set[str]] = {}
        self._fingerprint_to_incident: Dict[str, str] = {}
        
        # Callbacks
        self._on_incident_created: List[Callable[[Incident], None]] = []
        self._on_incident_resolved: List[Callable[[Incident], None]] = []
        self._on_incident_escalated: List[Callable[[Incident], None]] = []

    def start(self) -> None:
        """Start the incident tracker and subscribe to message bus."""
        if self._running:
            return
        
        self._running = True
        
        # Subscribe to message bus events
        bus = get_message_bus()
        bus.subscribe(MessageType.ALERT, self._handle_alert)
        bus.subscribe(MessageType.ERROR_REPORT, self._handle_error)
        bus.subscribe(MessageType.AGENT_DEGRADED, self._handle_health_change)
        bus.subscribe(MessageType.AGENT_STOPPED, self._handle_health_change)
        bus.subscribe(MessageType.HEARTBEAT, self._handle_heartbeat)
        
        # Start maintenance thread
        self._maintenance_thread = threading.Thread(
            target=self._maintenance_loop, daemon=True, name="incident-tracker"
        )
        self._maintenance_thread.start()
        
        logger.info("Incident tracker started")

    def stop(self) -> None:
        """Stop the incident tracker."""
        self._running = False
        if self._maintenance_thread:
            self._maintenance_thread.join(timeout=5.0)
        logger.info("Incident tracker stopped")

    # -- Public API --

    def create_incident(
        self,
        title: str,
        primary_agent: str,
        severity: IncidentSeverity = IncidentSeverity.MEDIUM,
        tags: Optional[List[str]] = None,
    ) -> Incident:
        """Manually create a new incident."""
        with self._lock:
            self._incident_counter += 1
            incident_id = f"INC-{self._incident_counter:05d}"
            
            incident = Incident(
                incident_id=incident_id,
                title=title,
                primary_agent=primary_agent,
                severity=severity,
                tags=set(tags) if tags else set(),
            )
            incident.agents.add(primary_agent)
            
            self._incidents[incident_id] = incident
            self._index_incident(incident)
            
            logger.info(f"Created incident {incident_id}: {title}")
            self._notify_created(incident)
            
            return incident

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        """Get an incident by ID."""
        with self._lock:
            return self._incidents.get(incident_id)

    def get_open_incidents(self) -> List[Dict[str, Any]]:
        """Get all open incidents (not resolved/closed)."""
        with self._lock:
            return [
                inc.summary()
                for inc in self._incidents.values()
                if inc.status in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING)
            ]

    def get_all_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all active incidents and recent history."""
        with self._lock:
            active = list(self._incidents.values())
            historical = self._closed_incidents[-limit:]
            all_incidents = active + historical
            all_incidents.sort(key=lambda i: i.updated_at, reverse=True)
            return [inc.summary() for inc in all_incidents[:limit]]

    def get_incident_details(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Get full incident details including timeline."""
        with self._lock:
            incident = self._incidents.get(incident_id)
            if incident:
                return incident.to_dict()
            # Check history
            for inc in self._closed_incidents:
                if inc.incident_id == incident_id:
                    return inc.to_dict()
            return None

    def get_agent_incidents(self, agent: str) -> List[Dict[str, Any]]:
        """Get all incidents affecting an agent."""
        with self._lock:
            incident_ids = self._agent_to_incidents.get(agent, set())
            return [
                self._incidents[iid].summary()
                for iid in incident_ids
                if iid in self._incidents
            ]

    def add_event(
        self,
        incident_id: str,
        event_type: EventType,
        agent: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Add an event to an existing incident."""
        with self._lock:
            incident = self._incidents.get(incident_id)
            if not incident:
                return False
            
            event = IncidentEvent(
                event_type=event_type,
                timestamp=datetime.now(),
                agent=agent,
                message=message,
                details=details or {},
            )
            incident.add_event(event)
            
            # Check for escalation
            old_severity = incident.severity
            incident._recalculate_severity()
            if incident.severity.value > old_severity.value:
                self._notify_escalated(incident)
            
            return True

    def add_error(
        self,
        incident_id: str,
        agent: str,
        message: str,
        error_details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Add an error event to an incident."""
        return self.add_event(
            incident_id,
            EventType.ERROR,
            agent,
            message,
            error_details,
        )

    def resolve_incident(self, incident_id: str, resolution: str = "") -> bool:
        """Mark an incident as resolved."""
        with self._lock:
            incident = self._incidents.get(incident_id)
            if not incident:
                return False
            
            incident.resolve(resolution)
            self._notify_resolved(incident)
            logger.info(f"Resolved incident {incident_id}: {resolution or 'No details'}")
            return True

    def close_incident(self, incident_id: str) -> bool:
        """Close an incident (final state)."""
        with self._lock:
            incident = self._incidents.get(incident_id)
            if not incident:
                return False
            
            incident.close()
            self._archive_incident(incident)
            logger.info(f"Closed incident {incident_id}")
            return True

    def investigate_incident(self, incident_id: str) -> bool:
        """Mark an incident as being investigated."""
        with self._lock:
            incident = self._incidents.get(incident_id)
            if not incident:
                return False
            
            incident.investigate()
            return True

    def add_note(self, incident_id: str, note: str, author: str = "user") -> bool:
        """Add an investigation note to an incident."""
        with self._lock:
            incident = self._incidents.get(incident_id)
            if not incident:
                return False
            
            incident.add_note(note, author)
            return True

    def get_status(self) -> Dict[str, Any]:
        """Get tracker status and statistics."""
        with self._lock:
            open_count = sum(
                1 for inc in self._incidents.values()
                if inc.status in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING)
            )
            by_severity = {}
            for sev in IncidentSeverity:
                by_severity[sev.value] = sum(
                    1 for inc in self._incidents.values()
                    if inc.severity == sev and inc.status != IncidentStatus.CLOSED
                )
            
            return {
                "running": self._running,
                "total_active": len(self._incidents),
                "open": open_count,
                "resolved": sum(1 for i in self._incidents.values() if i.status == IncidentStatus.RESOLVED),
                "historical": len(self._closed_incidents),
                "by_severity": by_severity,
                "config": {
                    "correlation_window_seconds": self._config.correlation_window_seconds,
                    "auto_resolve_after_healthy_seconds": self._config.auto_resolve_after_healthy_seconds,
                },
            }

    # -- Callbacks --

    def on_incident_created(self, callback: Callable[[Incident], None]) -> None:
        """Register callback for new incidents."""
        self._on_incident_created.append(callback)

    def on_incident_resolved(self, callback: Callable[[Incident], None]) -> None:
        """Register callback for resolved incidents."""
        self._on_incident_resolved.append(callback)

    def on_incident_escalated(self, callback: Callable[[Incident], None]) -> None:
        """Register callback for severity escalations."""
        self._on_incident_escalated.append(callback)

    # -- Internal: Message Handlers --

    def _handle_alert(self, message: Message) -> None:
        """Handle alert messages from the alert system."""
        if not self._config.auto_create_from_alerts:
            return
        
        agent = message.payload.get("agent", message.sender)
        alert_msg = message.payload.get("message", "")
        severity = message.payload.get("severity", "normal")
        
        # Skip normal/info alerts
        if severity in ("normal", "info"):
            return
        
        with self._lock:
            incident = self._find_or_create_incident(agent, alert_msg, "alert")
            
            event = IncidentEvent(
                event_type=EventType.ALERT,
                timestamp=datetime.now(),
                agent=agent,
                message=alert_msg,
                details={
                    "severity": severity,
                    "title": message.payload.get("title", ""),
                    "context": message.payload.get("context", {}),
                },
            )
            incident.add_event(event)
            incident.alert_ids.add(message.payload.get("alert_id", event.event_id))

    def _handle_error(self, message: Message) -> None:
        """Handle error report messages."""
        if not self._config.auto_create_from_errors:
            return
        
        agent = message.sender
        error_msg = message.payload.get("message", str(message.payload.get("error", "")))
        
        with self._lock:
            incident = self._find_or_create_incident(agent, error_msg, "error")
            
            event = IncidentEvent(
                event_type=EventType.ERROR,
                timestamp=datetime.now(),
                agent=agent,
                message=error_msg,
                details={
                    "severity": message.payload.get("severity", "error"),
                    "traceback": message.payload.get("traceback", ""),
                    "context": message.payload.get("context", {}),
                },
            )
            incident.add_event(event)

    def _handle_health_change(self, message: Message) -> None:
        """Handle agent health status changes."""
        agent = message.sender
        status = message.payload.get("status", "unknown")
        
        with self._lock:
            # Find existing incident for this agent
            incident_ids = self._agent_to_incidents.get(agent, set())
            for iid in incident_ids:
                incident = self._incidents.get(iid)
                if incident and incident.status == IncidentStatus.OPEN:
                    event = IncidentEvent(
                        event_type=EventType.HEALTH_CHANGE,
                        timestamp=datetime.now(),
                        agent=agent,
                        message=f"Agent health changed to {status}",
                        details={"status": status},
                    )
                    incident.add_event(event)

    def _handle_heartbeat(self, message: Message) -> None:
        """Handle heartbeat messages - check for recovery."""
        if not self._config.auto_resolve_on_recovery:
            return
        
        agent = message.sender
        status = message.payload.get("status", "unknown")
        
        if status != "healthy":
            return
        
        with self._lock:
            incident_ids = self._agent_to_incidents.get(agent, set()).copy()
            for iid in incident_ids:
                incident = self._incidents.get(iid)
                if not incident:
                    continue
                if incident.status not in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                    continue
                
                # Check if this was a single-agent incident and agent is now healthy
                if len(incident.agents) == 1 and agent in incident.agents:
                    event = IncidentEvent(
                        event_type=EventType.RECOVERY_SUCCESS,
                        timestamp=datetime.now(),
                        agent=agent,
                        message=f"Agent {agent} reporting healthy",
                    )
                    incident.add_event(event)

    # -- Internal: Correlation --

    def _find_or_create_incident(
        self,
        agent: str,
        message: str,
        source: str,
    ) -> Incident:
        """Find an existing related incident or create a new one."""
        fingerprint = _generate_error_fingerprint(agent, message)
        now = datetime.now()
        window = timedelta(seconds=self._config.correlation_window_seconds)
        
        # Check fingerprint correlation
        if fingerprint in self._fingerprint_to_incident:
            iid = self._fingerprint_to_incident[fingerprint]
            incident = self._incidents.get(iid)
            if incident and incident.status in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                return incident
        
        # Check for recent incident from same agent
        agent_incidents = self._agent_to_incidents.get(agent, set())
        for iid in agent_incidents:
            incident = self._incidents.get(iid)
            if not incident:
                continue
            if incident.status not in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                continue
            if now - incident.updated_at < window:
                # Correlate to this incident
                incident.error_fingerprints.add(fingerprint)
                self._fingerprint_to_incident[fingerprint] = iid
                return incident
        
        # Create new incident
        title = self._generate_incident_title(agent, message, source)
        incident = self.create_incident(title, agent)
        incident.error_fingerprints.add(fingerprint)
        self._fingerprint_to_incident[fingerprint] = incident.incident_id
        
        return incident

    def _generate_incident_title(self, agent: str, message: str, source: str) -> str:
        """Generate a readable incident title."""
        # Extract key info from message
        if "timeout" in message.lower():
            return f"{agent}: Timeout issues"
        if "connection" in message.lower():
            return f"{agent}: Connection problems"
        if "memory" in message.lower():
            return f"{agent}: Memory issues"
        if "cpu" in message.lower() or "load" in message.lower():
            return f"{agent}: CPU/Load issues"
        if "disk" in message.lower():
            return f"{agent}: Disk issues"
        
        # Default: truncate message
        short_msg = message[:50] + "..." if len(message) > 50 else message
        return f"{agent}: {short_msg}"

    def _index_incident(self, incident: Incident) -> None:
        """Update correlation indexes for an incident."""
        for agent in incident.agents:
            if agent not in self._agent_to_incidents:
                self._agent_to_incidents[agent] = set()
            self._agent_to_incidents[agent].add(incident.incident_id)

    def _archive_incident(self, incident: Incident) -> None:
        """Move a closed incident to history."""
        # Remove from active
        del self._incidents[incident.incident_id]
        
        # Remove from indexes
        for agent in incident.agents:
            if agent in self._agent_to_incidents:
                self._agent_to_incidents[agent].discard(incident.incident_id)
        
        for fp in incident.error_fingerprints:
            if self._fingerprint_to_incident.get(fp) == incident.incident_id:
                del self._fingerprint_to_incident[fp]
        
        # Add to history
        self._closed_incidents.append(incident)
        if len(self._closed_incidents) > self._config.max_incident_history:
            self._closed_incidents = self._closed_incidents[-self._config.max_incident_history:]

    # -- Internal: Maintenance --

    def _maintenance_loop(self) -> None:
        """Background maintenance: auto-resolve, auto-close, cleanup."""
        while self._running:
            time.sleep(60.0)  # Check every minute
            try:
                self._auto_resolve_healthy()
                self._auto_close_old()
                self._cleanup_old_events()
            except Exception as e:
                logger.error(f"Incident maintenance error: {e}")

    def _auto_resolve_healthy(self) -> None:
        """Auto-resolve incidents where all agents have been healthy."""
        if not self._config.auto_resolve_on_recovery:
            return
        
        threshold = timedelta(seconds=self._config.auto_resolve_after_healthy_seconds)
        now = datetime.now()
        
        with self._lock:
            for incident in list(self._incidents.values()):
                if incident.status not in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                    continue
                
                # Check if we have recent recovery success events
                recent_recovery = None
                for event in reversed(incident.events):
                    if event.event_type == EventType.RECOVERY_SUCCESS:
                        recent_recovery = event.timestamp
                        break
                    if event.event_type in (EventType.ERROR, EventType.ALERT):
                        break  # Still having issues
                
                if recent_recovery and now - recent_recovery >= threshold:
                    incident.resolve("Auto-resolved after sustained healthy state")
                    self._notify_resolved(incident)
                    logger.info(f"Auto-resolved incident {incident.incident_id}")

    def _auto_close_old(self) -> None:
        """Auto-close resolved incidents after a period."""
        threshold = timedelta(hours=self._config.auto_close_resolved_after_hours)
        now = datetime.now()
        
        with self._lock:
            for incident in list(self._incidents.values()):
                if incident.status != IncidentStatus.RESOLVED:
                    continue
                if incident.resolved_at and now - incident.resolved_at >= threshold:
                    incident.close()
                    self._archive_incident(incident)
                    logger.info(f"Auto-closed incident {incident.incident_id}")

    def _cleanup_old_events(self) -> None:
        """Trim old events from large incidents."""
        with self._lock:
            for incident in self._incidents.values():
                if len(incident.events) > self._config.max_events_per_incident:
                    incident.events = incident.events[-self._config.max_events_per_incident:]

    # -- Internal: Notifications --

    def _notify_created(self, incident: Incident) -> None:
        for cb in self._on_incident_created:
            try:
                cb(incident)
            except Exception as e:
                logger.error(f"Incident created callback error: {e}")

    def _notify_resolved(self, incident: Incident) -> None:
        for cb in self._on_incident_resolved:
            try:
                cb(incident)
            except Exception as e:
                logger.error(f"Incident resolved callback error: {e}")

    def _notify_escalated(self, incident: Incident) -> None:
        for cb in self._on_incident_escalated:
            try:
                cb(incident)
            except Exception as e:
                logger.error(f"Incident escalated callback error: {e}")


# -- Singleton --

_tracker_instance: Optional[IncidentTracker] = None
_tracker_lock = threading.Lock()


def get_incident_tracker(
    config: Optional[IncidentTrackerConfig] = None,
) -> IncidentTracker:
    """Get the singleton IncidentTracker."""
    global _tracker_instance
    with _tracker_lock:
        if _tracker_instance is None:
            _tracker_instance = IncidentTracker(config)
        return _tracker_instance
