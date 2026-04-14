"""
gcp_costs.py — GCP cost tracking and free-tier awareness for the Accountant.

Tracks known GCP usage and compares against free tier limits.
When Cloud Run is deployed (plugops on GCP), this module estimates
real costs and warns before billing starts.

Free tiers (as of 2025):
  Cloud Run:   2M requests/mo, 360K vCPU-sec/mo, 720K mem-GB-sec/mo
  Cloud Build: 120 build-min/day
  Artifact Registry: 0.5 GB storage
  GCS:         5 GB storage, 1 GB egress/mo
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("accountant.gcp_costs")

FREE_TIER_PATH = Path.home() / ".accountant" / "free_tier.json"

# GCP Cloud Run free tier limits (monthly)
CLOUD_RUN_FREE = {
    "requests":          2_000_000,     # requests per month
    "vcpu_seconds":      180_000,       # vCPU-seconds per month
    "memory_gb_seconds": 360_000,       # GB-seconds per month
}

# GCP pricing (after free tier, us-central1, 2025)
CLOUD_RUN_RATES = {
    "requests_per_million":     0.40,
    "vcpu_per_second":          0.000024,
    "memory_gb_per_second":     0.0000025,
}


def _load_usage() -> dict:
    if FREE_TIER_PATH.exists():
        with open(FREE_TIER_PATH) as f:
            return json.load(f)
    return {}


def _save_usage(data: dict) -> None:
    FREE_TIER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FREE_TIER_PATH, "w") as f:
        json.dump(data, f, indent=2)


class GCPCostTracker:
    """
    Tracks GCP Cloud Run usage and cost.

    Usage:
        gcp = GCPCostTracker()
        gcp.record_cloud_run_request(count=1000, vcpu_seconds=120, memory_gb_seconds=240)
        print(gcp.status())
        print(gcp.monthly_estimate())
    """

    def __init__(self):
        self.usage = _load_usage()

    def _current_month_key(self) -> str:
        return datetime.now().strftime("%Y-%m")

    def record_cloud_run_request(
        self,
        count: int = 1,
        vcpu_seconds: float = 0.1,
        memory_gb_seconds: float = 0.05,
    ) -> None:
        """
        Record Cloud Run usage. Call this each time PlugOps handles a request.
        Estimates are: ~0.1 vCPU-sec and ~0.05 GB-sec per request for PlugOps.
        """
        month = self._current_month_key()
        cr    = self.usage.setdefault("cloud_run", {}).setdefault(month, {
            "requests": 0, "vcpu_seconds": 0.0, "memory_gb_seconds": 0.0,
        })
        cr["requests"]          += count
        cr["vcpu_seconds"]      += vcpu_seconds
        cr["memory_gb_seconds"] += memory_gb_seconds
        _save_usage(self.usage)

    def monthly_usage(self, month: Optional[str] = None) -> dict:
        month = month or self._current_month_key()
        return self.usage.get("cloud_run", {}).get(month, {
            "requests": 0, "vcpu_seconds": 0.0, "memory_gb_seconds": 0.0,
        })

    def monthly_cost(self, month: Optional[str] = None) -> dict:
        """
        Calculate actual billable cost after free tier for a given month.
        Returns breakdown of requests, compute, and memory costs.
        """
        u = self.monthly_usage(month)

        req_used  = u.get("requests", 0)
        vcpu_used = u.get("vcpu_seconds", 0)
        mem_used  = u.get("memory_gb_seconds", 0)

        # Subtract free tier
        bill_req  = max(0, req_used  - CLOUD_RUN_FREE["requests"])
        bill_vcpu = max(0, vcpu_used - CLOUD_RUN_FREE["vcpu_seconds"])
        bill_mem  = max(0, mem_used  - CLOUD_RUN_FREE["memory_gb_seconds"])

        cost_req  = (bill_req  / 1_000_000) * CLOUD_RUN_RATES["requests_per_million"]
        cost_vcpu = bill_vcpu  * CLOUD_RUN_RATES["vcpu_per_second"]
        cost_mem  = bill_mem   * CLOUD_RUN_RATES["memory_gb_per_second"]
        total     = cost_req + cost_vcpu + cost_mem

        return {
            "month":              month or self._current_month_key(),
            "requests_used":      req_used,
            "requests_free":      min(req_used, CLOUD_RUN_FREE["requests"]),
            "requests_billed":    bill_req,
            "vcpu_seconds_used":  round(vcpu_used, 2),
            "vcpu_seconds_free":  round(min(vcpu_used, CLOUD_RUN_FREE["vcpu_seconds"]), 2),
            "vcpu_seconds_billed":round(bill_vcpu, 2),
            "cost_requests_usd":  round(cost_req,  6),
            "cost_vcpu_usd":      round(cost_vcpu, 6),
            "cost_memory_usd":    round(cost_mem,  6),
            "total_cost_usd":     round(total, 6),
            "within_free_tier":   total == 0,
        }

    def free_tier_pct(self) -> dict:
        """Return percentage of free tier used this month for each resource."""
        u = self.monthly_usage()
        return {
            "requests":           round(u.get("requests", 0) / CLOUD_RUN_FREE["requests"] * 100, 1),
            "vcpu_seconds":       round(u.get("vcpu_seconds", 0) / CLOUD_RUN_FREE["vcpu_seconds"] * 100, 1),
            "memory_gb_seconds":  round(u.get("memory_gb_seconds", 0) / CLOUD_RUN_FREE["memory_gb_seconds"] * 100, 1),
        }

    def status(self) -> str:
        cost = self.monthly_cost()
        pcts = self.free_tier_pct()
        lines = [
            f"─── GCP Cloud Run — {cost['month']} ──────────────────────────",
            f"  Requests:       {cost['requests_used']:>10,}  ({pcts['requests']:.1f}% of free tier)",
            f"  vCPU-sec:       {cost['vcpu_seconds_used']:>10.1f}  ({pcts['vcpu_seconds']:.1f}% of free tier)",
            f"  Mem GB-sec:     {cost['memory_gb_seconds_used'] if 'memory_gb_seconds_used' in cost else 0:>10.1f}  ({pcts['memory_gb_seconds']:.1f}% of free tier)",
            f"  Billable cost:  {('$0.00 (within free tier)' if cost['within_free_tier'] else ('$' + str(round(cost['total_cost_usd'], 4))))}",
            "─────────────────────────────────────────────────────────",
        ]
        return "\n".join(lines)

    def alert_if_approaching_limit(self, threshold_pct: float = 85.0) -> list[str]:
        """Return alert messages for any resource approaching the free tier limit."""
        pcts   = self.free_tier_pct()
        alerts = []
        for resource, pct in pcts.items():
            if pct >= threshold_pct:
                level = "CRITICAL" if pct >= 100 else "WARNING"
                alerts.append(
                    f"[{level}] GCP Cloud Run {resource}: {pct:.1f}% of free tier used. "
                    f"{'Billing has started.' if pct >= 100 else 'Billing will start soon.'}"
                )
        return alerts
