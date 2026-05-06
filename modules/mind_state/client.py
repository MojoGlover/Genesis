"""
mind_state/client.py — Python client for the MindState node.

Agents use this to save and restore their state across restarts.
Agent Hospital uses it to recover dead agents.

Usage:
    from mind_state.client import MindStateClient

    ms = MindStateClient(agent_id="engineer0")

    # Save state before sleep / after task completion
    ms.save(state={
        "memory":         [...],
        "active_task":    {"id": "task-42", "step": 3},
        "context_summary": "Working on registry module build.",
        "goals":          ["finish registry", "seal module"],
    })

    # On startup — restore if available
    state = ms.restore()
    if state:
        print(f"Resuming from version {state['version']}")

    # Explicit checkpoint before risky operation
    ms.checkpoint(label="before_deploy")
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("mind_state.client")

DEFAULT_URL = "http://127.0.0.1:9102"


class MindStateError(Exception):
    pass


class MindStateClient:
    """
    Thread-safe client for the MindState node.
    All methods are synchronous and safe to call from any thread.
    """

    def __init__(self, agent_id: str, url: str = DEFAULT_URL, timeout: float = 10.0):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.timeout  = timeout

    # ── Save ─────────────────────────────────────────────────────────────────

    def save(
        self,
        state:         dict[str, Any],
        snapshot_type: str = "auto",
        label:         str = "",
    ) -> dict:
        """
        Save agent state. Creates a new version automatically.

        snapshot_type options:
          auto            — routine save during normal operation
          checkpoint      — explicit save to keep long-term
          shutdown        — clean shutdown, state is stable
          crash_recovery  — state saved just before suspected crash
        """
        resp = httpx.post(
            f"{self.url}/agents/{self.agent_id}/state",
            json={"state": state, "snapshot_type": snapshot_type, "label": label},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.debug(
            f"[mind_state] saved {self.agent_id} v{data['version']} "
            f"({data['size_bytes']}B, {snapshot_type})"
        )
        return data

    def checkpoint(self, state: dict[str, Any] | None = None, label: str = "") -> dict:
        """
        Save or promote current state as a checkpoint.
        If state is provided, saves it first then marks as checkpoint.
        If state is None, promotes the existing latest version.
        """
        if state is not None:
            self.save(state, snapshot_type="checkpoint", label=label)

        resp = httpx.post(
            f"{self.url}/agents/{self.agent_id}/state/checkpoint",
            params={"label": label},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def save_shutdown(self, state: dict[str, Any], label: str = "clean_shutdown") -> dict:
        """Save state on clean shutdown so Agent Hospital knows the agent stopped intentionally."""
        return self.save(state, snapshot_type="shutdown", label=label)

    # ── Restore ───────────────────────────────────────────────────────────────

    def restore(self) -> Optional[dict]:
        """
        Get latest saved state. Returns None if no state exists.
        This is what Agent Hospital calls to rebuild a dead agent.

        Returns dict with keys:
          version, snapshot_type, label, size_bytes, saved_at, state
        """
        resp = httpx.get(
            f"{self.url}/agents/{self.agent_id}/state",
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def restore_version(self, version: int) -> Optional[dict]:
        """Get a specific version — useful for rollback."""
        resp = httpx.get(
            f"{self.url}/agents/{self.agent_id}/state/{version}",
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def history(self, limit: int = 20) -> list[dict]:
        """List available versions (metadata only, no state payload)."""
        resp = httpx.get(
            f"{self.url}/agents/{self.agent_id}/state/history",
            params={"limit": limit},
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json().get("history", [])

    def last_checkpoint(self) -> Optional[dict]:
        """Find and restore the most recent checkpoint version."""
        versions = self.history(limit=50)
        for v in versions:
            if v["snapshot_type"] == "checkpoint":
                return self.restore_version(v["version"])
        return None

    # ── Wipe ─────────────────────────────────────────────────────────────────

    def wipe(self) -> dict:
        """Delete all saved state. Called by Agent Hospital after successful rebuild."""
        resp = httpx.delete(
            f"{self.url}/agents/{self.agent_id}/state",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        logger.info(f"[mind_state] wiped all state for {self.agent_id}")
        return resp.json()

    # ── Introspection ─────────────────────────────────────────────────────────

    def has_state(self) -> bool:
        resp = httpx.get(
            f"{self.url}/agents/{self.agent_id}/state",
            timeout=self.timeout,
        )
        return resp.status_code == 200

    def latest_version(self) -> int:
        h = self.history(limit=1)
        return h[0]["version"] if h else 0
