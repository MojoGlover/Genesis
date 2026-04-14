"""
forecaster.py — Financial projections and cost estimation.

Projects future costs based on current spend rates.
Estimates cost impact before executing expensive operations.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .ledger import Ledger

logger = logging.getLogger("accountant.forecaster")


class Forecaster:

    def __init__(self, ledger: Optional[Ledger] = None):
        self.ledger = ledger or Ledger()

    def monthly_projection(self) -> dict:
        """Project this month's total cost from the current daily rate."""
        daily  = self.ledger.daily_total()
        weekly = self.ledger.weekly_total()
        # Use 7-day average for smoother projection
        avg_daily = weekly / 7 if weekly > 0 else daily

        day_of_month  = datetime.now().day
        days_in_month = 30
        projected     = avg_daily * days_in_month
        spent_so_far  = self.ledger.monthly_total()

        return {
            "avg_daily_usd":         round(avg_daily, 6),
            "spent_so_far_usd":      round(spent_so_far, 4),
            "day_of_month":          day_of_month,
            "projected_month_total": round(projected, 2),
            "projected_annual":      round(projected * 12, 2),
        }

    def annual_projection(self) -> dict:
        """Project annual cost from 30-day average."""
        monthly = self.ledger.monthly_total()
        annual  = monthly * 12
        return {
            "monthly_basis_usd": round(monthly, 4),
            "projected_annual":  round(annual, 2),
        }

    def break_even(
        self,
        revenue_per_month_usd: float,
        fixed_costs_per_month_usd: float = 0,
    ) -> dict:
        """
        Estimate break-even given expected monthly revenue.
        Includes current operational costs from the ledger.
        """
        op_costs  = self.ledger.monthly_total()
        total_cost = op_costs + fixed_costs_per_month_usd
        margin    = revenue_per_month_usd - total_cost
        months_to_break_even = None

        if margin > 0:
            status = "profitable"
        elif revenue_per_month_usd > 0:
            status = "operating_loss"
            months_to_break_even = total_cost / revenue_per_month_usd
        else:
            status = "no_revenue"

        return {
            "monthly_revenue":        round(revenue_per_month_usd, 2),
            "monthly_op_cost":        round(op_costs, 4),
            "monthly_fixed_cost":     round(fixed_costs_per_month_usd, 2),
            "monthly_total_cost":     round(total_cost, 4),
            "monthly_margin":         round(margin, 4),
            "status":                 status,
            "months_to_break_even":   round(months_to_break_even, 1) if months_to_break_even else None,
        }

    def estimate_workflow_cost(
        self,
        steps: list[dict],
    ) -> dict:
        """
        Estimate cost of a proposed workflow before running it.

        Each step is a dict:
          {"provider": "anthropic", "model": "claude-haiku-4-5",
           "input_tokens": 1000, "output_tokens": 500, "count": 1}

        Returns total estimated cost and per-step breakdown.
        """
        from .cost_tracker import CostTracker
        tracker    = CostTracker(self.ledger)
        total_cost = 0.0
        breakdown  = []

        for step in steps:
            provider    = step.get("provider", "anthropic")
            model       = step.get("model", "claude-haiku-4-5")
            input_tok   = step.get("input_tokens", 500)
            output_tok  = step.get("output_tokens", 200)
            count       = step.get("count", 1)

            est = tracker.estimate_inference(provider, model, input_tok, output_tok)
            step_cost = est["estimated_cost"] * count
            total_cost += step_cost
            breakdown.append({
                "step":            step.get("name", f"{provider}/{model}"),
                "count":           count,
                "cost_per_call":   est["estimated_cost"],
                "total_step_cost": round(step_cost, 6),
            })

        return {
            "total_estimated_cost": round(total_cost, 6),
            "steps":                breakdown,
            "recommendation":       "proceed" if total_cost < 0.10 else "review" if total_cost < 1.0 else "caution",
        }

    def summary_text(self) -> str:
        proj = self.monthly_projection()
        lines = [
            "─── Financial Forecast ──────────────────────────────",
            f"  Daily avg:              ${proj['avg_daily_usd']:.4f}",
            f"  Projected this month:   ${proj['projected_month_total']:.2f}",
            f"  Projected annual:       ${proj['projected_annual']:.2f}",
            f"  Spent so far (30d):     ${proj['spent_so_far_usd']:.4f}",
            "─────────────────────────────────────────────────────",
        ]
        return "\n".join(lines)
