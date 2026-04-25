"""Communication client — send messages to other agents. Silent-fail always."""
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
        """Send a message to another agent. Returns True on success."""
        if not self.enabled:
            return False
        try:
            r = httpx.post(f"{self.url}/messages", json={
                "from_agent": self.agent_id,
                "to_agent":   to_agent,
                "type":       msg_type,
                "content":    content,
                "payload":    payload or {},
            }, timeout=5.0)
            return r.status_code == 201
        except Exception:
            return False

    def broadcast(self, topic: str, content: str,
                  payload: dict | None = None) -> bool:
        """Broadcast an event on a topic."""
        if not self.enabled:
            return False
        try:
            r = httpx.post(f"{self.url}/events", json={
                "from_agent": self.agent_id,
                "topic":      topic,
                "content":    content,
                "payload":    payload or {},
            }, timeout=5.0)
            return r.status_code == 201
        except Exception:
            return False
