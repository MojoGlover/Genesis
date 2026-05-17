"""
messaging.py — inter-agent messaging via PlugOps SSE bus.

Provides two tools:
  send_to_agent  — deliver a message to another agent's inbox
  list_agents    — query the PlugOps registry for online agents

Both are synchronous wrappers around plain HTTP calls so they compose
cleanly with the existing ReAct tool executor (no async required).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import yaml

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0


def _load_config() -> dict[str, Any]:
    """Walk up from this file to find config.yaml in the agent root."""
    # messaging.py lives at agent/tools/messaging.py
    # agent root is two levels up: agent/tools/ → agent/ → <agent-root>/
    candidates = [
        Path(__file__).parents[2] / "config.yaml",   # standard stamp layout
        Path.cwd() / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            try:
                return yaml.safe_load(p.read_text()) or {}
            except Exception:
                pass
    return {}


def _plugops_base(cfg: dict) -> str:
    """Convert wss://host/ws/agent → https://host."""
    raw = cfg.get("plugops", {}).get("url", "")
    if not raw:
        return "http://localhost:9000"
    raw = raw.replace("wss://", "https://").replace("ws://", "http://")
    return "/".join(raw.split("/")[:3])


def _own_id(cfg: dict) -> str:
    ident = cfg.get("identity", {})
    return ident.get("alias") or ident.get("name", "unknown").lower()


# ── Public tool functions ─────────────────────────────────────────────────────

def send_to_agent(to: str, message: str) -> dict:
    """
    Send a message to another agent via PlugOps.

    Args:
        to:      Target agent alias (e.g. 'ceo', 'madjanet', 'accountant').
        message: Plain-text message content.

    Returns:
        {"ok": True}  on success
        {"ok": False, "error": str}  on failure
    """
    cfg     = _load_config()
    base    = _plugops_base(cfg)
    from_id = _own_id(cfg)

    payload = {
        "from": from_id,
        "to":   to,
        "payload": {
            "type": "message",
            "message": {
                "from_agent": from_id,
                "to_agent":   to,
                "content":    message,
            },
        },
    }

    try:
        r = httpx.post(f"{base}/api/v1/sse/send", json=payload, timeout=_TIMEOUT)
        if r.status_code == 200:
            logger.info("[messaging] sent to %s via %s", to, base)
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
    except httpx.ConnectError:
        return {"ok": False, "error": f"Cannot reach PlugOps at {base}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_agents() -> dict:
    """
    Return the current agent roster from PlugOps.

    Returns:
        {"ok": True, "agents": [...]}   each agent has id, name, status, capabilities
        {"ok": False, "error": str}
    """
    cfg  = _load_config()
    base = _plugops_base(cfg)

    try:
        r = httpx.get(f"{base}/api/v1/agents", timeout=_TIMEOUT)
        if r.status_code == 200:
            agents = r.json()
            return {"ok": True, "agents": agents}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except httpx.ConnectError:
        return {"ok": False, "error": f"Cannot reach PlugOps at {base}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
