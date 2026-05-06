"""
tool_bus/client.py — Python client for the ToolBus node.

Two roles:
  Requester — asks the bus to execute a tool (every agent)
  Provider  — registers tools it can execute and handles incoming requests

Usage (requester):
    from tool_bus.client import ToolBusClient

    tb = ToolBusClient(agent_id="ceo")

    # Execute synchronously
    result = tb.execute("web_search", {"query": "AI news"})
    print(result["result"])

    # Execute asynchronously (fire and forget, poll for result)
    job = tb.execute_async("shell", {"command": "ls -la"})
    time.sleep(2)
    done = tb.job(job["job_id"])

Usage (provider):
    from tool_bus.client import ToolBusClient

    tb = ToolBusClient(agent_id="operator")

    # Register tools
    tb.register([
        {"name": "web_search", "description": "Search the web", "priority": 10},
        {"name": "shell",      "description": "Run shell commands", "priority": 10},
    ], exec_url="http://127.0.0.1:5000/tools/exec")

    # On shutdown
    tb.deregister()
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("tool_bus.client")

DEFAULT_URL = "http://127.0.0.1:9105"


class ToolBusError(Exception):
    pass


class ToolBusClient:
    def __init__(self, agent_id: str, url: str = DEFAULT_URL, timeout: float = 35.0):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.timeout  = timeout

    # ── Provider side ─────────────────────────────────────────────────────────

    def register(self, tools: list[dict], exec_url: str) -> dict:
        """
        Register tools this agent provides.
        tools: list of {name, description?, input_schema?, priority?}
        exec_url: URL the bus will POST execution requests to.
        """
        resp = httpx.post(
            f"{self.url}/tools/register",
            json={
                "agent_id": self.agent_id,
                "exec_url": exec_url,
                "tools":    tools,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"[tool_bus] registered {len(tools)} tools for {self.agent_id}")
        return data

    def deregister(self) -> dict:
        """Remove all tools registered by this agent."""
        resp = httpx.delete(
            f"{self.url}/tools/provider/{self.agent_id}",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Requester side ────────────────────────────────────────────────────────

    def execute(
        self,
        tool_name: str,
        input:     dict[str, Any] | None = None,
        timeout:   float = 30.0,
    ) -> dict:
        """
        Execute a tool synchronously. Returns result dict.
        Raises ToolBusError if tool not found or execution fails.
        """
        resp = httpx.post(
            f"{self.url}/execute",
            json={
                "from_agent": self.agent_id,
                "tool_name":  tool_name,
                "input":      input or {},
                "timeout":    timeout,
                "mode":       "sync",
            },
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            data = resp.json()
            raise ToolBusError(f"Tool not found: {data.get('detail', {}).get('tool_name', tool_name)}")
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise ToolBusError(f"Tool error: {data['error']}")
        return data

    def execute_async(
        self,
        tool_name: str,
        input:     dict[str, Any] | None = None,
        timeout:   float = 60.0,
    ) -> dict:
        """Submit async job. Returns {"job_id": ..., "status": "pending"}."""
        resp = httpx.post(
            f"{self.url}/execute",
            json={
                "from_agent": self.agent_id,
                "tool_name":  tool_name,
                "input":      input or {},
                "timeout":    timeout,
                "mode":       "async",
            },
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            raise ToolBusError(f"Tool not found: {tool_name}")
        resp.raise_for_status()
        return resp.json()

    def job(self, job_id: str) -> dict:
        """Get job status and result."""
        resp = httpx.get(f"{self.url}/jobs/{job_id}", timeout=self.timeout)
        if resp.status_code == 404:
            raise ToolBusError(f"Job not found: {job_id}")
        resp.raise_for_status()
        return resp.json()

    def jobs(self, limit: int = 20, status: str = "") -> list[dict]:
        """List recent jobs for this agent."""
        params: dict = {"from_agent": self.agent_id, "limit": limit}
        if status:
            params["status"] = status
        resp = httpx.get(f"{self.url}/jobs", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("jobs", [])

    def list_tools(self) -> list[dict]:
        resp = httpx.get(f"{self.url}/tools", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("tools", [])

    def is_healthy(self) -> bool:
        try:
            r = httpx.get(f"{self.url}/health", timeout=3.0)
            return r.status_code == 200 and r.json().get("ok")
        except Exception:
            return False
