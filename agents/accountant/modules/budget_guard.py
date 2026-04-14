"""
budget_guard.py — Budget threshold enforcement and alert system.

Watches running totals against configured limits. Fires alerts when approaching
or exceeding budgets. Tracks free-tier usage to prevent surprise overages.

Usage:
    guard = BudgetGuard()
    alerts = guard.check()      # Returns list of active alerts
    guard.print_status()        # Human-readable budget status
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .ledger import Ledger

logger = logging.getLogger("accountant.budget_guard")

CONFIG_PATH   = Path(__file__).resolve().parents[1] / "config.yaml"
BUDGETS_PATH  = Path.home() / ".accountant" / "budgets.json"
ALERTS_PATH   = Path.home() / ".accountant" / "alerts.jsonl"
FREE_TIER_PATH = Path.home() / ".accountant" / "free_tier.json"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)
    return {}


class BudgetAlert:
    WARN  = "warning"
    CRIT  = "critical"
    INFO  = "info"

    def __init__(self, level: str, title: str, message: str, value: float, limit: float):
        self.level   = level
        self.title   = title
        self.message = message
        self.value   = value
        self.limit   = limit
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level":     self.level,
            "title":     self.title,
            "message":   self.message,
            "value":     self.value,
            "limit":     self.limit,
        }

    def __repr__(self) -> str:
        icon = "🔴" if self.level == self.CRIT else ("🟡" if self.level == self.WARN else "🔵")
        pct  = (self.value / self.limit * 100) if self.limit > 0 else 0
        return f"{icon} [{self.level.upper()}] {self.title}: ${self.value:.4f} / ${self.limit:.2f} ({pct:.0f}%)"


class BudgetGuard:
    """
    Monitors spend against budget limits and fires alerts.

    Budgets are loaded from:
      1. ~/.accountant/budgets.json  (user overrides)
      2. config.yaml defaults
    """

    def __init__(self, ledger: Optional[Ledger] = None):
        self.ledger  = ledger or Ledger()
        self.config  = _load_config()
        self.budgets = self._load_budgets()
        ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _load_budgets(self) -> dict:
        defaults = self.config.get("budgets", {
            "daily_limit_usd":    5.0,
            "weekly_limit_usd":   25.0,
            "monthly_limit_usd":  100.0,
            "alert_at_percent":   80,
        })
        if BUDGETS_PATH.exists():
            with open(BUDGETS_PATH) as f:
                user = json.load(f)
            defaults.update(user)
        return defaults

    def _log_alert(self, alert: BudgetAlert) -> None:
        with open(ALERTS_PATH, "a") as f:
            f.write(json.dumps(alert.to_dict()) + "\n")

    # ── Core check ────────────────────────────────────────────────────────────

    def check(self) -> list[BudgetAlert]:
        """
        Run all budget checks. Returns list of active alerts.
        Also writes alerts to the alert log.
        """
        alerts = []
        warn_pct = self.budgets.get("alert_at_percent", 80) / 100

        checks = [
            ("Daily",   self.ledger.daily_total(),   self.budgets.get("daily_limit_usd",   5.0)),
            ("Weekly",  self.ledger.weekly_total(),  self.budgets.get("weekly_limit_usd",  25.0)),
            ("Monthly", self.ledger.monthly_total(), self.budgets.get("monthly_limit_usd", 100.0)),
        ]

        for label, spent, limit in checks:
            if limit <= 0:
                continue
            pct = spent / limit
            if pct >= 1.0:
                a = BudgetAlert(
                    BudgetAlert.CRIT,
                    f"{label} budget exceeded",
                    f"Spent ${spent:.4f} against ${limit:.2f} limit.",
                    spent, limit,
                )
                alerts.append(a)
                self._log_alert(a)
                logger.error(repr(a))
            elif pct >= warn_pct:
                a = BudgetAlert(
                    BudgetAlert.WARN,
                    f"{label} budget {pct*100:.0f}% used",
                    f"Spent ${spent:.4f} of ${limit:.2f} limit. ${limit-spent:.4f} remaining.",
                    spent, limit,
                )
                alerts.append(a)
                self._log_alert(a)
                logger.warning(repr(a))

        return alerts

    def check_free_tier(self) -> list[BudgetAlert]:
        """Check free-tier usage against known limits."""
        if not FREE_TIER_PATH.exists():
            return []

        with open(FREE_TIER_PATH) as f:
            tiers = json.load(f)

        warn_pct = self.config.get("alerts", {}).get("free_tier_warning_pct", 85) / 100
        alerts = []

        for service, data in tiers.items():
            used  = data.get("used", 0)
            limit = data.get("limit", 0)
            if limit <= 0:
                continue
            pct = used / limit
            if pct >= warn_pct:
                level = BudgetAlert.CRIT if pct >= 1.0 else BudgetAlert.WARN
                a = BudgetAlert(
                    level,
                    f"Free tier: {service}",
                    f"Used {used:,} of {limit:,} {data.get('unit','units')} ({pct*100:.0f}%). "
                    f"Billing begins after limit.",
                    pct * 100, 100,
                )
                alerts.append(a)
                self._log_alert(a)

        return alerts

    def detect_cost_spike(self) -> Optional[BudgetAlert]:
        """
        Compare today's spend to the 7-day rolling average.
        Alert if today is N× higher than average.
        """
        multiplier = self.config.get("alerts", {}).get("cost_spike_multiplier", 2.5)
        today   = self.ledger.daily_total()
        week    = self.ledger.weekly_total()
        avg_day = week / 7 if week > 0 else 0

        if avg_day > 0 and today >= avg_day * multiplier:
            a = BudgetAlert(
                BudgetAlert.WARN,
                "Cost spike detected",
                f"Today: ${today:.4f} is {today/avg_day:.1f}× the 7-day average (${avg_day:.4f}/day).",
                today, avg_day * multiplier,
            )
            self._log_alert(a)
            return a
        return None

    # ── Status display ────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return a structured budget status dict."""
        daily_limit   = self.budgets.get("daily_limit_usd",   5.0)
        weekly_limit  = self.budgets.get("weekly_limit_usd",  25.0)
        monthly_limit = self.budgets.get("monthly_limit_usd", 100.0)

        daily   = self.ledger.daily_total()
        weekly  = self.ledger.weekly_total()
        monthly = self.ledger.monthly_total()

        return {
            "daily":   {"spent": daily,   "limit": daily_limit,   "remaining": daily_limit - daily,   "pct": daily/daily_limit*100     if daily_limit else 0},
            "weekly":  {"spent": weekly,  "limit": weekly_limit,  "remaining": weekly_limit - weekly,  "pct": weekly/weekly_limit*100   if weekly_limit else 0},
            "monthly": {"spent": monthly, "limit": monthly_limit, "remaining": monthly_limit - monthly,"pct": monthly/monthly_limit*100 if monthly_limit else 0},
        }

    def print_status(self) -> None:
        s = self.status()
        print("\n─── Budget Status ───────────────────────────────")
        for period, data in s.items():
            bar_filled = int(data["pct"] / 5)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            print(f"  {period.capitalize():8s}  [{bar}] {data['pct']:5.1f}%  ${data['spent']:.4f} / ${data['limit']:.2f}")
        print("─────────────────────────────────────────────────\n")
