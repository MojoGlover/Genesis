"""Ledger client — immutable cost accounting. Silent-fail always."""
from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)


class LedgerClient:
    def __init__(self, agent_id: str, url: str, enabled: bool = True):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.enabled  = enabled

    def record(self, resource: str, units: float, cost_usd: float,
               unit_type: str = "tokens") -> None:
        if not self.enabled:
            return
        try:
            httpx.post(f"{self.url}/entries", json={
                "agent_id": self.agent_id, "resource": resource,
                "units": units, "unit_type": unit_type, "cost_usd": cost_usd,
            }, timeout=3.0)
        except Exception:
            pass

    def record_llm(self, model_id: str, input_tokens: int, output_tokens: int,
                   cost_usd: float) -> None:
        """Convenience: record an LLM inference cost."""
        self.record(resource=model_id,
                    units=input_tokens + output_tokens,
                    unit_type="tokens",
                    cost_usd=cost_usd)

    def record_api_call(self, service: str, cost_usd: float = 0.0) -> None:
        """Convenience: record an external API call cost."""
        self.record(resource=service, units=1.0, unit_type="api_call", cost_usd=cost_usd)
