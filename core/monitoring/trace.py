"""
GENESIS Distributed Tracing

Provides request correlation across agents for debugging multi-agent workflows.

Features:
- Trace context propagation via message bus
- Span hierarchy (trace -> span -> child spans)
- Timing, tags, and error capture
- Sampling and retention policies
- Integration with LogAggregator and IncidentTracker

Usage:
    from core.monitoring import get_tracer, trace_context
    
    tracer = get_tracer()
    
    # Start a new trace
    with tracer.start_trace("order_processing", agent="order_agent") as trace:
        # Create child spans
        with trace.span("validate_order") as span:
            span.set_tag("order_id", "12345")
            # ... do work ...
        
        with trace.span("process_payment") as span:
            # ... do work ...
            span.set_error("Payment declined")
    
    # Propagate context via message bus
    context = trace_context()  # Gets current trace context
    message_bus.publish("order.created", data, context=context)
    
    # Continue trace from received message
    with tracer.continue_trace(message.context) as trace:
        # ... handle message ...
"""

from __future__ import annotations
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class SpanStatus(Enum):
    """Status of a span."""
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class SpanTag:
    """A key-value tag on a span."""
    key: str
    value: Any
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SpanEvent:
    """An event/log entry within a span."""
    name: str
    timestamp: datetime
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "timestamp": self.timestamp.isoformat(),
            "attributes": self.attributes,
        }


@dataclass
class Span:
    """A single unit of work within a trace."""
    span_id: str
    trace_id: str
    name: str
    agent: str
    parent_span_id: Optional[str] = None
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    status: SpanStatus = SpanStatus.OK
    tags: List[SpanTag] = field(default_factory=list)
    events: List[SpanEvent] = field(default_factory=list)
    error_message: Optional[str] = None
    _tracer: Optional["Tracer"] = field(default=None, repr=False)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds() * 1000

    @property
    def is_root(self) -> bool:
        return self.parent_span_id is None

    def set_tag(self, key: str, value: Any) -> None:
        self.tags.append(SpanTag(key=key, value=value))

    def set_tags(self, tags: Dict[str, Any]) -> None:
        for key, value in tags.items():
            self.set_tag(key, value)

    def log_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self.events.append(SpanEvent(
            name=name,
            timestamp=datetime.now(),
            attributes=attributes or {},
        ))

    def set_error(self, message: str, exception: Optional[Exception] = None) -> None:
        self.status = SpanStatus.ERROR
        self.error_message = message
        if exception:
            self.log_event("exception", {
                "type": type(exception).__name__,
                "message": str(exception),
            })

    def finish(self) -> None:
        if self.end_time is None:
            self.end_time = datetime.now()
        if self._tracer:
            self._tracer._on_span_finish(self)

    def __enter__(self) -> "Span":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.set_error(str(exc_val), exc_val)
        self.finish()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "name": self.name,
            "agent": self.agent,
            "parent_span_id": self.parent_span_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "tags": [t.to_dict() for t in self.tags],
            "events": [e.to_dict() for e in self.events],
            "error_message": self.error_message,
            "is_root": self.is_root,
        }


class SpanContext:
    """Context manager for nested spans."""
    def __init__(self, span: Span, trace: "Trace", prev: Optional[Span]):
        self.span = span
        self.trace = trace
        self.prev = prev

    def __enter__(self) -> Span:
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.span.set_error(str(exc_val), exc_val)
        self.span.finish()
        self.trace._current_span = self.prev


