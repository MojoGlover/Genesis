"""
policy_gate/client.py — Python client for the PolicyGate node.

Every agent calls this before performing a sensitive action.
Fast path (milliseconds). Cerberus is only invoked when a rule triggers it.

Usage:
    from policy_gate.client import PolicyGateClient, PolicyDenied

    pg = PolicyGateClient(agent_id="engineer0")

    # Check before writing a file
    pg.allow("write", resource="~/ai/policies/security.md")  # raises PolicyDenied
    pg.allow("write", resource="~/ai/cmptrblk/output.txt")   # passes

    # Check before messaging another agent
    pg.allow("message", to_agent="cerberus")

    # Non-raising form — get the decision object
    result = pg.evaluate("deploy", resource="production-cloud-run")
    if result["decision"] != "allow":
        print(f"Blocked: {result['reason']}")

    # Cerberus / Operator can update rules at runtime
    pg.add_rule(
        rule_id="deny_external_writes",
        description="Engineer0 may not write outside its workspace",
        priority=800,
        from_agent="engineer0",
        action_type="write",
        resource_pattern="/etc/*",
        effect="deny",
        reason="Out-of-scope write.",
    )
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("policy_gate.client")

DEFAULT_URL = "http://127.0.0.1:9104"


class PolicyDenied(Exception):
    """Raised when an action is denied by the policy gate."""
    def __init__(self, decision: str, rule_id: str, reason: str):
        self.decision = decision
        self.rule_id  = rule_id
        self.reason   = reason
        super().__init__(f"PolicyGate [{decision}] rule={rule_id}: {reason}")


class PolicyGateClient:
    """
    Thread-safe client for the PolicyGate node.
    All methods are synchronous.
    """

    def __init__(self, agent_id: str, url: str = DEFAULT_URL, timeout: float = 10.0):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.timeout  = timeout

    def evaluate(
        self,
        action_type: str,
        resource:    str = "",
        to_agent:    str = "",
        payload:     dict[str, Any] | None = None,
        context:     dict[str, Any] | None = None,
    ) -> dict:
        """
        Evaluate an action. Returns the full decision dict.
        Does NOT raise on deny — use allow() for that.
        """
        resp = httpx.post(
            f"{self.url}/evaluate",
            json={
                "from_agent":  self.agent_id,
                "action_type": action_type,
                "resource":    resource,
                "to_agent":    to_agent,
                "payload":     payload or {},
                "context":     context or {},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def allow(
        self,
        action_type: str,
        resource:    str = "",
        to_agent:    str = "",
        payload:     dict[str, Any] | None = None,
        context:     dict[str, Any] | None = None,
    ) -> dict:
        """
        Evaluate an action. Raises PolicyDenied if not allowed.
        Returns the decision dict on success.
        """
        result = self.evaluate(action_type, resource, to_agent, payload, context)
        decision = result.get("decision", "allow")

        if decision in ("deny", "approve_required"):
            logger.warning(
                f"[policy_gate] {self.agent_id} {action_type} {resource!r} → {decision}: {result.get('reason')}"
            )
            raise PolicyDenied(
                decision=decision,
                rule_id=result.get("rule_id", "unknown"),
                reason=result.get("reason", ""),
            )

        logger.debug(
            f"[policy_gate] {self.agent_id} {action_type} {resource!r} → {decision}"
        )
        return result

    # ── Rule management (Cerberus / Operator use) ─────────────────────────────

    def add_rule(
        self,
        rule_id:          str,
        effect:           str,
        description:      str = "",
        priority:         int = 50,
        from_agent:       str = "",
        action_type:      str = "",
        resource_pattern: str = "",
        to_agent:         str = "",
        payload_keys:     list[str] | None = None,
        reason:           str = "",
        enabled:          bool = True,
    ) -> dict:
        resp = httpx.post(
            f"{self.url}/rules",
            json={
                "rule_id":          rule_id,
                "description":      description,
                "priority":         priority,
                "from_agent":       from_agent,
                "action_type":      action_type,
                "resource_pattern": resource_pattern,
                "to_agent":         to_agent,
                "payload_keys":     payload_keys or [],
                "effect":           effect,
                "reason":           reason,
                "enabled":          enabled,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def remove_rule(self, rule_id: str) -> dict:
        resp = httpx.delete(f"{self.url}/rules/{rule_id}", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def list_rules(self) -> list[dict]:
        resp = httpx.get(f"{self.url}/rules", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["rules"]

    def decisions(self, limit: int = 50) -> list[dict]:
        resp = httpx.get(
            f"{self.url}/decisions/{self.agent_id}",
            params={"limit": limit},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("decisions", [])

    def is_healthy(self) -> bool:
        try:
            r = httpx.get(f"{self.url}/health", timeout=3.0)
            return r.status_code == 200 and r.json().get("ok")
        except Exception:
            return False
