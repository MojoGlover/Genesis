"""
cerberus_client — Security gateway client for the cognitive loop.

Routes security-sensitive operations through Cerberus instead of handling
them locally. Any agent that loads this module can:

  - Request / validate / revoke credentials via Cerberus
  - Report security events to Cerberus's audit log
  - Trigger health and integrity scans
  - Check whether an action is permitted before executing it

This makes Cerberus the single security authority for the ecosystem.
No agent should manage credentials or run security scans independently.

Config keys (under modules.cerberus_client in config.yaml):
    url:      Cerberus API base URL (default: http://localhost:8200)
    timeout:  Request timeout in seconds (default: 10)
    agent_id: This agent's ID for credential requests (default: identity.designation)

If Cerberus is unreachable:
  - credential ops raise CerberusUnavailable (agent should not proceed without creds)
  - health/audit ops log a warning and return gracefully (non-blocking)

Returns:
    {
        "tools":        [CerberusGatewayTool],
        "capabilities": ["security_gateway"],
    }
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST = {
    "name": "cerberus_client",
    "description": "Security gateway — routes credential and security ops through Cerberus",
    "requires_credentials": [],
    "optional_credentials": ["CERBERUS_URL"],
    "requires_config": [],
    "provides": ["tools"],
    "capabilities": ["security_gateway"],
}

_DEFAULTS = {
    "url":      "http://localhost:8200",
    "timeout":  10,
    "agent_id": None,   # filled from identity config at setup time
}


# ── Exception ─────────────────────────────────────────────────────────────────

class CerberusUnavailable(Exception):
    """Raised when Cerberus API is not reachable and the operation cannot proceed."""


# ── Gateway client ────────────────────────────────────────────────────────────

class CerberusClient:
    """
    HTTP client for the Cerberus security API.

    All methods raise CerberusUnavailable on connection errors for credential
    operations (so the caller knows not to proceed). Health/audit calls fail
    silently to avoid blocking the agent loop.
    """

    def __init__(self, url: str, agent_id: str, timeout: int) -> None:
        self._base    = url.rstrip("/")
        self._agent_id = agent_id
        self._timeout = timeout

    # ── Credentials ──────────────────────────────────────────────────────────

    def request_credential(self, scopes: list[str] | None = None, ttl_days: int = 30) -> dict:
        """Ask Cerberus to issue a credential token for this agent."""
        return self._post("/credentials/issue", {
            "agent_id":  self._agent_id,
            "scopes":    scopes or [],
            "ttl_days":  ttl_days,
        }, critical=True)

    def validate_credential(self, token: str) -> dict:
        """Validate a credential token. Returns {valid, agent_id, scopes, ...}."""
        return self._post("/credentials/validate", {
            "agent_id": self._agent_id,
            "token":    token,
        }, critical=True)

    def revoke_credential(self, agent_id: str | None = None) -> dict:
        """Revoke this agent's (or another's) credential."""
        return self._post("/credentials/revoke", {
            "agent_id": agent_id or self._agent_id,
        }, critical=True)

    def rotate_credential(self, agent_id: str | None = None) -> dict:
        """Rotate (revoke + reissue) a credential."""
        return self._post("/credentials/rotate", {
            "agent_id": agent_id or self._agent_id,
        }, critical=True)

    def list_credentials(self) -> dict:
        """Return the current credential list from Cerberus."""
        return self._get("/credentials", critical=False)

    # ── Health & Integrity ────────────────────────────────────────────────────

    def health_check(self, agent: str | None = None) -> dict:
        """Run a health check on this agent (or another)."""
        path = f"/health/{agent}" if agent else "/health"
        return self._get(path, critical=False)

    def integrity_check(self, agent: str | None = None) -> dict:
        """Check file-level integrity of this agent's codebase."""
        target = agent or self._agent_id
        return self._post(f"/integrity/{target}", {}, critical=False)

    # ── Security scan ─────────────────────────────────────────────────────────

    def scan(self, mode: str = "quick") -> dict:
        """Request a security scan. mode: quick | standard | full."""
        return self._post("/scan", {"scan_type": mode}, critical=False)

    # ── Audit log ─────────────────────────────────────────────────────────────

    def audit_event(self, event_type: str, detail: str, severity: str = "info") -> None:
        """Record an audit event in Cerberus's tamper-evident log."""
        try:
            self._post("/audit/record", {
                "agent_id":   self._agent_id,
                "event_type": event_type,
                "detail":     detail,
                "severity":   severity,
            }, critical=False)
        except Exception as e:
            logger.warning(f"CerberusClient: failed to record audit event: {e}")

    def query_audit(self, event_type: str | None = None, limit: int = 50) -> dict:
        """Query the Cerberus audit log."""
        params = f"?limit={limit}"
        if event_type:
            params += f"&event_type={event_type}"
        return self._get(f"/audit{params}", critical=False)

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return Cerberus system status summary."""
        return self._get("/status", critical=False)

    def ping(self) -> bool:
        """Return True if Cerberus is reachable."""
        try:
            self._get("/health", critical=True)
            return True
        except CerberusUnavailable:
            return False
        except Exception:
            return False

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str, critical: bool) -> dict:
        try:
            import requests
            resp = requests.get(
                f"{self._base}{path}",
                timeout=self._timeout,
                headers={"X-Agent-ID": self._agent_id},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            msg = f"CerberusClient: GET {path} failed: {e}"
            if critical:
                raise CerberusUnavailable(msg)
            logger.warning(msg)
            return {}

    def _post(self, path: str, body: dict, critical: bool) -> dict:
        try:
            import requests
            resp = requests.post(
                f"{self._base}{path}",
                json=body,
                timeout=self._timeout,
                headers={"X-Agent-ID": self._agent_id},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            msg = f"CerberusClient: POST {path} failed: {e}"
            if critical:
                raise CerberusUnavailable(msg)
            logger.warning(msg)
            return {}


# ── Tool wrapper ──────────────────────────────────────────────────────────────

try:
    from tools.base_tool import BaseTool, ToolError
    _HAS_BASE = True
except ImportError:
    # BlackZero not on path — define a minimal stub
    class BaseTool:  # type: ignore[no-redef]
        pass
    class ToolError(Exception):  # type: ignore[no-redef]
        pass
    _HAS_BASE = False


class CerberusGatewayTool(BaseTool):
    """
    Tool interface for the executor to call Cerberus operations by name.

    Input schema:
        {"action": "credential_request", "scopes": [...], "ttl_days": 30}
        {"action": "credential_validate", "token": "..."}
        {"action": "credential_revoke",   "agent_id": "..."}   # optional
        {"action": "credential_rotate",   "agent_id": "..."}   # optional
        {"action": "health_check",        "agent": "..."}       # optional
        {"action": "integrity_check",     "agent": "..."}       # optional
        {"action": "scan",                "mode": "quick"}
        {"action": "audit_event",         "event_type": "...", "detail": "...", "severity": "info"}
        {"action": "status"}
        {"action": "ping"}
    """

    def __init__(self, client: CerberusClient) -> None:
        self._c = client

    @property
    def name(self) -> str:
        return "cerberus"

    @property
    def description(self) -> str:
        return (
            "Security gateway — all credential, health, integrity, and audit operations "
            "go through Cerberus. Actions: credential_request, credential_validate, "
            "credential_revoke, credential_rotate, health_check, integrity_check, "
            "scan, audit_event, status, ping."
        )

    def run(self, input: dict[str, Any]) -> dict[str, Any]:  # noqa: A002
        action = input.get("action", "")
        dispatch = {
            "credential_request":  lambda: self._c.request_credential(
                input.get("scopes"), input.get("ttl_days", 30)),
            "credential_validate": lambda: self._c.validate_credential(input["token"]),
            "credential_revoke":   lambda: self._c.revoke_credential(input.get("agent_id")),
            "credential_rotate":   lambda: self._c.rotate_credential(input.get("agent_id")),
            "health_check":        lambda: self._c.health_check(input.get("agent")),
            "integrity_check":     lambda: self._c.integrity_check(input.get("agent")),
            "scan":                lambda: self._c.scan(input.get("mode", "quick")),
            "audit_event":         lambda: (self._c.audit_event(
                input["event_type"], input["detail"], input.get("severity", "info")) or {}),
            "status":              lambda: self._c.status(),
            "ping":                lambda: {"reachable": self._c.ping()},
        }
        handler = dispatch.get(action)
        if not handler:
            raise ToolError(
                f"CerberusGateway: unknown action '{action}'. "
                f"Valid actions: {list(dispatch.keys())}"
            )
        try:
            return handler()
        except CerberusUnavailable as e:
            raise ToolError(str(e))


# ── Module entry point ────────────────────────────────────────────────────────

def setup(config: dict) -> dict:
    """Module entry point. Called by the loader."""
    try:
        from modules.module_manifest import registry
        registry.register("cerberus_client", MANIFEST, status="pending")
    except Exception:
        pass   # module manifest optional

    module_cfg = config.get("modules", {}).get("cerberus_client", {})
    cfg = {**_DEFAULTS, **module_cfg}

    # Resolve agent_id from identity config if not set explicitly
    agent_id = (
        cfg.get("agent_id")
        or config.get("identity", {}).get("designation", "unknown_agent")
    )

    # Allow env override
    url = os.environ.get("CERBERUS_URL", cfg["url"])

    client = CerberusClient(url=url, agent_id=agent_id, timeout=int(cfg["timeout"]))

    # Ping Cerberus — warn if unreachable but don't fail (might start later)
    if client.ping():
        logger.info(f"CerberusClient: connected to Cerberus at {url} as '{agent_id}'.")
        try:
            from modules.module_manifest import registry
            registry.mark_active("cerberus_client")
        except Exception:
            pass
    else:
        logger.warning(
            f"CerberusClient: Cerberus unreachable at {url}. "
            "Security gateway is offline. Start Cerberus with: python api.py"
        )

    tool = CerberusGatewayTool(client)
    return {
        "tools":        [tool],
        "capabilities": ["security_gateway"],
    }
