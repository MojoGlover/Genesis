"""
bridge.py — PlugOps SSE/HTTP connection.

Replaced WebSocket transport with SSE + HTTP (2026-05-04).
WebSocket was the primary source of agent connection fragility —
it breaks on proxies, Cloud Run timeouts, and network interruptions
with no clean recovery path.

SSE + HTTP is:
- Stateless on the send side (plain HTTP POST)
- Auto-reconnecting on the receive side (SSE EventSource pattern)
- Proxy/Cloud Run friendly
- Identical interface to the old bridge — callers unchanged

Responsibilities:
- HTTP POST /api/v1/agents/register  — register on startup + reconnect
- HTTP POST /api/v1/agents/{id}/heartbeat  — keepalive every N seconds
- GET  /api/v1/sse/inbox/{id}  — SSE stream, auto-reconnects on drop
- HTTP POST /api/v1/sse/send   — deliver message to another agent
- Dispatch inbound messages to on_message_callback
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Callable, Awaitable

import httpx
from httpx_sse import aconnect_sse

logger = logging.getLogger(__name__)

# Same heuristic as capability_audit.py (cmptrblk root) — kept in sync
# manually since this runs inside each agent's own process, not against
# the grid from outside. If you tune one, tune the other.
_IDENTIFIER_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_KNOWN_NON_TOOL_WORDS = {"per_request", "per_account", "per_dollar", "e_g", "i_e"}


def capability_self_check(agent_name: str) -> dict:
    """
    Claim-drift self-check, run once at registration.

    Compares this agent's own missions/{NAME}.mission.txt against its own
    agent/tools/registry.py TOOL_SCHEMAS. Returns a status PlugOps can show
    next to the heartbeat — so "online" stops being the only signal, and
    "alive" and "actually capable of its mission" are visibly different
    things (see governance/AUDIT_STANDARD.md, Botico repo — this is claim
    drift, check #3 of 5, run automatically instead of only on demand).

    Best-effort: any failure here must never block registration or crash
    the agent. Returns status="unknown" rather than raising.

    Known limitation: purely lexical — can't tell "I use get_elements" from
    "get_elements does not exist." Errs toward flagging for a human glance,
    not toward silently hiding a real gap.
    """
    try:
        repo_root = Path(__file__).resolve().parent.parent.parent
        mission_path = repo_root / "missions" / f"{agent_name.upper()}.mission.txt"
        if not mission_path.exists():
            return {"status": "unknown", "reason": "mission file not found"}
        mission_text = mission_path.read_text(encoding="utf-8", errors="replace")
        referenced = {
            tok for tok in _IDENTIFIER_RE.findall(mission_text)
            if tok not in _KNOWN_NON_TOOL_WORDS
        }

        from agent.tools.registry import TOOL_SCHEMAS
        registered = {t["name"] for t in TOOL_SCHEMAS}

        missing = sorted(referenced - registered)
        if missing:
            return {"status": "hollow", "missing_tool_claims": missing}
        return {"status": "capable", "missing_tool_claims": []}
    except Exception as e:
        logger.warning(f"[bridge] capability_self_check failed: {e}")
        return {"status": "unknown", "reason": str(e)}



class PlugOpsBridge:
    def __init__(
        self,
        url: str,
        agent_id: str,
        agent_name: str,
        capabilities: list[str],
        on_message_callback: Callable[[dict], Awaitable[None]],
        config: dict | None = None,
    ) -> None:
        cfg = config or {}
        # Accept ws:// or http:// — normalise to http://
        self.base_url            = url.replace("ws://", "http://").replace("wss://", "https://")
        # Strip any path — we only want scheme://host:port
        self.base_url            = "/".join(self.base_url.split("/")[:3])
        self.agent_id            = agent_id
        self.agent_name          = agent_name
        self.capabilities        = capabilities
        self.on_message_callback = on_message_callback
        self._heartbeat_secs     = cfg.get("heartbeat_seconds", 10)
        self._backoff_max        = cfg.get("reconnect_max_seconds", 30)
        # If PlugOps goes silent, reconnect after this many seconds with no event.
        # PlugOps must send keepalive SSE comments (": keepalive") at a shorter interval.
        self._sse_read_timeout   = cfg.get("sse_read_timeout_seconds", 90)
        self._should_run         = True
        self._connected          = False
        self._client: httpx.AsyncClient | None = None
        self._sse_client: httpx.AsyncClient | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── public API ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Register, then run heartbeat + SSE inbox loops forever."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
        )
        # Separate client for SSE: read timeout triggers reconnect if PlugOps goes silent.
        self._sse_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=self._sse_read_timeout, write=10.0, pool=10.0)
        )
        try:
            await self._register()
            await asyncio.gather(
                self._heartbeat_loop(),
                self._inbox_loop(),
            )
        finally:
            await self._client.aclose()
            await self._sse_client.aclose()

    async def stop(self) -> None:
        self._should_run = False
        self._connected  = False

    async def send(self, message: dict) -> None:
        """Send a message to another agent via PlugOps SSE bus."""
        to_agent = (
            message.get("message", {}).get("to_agent")
            or message.get("to_agent", "")
        )
        if not to_agent:
            logger.warning("[bridge] send() called with no to_agent — dropped")
            return
        payload = {
            "from":    self.agent_id,
            "to":      to_agent,
            "payload": message,
        }
        try:
            assert self._client is not None
            await self._client.post(f"{self.base_url}/api/v1/sse/send", json=payload)
        except Exception as e:
            logger.error(f"[bridge] send failed: {e!r}")

    async def send_response(self, to_agent: str, content: str, request_id: str = "") -> None:
        msg: dict = {
            "from_agent": self.agent_name,
            "to_agent":   to_agent,
            "content":    content,
        }
        if request_id:
            msg["request_id"] = request_id
        await self.send({"type": "chat", "message": msg})

    # ── internals ─────────────────────────────────────────────────────────

    async def _register(self, retries: int = 20, delay: float = 0.5) -> None:
        assert self._client is not None
        for attempt in range(retries):
            try:
                r = await self._client.post(
                    f"{self.base_url}/api/v1/agents/register",
                    json={
                        "id":           self.agent_id,
                        "name":         self.agent_name,
                        "type":         "autonomous",
                        "base_dir":     f"/agents/{self.agent_id}",
                        "capabilities": self.capabilities,
                        "metadata": {
                            "emoji": "⚙️",
                            "role":  "Systems, code & infrastructure",
                            "capability_status": capability_self_check(self.agent_name),
                        },
                    },
                )
                if r.status_code in (200, 201, 409):
                    self._connected = True
                    logger.info(f"[bridge] HTTP registered with PlugOps — online")
                    return
                logger.warning(f"[bridge] register returned {r.status_code}")
            except Exception as e:
                logger.warning(f"[bridge] register attempt {attempt+1}: {e!r}")
            await asyncio.sleep(delay)
        logger.error("[bridge] Could not register with PlugOps after retries")

    async def _heartbeat_loop(self) -> None:
        assert self._client is not None
        while self._should_run:
            await asyncio.sleep(self._heartbeat_secs)
            if not self._should_run:
                break
            try:
                await self._client.post(
                    f"{self.base_url}/api/v1/agents/{self.agent_id}/heartbeat"
                )
                logger.debug("[bridge] heartbeat sent")
            except Exception as e:
                logger.warning(f"[bridge] heartbeat failed: {e!r}")

    async def _inbox_loop(self) -> None:
        """SSE inbox — auto-reconnects on any error or read timeout."""
        assert self._sse_client is not None
        backoff = 1
        last_event_id: str = ""
        while self._should_run:
            try:
                headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
                async with aconnect_sse(
                    self._sse_client,
                    "GET",
                    f"{self.base_url}/api/v1/sse/inbox/{self.agent_id}",
                    headers=headers,
                ) as es:
                    self._connected = True
                    backoff = 1
                    async for sse in es.aiter_sse():
                        if not self._should_run:
                            return
                        if sse.id:
                            last_event_id = sse.id
                        if sse.event != "message":
                            continue
                        try:
                            msg = json.loads(sse.data)
                            inner = msg.get("payload", msg)
                            await self._dispatch(inner)
                        except Exception as e:
                            logger.warning(f"[bridge] dispatch error: {e!r} data={sse.data[:120]!r}")
            except Exception as e:
                self._connected = False
                logger.warning(
                    f"[bridge] inbox error: {e!r} last_event_id={last_event_id!r} "
                    f"— reconnecting in {backoff}s"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._backoff_max)
                await self._register()

    async def _dispatch(self, msg: dict) -> None:
        msg_type = msg.get("type", "")
        if msg_type == "message":
            await self.on_message_callback(msg)
        elif msg_type == "learning_package":
            await self._handle_learning_package(msg)
        elif msg_type in ("heartbeat_ack", "register_ack", "ping"):
            logger.debug(f"[bridge] {msg_type} — ok")
        else:
            logger.debug(f"[bridge] unhandled type: {msg_type}")
            await self.on_message_callback(msg)

    async def _handle_learning_package(self, msg: dict) -> None:
        package    = msg.get("package", {})
        package_id = msg.get("package_id", "unknown")
        title      = package.get("metadata", {}).get("title", package_id)
        logger.info(f"[bridge] learning package received: {title}")
        content      = package.get("content", {})
        summary      = content.get("summary", "")
        phases       = content.get("phases", [])
        lessons_text = []
        for phase in phases:
            for module in phase.get("modules", []):
                for lesson in module.get("lessons", []):
                    lessons_text.append(
                        f"## {lesson.get('title','')}\n{lesson.get('content','')}"
                    )
        body = f"Learning package: {title}\n\n{summary}"
        if lessons_text:
            body += "\n\n" + "\n\n".join(lessons_text[:3])
        body += "\n\nAcknowledge receipt."
        await self.on_message_callback({
            "type":    "message",
            "message": {"from_agent": "learning_manager", "content": body},
            "_learning_package_id": package_id,
        })
