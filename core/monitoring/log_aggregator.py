"""
GENESIS Log Aggregator

Centralized structured logging for all agents with search, filtering,
and correlation capabilities.

Features:
- Structured JSON log collection from all agents
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Context tagging (agent, task, request_id)
- In-memory ring buffer with configurable size
- Full-text search across log messages
- Time-range queries
- Log export for debugging
- Integration with message bus for distributed logging

Usage:
    from core.monitoring import get_log_aggregator, LogLevel
    
    logger = get_log_aggregator()
    logger.log(
        level=LogLevel.INFO,
        agent="route_optimizer",
        message="Route calculation complete",
        context={"route_id": "abc123", "waypoints": 5}
    )
    
    # Search logs
    results = logger.search("route", agent="route_optimizer", hours=1.0)
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional

from core.messaging import Message, MessageType, get_message_bus

module_logger = logging.getLogger(__name__)


class LogLevel(Enum):
    """Log severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# Level ordering for filtering
_LEVEL_ORDER = {
    LogLevel.DEBUG: 0,
    LogLevel.INFO: 1,
    LogLevel.WARNING: 2,
    LogLevel.ERROR: 3,
    LogLevel.CRITICAL: 4,
}


@dataclass
class LogEntry:
    """A single log entry with structured data."""
    log_id: str
    timestamp: datetime
    level: LogLevel
    agent: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    
    # Optional correlation fields
    request_id: Optional[str] = None
    task_id: Optional[str] = None
    parent_id: Optional[str] = None
    
    # Source info
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    
    def __post_init__(self):
        if not self.log_id:
            self.log_id = self._generate_id()
    
    def _generate_id(self) -> str:
        data = f"{self.agent}:{self.timestamp.isoformat()}:{self.message[:50]}"
        return hashlib.md5(data.encode()).hexdigest()[:12]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "agent": self.agent,
            "message": self.message,
            "context": self.context,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "parent_id": self.parent_id,
            "source_file": self.source_file,
            "source_line": self.source_line,
        }
    
    def matches_filter(
        self,
        min_level: Optional[LogLevel] = None,
        agent: Optional[str] = None,
        request_id: Optional[str] = None,
        task_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> bool:
        """Check if entry matches filter criteria."""
        if min_level and _LEVEL_ORDER[self.level] < _LEVEL_ORDER[min_level]:
            return False
        if agent and self.agent != agent:
            return False
        if request_id and self.request_id != request_id:
            return False
        if task_id and self.task_id != task_id:
            return False
        if since and self.timestamp < since:
            return False
        if until and self.timestamp > until:
            return False
        return True
    
    def matches_search(self, query: str) -> bool:
        """Check if entry matches search query."""
        query_lower = query.lower()
        if query_lower in self.message.lower():
            return True
        if query_lower in self.agent.lower():
            return True
        for value in self.context.values():
            if query_lower in str(value).lower():
                return True
        return False


@dataclass
class LogAggregatorConfig:
    """Configuration for log aggregation."""
    max_entries: int = 10000
    max_entries_per_agent: int = 2000
    retention_hours: float = 24.0
    cleanup_interval_seconds: float = 300.0
    subscribe_to_bus: bool = True
    also_log_to_python: bool = True
    min_level_to_store: LogLevel = LogLevel.DEBUG


class LogAggregator:
    """Central log aggregation service for all GENESIS agents."""
    
    def __init__(self, config: Optional[LogAggregatorConfig] = None):
        self._config = config or LogAggregatorConfig()
        self._entries: Deque[LogEntry] = deque(maxlen=self._config.max_entries)
        self._entries_by_agent: Dict[str, Deque[LogEntry]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stats = {
            "total_logged": 0,
            "by_level": {level.value: 0 for level in LogLevel},
            "by_agent": {},
        }
        self._on_log: List[Callable[[LogEntry], None]] = []
    
    def start(self) -> None:
        """Start the log aggregator."""
        if self._running:
            return
        self._running = True
        if self._config.subscribe_to_bus:
            bus = get_message_bus()
            bus.subscribe(MessageType.LOG, self._handle_log_message)
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="log-cleanup"
        )
        self._cleanup_thread.start()
        module_logger.info("Log aggregator started")
    
    def stop(self) -> None:
        """Stop the log aggregator."""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5.0)
        module_logger.info("Log aggregator stopped")
    
    def log(
        self,
        level: LogLevel,
        agent: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        task_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        source_file: Optional[str] = None,
        source_line: Optional[int] = None,
    ) -> str:
        """Log a structured message."""
        if _LEVEL_ORDER[level] < _LEVEL_ORDER[self._config.min_level_to_store]:
            return ""
        
        entry = LogEntry(
            log_id="",
            timestamp=datetime.now(),
            level=level,
            agent=agent,
            message=message,
            context=context or {},
            request_id=request_id,
            task_id=task_id,
            parent_id=parent_id,
            source_file=source_file,
            source_line=source_line,
        )
        
        with self._lock:
            self._entries.append(entry)
            if agent not in self._entries_by_agent:
                self._entries_by_agent[agent] = deque(maxlen=self._config.max_entries_per_agent)
            self._entries_by_agent[agent].append(entry)
            self._stats["total_logged"] += 1
            self._stats["by_level"][level.value] += 1
            self._stats["by_agent"][agent] = self._stats["by_agent"].get(agent, 0) + 1
        
        if self._config.also_log_to_python:
            py_level = {
                LogLevel.DEBUG: logging.DEBUG,
                LogLevel.INFO: logging.INFO,
                LogLevel.WARNING: logging.WARNING,
                LogLevel.ERROR: logging.ERROR,
                LogLevel.CRITICAL: logging.CRITICAL,
            }.get(level, logging.INFO)
            module_logger.log(py_level, f"[{agent}] {message}")
        
        for callback in self._on_log:
            try:
                callback(entry)
            except Exception as e:
                module_logger.error(f"Log callback error: {e}")
        
        return entry.log_id
    
    def debug(self, agent: str, message: str, **kwargs) -> str:
        return self.log(LogLevel.DEBUG, agent, message, **kwargs)
    
    def info(self, agent: str, message: str, **kwargs) -> str:
        return self.log(LogLevel.INFO, agent, message, **kwargs)
    
    def warning(self, agent: str, message: str, **kwargs) -> str:
        return self.log(LogLevel.WARNING, agent, message, **kwargs)
    
    def error(self, agent: str, message: str, **kwargs) -> str:
        return self.log(LogLevel.ERROR, agent, message, **kwargs)
    
    def critical(self, agent: str, message: str, **kwargs) -> str:
        return self.log(LogLevel.CRITICAL, agent, message, **kwargs)
    
    def query(
        self,
        min_level: Optional[LogLevel] = None,
        agent: Optional[str] = None,
        request_id: Optional[str] = None,
        task_id: Optional[str] = None,
        hours: Optional[float] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LogEntry]:
        """Query log entries with filters."""
        if hours is not None:
            since = datetime.now() - timedelta(hours=hours)
        with self._lock:
            if agent and agent in self._entries_by_agent:
                source = list(self._entries_by_agent[agent])
            else:
                source = list(self._entries)
            results = []
            for entry in reversed(source):
                if entry.matches_filter(min_level=min_level, agent=agent, request_id=request_id, task_id=task_id, since=since, until=until):
                    results.append(entry)
            return results[offset:offset + limit]
    
    def search(self, query: str, min_level: Optional[LogLevel] = None, agent: Optional[str] = None, hours: float = 1.0, limit: int = 100) -> List[LogEntry]:
        """Full-text search across log messages."""
        since = datetime.now() - timedelta(hours=hours)
        with self._lock:
            results = []
            for entry in reversed(list(self._entries)):
                if len(results) >= limit:
                    break
                if entry.timestamp < since:
                    continue
                if not entry.matches_filter(min_level=min_level, agent=agent):
                    continue
                if entry.matches_search(query):
                    results.append(entry)
            return results
    
    def get_by_request(self, request_id: str, limit: int = 100) -> List[LogEntry]:
        return self.query(request_id=request_id, limit=limit)
    
    def get_by_task(self, task_id: str, limit: int = 100) -> List[LogEntry]:
        return self.query(task_id=task_id, limit=limit)
    
    def get_recent(self, limit: int = 50, agent: Optional[str] = None, min_level: Optional[LogLevel] = None) -> List[Dict[str, Any]]:
        entries = self.query(agent=agent, min_level=min_level, limit=limit)
        return [e.to_dict() for e in entries]
    
    def get_agent_logs(self, agent: str, limit: int = 100, min_level: Optional[LogLevel] = None) -> List[Dict[str, Any]]:
        entries = self.query(agent=agent, min_level=min_level, limit=limit)
        return [e.to_dict() for e in entries]
    
    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "total_entries": len(self._entries),
                "total_logged": self._stats["total_logged"],
                "by_level": dict(self._stats["by_level"]),
                "by_agent": dict(self._stats["by_agent"]),
                "agents": list(self._entries_by_agent.keys()),
                "config": {"max_entries": self._config.max_entries, "retention_hours": self._config.retention_hours},
            }
    
    def get_agents(self) -> List[str]:
        with self._lock:
            return list(self._entries_by_agent.keys())
    
    def clear(self, agent: Optional[str] = None) -> int:
        with self._lock:
            if agent:
                if agent in self._entries_by_agent:
                    count = len(self._entries_by_agent[agent])
                    self._entries_by_agent[agent].clear()
                    self._entries = deque((e for e in self._entries if e.agent != agent), maxlen=self._config.max_entries)
                    return count
                return 0
            else:
                count = len(self._entries)
                self._entries.clear()
                self._entries_by_agent.clear()
                return count
    
    def export(self, agent: Optional[str] = None, hours: float = 1.0, min_level: Optional[LogLevel] = None) -> List[Dict[str, Any]]:
        entries = self.query(agent=agent, hours=hours, min_level=min_level, limit=10000)
        return [e.to_dict() for e in entries]
    
    def on_log(self, callback: Callable[[LogEntry], None]) -> None:
        self._on_log.append(callback)
    
    def _handle_log_message(self, message: Message) -> None:
        payload = message.payload
        try:
            level = LogLevel(payload.get("level", "info"))
        except ValueError:
            level = LogLevel.INFO
        self.log(level=level, agent=message.sender, message=payload.get("message", ""), context=payload.get("context", {}), request_id=payload.get("request_id"), task_id=payload.get("task_id"), source_file=payload.get("source_file"), source_line=payload.get("source_line"))
    
    def _cleanup_loop(self) -> None:
        while self._running:
            time.sleep(self._config.cleanup_interval_seconds)
            try:
                self._cleanup_old_entries()
            except Exception as e:
                module_logger.error(f"Log cleanup error: {e}")
    
    def _cleanup_old_entries(self) -> None:
        cutoff = datetime.now() - timedelta(hours=self._config.retention_hours)
        with self._lock:
            while self._entries and self._entries[0].timestamp < cutoff:
                self._entries.popleft()
            for agent_entries in self._entries_by_agent.values():
                while agent_entries and agent_entries[0].timestamp < cutoff:
                    agent_entries.popleft()


_aggregator_instance: Optional[LogAggregator] = None
_aggregator_lock = threading.Lock()


def get_log_aggregator(config: Optional[LogAggregatorConfig] = None) -> LogAggregator:
    global _aggregator_instance
    with _aggregator_lock:
        if _aggregator_instance is None:
            _aggregator_instance = LogAggregator(config)
        return _aggregator_instance


def log_debug(agent: str, message: str, **kwargs) -> str:
    return get_log_aggregator().debug(agent, message, **kwargs)


def log_info(agent: str, message: str, **kwargs) -> str:
    return get_log_aggregator().info(agent, message, **kwargs)


def log_warning(agent: str, message: str, **kwargs) -> str:
    return get_log_aggregator().warning(agent, message, **kwargs)


def log_error(agent: str, message: str, **kwargs) -> str:
    return get_log_aggregator().error(agent, message, **kwargs)


def log_critical(agent: str, message: str, **kwargs) -> str:
    return get_log_aggregator().critical(agent, message, **kwargs)
