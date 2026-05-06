"""
supervisor/client.py — Python client for the Supervisor node.

Usage:
    from supervisor.client import SupervisorClient

    sv = SupervisorClient()

    # Register an agent so supervisor can manage it
    sv.declare("engineer0",
               name="Engineer0",
               command=["python3", "main_agent.py"],
               working_dir="~/ai/cmptrblk/Engineer0",
               restart_policy="on_failure")

    sv.start("engineer0")
    sv.restart("engineer0")
    sv.stop("engineer0")

    # Trigger Agent Hospital manually
    sv.heal("engineer0")

    # Inspect
    status = sv.get("engineer0")
    all_agents = sv.list_agents()
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger("supervisor.client")
DEFAULT_URL = "http://127.0.0.1:9103"


class SupervisorClient:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 10.0):
        self.url     = url.rstrip("/")
        self.timeout = timeout

    def declare(
        self,
        agent_id:       str,
        name:           str,
        command:        list[str],
        working_dir:    str,
        env_extra:      dict | None = None,
        restart_policy: str = "on_failure",
        max_restarts:   int = 5,
        backoff_base:   int = 2,
    ) -> dict:
        """Register an agent with the supervisor."""
        resp = httpx.post(
            f"{self.url}/agents/{agent_id}/declare",
            json={
                "name":           name,
                "command":        command,
                "working_dir":    working_dir,
                "env_extra":      env_extra or {},
                "restart_policy": restart_policy,
                "max_restarts":   max_restarts,
                "backoff_base":   backoff_base,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def start(self, agent_id: str) -> dict:
        resp = httpx.post(f"{self.url}/agents/{agent_id}/start", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def stop(self, agent_id: str) -> dict:
        resp = httpx.post(f"{self.url}/agents/{agent_id}/stop", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def restart(self, agent_id: str) -> dict:
        resp = httpx.post(f"{self.url}/agents/{agent_id}/restart", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def heal(self, agent_id: str) -> dict:
        """Trigger Agent Hospital — restore mind_state and restart."""
        resp = httpx.post(f"{self.url}/agents/{agent_id}/heal", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def remove(self, agent_id: str) -> dict:
        resp = httpx.delete(f"{self.url}/agents/{agent_id}", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get(self, agent_id: str) -> Optional[dict]:
        resp = httpx.get(f"{self.url}/agents/{agent_id}", timeout=self.timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def list_agents(self) -> list[dict]:
        resp = httpx.get(f"{self.url}/agents", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["agents"]

    def events(self, agent_id: str = "", limit: int = 50) -> list[dict]:
        params = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        resp = httpx.get(f"{self.url}/events", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["events"]

    def is_running(self, agent_id: str) -> bool:
        agent = self.get(agent_id)
        return agent is not None and agent.get("state") == "running"
