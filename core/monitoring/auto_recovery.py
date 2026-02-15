"""
GENESIS Auto-Recovery System

Automated agent recovery with graduated escalation:
1. Clear errors and wait for heartbeat
2. Restart agent via registry
3. Recreate agent via factory (if available)
4. Give up and alert for manual intervention

Uses exponential backoff to prevent flapping. Integrates with
HealthMonitor, AgentRegistry, AlertSystem, and CircuitBreaker.
"""

from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.messaging import Message, MessageType, get_message_bus

logger = logging.getLogger(__name__)


class RecoveryStage(Enum):
    """Graduated recovery stages."""
    CLEAR_ERRORS = "clear_errors"
    RESTART = "restart"
    RECREATE = "recreate"
    MANUAL = "manual"


class RecoveryOutcome(Enum):
    """Outcome of a recovery attempt."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"


@dataclass
class RecoveryAttempt:
    """Record of a single recovery attempt."""
    agent: str
    stage: RecoveryStage
    outcome: RecoveryOutcome
    timestamp: datetime = field(default_factory=datetime.now)
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "stage": self.stage.value,
            "outcome": self.outcome.value,
            "timestamp": self.timestamp.isoformat(),
            "detail": self.detail,
        }


@dataclass
class AgentRecoveryState:
    """Tracks recovery state for a single agent."""
    agent_name: str
    current_stage: RecoveryStage = RecoveryStage.CLEAR_ERRORS
    attempt_count: int = 0
    last_attempt: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    backoff_seconds: float = 10.0
    consecutive_failures: int = 0
    escalated_to_manual: bool = False
    suppressed: bool = False

    # Limits
    max_attempts_per_stage: int = 2
    max_backoff_seconds: float = 300.0  # 5 minutes
    backoff_multiplier: float = 2.0

    def advance_stage(self) -> bool:
        """Move to next recovery stage. Returns False if already at MANUAL."""
        stages = list(RecoveryStage)
        idx = stages.index(self.current_stage)
        if idx < len(stages) - 1:
            self.current_stage = stages[idx + 1]
            self.attempt_count = 0
            return True
        return False

    def record_failure(self) -> None:
        """Record a failed attempt, increase backoff."""
        self.attempt_count += 1
        self.consecutive_failures += 1
        self.last_attempt = datetime.now()
        self.backoff_seconds = min(
            self.backoff_seconds * self.backoff_multiplier,
            self.max_backoff_seconds,
        )
        self.next_retry_at = datetime.fromtimestamp(
            time.time() + self.backoff_seconds
        )

    def record_success(self) -> None:
        """Record successful recovery, reset state."""
        self.current_stage = RecoveryStage.CLEAR_ERRORS
        self.attempt_count = 0
        self.consecutive_failures = 0
        self.backoff_seconds = 10.0
        self.last_attempt = datetime.now()
        self.next_retry_at = None
        self.escalated_to_manual = False

    def should_advance(self) -> bool:
        """Check if we should move to next stage."""
        return self.attempt_count >= self.max_attempts_per_stage

    def is_ready(self) -> bool:
        """Check if backoff period has elapsed."""
        if self.next_retry_at is None:
            return True
        return datetime.now() >= self.next_retry_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent_name,
            "stage": self.current_stage.value,
            "attempt_count": self.attempt_count,
            "consecutive_failures": self.consecutive_failures,
            "backoff_seconds": round(self.backoff_seconds, 1),
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "escalated_to_manual": self.escalated_to_manual,
            "suppressed": self.suppressed,
        }


@dataclass
class AutoRecoveryConfig:
    """Configuration for auto-recovery behavior."""
    enabled: bool = True
    check_interval: float = 15.0
    max_concurrent_recoveries: int = 3
    cooldown_after_recovery: float = 60.0
    excluded_agents: List[str] = field(default_factory=list)


class AutoRecovery:
    """
    Automated agent recovery with graduated escalation.

    Monitors agent health via the message bus and attempts recovery
    when agents become CRITICAL or stop responding.

    Recovery stages (in order):
    1. clear_errors - Reset error counters, wait for heartbeat
    2. restart - Stop and restart via AgentRegistry
    3. recreate - Recreate via factory function (if available)
    4. manual - Give up, send critical alert for human intervention

    Usage:
        recovery = get_auto_recovery()
        recovery.start()

        # Check status
        status = recovery.get_status()

        # Suppress recovery for maintenance
        recovery.suppress_agent("my_agent")
        recovery.unsuppress_agent("my_agent")
    """

    def __init__(self, config: Optional[AutoRecoveryConfig] = None):
        self._config = config or AutoRecoveryConfig()
        self._states: Dict[str, AgentRecoveryState] = {}
        self._history: List[RecoveryAttempt] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._active_recoveries: int = 0

        # Callbacks
        self._on_recovery_success: List[Callable[[str, RecoveryStage], None]] = []
        self._on_recovery_failed: List[Callable[[str], None]] = []
        self._on_escalation: List[Callable[[str, RecoveryStage], None]] = []

    def start(self) -> None:
        """Start the auto-recovery monitor."""
        if self._running:
            return

        self._running = True

        bus = get_message_bus()
        bus.subscribe(MessageType.AGENT_STOPPED, self._handle_agent_stopped)
        bus.subscribe(MessageType.AGENT_DEGRADED, self._handle_agent_degraded)
        bus.subscribe(MessageType.HEARTBEAT, self._handle_heartbeat)

        self._thread = threading.Thread(
            target=self._recovery_loop, daemon=True, name="auto-recovery"
        )
        self._thread.start()
        logger.info("Auto-recovery started")

    def stop(self) -> None:
        """Stop the auto-recovery monitor."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Auto-recovery stopped")

    def suppress_agent(self, agent_name: str) -> None:
        """Suppress auto-recovery for an agent (e.g. during maintenance)."""
        with self._lock:
            state = self._get_or_create_state(agent_name)
            state.suppressed = True
        logger.info(f"Recovery suppressed for {agent_name}")

    def unsuppress_agent(self, agent_name: str) -> None:
        """Re-enable auto-recovery for an agent."""
        with self._lock:
            state = self._get_or_create_state(agent_name)
            state.suppressed = False
        logger.info(f"Recovery unsuppressed for {agent_name}")

    def reset_agent(self, agent_name: str) -> None:
        """Reset recovery state for an agent (e.g. after manual fix)."""
        with self._lock:
            if agent_name in self._states:
                self._states[agent_name].record_success()
        logger.info(f"Recovery state reset for {agent_name}")

    def get_status(self) -> Dict[str, Any]:
        """Get full auto-recovery status."""
        with self._lock:
            return {
                "enabled": self._config.enabled,
                "running": self._running,
                "active_recoveries": self._active_recoveries,
                "agents": {
                    name: state.to_dict()
                    for name, state in self._states.items()
                },
                "config": {
                    "check_interval": self._config.check_interval,
                    "max_concurrent": self._config.max_concurrent_recoveries,
                    "cooldown": self._config.cooldown_after_recovery,
                    "excluded": self._config.excluded_agents,
                },
                "stats": self._get_stats(),
            }

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent recovery attempt history."""
        with self._lock:
            return [a.to_dict() for a in self._history[-limit:][::-1]]

    def on_recovery_success(self, callback: Callable[[str, RecoveryStage], None]) -> None:
        """Register callback for successful recovery."""
        self._on_recovery_success.append(callback)

    def on_recovery_failed(self, callback: Callable[[str], None]) -> None:
        """Register callback for recovery giving up (escalated to manual)."""
        self._on_recovery_failed.append(callback)

    def on_escalation(self, callback: Callable[[str, RecoveryStage], None]) -> None:
        """Register callback for stage escalation."""
        self._on_escalation.append(callback)

    # -- Internal --

    def _get_or_create_state(self, agent_name: str) -> AgentRecoveryState:
        """Get or create recovery state for an agent."""
        if agent_name not in self._states:
            self._states[agent_name] = AgentRecoveryState(agent_name=agent_name)
        return self._states[agent_name]

    def _handle_agent_stopped(self, message: Message) -> None:
        """Agent stopped -- queue for recovery."""
        agent_name = message.sender
        if agent_name in self._config.excluded_agents:
            return
        with self._lock:
            state = self._get_or_create_state(agent_name)
            if not state.escalated_to_manual and not state.suppressed:
                logger.info(f"Agent {agent_name} stopped -- queuing recovery")

    def _handle_agent_degraded(self, message: Message) -> None:
        """Agent degraded -- note for monitoring but don't recover yet."""
        pass

    def _handle_heartbeat(self, message: Message) -> None:
        """Heartbeat received -- agent may have recovered."""
        agent_name = message.sender
        status = message.payload.get("status", "healthy")

        if status == "healthy":
            with self._lock:
                if agent_name in self._states:
                    state = self._states[agent_name]
                    if state.consecutive_failures > 0:
                        logger.info(
                            f"Agent {agent_name} recovered "
                            f"(was at stage {state.current_stage.value})"
                        )
                        old_stage = state.current_stage
                        state.record_success()
                        self._record_attempt(
                            agent_name, old_stage, RecoveryOutcome.SUCCESS,
                            "Agent resumed healthy heartbeats"
                        )
                        self._notify_success(agent_name, old_stage)

    def _recovery_loop(self) -> None:
        """Main recovery check loop."""
        while self._running:
            time.sleep(self._config.check_interval)
            if not self._config.enabled:
                continue
            self._check_and_recover()

    def _check_and_recover(self) -> None:
        """Check all agents and attempt recovery where needed."""
        from .monitor import get_health_monitor

        monitor = get_health_monitor()
        health = monitor.get_all_health()
        agents = health.get("agents", {})

        for name, agent_data in agents.items():
            if name in self._config.excluded_agents:
                continue

            status_str = agent_data.get("status", "healthy")
            is_alive = agent_data.get("is_alive", True)

            needs_recovery = (
                status_str in ("critical", "failing")
                or not is_alive
            )

            if needs_recovery:
                self._attempt_recovery(name)

    def _attempt_recovery(self, agent_name: str) -> None:
        """Attempt recovery for a single agent."""
        with self._lock:
            state = self._get_or_create_state(agent_name)

            if state.suppressed:
                return
            if state.escalated_to_manual:
                return
            if not state.is_ready():
                return
            if self._active_recoveries >= self._config.max_concurrent_recoveries:
                return

            self._active_recoveries += 1

        try:
            self._execute_recovery(agent_name, state)
        finally:
            with self._lock:
                self._active_recoveries = max(0, self._active_recoveries - 1)

    def _execute_recovery(self, agent_name: str, state: AgentRecoveryState) -> None:
        """Execute the current recovery stage."""
        stage = state.current_stage
        logger.info(
            f"Recovery attempt for {agent_name}: "
            f"stage={stage.value}, attempt={state.attempt_count + 1}"
        )

        if stage == RecoveryStage.CLEAR_ERRORS:
            success = self._try_clear_errors(agent_name)
        elif stage == RecoveryStage.RESTART:
            success = self._try_restart(agent_name)
        elif stage == RecoveryStage.RECREATE:
            success = self._try_recreate(agent_name)
        elif stage == RecoveryStage.MANUAL:
            self._escalate_to_manual(agent_name, state)
            return
        else:
            return

        with self._lock:
            if success:
                # Don't mark success yet -- wait for heartbeat confirmation
                self._record_attempt(
                    agent_name, stage, RecoveryOutcome.PENDING,
                    f"Recovery action executed, waiting for heartbeat"
                )
                state.last_attempt = datetime.now()
                state.next_retry_at = datetime.fromtimestamp(
                    time.time() + self._config.cooldown_after_recovery
                )
            else:
                state.record_failure()
                self._record_attempt(
                    agent_name, stage, RecoveryOutcome.FAILED,
                    f"Recovery action failed at stage {stage.value}"
                )

                if state.should_advance():
                    advanced = state.advance_stage()
                    if advanced:
                        logger.warning(
                            f"Escalating recovery for {agent_name} "
                            f"to {state.current_stage.value}"
                        )
                        self._notify_escalation(agent_name, state.current_stage)
                    else:
                        self._escalate_to_manual(agent_name, state)

    def _try_clear_errors(self, agent_name: str) -> bool:
        """Stage 1: Clear agent errors."""
        try:
            from .registry import get_agent_registry, AgentAction
            registry = get_agent_registry()
            result = registry.perform_action(agent_name, AgentAction.CLEAR_ERRORS)
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Clear errors failed for {agent_name}: {e}")
            return False

    def _try_restart(self, agent_name: str) -> bool:
        """Stage 2: Restart the agent."""
        try:
            from .registry import get_agent_registry, AgentAction
            registry = get_agent_registry()
            result = registry.perform_action(agent_name, AgentAction.RESTART)
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Restart failed for {agent_name}: {e}")
            return False

    def _try_recreate(self, agent_name: str) -> bool:
        """Stage 3: Recreate agent via factory."""
        try:
            from .registry import get_agent_registry, AgentAction

            registry = get_agent_registry()
            has_factory = agent_name in registry._agent_factories
            if not has_factory:
                logger.warning(
                    f"No factory for {agent_name}, restart instead"
                )
                return self._try_restart(agent_name)

            result = registry.perform_action(agent_name, AgentAction.RESTART)
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Recreate failed for {agent_name}: {e}")
            return False

    def _escalate_to_manual(self, agent_name: str, state: AgentRecoveryState) -> None:
        """Final stage: give up and alert for manual intervention."""
        state.escalated_to_manual = True
        logger.error(
            f"Auto-recovery exhausted for {agent_name} "
            f"after {state.consecutive_failures} attempts -- "
            f"manual intervention required"
        )

        self._record_attempt(
            agent_name, RecoveryStage.MANUAL, RecoveryOutcome.FAILED,
            f"All recovery stages exhausted after {state.consecutive_failures} attempts"
        )

        # Send critical alert
        try:
            from .alerting import get_alert_system, AlertSeverity
            alert_system = get_alert_system()
            alert_system.send_alert(
                severity=AlertSeverity.CRITICAL,
                agent=agent_name,
                title="Manual Intervention Required",
                message=(
                    f"Auto-recovery failed for {agent_name} after "
                    f"{state.consecutive_failures} attempts across all stages. "
                    f"Manual restart or investigation needed."
                ),
                context={
                    "recovery_attempts": state.consecutive_failures,
                    "last_stage": state.current_stage.value,
                },
            )
        except Exception as e:
            logger.error(f"Failed to send escalation alert for {agent_name}: {e}")

        for cb in self._on_recovery_failed:
            try:
                cb(agent_name)
            except Exception as e:
                logger.error(f"Recovery failed callback error: {e}")

    def _record_attempt(
        self, agent: str, stage: RecoveryStage,
        outcome: RecoveryOutcome, detail: str
    ) -> None:
        """Record a recovery attempt in history."""
        attempt = RecoveryAttempt(
            agent=agent, stage=stage, outcome=outcome, detail=detail
        )
        self._history.append(attempt)
        if len(self._history) > 500:
            self._history = self._history[-500:]

    def _notify_success(self, agent_name: str, stage: RecoveryStage) -> None:
        """Notify success callbacks."""
        for cb in self._on_recovery_success:
            try:
                cb(agent_name, stage)
            except Exception as e:
                logger.error(f"Recovery success callback error: {e}")

        try:
            from .alerting import get_alert_system, AlertSeverity
            alert_system = get_alert_system()
            alert_system.send_alert(
                severity=AlertSeverity.NORMAL,
                agent=agent_name,
                message=f"Agent {agent_name} recovered via auto-recovery (stage: {stage.value})",
            )
        except Exception:
            pass

    def _notify_escalation(self, agent_name: str, new_stage: RecoveryStage) -> None:
        """Notify escalation callbacks."""
        for cb in self._on_escalation:
            try:
                cb(agent_name, new_stage)
            except Exception as e:
                logger.error(f"Escalation callback error: {e}")

    def _get_stats(self) -> Dict[str, Any]:
        """Calculate recovery statistics."""
        total = len(self._history)
        if total == 0:
            return {
                "total_attempts": 0,
                "success_count": 0,
                "failed_count": 0,
                "pending_count": 0,
                "success_rate": 0.0,
                "agents_in_recovery": 0,
                "agents_escalated": 0,
            }

        success = sum(1 for a in self._history if a.outcome == RecoveryOutcome.SUCCESS)
        failed = sum(1 for a in self._history if a.outcome == RecoveryOutcome.FAILED)
        pending = sum(1 for a in self._history if a.outcome == RecoveryOutcome.PENDING)
        in_recovery = sum(
            1 for s in self._states.values()
            if s.consecutive_failures > 0 and not s.escalated_to_manual
        )
        escalated = sum(1 for s in self._states.values() if s.escalated_to_manual)

        return {
            "total_attempts": total,
            "success_count": success,
            "failed_count": failed,
            "pending_count": pending,
            "success_rate": round(success / max(1, success + failed), 3),
            "agents_in_recovery": in_recovery,
            "agents_escalated": escalated,
        }


# Singleton
_recovery_instance: Optional[AutoRecovery] = None
_recovery_lock = threading.Lock()


def get_auto_recovery(config: Optional[AutoRecoveryConfig] = None) -> AutoRecovery:
    """Get the singleton auto-recovery instance."""
    global _recovery_instance
    with _recovery_lock:
        if _recovery_instance is None:
            _recovery_instance = AutoRecovery(config)
        return _recovery_instance
