"""
GENESIS Error Logger

Centralized error logging for all agents.
- Writes to log files
- Stores in SQLite for analysis
- Triggers alerts for critical errors
"""

from __future__ import annotations
import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ErrorEntry:
    """A logged error entry."""
    id: Optional[int]
    timestamp: datetime
    agent: str
    severity: ErrorSeverity
    message: str
    context: Dict[str, Any]
    exception_type: Optional[str] = None
    stack_trace: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "agent": self.agent,
            "severity": self.severity.value,
            "message": self.message,
            "context": self.context,
            "exception_type": self.exception_type,
            "stack_trace": self.stack_trace,
        }


class ErrorLogger:
    """
    Centralized error logging system.

    Usage:
        logger = get_error_logger()

        # Log an error
        logger.log_error(
            agent="route_optimizer",
            error="Failed to calculate route",
            context={"stops": 5},
            severity=ErrorSeverity.ERROR
        )

        # Query recent errors
        errors = logger.get_recent_errors(limit=10)

        # Get errors for specific agent
        errors = logger.get_agent_errors("route_optimizer")
    """

    def __init__(self, log_dir: Optional[Path] = None, db_path: Optional[Path] = None):
        """
        Initialize the error logger.

        Args:
            log_dir: Directory for log files
            db_path: Path to SQLite database
        """
        self._log_dir = log_dir or Path.home() / ".genesis" / "logs"
        self._db_path = db_path or Path.home() / ".genesis" / "errors.db"

        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._alert_callback: Optional[callable] = None

        # Initialize database
        self._init_db()

        # Set up file logging
        self._setup_file_logging()

    def _init_db(self) -> None:
        """Initialize SQLite database."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    context TEXT,
                    exception_type TEXT,
                    stack_trace TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_errors_agent ON errors(agent)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_errors_timestamp ON errors(timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_errors_severity ON errors(severity)
            """)
            conn.commit()

    def _setup_file_logging(self) -> None:
        """Set up rotating file logging."""
        log_file = self._log_dir / "genesis_errors.log"

        handler = logging.FileHandler(log_file)
        handler.setLevel(logging.WARNING)
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(name)s | %(message)s'
        )
        handler.setFormatter(formatter)

        # Add to root logger
        logging.getLogger().addHandler(handler)

    def log_error(
        self,
        agent: str,
        error: str,
        context: Optional[Dict[str, Any]] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        exception: Optional[Exception] = None,
    ) -> int:
        """
        Log an error.

        Args:
            agent: Name of the agent that raised the error
            error: Error message
            context: Additional context
            severity: Error severity level
            exception: Original exception if available

        Returns:
            Error entry ID
        """
        timestamp = datetime.now()
        context = context or {}

        exception_type = None
        stack_trace = None
        if exception:
            exception_type = type(exception).__name__
            import traceback
            stack_trace = traceback.format_exc()

        # Log to Python logger
        log_level = getattr(logging, severity.value.upper(), logging.ERROR)
        logger.log(log_level, f"[{agent}] {error}", extra={"context": context})

        # Store in database
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO errors (timestamp, agent, severity, message, context, exception_type, stack_trace)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp.isoformat(),
                        agent,
                        severity.value,
                        error,
                        json.dumps(context),
                        exception_type,
                        stack_trace,
                    )
                )
                error_id = cursor.lastrowid
                conn.commit()

        # Trigger alert for critical errors
        if severity in (ErrorSeverity.ERROR, ErrorSeverity.CRITICAL) and self._alert_callback:
            self._alert_callback(agent, error, severity, context)

        return error_id

    def get_recent_errors(self, limit: int = 50, severity: Optional[ErrorSeverity] = None) -> List[ErrorEntry]:
        """Get recent errors."""
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                if severity:
                    cursor = conn.execute(
                        """
                        SELECT id, timestamp, agent, severity, message, context, exception_type, stack_trace
                        FROM errors
                        WHERE severity = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (severity.value, limit)
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT id, timestamp, agent, severity, message, context, exception_type, stack_trace
                        FROM errors
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (limit,)
                    )

                return [self._row_to_entry(row) for row in cursor.fetchall()]

    def get_agent_errors(self, agent: str, limit: int = 20) -> List[ErrorEntry]:
        """Get errors for a specific agent."""
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    """
                    SELECT id, timestamp, agent, severity, message, context, exception_type, stack_trace
                    FROM errors
                    WHERE agent = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (agent, limit)
                )
                return [self._row_to_entry(row) for row in cursor.fetchall()]

    def get_error_stats(self) -> Dict[str, Any]:
        """Get error statistics."""
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                # Total counts by severity
                cursor = conn.execute(
                    """
                    SELECT severity, COUNT(*) as count
                    FROM errors
                    GROUP BY severity
                    """
                )
                by_severity = {row[0]: row[1] for row in cursor.fetchall()}

                # Counts by agent
                cursor = conn.execute(
                    """
                    SELECT agent, COUNT(*) as count
                    FROM errors
                    GROUP BY agent
                    ORDER BY count DESC
                    LIMIT 10
                    """
                )
                by_agent = {row[0]: row[1] for row in cursor.fetchall()}

                # Recent 24 hours
                cursor = conn.execute(
                    """
                    SELECT COUNT(*) FROM errors
                    WHERE timestamp > datetime('now', '-1 day')
                    """
                )
                last_24h = cursor.fetchone()[0]

                return {
                    "by_severity": by_severity,
                    "by_agent": by_agent,
                    "last_24h": last_24h,
                    "total": sum(by_severity.values()),
                }

    def clear_old_errors(self, days: int = 30) -> int:
        """Clear errors older than specified days."""
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    f"""
                    DELETE FROM errors
                    WHERE timestamp < datetime('now', '-{days} days')
                    """
                )
                deleted = cursor.rowcount
                conn.commit()
                return deleted

    def set_alert_callback(self, callback: callable) -> None:
        """Set callback for error alerts."""
        self._alert_callback = callback

    def _row_to_entry(self, row: tuple) -> ErrorEntry:
        """Convert database row to ErrorEntry."""
        return ErrorEntry(
            id=row[0],
            timestamp=datetime.fromisoformat(row[1]),
            agent=row[2],
            severity=ErrorSeverity(row[3]),
            message=row[4],
            context=json.loads(row[5]) if row[5] else {},
            exception_type=row[6],
            stack_trace=row[7],
        )


# Singleton
_logger_instance: Optional[ErrorLogger] = None
_logger_lock = threading.Lock()


def get_error_logger() -> ErrorLogger:
    """Get the singleton error logger instance."""
    global _logger_instance
    with _logger_lock:
        if _logger_instance is None:
            _logger_instance = ErrorLogger()
        return _logger_instance
