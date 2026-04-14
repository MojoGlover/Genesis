"""
reporter.py — Financial report generation for the Accountant agent.

Generates structured reports: daily summaries, monthly breakdowns, tax exports,
P&L summaries, and vendor/agent/category breakdowns.

Usage:
    reporter = Reporter()
    print(reporter.daily_summary())
    reporter.export_tax_csv(year=2025, path="~/Desktop/2025_expenses.csv")
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .ledger import Ledger, Transaction

logger = logging.getLogger("accountant.reporter")

REPORTS_DIR = Path.home() / ".accountant" / "reports"


class Reporter:

    def __init__(self, ledger: Optional[Ledger] = None):
        self.ledger = ledger or Ledger()
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Text summaries ────────────────────────────────────────────────────────

    def daily_summary(self) -> str:
        txs   = self.ledger.since_days(1)
        total = self.ledger.total_usd(txs)
        lines = [
            f"Daily Cost Summary — {datetime.now(timezone.utc).date()}",
            f"Total: ${total:.4f}",
            "",
        ]
        if not txs:
            lines.append("  No transactions recorded today.")
        else:
            by_vendor = {}
            for tx in txs:
                by_vendor[tx.vendor] = by_vendor.get(tx.vendor, 0) + tx.amount_usd
            for vendor, amt in sorted(by_vendor.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {vendor:30s}  ${amt:.4f}")
        return "\n".join(lines)

    def weekly_summary(self) -> str:
        txs   = self.ledger.since_days(7)
        total = self.ledger.total_usd(txs)
        lines = [
            f"Weekly Cost Summary (last 7 days)",
            f"Total: ${total:.4f}",
            f"Daily average: ${total/7:.4f}",
            "",
            "By category:",
        ]
        by_cat = {}
        for tx in txs:
            by_cat[tx.category] = by_cat.get(tx.category, 0) + tx.amount_usd
        for cat, amt in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
            pct = (amt / total * 100) if total > 0 else 0
            lines.append(f"  {cat:35s}  ${amt:.4f}  ({pct:.1f}%)")
        return "\n".join(lines)

    def monthly_summary(self) -> str:
        txs   = self.ledger.since_days(30)
        total = self.ledger.total_usd(txs)
        by_agent  = {}
        by_cat    = {}
        by_vendor = {}

        for tx in txs:
            by_agent[tx.agent]    = by_agent.get(tx.agent, 0)    + tx.amount_usd
            by_cat[tx.category]   = by_cat.get(tx.category, 0)   + tx.amount_usd
            by_vendor[tx.vendor]  = by_vendor.get(tx.vendor, 0)  + tx.amount_usd

        lines = [
            f"Monthly Cost Summary (last 30 days)",
            f"Total:    ${total:.4f}",
            f"Per day:  ${total/30:.4f}  (projected annual: ${total/30*365:.2f})",
            "",
            "By agent:",
        ]
        for agent, amt in sorted(by_agent.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {agent:30s}  ${amt:.4f}")
        lines += ["", "By category:"]
        for cat, amt in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {cat:35s}  ${amt:.4f}")
        lines += ["", "By vendor:"]
        for vendor, amt in sorted(by_vendor.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {vendor:30s}  ${amt:.4f}")

        return "\n".join(lines)

    def agent_cost_breakdown(self) -> str:
        totals = self.ledger.by_agent_totals()
        grand  = sum(totals.values())
        lines  = ["Agent Cost Breakdown (all time)", f"Grand total: ${grand:.4f}", ""]
        for agent, amt in totals.items():
            pct = (amt / grand * 100) if grand > 0 else 0
            lines.append(f"  {agent:30s}  ${amt:.4f}  ({pct:.1f}%)")
        return "\n".join(lines)

    # ── Tax preparation ───────────────────────────────────────────────────────

    def tax_summary(self, year: Optional[int] = None) -> str:
        year = year or datetime.now().year
        txs  = [tx for tx in self.ledger.all() if tx.timestamp.startswith(str(year))]
        total      = self.ledger.total_usd(txs)
        deductible = self.ledger.total_usd([tx for tx in txs if tx.deductible])

        lines = [
            f"Tax Summary — {year}",
            f"Total business expenses:     ${total:.2f}",
            f"Likely deductible:           ${deductible:.2f}",
            "",
            "By tax category:",
        ]
        by_cat: dict[str, float] = {}
        for tx in txs:
            if tx.deductible:
                by_cat[tx.category] = by_cat.get(tx.category, 0) + tx.amount_usd
        for cat, amt in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {cat:35s}  ${amt:.2f}")
        lines += [
            "",
            "Note: Consult a tax professional to confirm deductibility.",
            "Export full transaction data with: export_tax_csv()",
        ]
        return "\n".join(lines)

    def export_tax_csv(
        self,
        year: Optional[int] = None,
        path: Optional[str | Path] = None,
    ) -> Path:
        """
        Export all transactions for a year to a CSV file suitable for
        handing to an accountant or importing into tax software.
        """
        year = year or datetime.now().year
        txs  = [tx for tx in self.ledger.all() if tx.timestamp.startswith(str(year))]

        if path is None:
            path = REPORTS_DIR / f"tax_export_{year}.csv"
        path = Path(path).expanduser()

        fieldnames = [
            "date", "vendor", "service", "amount_usd", "currency",
            "category", "cost_type", "agent", "workflow", "project",
            "frequency", "recurring", "deductible", "notes",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for tx in sorted(txs, key=lambda x: x.timestamp):
                writer.writerow({
                    "date":       tx.timestamp[:10],
                    "vendor":     tx.vendor,
                    "service":    tx.service,
                    "amount_usd": f"{tx.amount_usd:.6f}",
                    "currency":   tx.currency,
                    "category":   tx.category,
                    "cost_type":  tx.cost_type,
                    "agent":      tx.agent,
                    "workflow":   tx.workflow,
                    "project":    tx.project,
                    "frequency":  tx.frequency,
                    "recurring":  tx.recurring,
                    "deductible": tx.deductible,
                    "notes":      tx.notes,
                })

        logger.info(f"Tax export written: {path} ({len(txs)} transactions)")
        return path

    def export_json(
        self,
        days: Optional[int] = None,
        path: Optional[str | Path] = None,
    ) -> Path:
        """Export transactions to JSON for analysis or import."""
        txs = self.ledger.since_days(days) if days else self.ledger.all()
        if path is None:
            path = REPORTS_DIR / f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = Path(path).expanduser()
        with open(path, "w") as f:
            json.dump([tx.to_dict() for tx in txs], f, indent=2)
        return path
