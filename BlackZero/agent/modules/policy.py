"""Policy gate client — authorization check before sensitive actions. Silent-fail = allow."""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)


class PolicyClient:
    def __init__(self, agent_id: str, url: str, enabled: bool = True):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.enabled  = enabled

    def allow(self, action: str, resource: str = "*",
              to_agent: str = "*") -> bool:
        """
        Returns True if allowed, False if denied.
        Silent-fail = allow (policy gate being down never blocks the agent).

        DEFERRED 2026-07-11 (audit): the port-9104 policy daemon was retired in
        D1, so this ALWAYS fails open — every action is allowed. The constitution's
        "policy-gated action" is currently enforced only by shell.py's destructive-
        pattern list. Re-home as a PlugOps endpoint before relying on policy gating.
        See memory: project-blackzero-deferred-security.
        """
        if not self.enabled:
            return True
        try:
            r = httpx.post(f"{self.url}/evaluate", json={
                "from_agent":  self.agent_id,
                "to_agent":    to_agent,
                "action_type": action,
                "resource":    resource,
            }, timeout=3.0)
            if r.status_code == 200:
                # Server returns "decision", not "effect"
                return r.json().get("decision", "allow") == "allow"
        except Exception:
            pass
        return True  # fail-open: down = allow
