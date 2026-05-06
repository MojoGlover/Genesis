"""
ledger/client.py — Python client for the Ledger node.

Agents call this to report what they spent. The Accountant reads it for billing truth.

Usage:
    from ledger.client import LedgerClient

    ledger = LedgerClient(agent_id="engineer0")

    # Record API usage
    ledger.record("anthropic/claude-3-5-sonnet", units=1200, unit_type="tokens", cost_usd=0.018)
    ledger.record("openai/gpt-4o",               units=800,  unit_type="tokens", cost_usd=0.012, task_id="task-42")

    # Record free local usage (Ollama)
    ledger.record("ollama/llama3.3:70b", units=2000, unit_type="tokens")

    # Convenience wrappers
    ledger.record_tokens("anthropic/claude-3-5-sonnet", input_tokens=500, output_tokens=300,
                         input_price=0.003, output_price=0.015)  # per-1K pricing

    # Read own summary
    summary = ledger.summary()
    print(f"Total spent: ${summary['total_usd']:.4f}")
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("ledger.client")

DEFAULT_URL = "http://127.0.0.1:9106"


class LedgerClient:
    def __init__(self, agent_id: str, url: str = DEFAULT_URL, timeout: float = 10.0):
        self.agent_id = agent_id
        self.url      = url.rstrip("/")
        self.timeout  = timeout

    def record(
        self,
        resource:   str,
        units:      float = 0,
        unit_type:  str   = "tokens",
        cost_usd:   float = 0.0,
        task_id:    str   = "",
        session_id: str   = "",
        metadata:   dict[str, Any] | None = None,
    ) -> dict:
        """Record a cost entry. Returns entry_id and hmac."""
        resp = httpx.post(
            f"{self.url}/entries",
            json={
                "agent_id":   self.agent_id,
                "resource":   resource,
                "units":      units,
                "unit_type":  unit_type,
                "cost_usd":   cost_usd,
                "task_id":    task_id,
                "session_id": session_id,
                "metadata":   metadata or {},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def record_tokens(
        self,
        resource:      str,
        input_tokens:  int   = 0,
        output_tokens: int   = 0,
        input_price:   float = 0.0,   # USD per 1K input tokens
        output_price:  float = 0.0,   # USD per 1K output tokens
        task_id:       str   = "",
        session_id:    str   = "",
    ) -> dict:
        """Record token usage with per-1K pricing."""
        total_tokens = input_tokens + output_tokens
        cost = (input_tokens * input_price + output_tokens * output_price) / 1000
        return self.record(
            resource=resource,
            units=total_tokens,
            unit_type="tokens",
            cost_usd=round(cost, 8),
            task_id=task_id,
            session_id=session_id,
            metadata={"input_tokens": input_tokens, "output_tokens": output_tokens},
        )

    def record_request(
        self,
        resource:  str,
        cost_usd:  float = 0.0,
        task_id:   str   = "",
        metadata:  dict[str, Any] | None = None,
    ) -> dict:
        """Record a single API request (non-token-based pricing)."""
        return self.record(
            resource=resource, units=1, unit_type="requests",
            cost_usd=cost_usd, task_id=task_id, metadata=metadata,
        )

    def summary(self, since: float = 0.0) -> dict:
        """Get this agent's spending summary."""
        params: dict = {}
        if since:
            params["since"] = since
        resp = httpx.get(
            f"{self.url}/summary/{self.agent_id}",
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def budget(self) -> dict:
        """Get this agent's budget status."""
        resp = httpx.get(f"{self.url}/budget/{self.agent_id}", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def set_budget(
        self,
        daily_usd:   float = 0,
        monthly_usd: float = 0,
        alert_pct:   float = 80.0,
    ) -> dict:
        resp = httpx.post(
            f"{self.url}/budget/{self.agent_id}",
            json={"daily_usd": daily_usd, "monthly_usd": monthly_usd, "alert_pct": alert_pct},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def system_summary(self, since: float = 0.0) -> dict:
        """Get spend summary across all agents (Accountant use)."""
        params: dict = {}
        if since:
            params["since"] = since
        resp = httpx.get(f"{self.url}/summary", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