@dataclass
class Trace:
    """A distributed trace representing an end-to-end request flow."""
    trace_id: str
    name: str
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    root_span: Optional[Span] = None
    spans: List[Span] = field(default_factory=list)
    tags: Dict[str, Any] = field(default_factory=dict)
    _tracer: Optional["Tracer"] = field(default=None, repr=False)
    _current_span: Optional[Span] = field(default=None, repr=False)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds() * 1000

    @property
    def span_count(self) -> int:
        return len(self.spans)

    @property
    def has_errors(self) -> bool:
        return any(s.status == SpanStatus.ERROR for s in self.spans)

    @property
    def error_count(self) -> int:
        return sum(1 for s in self.spans if s.status == SpanStatus.ERROR)

    def set_tag(self, key: str, value: Any) -> None:
        self.tags[key] = value

    def span(self, name: str, agent: Optional[str] = None) -> SpanContext:
        """Create a child span within the trace."""
        parent_id = self._current_span.span_id if self._current_span else (
            self.root_span.span_id if self.root_span else None
        )
        span = Span(
            span_id=str(uuid.uuid4())[:8],
            trace_id=self.trace_id,
            name=name,
            agent=agent or (self._current_span.agent if self._current_span else "unknown"),
            parent_span_id=parent_id,
            _tracer=self._tracer,
        )
        self.spans.append(span)
        old_span = self._current_span
        self._current_span = span
        return SpanContext(span, self, old_span)

    def finish(self) -> None:
        if self.end_time is None:
            self.end_time = datetime.now()
        if self._tracer:
            self._tracer._on_trace_finish(self)

    def __enter__(self) -> "Trace":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.root_span and self.root_span.end_time is None:
            if exc_type is not None:
                self.root_span.set_error(str(exc_val), exc_val)
            self.root_span.finish()
        self.finish()

    def get_context(self) -> Dict[str, str]:
        """Get propagation context for passing to other agents."""
        return {
            "trace_id": self.trace_id,
            "span_id": self._current_span.span_id if self._current_span else (
                self.root_span.span_id if self.root_span else None
            ),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "name": self.name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "span_count": self.span_count,
            "has_errors": self.has_errors,
            "error_count": self.error_count,
            "tags": self.tags,
            "spans": [s.to_dict() for s in self.spans],
        }

    def to_tree(self) -> Dict[str, Any]:
        """Get a tree representation of spans."""
        span_map: Dict[str, Dict[str, Any]] = {}
        for span in self.spans:
            span_map[span.span_id] = {**span.to_dict(), "children": []}
        
        root_spans = []
        for span in self.spans:
            span_dict = span_map[span.span_id]
            if span.parent_span_id and span.parent_span_id in span_map:
                span_map[span.parent_span_id]["children"].append(span_dict)
            else:
                root_spans.append(span_dict)
        
        return {
            "trace_id": self.trace_id,
            "name": self.name,
            "duration_ms": self.duration_ms,
            "spans": root_spans,
        }


@dataclass
class TracerConfig:
    """Configuration for the distributed tracer."""
    enabled: bool = True
    sample_rate: float = 1.0
    max_traces: int = 1000
    max_trace_age_hours: float = 24.0
    log_completed_traces: bool = True
    propagate_to_incidents: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "sample_rate": self.sample_rate,
            "max_traces": self.max_traces,
            "max_trace_age_hours": self.max_trace_age_hours,
            "log_completed_traces": self.log_completed_traces,
            "propagate_to_incidents": self.propagate_to_incidents,
        }


