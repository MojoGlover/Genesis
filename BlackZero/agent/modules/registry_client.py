"""Registry client — agent directory. Register on boot, deregister on shutdown."""
from __future__ import annotations
import asyncio
import logging
import httpx

logger = logging.getLogger(__name__)

# Registry liveness TTL is 90s; send a beat every 30s (3× safety margin).
_HEARTBEAT_INTERVAL = 30


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
        """One-shot sync heartbeat — use heartbeat_loop() for the ongoing loop."""
        if not self.enabled:
            return
        try:
            httpx.post(f"{self.url}/agents/{agent_id}/heartbeat", timeout=3.0)
        except Exception:
            pass

    async def heartbeat_loop(self, agent_id: str,
                              interval: int = _HEARTBEAT_INTERVAL) -> None:
        """Run forever, sending a heartbeat every `interval` seconds.

        If the registry returns 404 the agent has been swept dead — re-register.
        Wire this into asyncio.gather() alongside the bridge and API server.
        """
        if not self.enabled:
            return
        while True:
            await asyncio.sleep(interval)
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.post(
                        f"{self.url}/agents/{agent_id}/heartbeat"
                    )
                if r.status_code == 404:
                    logger.warning(
                        "[registry] Heartbeat 404 — agent swept dead, must re-register"
                    )
                elif r.status_code not in (200, 204):
                    logger.debug(f"[registry] Heartbeat returned {r.status_code}")
            except Exception as e:
                logger.debug(f"[registry] Heartbeat failed (registry down?): {e}")
