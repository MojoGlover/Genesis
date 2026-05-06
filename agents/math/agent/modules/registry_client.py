"""Registry client — agent directory. Register on boot, deregister on shutdown."""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)


class RegistryClient:
    def __init__(self, agent_id: str, url: str, enabled: bool = True):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.enabled  = enabled

    def register(self, agent_id: str, name: str, role: str,
                 capabilities: list[str], api_port: int) -> bool:
        if not self.enabled:
            return False
        try:
            r = httpx.post(f"{self.url}/register", json={
                "agent_id":     agent_id,
                "name":         name,
                "role":         role,
                "capabilities": capabilities,
                "port":         api_port,
            }, timeout=5.0)
            if r.status_code in (200, 201, 409):
                logger.info(f"[registry] Registered {agent_id}")
                return True
            logger.warning(f"[registry] register returned {r.status_code}")
        except Exception as e:
            logger.warning(f"[registry] register failed: {e}")
        return False

    def deregister(self, agent_id: str) -> None:
        if not self.enabled:
            return
        try:
            httpx.delete(f"{self.url}/agents/{agent_id}", timeout=3.0)
            logger.info(f"[registry] Deregistered {agent_id}")
        except Exception:
            pass

    def heartbeat(self, agent_id: str) -> None:
        if not self.enabled:
            return
        try:
            httpx.post(f"{self.url}/agents/{agent_id}/heartbeat", timeout=3.0)
        except Exception:
            pass