class Tracer:
    """Distributed tracing system for GENESIS."""

    def __init__(self, config: Optional[TracerConfig] = None):
        self._config = config or TracerConfig()
        self._lock = threading.Lock()
        self._traces: Dict[str, Trace] = {}
        self._completed_traces: List[Trace] = []
        self._current_trace: threading.local = threading.local()
        self._on_trace_complete_callbacks: List[Callable[[Trace], None]] = []
        self._cleanup_task = None
        self._running = False

    def configure(
        self,
        enabled: Optional[bool] = None,
        sample_rate: Optional[float] = None,
        max_traces: Optional[int] = None,
        max_trace_age_hours: Optional[float] = None,
    ) -> None:
        if enabled is not None:
            self._config.enabled = enabled
        if sample_rate is not None:
            self._config.sample_rate = max(0.0, min(1.0, sample_rate))
        if max_traces is not None:
            self._config.max_traces = max_traces
        if max_trace_age_hours is not None:
            self._config.max_trace_age_hours = max_trace_age_hours

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            self._cleanup_task = loop.create_task(self._cleanup_loop())
        except RuntimeError:
            pass
        logger.info("Distributed tracer started")

    def stop(self) -> None:
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("Distributed tracer stopped")

    async def _cleanup_loop(self) -> None:
        import asyncio
        while self._running:
            await asyncio.sleep(300)
            self._cleanup_old_traces()

    def _cleanup_old_traces(self) -> None:
        cutoff = datetime.now() - timedelta(hours=self._config.max_trace_age_hours)
        with self._lock:
            self._completed_traces = [
                t for t in self._completed_traces
                if t.end_time and t.end_time > cutoff
            ]
            to_remove = [
                tid for tid, t in self._traces.items()
                if t.start_time < cutoff
            ]
            for tid in to_remove:
                del self._traces[tid]
            if len(self._completed_traces) > self._config.max_traces:
                self._completed_traces = self._completed_traces[-self._config.max_traces:]

    def _should_sample(self) -> bool:
        import random
        return random.random() < self._config.sample_rate

    def start_trace(
        self,
        name: str,
        agent: str,
        tags: Optional[Dict[str, Any]] = None,
    ) -> Trace:
        if not self._config.enabled or not self._should_sample():
            return self._create_noop_trace(name)

        trace_id = str(uuid.uuid4())[:12]
        trace = Trace(
            trace_id=trace_id,
            name=name,
            tags=tags or {},
            _tracer=self,
        )
        
        root_span = Span(
            span_id=str(uuid.uuid4())[:8],
            trace_id=trace_id,
            name=name,
            agent=agent,
            _tracer=self,
        )
        trace.root_span = root_span
        trace.spans.append(root_span)
        trace._current_span = root_span

        with self._lock:
            self._traces[trace_id] = trace

        self._current_trace.trace = trace
        logger.debug(f"Started trace {trace_id}: {name}")
        return trace

    def _create_noop_trace(self, name: str) -> Trace:
        return Trace(trace_id="noop", name=name, _tracer=None)

    def continue_trace(
        self,
        context: Dict[str, str],
        name: str,
        agent: str,
    ) -> Trace:
        if not self._config.enabled:
            return self._create_noop_trace(name)

        trace_id = context.get("trace_id")
        parent_span_id = context.get("span_id")

        if not trace_id:
            return self.start_trace(name, agent)

        with self._lock:
            trace = self._traces.get(trace_id)

        if trace is None:
            trace = Trace(trace_id=trace_id, name=name, _tracer=self)
            with self._lock:
                self._traces[trace_id] = trace

        span = Span(
            span_id=str(uuid.uuid4())[:8],
            trace_id=trace_id,
            name=name,
            agent=agent,
            parent_span_id=parent_span_id,
            _tracer=self,
        )
        trace.spans.append(span)
        trace._current_span = span
        self._current_trace.trace = trace
        logger.debug(f"Continued trace {trace_id}: {name}")
        return trace

    def get_current_trace(self) -> Optional[Trace]:
        return getattr(self._current_trace, "trace", None)

    def get_current_context(self) -> Optional[Dict[str, str]]:
        trace = self.get_current_trace()
        if trace and trace.trace_id != "noop":
            return trace.get_context()
        return None

    def _on_span_finish(self, span: Span) -> None:
        if span.duration_ms:
            logger.debug(f"Span finished: {span.name} ({span.duration_ms:.1f}ms)")

    def _on_trace_finish(self, trace: Trace) -> None:
        with self._lock:
            if trace.trace_id in self._traces:
                del self._traces[trace.trace_id]
            self._completed_traces.append(trace)

        if self._config.log_completed_traces and trace.duration_ms:
            status = "ERROR" if trace.has_errors else "OK"
            logger.info(
                f"Trace completed: {trace.name} [{status}] "
                f"({trace.duration_ms:.1f}ms, {trace.span_count} spans)"
            )

        for callback in self._on_trace_complete_callbacks:
            try:
                callback(trace)
            except Exception as e:
                logger.error(f"Error in trace callback: {e}")

        if trace.has_errors and self._config.propagate_to_incidents:
            self._create_incident_for_trace(trace)

    def _create_incident_for_trace(self, trace: Trace) -> None:
        try:
            from .incident_tracker import get_incident_tracker, IncidentSeverity
            
            tracker = get_incident_tracker()
            errored_spans = [s for s in trace.spans if s.status == SpanStatus.ERROR]
            primary_agent = errored_spans[0].agent if errored_spans else "unknown"
            
            tracker.create_incident(
                title=f"Trace error: {trace.name}",
                primary_agent=primary_agent,
                severity=IncidentSeverity.MEDIUM,
                tags=["trace_error", trace.trace_id],
            )
        except Exception as e:
            logger.error(f"Failed to create incident for trace: {e}")

    def on_trace_complete(self, callback: Callable[[Trace], None]) -> None:
        self._on_trace_complete_callbacks.append(callback)

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        with self._lock:
            if trace_id in self._traces:
                return self._traces[trace_id]
            for trace in self._completed_traces:
                if trace.trace_id == trace_id:
                    return trace
        return None

    def get_active_traces(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [t.to_dict() for t in self._traces.values()]

    def get_recent_traces(
        self,
        limit: int = 50,
        agent: Optional[str] = None,
        has_errors: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            traces = list(self._completed_traces)

        if agent:
            traces = [t for t in traces if any(s.agent == agent for s in t.spans)]
        if has_errors is not None:
            traces = [t for t in traces if t.has_errors == has_errors]

        return [t.to_dict() for t in traces[-limit:]]

    def search_traces(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        query_lower = query.lower()
        with self._lock:
            results = []
            for trace in self._completed_traces:
                if query_lower in trace.name.lower():
                    results.append(trace)
                    continue
                for key, value in trace.tags.items():
                    if query_lower in str(key).lower() or query_lower in str(value).lower():
                        results.append(trace)
                        break
                else:
                    for span in trace.spans:
                        if query_lower in span.name.lower():
                            results.append(trace)
                            break
            return [t.to_dict() for t in results[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            active_count = len(self._traces)
            completed_count = len(self._completed_traces)
            error_count = sum(1 for t in self._completed_traces if t.has_errors)
            
            durations = [
                t.duration_ms for t in self._completed_traces
                if t.duration_ms is not None
            ]
            avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "active_traces": active_count,
            "completed_traces": completed_count,
            "error_traces": error_count,
            "error_rate": error_count / completed_count if completed_count > 0 else 0,
            "avg_duration_ms": avg_duration,
            "config": self._config.to_dict(),
        }

    def get_status(self) -> Dict[str, Any]:
        return {"running": self._running, **self.get_stats()}

    def clear(self) -> int:
        with self._lock:
            count = len(self._completed_traces)
            self._completed_traces = []
            return count


# Singleton
_tracer_instance: Optional[Tracer] = None
_tracer_lock = threading.Lock()


def get_tracer() -> Tracer:
    global _tracer_instance
    with _tracer_lock:
        if _tracer_instance is None:
            _tracer_instance = Tracer()
        return _tracer_instance


def trace_context() -> Optional[Dict[str, str]]:
    """Get the current trace context for propagation."""
    return get_tracer().get_current_context()


def traced(name: Optional[str] = None, agent: Optional[str] = None):
    """Decorator to automatically trace a function."""
    def decorator(func):
        import functools
        import asyncio

        trace_name = name or func.__name__
        trace_agent = agent or "unknown"

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            current = tracer.get_current_trace()
            
            if current:
                with current.span(trace_name, trace_agent):
                    return func(*args, **kwargs)
            else:
                with tracer.start_trace(trace_name, trace_agent):
                    return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            current = tracer.get_current_trace()
            
            if current:
                with current.span(trace_name, trace_agent):
                    return await func(*args, **kwargs)
            else:
                with tracer.start_trace(trace_name, trace_agent):
                    return await func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
