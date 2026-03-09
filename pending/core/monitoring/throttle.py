"""
GENESIS Alert Throttle

Prevents alert fatigue through intelligent throttling.

Features:
- Per-agent rate limiting
- Deduplication of similar alerts
- Escalation for repeated issues
- Quiet hours support
- Alert grouping/batching
"""

from __future__ import annotations
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ThrottleConfig:
    """Configuration for alert throttling."""
    # Rate limiting
    min_interval_seconds: float = 60.0    # Min time between same alert
    max_alerts_per_hour: int = 10         # Max alerts per agent per hour

    # Deduplication
    dedup_window_seconds: float = 300.0   # Window for considering alerts as duplicates
    similarity_threshold: float = 0.8     # Message similarity threshold

    # Escalation
    escalation_count: int = 3             # After this many suppressed, escalate
    escalation_window_seconds: float = 600.0  # Window for counting suppressed

    # Quiet hours (24-hour format)
    quiet_hours_start: Optional[int] = None  # e.g., 22 for 10 PM
    quiet_hours_end: Optional[int] = None    # e.g., 7 for 7 AM
    quiet_hours_buffer: bool = True          # Buffer alerts during quiet hours


@dataclass
class AlertRecord:
    """Record of an alert for throttling purposes."""
    agent: str
    message: str
    severity: str
    timestamp: datetime
    hash_key: str
    suppressed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "message": self.message,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat(),
            "suppressed": self.suppressed,
        }


