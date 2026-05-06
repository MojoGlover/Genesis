"""
scheduler/client.py — Python client for the Scheduler node.

Usage:
    from scheduler.client import SchedulerClient

    sc = SchedulerClient(agent_id="accountant")

    # Run every day at 9am UTC
    job = sc.cron("daily_report", "0 9 * * *",
                  callback="http://localhost:5002/hooks/daily_report")

    # Run once in 60 seconds
    sc.once("send_welcome", delay_seconds=60,
            callback="http://localhost:5002/hooks/welcome",
            payload={"user_id": "abc123"})

    # Run every 5 minutes
    sc.interval("heartbeat", seconds=300,
                callback="http://localhost:5002/hooks/heartbeat")

    # Pause / resume / cancel
    sc.pause(job["job_id"])
    sc.resume(job["job_id"])
    sc.cancel(job["job_id"])

    # Manual trigger
    sc.fire(job["job_id"])

    # List my jobs
    jobs = sc.my_jobs()
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("scheduler.client")

DEFAULT_URL = "http://127.0.0.1:9107"


class SchedulerClient:
    def __init__(self, agent_id: str, url: str = DEFAULT_URL, timeout: float = 10.0):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.timeout  = timeout

    def _create(self, name: str, callback: str, job_type: str,
                schedule: str, payload: dict | None) -> dict:
        resp = httpx.post(
            f"{self.url}/jobs",
            json={
                "name":         name,
                "agent_id":     self.agent_id,
                "callback_url": callback,
                "job_type":     job_type,
                "schedule":     schedule,
                "payload":      payload or {},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def cron(self, name: str, expression: str, callback: str,
             payload: dict | None = None) -> dict:
        """Schedule a cron job. expression: 5-field cron string."""
        return self._create(name, callback, "cron", expression, payload)

    def interval(self, name: str, seconds: int, callback: str,
                 payload: dict | None = None) -> dict:
        """Schedule a repeating interval job."""
        return self._create(name, callback, "interval", str(seconds), payload)

    def once(self, name: str, delay_seconds: int, callback: str,
             payload: dict | None = None) -> dict:
        """Schedule a one-shot job to fire after delay_seconds."""
        return self._create(name, callback, "once", str(delay_seconds), payload)

    def cancel(self, job_id: str) -> dict:
        resp = httpx.delete(f"{self.url}/jobs/{job_id}", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def pause(self, job_id: str) -> dict:
        resp = httpx.post(f"{self.url}/jobs/{job_id}/pause", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def resume(self, job_id: str) -> dict:
        resp = httpx.post(f"{self.url}/jobs/{job_id}/resume", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fire(self, job_id: str) -> dict:
        """Manually trigger a job now."""
        resp = httpx.post(f"{self.url}/jobs/{job_id}/fire", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get(self, job_id: str) -> dict | None:
        resp = httpx.get(f"{self.url}/jobs/{job_id}", timeout=self.timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def my_jobs(self, status: str = "") -> list[dict]:
        params: dict = {"agent_id": self.agent_id}
        if status:
            params["status"] = status
        resp = httpx.get(f"{self.url}/jobs", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("jobs", [])

    def history(self, job_id: str, limit: int = 20) -> list[dict]:
        resp = httpx.get(
            f"{self.url}/history/{job_id}",
            params={"limit": limit},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("history", [])
