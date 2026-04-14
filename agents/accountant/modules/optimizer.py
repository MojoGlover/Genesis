"""
optimizer.py — Cost optimization recommendations.

Analyzes spending patterns and suggests concrete ways to reduce costs:
  - Cheaper model alternatives
  - Free-tier substitutions
  - Redundant subscriptions
  - Inefficient patterns (high frequency, low value)
  - Vendor alternatives

Usage:
    opt = Optimizer()
    recs = opt.analyze()
    for r in recs:
        print(r)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

import yaml
from pathlib import Path

from .ledger import Ledger

logger = logging.getLogger("accountant.optimizer")

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class Recommendation:
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"

    def __init__(self, priority: str, title: str, detail: str, est_savings: float = 0):
        self.priority    = priority
        self.title       = title
        self.detail      = detail
        self.est_savings = est_savings

    def __repr__(self) -> str:
        icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(self.priority, "⚪")
        savings = f"  ~${self.est_savings:.4f}/mo savings" if self.est_savings > 0 else ""
        return f"{icon} [{self.priority.upper()}] {self.title}\n   {self.detail}{savings}"


class Optimizer:
    """
    Analyzes the transaction ledger and generates cost optimization recommendations.
    """

    def __init__(self, ledger: Optional[Ledger] = None):
        self.ledger = ledger or Ledger()
        self.config = self._load_config()

    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                return yaml.safe_load(f)
        return {}

    def analyze(self) -> list[Recommendation]:
        """Run all optimization checks. Returns ranked list of recommendations."""
        recs: list[Recommendation] = []
        recs.extend(self._check_model_usage())
        recs.extend(self._check_high_frequency_vendors())
        recs.extend(self._check_subscriptions())
        recs.extend(self._check_local_vs_cloud())

        # Sort: high first, then by estimated savings
        priority_order = {"high": 0, "medium": 1, "low": 2}
        recs.sort(key=lambda r: (priority_order.get(r.priority, 3), -r.est_savings))
        return recs

    def _check_model_usage(self) -> list[Recommendation]:
        """Flag expensive model usage where cheaper alternatives exist."""
        recs   = []
        rates  = self.config.get("api_rates", {})
        txs_30 = self.ledger.since_days(30)

        # Group by provider+model, calculate 30-day cost
        model_spend: dict[tuple, float] = defaultdict(float)
        for tx in txs_30:
            if tx.cost_type == "inference":
                model_spend[(tx.vendor, tx.service)] += tx.amount_usd

        expensive_threshold = 0.50  # $0.50/month triggers a look

        for (vendor, model), spend in model_spend.items():
            if spend < expensive_threshold:
                continue

            # Check if a cheaper local option exists
            ollama_available = any(
                m != "any" for m in rates.get("ollama", {})
            )
            if vendor != "ollama" and ollama_available:
                recs.append(Recommendation(
                    Recommendation.HIGH,
                    f"Switch {model} to Ollama for eligible tasks",
                    f"Spending ${spend:.2f}/mo on {vendor}/{model}. "
                    f"Local Ollama inference costs $0. "
                    f"Use cloud APIs only for tasks exceeding local model capability.",
                    est_savings=spend * 0.7,
                ))

            # Check for cheaper cloud alternative
            vendor_rates = rates.get(vendor, {})
            model_rates  = vendor_rates.get(model, {})
            if model_rates:
                for other_model, other_rates in vendor_rates.items():
                    if other_model == model or other_model == "any":
                        continue
                    other_in  = other_rates.get("input_per_1k", 0)
                    other_out = other_rates.get("output_per_1k", 0)
                    this_in   = model_rates.get("input_per_1k", 0)
                    this_out  = model_rates.get("output_per_1k", 0)
                    if (other_in + other_out) < (this_in + this_out) * 0.5:
                        ratio = (this_in + this_out) / max(other_in + other_out, 0.000001)
                        recs.append(Recommendation(
                            Recommendation.MEDIUM,
                            f"Consider {other_model} instead of {model}",
                            f"{model} is ~{ratio:.1f}× more expensive per token than {other_model}. "
                            f"Evaluate if quality difference justifies the cost.",
                            est_savings=spend * 0.4,
                        ))

        return recs

    def _check_high_frequency_vendors(self) -> list[Recommendation]:
        """Flag vendors with unusually high call frequency."""
        recs       = []
        txs_7      = self.ledger.since_days(7)
        vendor_ct: dict[str, int] = defaultdict(int)
        for tx in txs_7:
            vendor_ct[tx.vendor] += 1

        for vendor, count in vendor_ct.items():
            daily_avg = count / 7
            if daily_avg > 100:
                recs.append(Recommendation(
                    Recommendation.MEDIUM,
                    f"High call frequency: {vendor}",
                    f"Averaging {daily_avg:.0f} calls/day to {vendor}. "
                    f"Consider caching responses, batching requests, or "
                    f"reducing polling frequency.",
                ))
        return recs

    def _check_subscriptions(self) -> list[Recommendation]:
        """Flag subscriptions that may be redundant or unused."""
        recs = []
        all_txs = self.ledger.all()
        subs = [tx for tx in all_txs if tx.recurring]

        # Group by vendor to find duplicates in same category
        cat_vendors: dict[str, list[str]] = defaultdict(list)
        for tx in subs:
            if tx.vendor not in cat_vendors[tx.category]:
                cat_vendors[tx.category].append(tx.vendor)

        for cat, vendors in cat_vendors.items():
            if len(vendors) > 1:
                recs.append(Recommendation(
                    Recommendation.MEDIUM,
                    f"Multiple subscriptions in same category: {cat}",
                    f"Active vendors: {', '.join(vendors)}. "
                    f"Review for overlapping functionality and consolidate where possible.",
                ))
        return recs

    def _check_local_vs_cloud(self) -> list[Recommendation]:
        """Encourage use of local Ollama over paid APIs for routine tasks."""
        recs    = []
        txs_30  = self.ledger.since_days(30)
        api_spend = sum(
            tx.amount_usd for tx in txs_30
            if tx.cost_type == "inference" and tx.vendor != "ollama"
        )
        if api_spend > 1.0:
            recs.append(Recommendation(
                Recommendation.HIGH if api_spend > 10 else Recommendation.LOW,
                "Route routine inference through local Ollama",
                f"${api_spend:.2f} spent on cloud inference this month. "
                f"Ollama (engineer0:latest, madjanet:latest, qwen2.5-coder:3b) "
                f"handles most internal tasks at $0 cost.",
                est_savings=api_spend * 0.6,
            ))
        return recs

    def print_recommendations(self) -> None:
        recs = self.analyze()
        if not recs:
            print("✅ No optimization recommendations at this time.")
            return
        print(f"\n─── {len(recs)} Optimization Recommendations ───────────────")
        for r in recs:
            print(f"\n{r}")
        print("\n" + "─" * 52 + "\n")