class AlertThrottle:
    """
    Throttles alerts to prevent alert fatigue.

    Usage:
        throttle = get_alert_throttle()

        # Wrap alert sending
        if throttle.should_send(agent, message, severity):
            send_alert(agent, message, severity)

        # Or use decorator
        @throttle.throttled
        def send_my_alert(agent, message, severity):
            ...
    """

    def __init__(self, config: Optional[ThrottleConfig] = None):
        self._config = config or ThrottleConfig()
        self._lock = threading.Lock()

        # Tracking data
        self._alert_history: List[AlertRecord] = []
        self._agent_counts: Dict[str, List[datetime]] = defaultdict(list)
        self._last_alert: Dict[str, datetime] = {}
        self._suppressed_counts: Dict[str, int] = defaultdict(int)
        self._buffered_alerts: List[AlertRecord] = []

        # Max history size
        self._max_history = 1000

        # Callbacks
        self._on_escalation: List[Callable[[str, int], None]] = []

    def should_send(self, agent: str, message: str, severity: str) -> Tuple[bool, str]:
        """
        Check if an alert should be sent.

        Returns:
            Tuple of (should_send, reason)
        """
        now = datetime.now()
        hash_key = self._compute_hash(agent, message)

        with self._lock:
            # Check quiet hours
            if self._is_quiet_hours(now):
                record = AlertRecord(agent, message, severity, now, hash_key, suppressed=True)
                if self._config.quiet_hours_buffer:
                    self._buffered_alerts.append(record)
                self._add_to_history(record)
                return False, "quiet_hours"

            # Check rate limit (min interval)
            last = self._last_alert.get(hash_key)
            if last and (now - last).total_seconds() < self._config.min_interval_seconds:
                self._handle_suppressed(agent, message, severity, now, hash_key)
                return False, "rate_limited"

            # Check hourly limit
            self._cleanup_old_counts(agent, now)
            if len(self._agent_counts[agent]) >= self._config.max_alerts_per_hour:
                self._handle_suppressed(agent, message, severity, now, hash_key)
                return False, "hourly_limit"

            # Check for duplicate
            if self._is_duplicate(agent, message, now):
                self._handle_suppressed(agent, message, severity, now, hash_key)
                return False, "duplicate"

            # Alert can be sent
            self._last_alert[hash_key] = now
            self._agent_counts[agent].append(now)
            self._suppressed_counts[hash_key] = 0

            record = AlertRecord(agent, message, severity, now, hash_key, suppressed=False)
            self._add_to_history(record)

            return True, "allowed"

    def _handle_suppressed(self, agent: str, message: str, severity: str, 
                          now: datetime, hash_key: str) -> None:
        """Handle a suppressed alert."""
        record = AlertRecord(agent, message, severity, now, hash_key, suppressed=True)
        self._add_to_history(record)

        # Track suppression count for escalation
        self._suppressed_counts[hash_key] += 1

        # Check for escalation
        if self._suppressed_counts[hash_key] >= self._config.escalation_count:
            self._trigger_escalation(agent, self._suppressed_counts[hash_key])
            self._suppressed_counts[hash_key] = 0

    def _trigger_escalation(self, agent: str, count: int) -> None:
        """Trigger escalation callbacks."""
        logger.warning(f"Alert escalation for {agent}: {count} suppressed alerts")
        for callback in self._on_escalation:
            try:
                callback(agent, count)
            except Exception as e:
                logger.error(f"Escalation callback error: {e}")

    def _is_quiet_hours(self, now: datetime) -> bool:
        """Check if current time is during quiet hours."""
        if self._config.quiet_hours_start is None or self._config.quiet_hours_end is None:
            return False

        hour = now.hour
        start = self._config.quiet_hours_start
        end = self._config.quiet_hours_end

        if start < end:
            return start <= hour < end
        else:
            return hour >= start or hour < end

    def _is_duplicate(self, agent: str, message: str, now: datetime) -> bool:
        """Check if alert is a duplicate of recent alert."""
        cutoff = now - timedelta(seconds=self._config.dedup_window_seconds)

        for record in reversed(self._alert_history):
            if record.timestamp < cutoff:
                break
            if record.agent == agent and not record.suppressed:
                similarity = self._compute_similarity(message, record.message)
                if similarity >= self._config.similarity_threshold:
                    return True

        return False

    def _compute_hash(self, agent: str, message: str) -> str:
        """Compute a hash key for alert deduplication."""
        import hashlib
        content = f"{agent}:{message[:100]}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _compute_similarity(self, msg1: str, msg2: str) -> float:
        """Compute similarity between two messages."""
        if msg1 == msg2:
            return 1.0

        words1 = set(msg1.lower().split())
        words2 = set(msg2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def _cleanup_old_counts(self, agent: str, now: datetime) -> None:
        """Remove counts older than 1 hour."""
        cutoff = now - timedelta(hours=1)
        self._agent_counts[agent] = [
            ts for ts in self._agent_counts[agent] if ts > cutoff
        ]

    def _add_to_history(self, record: AlertRecord) -> None:
        """Add record to history with size limit."""
        self._alert_history.append(record)
        if len(self._alert_history) > self._max_history:
            self._alert_history = self._alert_history[-self._max_history:]

    def flush_buffered(self) -> List[AlertRecord]:
        """Get and clear buffered alerts from quiet hours."""
        with self._lock:
            alerts = self._buffered_alerts.copy()
            self._buffered_alerts.clear()
            return alerts

    def on_escalation(self, callback: Callable[[str, int], None]) -> None:
        """Register callback for alert escalation."""
        self._on_escalation.append(callback)

    def configure(self, **kwargs) -> None:
        """Update configuration."""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)

    def get_stats(self) -> Dict[str, Any]:
        """Get throttle statistics."""
        with self._lock:
            now = datetime.now()
            recent = [r for r in self._alert_history 
                     if (now - r.timestamp).total_seconds() < 3600]
            suppressed = [r for r in recent if r.suppressed]

            return {
                "total_alerts_1h": len(recent),
                "suppressed_1h": len(suppressed),
                "suppression_rate": len(suppressed) / max(1, len(recent)),
                "buffered_count": len(self._buffered_alerts),
                "agents_tracked": len(self._agent_counts),
                "is_quiet_hours": self._is_quiet_hours(now),
                "config": {
                    "min_interval_seconds": self._config.min_interval_seconds,
                    "max_alerts_per_hour": self._config.max_alerts_per_hour,
                    "quiet_hours": {
                        "start": self._config.quiet_hours_start,
                        "end": self._config.quiet_hours_end,
                    },
                },
            }

    def get_recent_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alert history."""
        with self._lock:
            return [r.to_dict() for r in self._alert_history[-limit:]]

    def reset(self) -> None:
        """Reset all throttle state."""
        with self._lock:
            self._alert_history.clear()
            self._agent_counts.clear()
            self._last_alert.clear()
            self._suppressed_counts.clear()
            self._buffered_alerts.clear()


_throttle_instance: Optional[AlertThrottle] = None
_throttle_lock = threading.Lock()


def get_alert_throttle() -> AlertThrottle:
    """Get the singleton alert throttle instance."""
    global _throttle_instance
    with _throttle_lock:
        if _throttle_instance is None:
            _throttle_instance = AlertThrottle()
        return _throttle_instance


def throttled_alert(agent: str, message: str, severity: str) -> Tuple[bool, str]:
    """Check if alert should be sent after throttling."""
    return get_alert_throttle().should_send(agent, message, severity)