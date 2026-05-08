"""Observability client — metrics, spans, health beats. Silent-fail always."""
from __future__ import annotations
import logging, time, uuid
import httpx

logger = logging.getLogger(__name__)


class ObsClient:
    def __init__(self, agent_id: str, url: str, enabled: bool = True):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.enabled  = enabled
        self._spans: dict[str, float] = {}

    def _post(self, path: str, body: dict) -> None:
        if not self.enabled:
            return
        try:
            httpx.post(f"{self.url}{path}", json=body, timeout=3.0)
        except Exception:
            pass

    def gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        self._post("/metrics", {"agent_id": self.agent_id, "metric_name": name,
                                "metric_type": "gauge", "value": value,
                                "labels": labels or {}})

    def counter(self, name: str, value: float = 1.0, labels: dict | None = None) -> None:
        self._post("/metrics", {"agent_id": self.agent_id, "metric_name": name,
                                "metric_type": "counter", "value": value,
                                "labels": labels or {}})

    def histogram(self, name: str, value: float, labels: dict | None = None) -> None:
        self._post("/metrics", {"agent_id": self.agent_id, "metric_name": name,
                                "metric_type": "histogram", "value": value,
                                "labels": labels or {}})

    def start_span(self, trace_id: str, name: str) -> str:
        span_id = str(uuid.uuid4())
        started = time.time()
        self._spans[span_id] = started
        self._post("/spans", {"span_id": span_id, "trace_id": trace_id,
                              "agent_id": self.agent_id, "name": name,
                              "started_at": started})
        return span_id

    def end_span(self, span_id: str, trace_id: str, name: str, status: str = "ok") -> None:
        ended   = time.time()
        started = self._spans.pop(span_id, ended)
        self._post("/spans", {"span_id": span_id, "trace_id": trace_id,
                              "agent_id": self.agent_id, "name": name,
                              "started_at": started, "ended_at": ended,
                              "status": status})

    def beat(self, status: str = "ok", cpu_pct: float | None = None,
             mem_mb: float | None = None) -> None:
        self._post("/health", {"agent_id": self.agent_id, "status": status,
                               "cpu_pct": cpu_pct, "mem_mb": mem_mb})
