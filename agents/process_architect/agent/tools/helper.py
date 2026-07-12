"""
helper.py — Zee's personal API delegation layer.

Zee doesn't make direct external API calls from her core logic.
Instead she assigns APIs to named helper slots and asks helpers to fetch data.

Pattern:
    1. assign_api("anthropic", "https://api.anthropic.com", "ANTHROPIC_API_KEY")
    2. ask_helper("anthropic", "POST", "/v1/messages", payload={...})

The registry persists in ~/.zero/helpers.json so assignments survive restarts.
Keys are NEVER stored — only the env var name. The key is read at call time.

Why helpers instead of direct calls:
- Zee stays self-contained; no API credentials hard-wired into her codebase
- Zee controls which APIs her helpers have — she can revoke by removing the slot
- She can assign different APIs to different "roles" (research, codegen, vision)
- Future: helper slots can be forwarded to EngineerV workers for parallel fetches
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Registry path — lives in THIS agent's own data dir.
# Must be per-agent: a shared path (the old ~/.zero default) let every stamped
# agent read, overwrite, and revoke each other's API-helper slots.
def _agent_data_dir() -> Path:
    agent_root = Path(__file__).resolve().parents[2]
    agent_id = os.environ.get("AGENT_ID", "")
    data_dir = ""
    try:
        cfg_path = agent_root / "config.yaml"
        if cfg_path.exists():
            import yaml
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f) or {}
            ident = cfg.get("identity", {})
            agent_id = agent_id or ident.get("id") or ident.get("alias") or ident.get("designation", "")
            data_dir = cfg.get("data_dir", "")
    except Exception:
        pass
    if not data_dir:
        data_dir = f"~/.{agent_id or 'agent'}"
    return Path(data_dir).expanduser()


_REGISTRY_PATH = _agent_data_dir() / "helpers.json"
_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── Registry I/O ──────────────────────────────────────────────────────────────

def _load() -> dict:
    if _REGISTRY_PATH.exists():
        try:
            return json.loads(_REGISTRY_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save(registry: dict) -> None:
    _REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


# ── Tools ─────────────────────────────────────────────────────────────────────

def assign_api(
    name: str,
    base_url: str,
    key_env: str,
    description: str = "",
    default_headers: dict | None = None,
) -> dict:
    """
    Assign an external API to a named helper slot.

    Args:
        name:            Helper slot name (e.g. "anthropic", "openai", "perplexity")
        base_url:        API base URL (e.g. "https://api.anthropic.com")
        key_env:         Name of the env var that holds the API key
        description:     Optional human note about what this helper does
        default_headers: Optional headers sent with every request from this helper
                         (e.g. {"anthropic-version": "2023-06-01"}).
                         Do NOT include Authorization — that's injected from key_env.

    Returns:
        {"ok": true, "name": ..., "base_url": ..., "key_env": ..., "key_present": bool}
    """
    registry = _load()
    registry[name] = {
        "base_url":        base_url.rstrip("/"),
        "key_env":         key_env,
        "description":     description,
        "default_headers": default_headers or {},
    }
    _save(registry)
    key_present = bool(os.environ.get(key_env))
    logger.info(f"[helper] Assigned API '{name}' → {base_url} (key_env={key_env}, present={key_present})")
    return {
        "ok":          True,
        "name":        name,
        "base_url":    base_url,
        "key_env":     key_env,
        "key_present": key_present,
        "description": description,
    }


def revoke_api(name: str) -> dict:
    """
    Remove a helper slot.

    Args:
        name: Helper slot name to remove

    Returns:
        {"ok": true, "removed": name} or {"ok": false, "error": "not found"}
    """
    registry = _load()
    if name not in registry:
        return {"ok": False, "error": f"No helper named '{name}'"}
    del registry[name]
    _save(registry)
    logger.info(f"[helper] Revoked API slot '{name}'")
    return {"ok": True, "removed": name}


def list_helpers() -> dict:
    """
    List all assigned helper slots.

    Returns:
        {"helpers": [{name, base_url, key_env, key_present, description}, ...]}
    """
    registry = _load()
    helpers = []
    for name, cfg in registry.items():
        helpers.append({
            "name":        name,
            "base_url":    cfg["base_url"],
            "key_env":     cfg["key_env"],
            "key_present": bool(os.environ.get(cfg["key_env"])),
            "description": cfg.get("description", ""),
        })
    return {"helpers": helpers, "count": len(helpers)}


def ask_helper(
    name: str,
    method: str,
    path: str,
    payload: dict | None = None,
    extra_headers: dict | None = None,
    timeout: float = 30.0,
    auth_header: str = "Authorization",
    auth_prefix: str = "Bearer",
) -> dict:
    """
    Ask a named helper to make an API call.

    Args:
        name:          Helper slot name (must be registered via assign_api)
        method:        HTTP method: GET, POST, PUT, PATCH, DELETE
        path:          Path appended to the helper's base_url (e.g. "/v1/messages")
        payload:       JSON body for POST/PUT/PATCH (optional)
        extra_headers: Additional headers for this request only (merged with defaults)
        timeout:       Request timeout in seconds (default: 30)
        auth_header:   Header name for the API key (default: "Authorization")
        auth_prefix:   Prefix before the key value (default: "Bearer").
                       Set to "" for APIs that want a bare key (e.g. X-API-Key).

    Returns:
        {"ok": bool, "status": int, "body": dict|str, "helper": name}
        On error: {"ok": false, "error": "...", "helper": name}
    """
    registry = _load()
    if name not in registry:
        known = list(registry.keys())
        return {
            "ok":    False,
            "error": f"No helper named '{name}'. Known helpers: {known}",
            "helper": name,
        }

    cfg      = registry[name]
    base_url = cfg["base_url"]
    key_env  = cfg["key_env"]
    api_key  = os.environ.get(key_env, "")

    if not api_key:
        return {
            "ok":    False,
            "error": f"API key env var '{key_env}' is not set. "
                     f"Export it before asking helper '{name}'.",
            "helper": name,
        }

    url = base_url + ("/" + path.lstrip("/") if path else "")

    headers = {
        "Content-Type": "application/json",
        **cfg.get("default_headers", {}),
        **(extra_headers or {}),
    }
    auth_val = f"{auth_prefix} {api_key}".strip() if auth_prefix else api_key
    headers[auth_header] = auth_val

    logger.info(f"[helper] {name}: {method.upper()} {url}")

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(
                method.upper(),
                url,
                headers=headers,
                json=payload if payload is not None else None,
            )

        # Try to parse JSON body
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text

        ok = 200 <= resp.status_code < 300
        if not ok:
            logger.warning(f"[helper] {name}: HTTP {resp.status_code}")

        return {
            "ok":     ok,
            "status": resp.status_code,
            "body":   body,
            "helper": name,
            "url":    url,
        }

    except httpx.TimeoutException:
        return {"ok": False, "error": f"Timed out after {timeout}s", "helper": name}
    except Exception as e:
        logger.error(f"[helper] {name} error: {e}")
        return {"ok": False, "error": str(e), "helper": name}


def format_result(result: dict) -> str:
    """Format a helper result for LLM context."""
    if not result.get("ok"):
        return f"[helper:{result.get('helper', '?')}] ERROR: {result.get('error', 'unknown')}"

    body = result.get("body", "")
    if isinstance(body, dict):
        body_str = json.dumps(body, indent=2)
    else:
        body_str = str(body)

    # Truncate very long responses
    if len(body_str) > 8000:
        body_str = body_str[:8000] + "\n…(truncated)"

    return (
        f"[helper:{result['helper']}] HTTP {result['status']}\n"
        f"{body_str}"
    )
