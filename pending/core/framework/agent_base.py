"""
GENESIS Agent Base Framework

All specialized agents inherit from AgentBase, which provides:
- Heartbeat reporting (I'm alive)
- Health status tracking
- Error handling with alerts
- Message bus integration
- Config-driven initialization
- Autonomy level management
"""

from __future__ import annotations
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json

from core.messaging import (
    MessageBus,
    Message,
    MessageType,
    get_message_bus,
)
from core.messaging.message import HealthStatus, heartbeat, status_report, error_report

logger = logging.getLogger(__name__)


class AutonomyLevel(Enum):
    """Agent autonomy levels - all start supervised."""
    SUPERVISED = "supervised"           # Requires approval for all actions
    SEMI_AUTONOMOUS = "semi_autonomous" # Can act within defined bounds
    FULLY_AUTONOMOUS = "fully_autonomous"  # Full autonomy (earned)


class AgentState(Enum):
    """Agent lifecycle states."""
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    DEGRADED = "degraded"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class AgentConfig:
    """Configuration for an agent."""
    agent_name: str
    mission: str
    autonomy_level: AutonomyLevel = AutonomyLevel.SUPERVISED
    capabilities: Dict[str, bool] = field(default_factory=dict)
    tools: List[str] = field(default_factory=list)
    heartbeat_interval: float = 5.0  # seconds
    error_threshold: int = 3  # errors before degraded
    alert_on_failure: bool = True

    # Autonomy upgrade criteria
    autonomy_upgrade_path: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "semi_autonomous": {
            "min_successful_tasks": 100,
            "max_error_rate": 0.05,
        },
        "fully_autonomous": {
            "min_successful_tasks": 500,
            "max_error_rate": 0.02,
        },
    })

    # Custom configuration for specialized agents
    custom_config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> AgentConfig:
        """Load config from JSON file."""
        with open(path) as f:
            data = json.load(f)

        # Extract known fields, rest goes to custom_config
        known_fields = {
            "agent_name", "mission", "autonomy_level", "capabilities",
            "tools", "heartbeat_interval", "error_threshold",
            "alert_on_failure", "autonomy_upgrade_path"
        }

        custom = {k: v for k, v in data.items() if k not in known_fields}

        return cls(
            agent_name=data["agent_name"],
            mission=data["mission"],
            autonomy_level=AutonomyLevel(data.get("autonomy_level", "supervised")),
            capabilities=data.get("capabilities", {}),
            tools=data.get("tools", []),
            heartbeat_interval=data.get("heartbeat_interval", 5.0),
            error_threshold=data.get("error_threshold", 3),
            alert_on_failure=data.get("alert_on_failure", True),
            autonomy_upgrade_path=data.get("autonomy_upgrade_path", {}),
            custom_config=custom,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "agent_name": self.agent_name,
            "mission": self.mission,
            "autonomy_level": self.autonomy_level.value,
            "capabilities": self.capabilities,
            "tools": self.tools,
            "heartbeat_interval": self.heartbeat_interval,
            "error_threshold": self.error_threshold,
            "alert_on_failure": self.alert_on_failure,
            "autonomy_upgrade_path": self.autonomy_upgrade_path,
        }
        # Merge custom config
        result.update(self.custom_config)
        return result


