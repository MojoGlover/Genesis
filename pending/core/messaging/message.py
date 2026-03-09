"""
Message definitions for the GENESIS message bus.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import uuid


class MessageType(Enum):
    """Types of messages that can be sent through the bus."""

    # Health & Status
    HEALTH_CHECK = "health_check"           # Request: Are you alive?
    STATUS_REPORT = "status_report"         # Response: Current health status
    HEARTBEAT = "heartbeat"                 # Periodic: I'm still alive

    # Task Management
    TASK_REQUEST = "task_request"           # Request: Do this task
    TASK_ACCEPTED = "task_accepted"         # Response: I'll do it
    TASK_REJECTED = "task_rejected"         # Response: I can't do it
    TASK_PROGRESS = "task_progress"         # Update: Here's my progress
    TASK_COMPLETE = "task_complete"         # Response: Task finished

    # Errors & Alerts
    ERROR_REPORT = "error_report"           # Alert: I failed, here's why
    WARNING = "warning"                     # Alert: Non-critical issue

    # Agent Lifecycle
    AGENT_STARTED = "agent_started"         # Notification: Agent came online
    AGENT_STOPPED = "agent_stopped"         # Notification: Agent going offline
    AGENT_DEGRADED = "agent_degraded"       # Alert: Agent having issues

    # System
    SHUTDOWN = "shutdown"                   # Command: System shutting down
    BROADCAST = "broadcast"                 # Info: Message to all agents


class HealthStatus(Enum):
    """Health status levels for agents."""
    HEALTHY = "healthy"         # Green - All good
    DEGRADED = "degraded"       # Yellow - Working but having issues
    FAILING = "failing"         # Orange - Critical errors, needs attention
    CRITICAL = "critical"       # Red - Dead, requires restart


@dataclass
class Message:
    """
    A message that can be sent through the message bus.

    Attributes:
        type: The message type
        sender: Name of the sending agent
        recipient: Target agent name, or None for broadcast
        payload: Message data
        correlation_id: Links related messages (e.g., request/response)
        timestamp: When the message was created
        id: Unique message identifier
    """
    type: MessageType
    sender: str
    payload: Dict[str, Any] = field(default_factory=dict)
    recipient: Optional[str] = None  # None = broadcast to all
    correlation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for logging/serialization."""
        return {
            "id": self.id,
            "type": self.type.value,
            "sender": self.sender,
            "recipient": self.recipient,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Message:
        """Create message from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            type=MessageType(data["type"]),
            sender=data["sender"],
            recipient=data.get("recipient"),
            payload=data.get("payload", {}),
            correlation_id=data.get("correlation_id"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
        )

    def reply(self, type: MessageType, payload: Dict[str, Any]) -> Message:
        """Create a reply message to this message."""
        return Message(
            type=type,
            sender=self.recipient or "system",
            recipient=self.sender,
            payload=payload,
            correlation_id=self.id,
        )

    def __repr__(self) -> str:
        return f"Message({self.type.value}, {self.sender}→{self.recipient or '*'}, id={self.id})"


# Convenience factory functions
def health_check(sender: str, target: str) -> Message:
    """Create a health check request."""
    return Message(
        type=MessageType.HEALTH_CHECK,
        sender=sender,
        recipient=target,
    )


def status_report(sender: str, status: HealthStatus, details: Dict[str, Any] = None) -> Message:
    """Create a status report."""
    return Message(
        type=MessageType.STATUS_REPORT,
        sender=sender,
        payload={
            "status": status.value,
            "details": details or {},
        },
    )


def heartbeat(sender: str, status: HealthStatus = HealthStatus.HEALTHY) -> Message:
    """Create a heartbeat message."""
    return Message(
        type=MessageType.HEARTBEAT,
        sender=sender,
        payload={"status": status.value},
    )


def task_request(sender: str, target: str, task: Dict[str, Any]) -> Message:
    """Create a task request."""
    return Message(
        type=MessageType.TASK_REQUEST,
        sender=sender,
        recipient=target,
        payload={"task": task},
    )


def task_complete(sender: str, task_id: str, result: Any, success: bool = True) -> Message:
    """Create a task completion message."""
    return Message(
        type=MessageType.TASK_COMPLETE,
        sender=sender,
        payload={
            "task_id": task_id,
            "success": success,
            "result": result,
        },
    )


def error_report(sender: str, error: str, context: Dict[str, Any] = None) -> Message:
    """Create an error report."""
    return Message(
        type=MessageType.ERROR_REPORT,
        sender=sender,
        payload={
            "error": error,
            "context": context or {},
        },
    )
