"""
ledger.py — Transaction ledger for the Accountant agent.

Every cost event in the system gets recorded here as an immutable JSONL entry.
The ledger is the source of truth for all financial reporting and tax preparation.

Each entry:
    timestamp       ISO-8601
    vendor          Service provider (e.g., "anthropic", "gcp", "github")
    service         Specific service (e.g., "claude-haiku-4-5", "cloud-run")
    amount_usd      Cost in USD (float)
    currency        Original currency (default "USD")
    frequency       "one_time" | "recurring_daily" | "recurring_monthly" | "recurring_annual"
    category        Tax category (see config.yaml tax_categories)
    agent           Which agent incurred this cost
    workflow        Which workflow/task triggered it
    project         Business project tag
    cost_type       "inference" | "compute" | "storage" | "subscription" | "transfer" | "other"
    recurring       bool
    deductible      bool (likely business deduction)
    notes           Free-text notes
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional
from dataclasses import dataclass, asdict, field

logger = logging.getLogger("accountant.ledger")

DEFAULT_LEDGER_PATH = Path.home() / ".accountant" / "ledger.jsonl"


@dataclass
class Transaction:
    """A single financial event."""
    timestamp:   str
    vendor:      str
    service:     str
    amount_usd:  float
    category:    str
    cost_type:   str
    agent:       str        = "system"
    workflow:    str        = ""
    project:     str        = ""
    currency:    str        = "USD"
    frequency:   str        = "one_time"
    recurring:   bool       = False
    deductible:  bool       = True
    notes:       str        = ""

    @classmethod
    def now(
        cls,
        vendor: str,
        service: str,
        amount_usd: float,
        category: str,
        cost_type: str,
        **kwargs: Any,
    ) -> "Transaction":
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            vendor=vendor,
            service=service,
            amount_usd=amount_usd,
            category=category,
            cost_type=cost_type,
            **kwargs,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Ledger:
    """
    Append-only JSONL transaction ledger.

    Usage:
        ledger = Ledger()
        ledger.record(
            vendor="anthropic",
            service="claude-haiku-4-5",
            amount_usd=0.0042,
            category="ai_services",
            cost_type="inference",
            agent="engineer0",
            workflow="code_review",
        )

        # Query
        for tx in ledger.since_days(30):
            print(tx.amount_usd, tx.vendor)
    """

    def __init__(self, path: Path = DEFAULT_LEDGER_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(
        self,
        vendor: str,
        service: str,
        amount_usd: float,
        category: str,
        cost_type: str,
        **kwargs: Any,
    ) -> Transaction:
        """Record a new transaction. Returns the saved Transaction."""
        tx = Transaction.now(
            vendor=vendor,
            service=service,
            amount_usd=amount_usd,
            category=category,
            cost_type=cost_type,
            **kwargs,
        )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(tx.to_dict()) + "\n")
        logger.info(f"Ledger: +${amount_usd:.4f} [{category}] {vendor}/{service}")
        return tx

    # ── Read ──────────────────────────────────────────────────────────────────

    def all(self) -> list[Transaction]:
        """Return all transactions, oldest first."""
        if not self.path.exists():
            return []
        entries = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(Transaction.from_dict(json.loads(line)))
                    except Exception as e:
                        logger.warning(f"Skipping malformed ledger entry: {e}")
        return entries

    def since_days(self, days: int) -> list[Transaction]:
        """Transactions from the last N days."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return [
            tx for tx in self.all()
            if datetime.fromisoformat(tx.timestamp) >= cutoff
        ]

    def by_agent(self, agent: str) -> list[Transaction]:
        return [tx for tx in self.all() if tx.agent == agent]

    def by_category(self, category: str) -> list[Transaction]:
        return [tx for tx in self.all() if tx.category == category]

    def by_vendor(self, vendor: str) -> list[Transaction]:
        return [tx for tx in self.all() if tx.vendor == vendor]

    def by_project(self, project: str) -> list[Transaction]:
        return [tx for tx in self.all() if tx.project == project]

    # ── Aggregates ────────────────────────────────────────────────────────────

    def total_usd(self, transactions: Optional[list[Transaction]] = None) -> float:
        txs = transactions if transactions is not None else self.all()
        return round(sum(tx.amount_usd for tx in txs), 6)

    def daily_total(self) -> float:
        return self.total_usd(self.since_days(1))

    def weekly_total(self) -> float:
        return self.total_usd(self.since_days(7))

    def monthly_total(self) -> float:
        return self.total_usd(self.since_days(30))

    def by_agent_totals(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for tx in self.all():
            totals[tx.agent] = round(totals.get(tx.agent, 0) + tx.amount_usd, 6)
        return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))

    def by_category_totals(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for tx in self.all():
            totals[tx.category] = round(totals.get(tx.category, 0) + tx.amount_usd, 6)
        return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))

    def by_vendor_totals(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for tx in self.all():
            totals[tx.vendor] = round(totals.get(tx.vendor, 0) + tx.amount_usd, 6)
        return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))

    def deductible_total(self, year: Optional[int] = None) -> float:
        txs = self.all()
        if year:
            txs = [tx for tx in txs if tx.timestamp.startswith(str(year))]
        return self.total_usd([tx for tx in txs if tx.deductible])
