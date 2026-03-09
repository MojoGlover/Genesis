"""
GENESIS Alert System

Send notifications via ntfy.sh for agent issues.

Severity levels:
- NORMAL: Just log, no notification
- DEGRADED: High priority push notification
- CRITICAL: Urgent push (bypasses Do Not Disturb)
"""

from __future__ import annotations
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""
    NORMAL = "normal"       # Log only
    DEGRADED = "degraded"   # High priority push
    CRITICAL = "critical"   # Urgent push (bypasses DND)


@dataclass
class AlertConfig:
    """Configuration for the alert system."""
    ntfy_topic: str = "genesis-alerts"
    ntfy_server: str = "https://ntfy.sh"
    enabled: bool = True
    min_severity: AlertSeverity = AlertSeverity.DEGRADED

    @classmethod
    def from_file(cls, path: Path) -> AlertConfig:
        """Load config from JSON file."""
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            return cls(
                ntfy_topic=data.get("ntfy_topic", "genesis-alerts"),
                ntfy_server=data.get("ntfy_server", "https://ntfy.sh"),
                enabled=data.get("enabled", True),
                min_severity=AlertSeverity(data.get("min_severity", "degraded")),
            )
        return cls()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ntfy_topic": self.ntfy_topic,
            "ntfy_server": self.ntfy_server,
            "enabled": self.enabled,
            "min_severity": self.min_severity.value,
        }


@dataclass
class Alert:
    """An alert to be sent."""
    severity: AlertSeverity
    agent: str
    title: str
    message: str
    timestamp: datetime
    context: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "agent": self.agent,
            "title": self.title,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
        }


class AlertSystem:
    """
    Alert system using ntfy.sh for push notifications.

    Usage:
        alerts = get_alert_system()

        # Configure (optional - uses defaults)
        alerts.configure(ntfy_topic="my-genesis-alerts")

        # Send alert
        alerts.send_alert(
            severity=AlertSeverity.CRITICAL,
            agent="route_optimizer",
            message="Agent has stopped responding"
        )
    """

    def __init__(self, config: Optional[AlertConfig] = None):
        """Initialize the alert system."""
        config_path = Path.home() / ".genesis" / "config" / "alerts.json"
        self._config = config or AlertConfig.from_file(config_path)
        self._lock = threading.Lock()
        self._alert_history: List[Alert] = []
        self._max_history = 100

    def configure(
        self,
        ntfy_topic: Optional[str] = None,
        ntfy_server: Optional[str] = None,
        enabled: Optional[bool] = None,
        min_severity: Optional[AlertSeverity] = None,
    ) -> None:
        """Update configuration."""
        with self._lock:
            if ntfy_topic:
                self._config.ntfy_topic = ntfy_topic
            if ntfy_server:
                self._config.ntfy_server = ntfy_server
            if enabled is not None:
                self._config.enabled = enabled
            if min_severity:
                self._config.min_severity = min_severity

    def send_alert(
        self,
        severity: AlertSeverity,
        agent: str,
        message: str,
        title: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send an alert.

        Args:
            severity: Alert severity level
            agent: Name of the agent
            message: Alert message
            title: Optional title (defaults to agent name)
            context: Additional context

        Returns:
            True if alert was sent successfully
        """
        alert = Alert(
            severity=severity,
            agent=agent,
            title=title or f"{severity.value.upper()}: {agent}",
            message=message,
            timestamp=datetime.now(),
            context=context or {},
        )

        # Store in history
        with self._lock:
            self._alert_history.append(alert)
            if len(self._alert_history) > self._max_history:
                self._alert_history = self._alert_history[-self._max_history:]

        # Log the alert
        log_level = {
            AlertSeverity.NORMAL: logging.INFO,
            AlertSeverity.DEGRADED: logging.WARNING,
            AlertSeverity.CRITICAL: logging.ERROR,
        }.get(severity, logging.WARNING)

        logger.log(log_level, f"Alert [{severity.value}] {agent}: {message}")

        # Check if we should send push notification
        if not self._config.enabled:
            logger.debug("Alerts disabled, skipping push")
            return True

        severity_order = [AlertSeverity.NORMAL, AlertSeverity.DEGRADED, AlertSeverity.CRITICAL]
        if severity_order.index(severity) < severity_order.index(self._config.min_severity):
            logger.debug(f"Severity {severity.value} below minimum {self._config.min_severity.value}")
            return True

        # Send push notification
        return self._send_ntfy(alert)

    def _send_ntfy(self, alert: Alert) -> bool:
        """Send notification via ntfy.sh."""
        url = f"{self._config.ntfy_server}/{self._config.ntfy_topic}"

        # Set priority based on severity
        priority = {
            AlertSeverity.NORMAL: "default",
            AlertSeverity.DEGRADED: "high",
            AlertSeverity.CRITICAL: "urgent",
        }.get(alert.severity, "default")

        # Build headers
        headers = {
            "Title": alert.title,
            "Priority": priority,
            "Tags": f"robot,{alert.severity.value}",
        }

        # Add click action for critical alerts
        if alert.severity == AlertSeverity.CRITICAL:
            headers["Actions"] = "view, Open Dashboard, http://localhost:8000/dashboard"

        try:
            data = alert.message.encode('utf-8')
            request = urllib.request.Request(url, data=data, headers=headers, method='POST')

            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status == 200:
                    logger.info(f"Alert sent to ntfy: {alert.title}")
                    return True
                else:
                    logger.warning(f"ntfy returned status {response.status}")
                    return False

        except urllib.error.URLError as e:
            logger.error(f"Failed to send ntfy alert: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending alert: {e}")
            return False

    def get_recent_alerts(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        with self._lock:
            return [a.to_dict() for a in self._alert_history[-limit:]]

    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return self._config.to_dict()

    def test_alert(self) -> bool:
        """Send a test alert to verify configuration."""
        return self.send_alert(
            severity=AlertSeverity.NORMAL,
            agent="alert_system",
            message="This is a test alert from GENESIS",
            title="GENESIS Test Alert",
        )


# Singleton
_alert_instance: Optional[AlertSystem] = None
_alert_lock = threading.Lock()


def get_alert_system() -> AlertSystem:
    """Get the singleton alert system instance."""
    global _alert_instance
    with _alert_lock:
        if _alert_instance is None:
            _alert_instance = AlertSystem()
        return _alert_instance


# Convenience functions
def alert_degraded(agent: str, message: str, context: Optional[Dict] = None) -> bool:
    """Send a degraded alert."""
    return get_alert_system().send_alert(
        AlertSeverity.DEGRADED, agent, message, context=context
    )


def alert_critical(agent: str, message: str, context: Optional[Dict] = None) -> bool:
    """Send a critical alert."""
    return get_alert_system().send_alert(
        AlertSeverity.CRITICAL, agent, message, context=context
    )
