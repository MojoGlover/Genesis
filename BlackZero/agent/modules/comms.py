"""
Communication client — send messages to other agents via the comm node.
Silent-fail always: a comm node being down never crashes the agent.

Server contract (communication node, port 9100):
  POST /register   {agent_id}
  POST /send       {from, to, payload}
  GET  /inbox/{id} SSE stream

The `from` field uses Python alias "from_" due to the reserved keyword,
but the JSON key sent to the server must be "from".
"""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)


class CommsClient:
    def __init__(self, agent_id: str, url: str, enabled: bool = True):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.enabled  = enabled

    def send(self, to_agent: str, content: str,
             msg_type: str = "message", payload: dict | None = None) -> bool:
        """
        Send a message to another agent via the comm node.
        Packs content and type into the payload dict.
        Returns True on delivery, False on any failure.
        """
        if not self.enabled:
            return False
        try:
            body = payload.copy() if payload else {}
            body.setdefault("content", content)
            body.setdefault("type", msg_type)
            r = httpx.post(f"{self.url}/send", json={
                "from":    self.agent_id,
                "to":      to_agent,
                "payload": body,
            }, timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def broadcast(self, topic: str, content: str,
                  payload: dict | None = None) -> bool:
        """
        Broadcast a message to all registered agents (sends to each via /send).
        The comm node has no native broadcast — this is a best-effort fan-out.
        Returns True if the comm node is reachable.
        """
        if not self.enabled:
            return False
        try:
            body = payload.copy() if payload else {}
            body.setdefault("content", content)
            body.setdefault("topic", topic)
            # Fan-out via /send to a special "__broadcast__" address.
            # Agents that want broadcasts must subscribe (future feature).
            r = httpx.post(f"{self.url}/send", json={
                "from":    self.agent_id,
                "to":      "__broadcast__",
                "payload": body,
            }, timeout=5.0)
            return r.status_code in (200, 404)  # 404 = no subscribers, still reachable
        except Exception:
            return False
