"""
agent/modules/grid.py — Dynamic grid resolver.

Replaces hardcoded agent URLs in configs. When an agent needs to call
another agent, it calls grid.resolve("target_id") to get the current URL.

Resolution hits PlugOps GET /api/v1/agents/{id}/url on every call.
PlugOps is the single source of truth for agent locations.

Why dynamic (not cached at boot):
- Agents can move between hosts mid-session (plugwan → plugfoe → RunPod)
- A cached URL goes stale silently; a live query fails loudly
- PlugOps is always-on (Cloud Run) so the query is cheap and reliable

Short-circuit cache (30s TTL) avoids hammering PlugOps on tight loops
while still picking up location changes within a reasonable window.

Usage:
    from agent.modules.grid import GridResolver
    grid = GridResolver(plugops_base="https://plugzero-581737577470.us-central1.run.app")

    url = grid.resolve("engineer0")          # → "http://178.105.62.143:5001"
    url = grid.resolve("engineer0", "/api/chat")  # → "http://178.105.62.143:5001/api/chat"
    info = grid.info("cerberus")             # → full agent info dict
"""
from __future__ import annotations

import logging
import ssl
import json
import time
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_TTL = 30        # seconds before re-querying PlugOps
_TIMEOUT   = 8         # seconds for the resolution HTTP call


class GridResolutionError(Exception):
    """Raised when an agent URL cannot be resolved."""


class GridResolver:
    """
    Resolves agent locations dynamically via PlugOps.

    Thread-safe short-circuit cache with 30s TTL.
    """

    def __init__(self, plugops_base: str):
        # Strip trailing slash — all paths are absolute
        self._base = plugops_base.rstrip("/")
        self._cache: dict[str, tuple[str, float]] = {}  # agent_id → (url, expires_at)
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE
        # NOTE: SSL verification disabled for Cloud Run endpoint —
        # Google-managed certs may not be in Python's default bundle.
        # This is intentional and scoped to our own known PlugOps URL.

    def resolve(self, agent_id: str, path: str = "") -> str:
        """
        Return the current base URL for agent_id, optionally with a path appended.

        Examples:
            grid.resolve("engineer0")             → "http://178.105.62.143:5001"
            grid.resolve("engineer0", "/api/chat")→ "http://178.105.62.143:5001/api/chat"

        Raises GridResolutionError if the agent is not registered or has no location.
        """
        base_url = self._resolve_base(agent_id)
        if path:
            return base_url.rstrip("/") + "/" + path.lstrip("/")
        return base_url

    def info(self, agent_id: str) -> dict:
        """Return the full agent info dict from PlugOps."""
        url = f"{self._base}/api/v1/agents/{agent_id}"
        return self._get_json(url)

    def invalidate(self, agent_id: str) -> None:
        """Remove an agent from the cache, forcing a fresh resolution next call."""
        self._cache.pop(agent_id, None)

    def invalidate_all(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _resolve_base(self, agent_id: str) -> str:
        now = time.monotonic()

        # Cache hit
        if agent_id in self._cache:
            url, expires = self._cache[agent_id]
            if now < expires:
                return url
            # Expired — fall through to live query

        # Live query
        endpoint = f"{self._base}/api/v1/agents/{agent_id}/url"
        try:
            data = self._get_json(endpoint)
        except GridResolutionError:
            raise
        except Exception as e:
            raise GridResolutionError(
                f"Cannot resolve '{agent_id}': PlugOps query failed — {e}"
            ) from e

        url = data.get("url")
        if not url:
            raise GridResolutionError(
                f"Agent '{agent_id}' is registered but has no location. "
                f"Re-register with host and port."
            )

        status = data.get("status", "unknown")
        if status not in ("online", "starting"):
            logger.warning(
                f"[grid] Resolved '{agent_id}' → {url} but status is '{status}'"
            )

        self._cache[agent_id] = (url, now + _CACHE_TTL)
        logger.debug(f"[grid] Resolved '{agent_id}' → {url} (status={status})")
        return url

    def _get_json(self, url: str) -> dict:
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self._ssl_ctx)
        )
        try:
            req = urllib.request.Request(url, method="GET")
            with opener.open(req, timeout=_TIMEOUT) as resp:
                if resp.status == 404:
                    raise GridResolutionError(f"Agent not found at {url}")
                if resp.status == 503:
                    body = json.loads(resp.read())
                    raise GridResolutionError(body.get("detail", f"503 from {url}"))
                if resp.status >= 400:
                    raise GridResolutionError(f"HTTP {resp.status} from {url}")
                return json.loads(resp.read())
        except GridResolutionError:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise GridResolutionError(f"Agent not registered at PlugOps (404 from {url})")
            raise GridResolutionError(f"HTTP {e.code} from {url}")
        except Exception as e:
            raise GridResolutionError(f"Request failed for {url}: {e}")
