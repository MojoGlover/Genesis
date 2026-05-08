"""Scheduler client — register cron/interval/once jobs. Silent-fail always."""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)


class SchedulerClient:
    def __init__(self, agent_id: str, url: str, enabled: bool = False):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.enabled  = enabled

    def cron(self, name: str, expression: str, callback_url: str,
             payload: dict | None = None) -> str | None:
        """Register a cron job. Returns job_id or None."""
        return self._create(name, "cron", expression, callback_url, payload)

    def interval(self, name: str, seconds: int, callback_url: str,
                 payload: dict | None = None) -> str | None:
        """Register an interval job. Returns job_id or None."""
        return self._create(name, "interval", str(seconds), callback_url, payload)

    def once(self, name: str, delay_seconds: int, callback_url: str,
             payload: dict | None = None) -> str | None:
        """Register a one-shot job. Returns job_id or None."""
        return self._create(name, "once", str(delay_seconds), callback_url, payload)

    def cancel(self, job_id: str) -> bool:
        if not self.enabled:
            return False
        try:
            r = httpx.delete(f"{self.url}/jobs/{job_id}", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def _create(self, name: str, job_type: str, schedule: str,
                callback_url: str, payload: dict | None) -> str | None:
        if not self.enabled:
            return None
        try:
            r = httpx.post(f"{self.url}/jobs", json={
                "name": name, "agent_id": self.agent_id,
                "job_type": job_type, "schedule": schedule,
                "callback_url": callback_url, "payload": payload or {},
            }, timeout=5.0)
            if r.status_code == 201:
                return r.json().get("job_id")
        except Exception:
            pass
        return None