class AgentBase(ABC):
    """
    Base class for all GENESIS agents.

    Subclasses must implement:
        - execute_task(task) -> result
        - get_capabilities() -> dict (optional, uses config if not overridden)

    Usage:
        class RouteOptimizer(AgentBase):
            def execute_task(self, task):
                # Do route optimization
                return optimized_route

        agent = RouteOptimizer(config)
        agent.start()
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.name = config.agent_name
        self.mission = config.mission
        self.autonomy_level = config.autonomy_level

        # State tracking
        self._state = AgentState.INITIALIZING
        self._health_status = HealthStatus.HEALTHY
        self._last_heartbeat: Optional[datetime] = None
        self._error_count = 0
        self._recent_errors: List[Dict] = []

        # Statistics
        self._stats = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "start_time": None,
            "total_errors": 0,
        }

        # Threading
        self._running = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Message bus
        self._bus: Optional[MessageBus] = None

    @property
    def state(self) -> AgentState:
        """Current agent state."""
        return self._state

    @property
    def health_status(self) -> HealthStatus:
        """Current health status."""
        return self._health_status

    def start(self) -> None:
        """Start the agent and begin heartbeat."""
        if self._running:
            logger.warning(f"{self.name}: Already running")
            return

        logger.info(f"{self.name}: Starting...")

        # Connect to message bus
        self._bus = get_message_bus()
        self._subscribe_to_messages()

        # Start heartbeat
        self._running = True
        self._stats["start_time"] = datetime.now()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

        # Transition to ready
        self._state = AgentState.READY
        self._broadcast_status(MessageType.AGENT_STARTED)

        logger.info(f"{self.name}: Started successfully")

    def stop(self) -> None:
        """Stop the agent gracefully."""
        if not self._running:
            return

        logger.info(f"{self.name}: Stopping...")
        self._running = False
        self._state = AgentState.STOPPED

        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2.0)

        self._broadcast_status(MessageType.AGENT_STOPPED)
        logger.info(f"{self.name}: Stopped")

    def _subscribe_to_messages(self) -> None:
        """Subscribe to relevant message types."""
        if not self._bus:
            return

        # Listen for messages addressed to this agent
        self._bus.subscribe_agent(self.name, self._handle_message)

        # Listen for health checks
        self._bus.subscribe(MessageType.HEALTH_CHECK, self._handle_health_check)

        # Listen for task requests
        self._bus.subscribe(MessageType.TASK_REQUEST, self._handle_task_request)

        # Listen for shutdown
        self._bus.subscribe(MessageType.SHUTDOWN, self._handle_shutdown)

    def _handle_message(self, message: Message) -> None:
        """Handle incoming messages addressed to this agent."""
        logger.debug(f"{self.name}: Received {message.type.value} from {message.sender}")

        if message.type == MessageType.TASK_REQUEST:
            self._handle_task_request(message)
        elif message.type == MessageType.HEALTH_CHECK:
            self._handle_health_check(message)

    def _handle_health_check(self, message: Message) -> None:
        """Respond to health check requests."""
        if message.recipient and message.recipient != self.name:
            return  # Not for us

        response = status_report(
            sender=self.name,
            status=self._health_status,
            details=self.get_health_details(),
        )
        response.correlation_id = message.id
        self._bus.publish(response)

    def _handle_task_request(self, message: Message) -> None:
        """Handle incoming task requests."""
        if message.recipient != self.name:
            return  # Not for us

        task = message.payload.get("task", {})

        # Check if we can handle this
        if not self._can_handle_task(task):
            self._send_task_rejected(message, "Cannot handle this task type")
            return

        # Check autonomy level
        if self.autonomy_level == AutonomyLevel.SUPERVISED:
            # Need approval - for now, just accept
            # TODO: Implement approval workflow
            pass

        # Accept the task
        self._send_task_accepted(message)

        # Execute
        self._state = AgentState.BUSY
        try:
            result = self.execute_task(task)
            self._send_task_complete(message, result, success=True)
            self._stats["tasks_completed"] += 1
        except Exception as e:
            self.handle_error(e, {"task": task})
            self._send_task_complete(message, str(e), success=False)
            self._stats["tasks_failed"] += 1
        finally:
            self._state = AgentState.READY

    def _can_handle_task(self, task: Dict) -> bool:
        """Check if this agent can handle the given task. Override in subclasses."""
        return True

    def _send_task_accepted(self, request: Message) -> None:
        """Send task accepted message."""
        self._bus.publish(Message(
            type=MessageType.TASK_ACCEPTED,
            sender=self.name,
            recipient=request.sender,
            correlation_id=request.id,
        ))

    def _send_task_rejected(self, request: Message, reason: str) -> None:
        """Send task rejected message."""
        self._bus.publish(Message(
            type=MessageType.TASK_REJECTED,
            sender=self.name,
            recipient=request.sender,
            payload={"reason": reason},
            correlation_id=request.id,
        ))

    def _send_task_complete(self, request: Message, result: Any, success: bool) -> None:
        """Send task completion message."""
        self._bus.publish(Message(
            type=MessageType.TASK_COMPLETE,
            sender=self.name,
            recipient=request.sender,
            payload={"result": result, "success": success},
            correlation_id=request.id,
        ))

    def _handle_shutdown(self, message: Message) -> None:
        """Handle system shutdown."""
        logger.info(f"{self.name}: Received shutdown signal")
        self.stop()

    def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self._running:
            self.send_heartbeat()
            time.sleep(self.config.heartbeat_interval)

    def send_heartbeat(self) -> None:
        """Send heartbeat message to indicate agent is alive."""
        self._last_heartbeat = datetime.now()

        if self._bus:
            msg = heartbeat(self.name, self._health_status)
            self._bus.publish(msg)

    def report_health(self) -> Dict[str, Any]:
        """Report current health status with details."""
        return {
            "agent": self.name,
            "state": self._state.value,
            "health": self._health_status.value,
            "last_heartbeat": self._last_heartbeat.isoformat() if self._last_heartbeat else None,
            "error_count": self._error_count,
            "stats": self._stats,
            "details": self.get_health_details(),
        }

    def get_health_details(self) -> Dict[str, Any]:
        """Get detailed health information. Override in subclasses for custom metrics."""
        return {
            "uptime_seconds": (datetime.now() - self._stats["start_time"]).total_seconds()
            if self._stats["start_time"]
            else 0,
            "error_rate": self._stats["tasks_failed"] / max(1, self._stats["tasks_completed"] + self._stats["tasks_failed"]),
            "recent_errors": self._recent_errors[-5:],
        }

    def handle_error(self, error: Exception, context: Dict[str, Any] = None) -> None:
        """
        Handle an error - log, track, alert if needed.

        This method:
        1. Logs the error
        2. Updates error count
        3. Checks if agent should be degraded
        4. Sends alert if critical
        """
        logger.error(f"{self.name}: Error - {error}", exc_info=True)

        with self._lock:
            self._error_count += 1
            self._stats["total_errors"] += 1

            error_entry = {
                "error": str(error),
                "type": type(error).__name__,
                "context": context or {},
                "timestamp": datetime.now().isoformat(),
            }
            self._recent_errors.append(error_entry)
            if len(self._recent_errors) > 20:
                self._recent_errors = self._recent_errors[-20:]

            # Check if we should degrade
            if self._error_count >= self.config.error_threshold:
                self._health_status = HealthStatus.DEGRADED
                self._state = AgentState.DEGRADED

                if self._bus:
                    self._bus.publish(Message(
                        type=MessageType.AGENT_DEGRADED,
                        sender=self.name,
                        payload={"reason": "Error threshold exceeded"},
                    ))

        # Send error report
        if self._bus and self.config.alert_on_failure:
            self._bus.publish(error_report(
                sender=self.name,
                error=str(error),
                context=context,
            ))

    def reset_error_count(self) -> None:
        """Reset error count (e.g., after manual intervention)."""
        with self._lock:
            self._error_count = 0
            if self._health_status == HealthStatus.DEGRADED:
                self._health_status = HealthStatus.HEALTHY
                self._state = AgentState.READY

    def _broadcast_status(self, message_type: MessageType) -> None:
        """Broadcast a status message."""
        if self._bus:
            self._bus.publish(Message(
                type=message_type,
                sender=self.name,
                payload=self.report_health(),
            ))

    def get_capabilities(self) -> Dict[str, bool]:
        """Return agent capabilities. Override for dynamic capabilities."""
        return self.config.capabilities

    @abstractmethod
    def execute_task(self, task: Dict[str, Any]) -> Any:
        """
        Execute a task. Must be implemented by subclasses.

        Args:
            task: Task definition with type and parameters

        Returns:
            Task result (varies by agent type)

        Raises:
            Exception: If task execution fails
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, state={self._state.value})"
