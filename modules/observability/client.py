"""
observability/client.py — Python client for the Observability node.

Usage:
    from observability.client import ObsClient
    import time, uuid

    obs = ObsClient(agent_id="engineer0")

    # Push a metric
    obs.gauge("queue_depth", 12)
    obs.counter("tasks_completed", 1)
    obs.histogram("llm_latency_ms", 350.5)

    # Batch push
    obs.batch([
        ("gauge", "cpu_pct", 45.2),
        ("gauge", "mem_mb", 1024),
    ])

    # Trace a request
    trace_id = str(uuid.uuid4())
    span_id  = obs.start_span(trace_id, "tool_call")
    # ... do work ...
    obs.end_span(span_id, trace_id, "tool_call", status="ok")

    # Health beat
    obs.beat(status="ok", cpu_pct=45.2, mem_mb=1024, model_latency_ms=350)
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx

logger = logging.getLogger("observability.client")

DEFAULT_URL = "http://127.0.0.1:9108"


class ObsClient:
    def __init__(self, agent_id: str, url: str = DEFAULT_URL, timeout: float = 5.0):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.timeout  = timeout
        self._spans: dict[str, float] = {}  # span_id → started_at

    def _push(self, metric_name: str, value: float, metric_type: str,
              labels: dict | None = None) -> None:
        try:
            httpx.post(
                f"{self.url}/metrics",
                json={
                    "agent_id":    self.agent_id,
                    "metric_name": metric_name,
                    "metric_type": metric_type,
                    "value":       value,
                    "labels":      labels or {},
                },
                timeout=self.timeout,
            )
        except Exception:
            pass  # observability errors must never crash the agent

    def gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        self._push(name, value, "gauge", labels)

    def counter(self, name: str, value: float = 1.0, labels: dict | None = None) -> None:
        self._push(name, value, "counter", labels)

    def histogram(self, name: str, value: float, labels: dict | None = None) -> None:
        self._push(name, value, "histogram", labels)

    def batch(self, points: list[tuple[str, str, float]]) -> None:
        """Push multiple metrics at once. points: [(metric_type, metric_name, value)]"""
        try:
            httpx.post(
                f"{self.url}/metrics/batch",
                json={
                    "points": [
                        {"agent_id": self.agent_id, "metric_type": t,
                         "metric_name": n, "value": v}
                        for t, n, v in points
                    ]
                },
                timeout=self.timeout,
            )
        except Exception:
            pass

    def start_span(self, trace_id: str, name: str, parent_id: str = "") -> str:
        span_id = str(uuid.uuid4())
        started = time.time()
        self._spans[span_id] = started
        try:
            httpx.post(f"{self.url}/spans", json={
                "span_id":    span_id,
                "trace_id":   trace_id,
                "parent_id":  parent_id,
                "agent_id":   self.agent_id,
                "name":       name,
                "started_at": started,
            }, timeout=self.timeout)
        except Exception:
            pass
        return span_id

    def end_span(self, span_id: str, trace_id: str, name: str,
                 status: str = "ok", labels: dict | None = None) -> None:
        ended = time.time()
        started = self._spans.pop(span_id, ended)
        try:
            httpx.post(f"{self.url}/spans", json={
                "span_id":    span_id,
                "trace_id":   trace_id,
                "parent_id":  "",
                "agent_id":   self.agent_id,
                "name":       name,
                "status":     status,
                "started_at": started,
                "ended_at":   ended,
                "labels":     labels or {},
            }, timeout=self.timeout)
        except Exception:
            pass

    def beat(
        self,
        status:           str   = "ok",
        cpu_pct:          float | None = None,
        mem_mb:           float | None = None,
        queue_depth:      int   | None = None,
        model_latency_ms: float | None = None,
        extra:            dict  | None = None,
    ) -> None:
        try:
            httpx.post(f"{self.url}/health", json={
                "agent_id":         self.agent_id,
                "status":           status,
                "cpu_pct":          cpu_pct,
                "mem_mb":           mem_mb,
                "queue_depth":      queue_depth,
                "model_latency_ms": model_latency_ms,
                "extra":            extra or {},
            }, timeout=self.timeout)
        except Exception:
            pass
