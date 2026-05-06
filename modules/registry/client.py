"""
registry/client.py — Python client for the Registry node.

All agents use this to register, send heartbeats, and look up peers.
Designed to slot in beside the comm client — same pattern.

Usage:
    from registry.client import RegistryClient

    client = RegistryClient(agent_id="engineer0", name="Engineer0",
                            role="infrastructure", capabilities=["code", "deploy"])
    client.register()
    # in background loop:
    client.heartbeat()          # call every 30s
    # peer discovery:
    agents = client.list_agents(capability="art_direction")
    janet  = client.get_agent("madjanet")
"""
from __future__ import annotations

import time
import threading
import logging
from typing import Optional

import httpx

logger = logging.getLogger("registry.client")

DEFAULT_URL     = "http://127.0.0.1:9101"
HB_INTERVAL     = 30   # seconds between heartbeats
HB_WARN_AT      = 60   # warn if heartbeat is this many seconds late


class RegistryError(Exception):
    pass


class AlreadyRegisteredError(RegistryError):
    """Raised on 409 — another instance of this agent is already live."""


class NotRegisteredError(RegistryError):
    """Raised on 404 heartbeat — agent must re-register."""


class RegistryClient:
    """
    Thin synchronous client for the Registry node.

    Thread-safe. Start the background heartbeat with start_heartbeat().
    Supervisor and other long-running processes should call this.
    """

    def __init__(
        self,
        agent_id:     str,
        name:         str,
        role:         str = "",
        capabilities: list[str] | None = None,
        host:         str = "localhost",
        port:         int | None = None,
        metadata:     dict | None = None,
        registry_url: str = DEFAULT_URL,
        timeout:      float = 5.0,
    ):
        self.agent_id     = agent_id
        self.name         = name
        self.role         = role
        self.capabilities = capabilities or []
        self.host         = host
        self.port         = port
        self.metadata     = metadata or {}
        self.url          = registry_url.rstrip("/")
        self.timeout      = timeout
        self.session_id: Optional[str] = None
        self._hb_thread: Optional[threading.Thread] = None
        self._stop_hb    = threading.Event()

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self) -> dict:
        """Register this agent. Raises AlreadyRegisteredError on 409."""
        resp = httpx.post(
            f"{self.url}/register",
            json={
                "agent_id":     self.agent_id,
                "name":         self.name,
                "role":         self.role,
                "capabilities": self.capabilities,
                "host":         self.host,
                "port":         self.port,
                "metadata":     self.metadata,
            },
            timeout=self.timeout,
        )
        if resp.status_code == 409:
            raise AlreadyRegisteredError(
                f"Agent '{self.agent_id}' is already registered: {resp.json()}"
            )
        resp.raise_for_status()
        data = resp.json()
        self.session_id = data["session_id"]
        logger.info(f"[registry] registered agent_id={self.agent_id} session={self.session_id}")
        return data

    def deregister(self) -> dict:
        """Cleanly deregister. Call on shutdown."""
        self._stop_hb.set()
        resp = httpx.delete(f"{self.url}/agents/{self.agent_id}", timeout=self.timeout)
        if resp.status_code == 404:
            return {"ok": False, "reason": "not_found"}
        resp.raise_for_status()
        logger.info(f"[registry] deregistered {self.agent_id}")
        return resp.json()

    def acquire_migration_lock(self) -> dict:
        """
        Acquire migration lock before shutting down to allow new instance to register.
        Call this BEFORE starting the new instance.
        """
        resp = httpx.post(
            f"{self.url}/agents/{self.agent_id}/migrate",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Heartbeat ────────────────────────────────────────────────────────────

    def heartbeat(self) -> dict:
        """Send a single heartbeat. Raises NotRegisteredError on 404."""
        resp = httpx.post(
            f"{self.url}/agents/{self.agent_id}/heartbeat",
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            raise NotRegisteredError(
                f"Registry doesn't know '{self.agent_id}'. Re-register."
            )
        resp.raise_for_status()
        return resp.json()

    def start_heartbeat(self, on_lost: callable | None = None) -> None:
        """
        Start background heartbeat thread. Non-blocking.

        on_lost: optional callback called if heartbeat gets a 404.
                 Default behavior: log error and attempt re-registration.
        """
        if self._hb_thread and self._hb_thread.is_alive():
            return

        self._stop_hb.clear()

        def _loop():
            while not self._stop_hb.wait(HB_INTERVAL):
                try:
                    self.heartbeat()
                    logger.debug(f"[registry] heartbeat ok — {self.agent_id}")
                except NotRegisteredError:
                    logger.error(f"[registry] heartbeat 404 — {self.agent_id} must re-register")
                    if on_lost:
                        on_lost()
                    else:
                        self._attempt_reregister()
                except Exception as e:
                    logger.warning(f"[registry] heartbeat failed — {self.agent_id}: {e}")

        self._hb_thread = threading.Thread(target=_loop, daemon=True, name=f"registry-hb-{self.agent_id}")
        self._hb_thread.start()
        logger.info(f"[registry] heartbeat thread started for {self.agent_id}")

    def stop_heartbeat(self) -> None:
        self._stop_hb.set()

    def _attempt_reregister(self) -> None:
        """Auto re-register after registry restart."""
        try:
            logger.info(f"[registry] attempting re-registration for {self.agent_id}")
            self.register()
        except AlreadyRegisteredError:
            logger.warning(f"[registry] re-register 409 — another instance running?")
        except Exception as e:
            logger.error(f"[registry] re-registration failed: {e}")

    # ── Discovery ────────────────────────────────────────────────────────────

    def list_agents(self, role: str = "", capability: str = "") -> list[dict]:
        """List all live agents, optionally filtered by role or capability."""
        params = {}
        if role:
            params["role"] = role
        if capability:
            params["capability"] = capability
        resp = httpx.get(f"{self.url}/agents", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["agents"]

    def get_agent(self, agent_id: str) -> dict | None:
        """Get a single agent record. Returns None if not found."""
        resp = httpx.get(f"{self.url}/agents/{agent_id}", timeout=self.timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def get_events(self, limit: int = 50) -> list[dict]:
        """Recent join/leave/death events — useful for supervisor."""
        resp = httpx.get(f"{self.url}/events", params={"limit": limit}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["events"]

    def is_live(self) -> bool:
        """Quick check: is this agent currently registered and live?"""
        agent = self.get_agent(self.agent_id)
        return agent is not None and agent.get("status") == "live"
