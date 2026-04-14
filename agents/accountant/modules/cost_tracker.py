"""
cost_tracker.py — Real-time cost tracking for API calls and compute usage.

Calculates the dollar cost of operations using rate tables from config.yaml,
then records them to the Ledger automatically.

Usage:
    tracker = CostTracker()

    # Track an LLM inference call
    tracker.track_inference(
        provider="anthropic",
        model="claude-haiku-4-5",
        input_tokens=1200,
        output_tokens=450,
        agent="engineer0",
        workflow="code_review",
    )

    # Track cloud compute
    tracker.track_compute(
        provider="gcp",
        service="cloud-run",
        vcpu_seconds=120,
        memory_gb_seconds=240,
    )

    # Track a subscription
    tracker.track_subscription(
        vendor="github",
        service="github-actions",
        amount_usd=0.008,
        notes="120 min CI @ $0.004/min",
    )
"""
from __future__ import annotations

import logging
import yaml
from pathlib import Path
from typing import Optional

from .ledger import Ledger

logger = logging.getLogger("accountant.cost_tracker")

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


def _load_rates() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("api_rates", {})
    return {}


class CostTracker:
    """
    Translates usage events into dollar amounts and logs them to the Ledger.
    All rate tables come from config.yaml — update there when providers change pricing.
    """

    def __init__(self, ledger: Optional[Ledger] = None):
        self.ledger = ledger or Ledger()
        self.rates  = _load_rates()

    def _inference_rate(self, provider: str, model: str) -> tuple[float, float]:
        """Return (input_per_1k, output_per_1k) for a given provider/model."""
        p = self.rates.get(provider, {})
        m = p.get(model) or p.get("any", {})
        return (
            m.get("input_per_1k",  0.0),
            m.get("output_per_1k", 0.0),
        )

    # ── Inference ─────────────────────────────────────────────────────────────

    def track_inference(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent: str   = "system",
        workflow: str = "",
        project: str  = "",
        notes: str    = "",
    ) -> float:
        """
        Calculate and log the cost of one LLM inference call.
        Returns cost in USD.
        """
        in_rate, out_rate = self._inference_rate(provider, model)
        cost = (input_tokens / 1000 * in_rate) + (output_tokens / 1000 * out_rate)

        if cost > 0:
            self.ledger.record(
                vendor=provider,
                service=model,
                amount_usd=cost,
                category="ai_services",
                cost_type="inference",
                agent=agent,
                workflow=workflow,
                project=project,
                notes=notes or f"in:{input_tokens} out:{output_tokens} tokens",
            )
        return cost

    # ── Compute ───────────────────────────────────────────────────────────────

    def track_compute(
        self,
        provider: str,
        service: str,
        vcpu_seconds: float    = 0,
        memory_gb_seconds: float = 0,
        requests: int          = 0,
        agent: str             = "system",
        workflow: str          = "",
        project: str           = "",
    ) -> float:
        """
        Calculate and log cloud compute cost.
        Currently models GCP Cloud Run; extend for other providers as needed.
        """
        cost = 0.0

        if provider == "gcp" and "cloud" in service.lower():
            # GCP Cloud Run rates (after free tier)
            CPU_RATE    = 0.000024     # per vCPU-second
            MEM_RATE    = 0.0000025    # per GB-second
            REQ_RATE    = 0.40 / 1e6  # per request
            cost = (
                vcpu_seconds * CPU_RATE
                + memory_gb_seconds * MEM_RATE
                + requests * REQ_RATE
            )
        else:
            # Generic: caller provides cost directly (fallback)
            cost = 0.0

        if cost > 0:
            self.ledger.record(
                vendor=provider,
                service=service,
                amount_usd=cost,
                category="cloud_services",
                cost_type="compute",
                agent=agent,
                workflow=workflow,
                project=project,
                notes=f"vcpu_s:{vcpu_seconds:.1f} mem_gb_s:{memory_gb_seconds:.1f} req:{requests}",
            )
        return cost

    # ── Subscriptions / one-off ───────────────────────────────────────────────

    def track_subscription(
        self,
        vendor: str,
        service: str,
        amount_usd: float,
        category:  str  = "subscriptions",
        recurring: bool = True,
        frequency: str  = "recurring_monthly",
        agent:    str   = "system",
        project:  str   = "",
        deductible: bool = True,
        notes:    str   = "",
    ) -> float:
        """Log a subscription or recurring service cost."""
        self.ledger.record(
            vendor=vendor,
            service=service,
            amount_usd=amount_usd,
            category=category,
            cost_type="subscription",
            recurring=recurring,
            frequency=frequency,
            agent=agent,
            project=project,
            deductible=deductible,
            notes=notes,
        )
        return amount_usd

    def track_manual(
        self,
        vendor: str,
        service: str,
        amount_usd: float,
        category:  str,
        cost_type: str   = "other",
        agent:     str   = "system",
        workflow:  str   = "",
        project:   str   = "",
        deductible: bool = True,
        notes:     str   = "",
    ) -> float:
        """Manually record any cost not covered by the auto-trackers above."""
        self.ledger.record(
            vendor=vendor,
            service=service,
            amount_usd=amount_usd,
            category=category,
            cost_type=cost_type,
            agent=agent,
            workflow=workflow,
            project=project,
            deductible=deductible,
            notes=notes,
        )
        return amount_usd

    # ── Cost estimation (pre-execution) ──────────────────────────────────────

    def estimate_inference(
        self,
        provider: str,
        model: str,
        est_input_tokens: int,
        est_output_tokens: int,
    ) -> dict:
        """
        Estimate the cost of an inference call BEFORE running it.
        Returns a dict with cost, rate, and recommendation.
        """
        in_rate, out_rate = self._inference_rate(provider, model)
        cost = (est_input_tokens / 1000 * in_rate) + (est_output_tokens / 1000 * out_rate)

        # Find cheaper alternatives
        alternatives = []
        for prov, models in self.rates.items():
            for mod, rates in models.items():
                if mod == "any":
                    continue
                alt_in  = rates.get("input_per_1k", 0)
                alt_out = rates.get("output_per_1k", 0)
                alt_cost = (est_input_tokens / 1000 * alt_in) + (est_output_tokens / 1000 * alt_out)
                if alt_cost < cost and alt_cost >= 0:
                    alternatives.append({
                        "provider": prov,
                        "model": mod,
                        "estimated_cost": round(alt_cost, 6),
                        "savings": round(cost - alt_cost, 6),
                    })

        alternatives.sort(key=lambda x: x["estimated_cost"])

        return {
            "provider":        provider,
            "model":           model,
            "input_tokens":    est_input_tokens,
            "output_tokens":   est_output_tokens,
            "estimated_cost":  round(cost, 6),
            "cheaper_options": alternatives[:3],
        }
