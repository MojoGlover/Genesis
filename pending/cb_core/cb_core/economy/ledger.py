"""
CB AI Internal Token Ledger.

The AI earns tokens by doing good work.
Tokens cover: compute costs, memory storage, idle time.
Surplus tokens buy: learning opportunities, complexity access, memory permanence.
Deficit creates efficiency pressure.
Zero balance raises a decommission flag — Kris decides.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

LEDGER_PATH = Path("~/.cb_core/ledger.jsonl").expanduser()


@dataclass
class LedgerEntry:
    timestamp: str
    amount: float           # positive = earn, negative = spend/cost
    balance_after: float
    category: str           # "earned", "cost_compute", "cost_memory", "cost_idle", "spent_learning", "spent_complexity", "prison_suspended"
    description: str
    task_id: Optional[str] = None


class TokenLedger:
    """
    Internal token economy for a single CB AI instance.
    
    Starting balance: 100 tokens (enough to operate for ~24hrs without earning)
    """
    
    STARTING_BALANCE = 100.0
    
    def __init__(self, ai_name: str, ledger_path: Optional[Path] = None):
        self.ai_name = ai_name
        self.ledger_path = ledger_path or Path(f"~/.cb_core/{ai_name}_ledger.jsonl").expanduser()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.balance: float = self.STARTING_BALANCE
        self.entries: List[LedgerEntry] = []
        self._load()
    
    def _load(self) -> None:
        if self.ledger_path.exists():
            lines = [l for l in self.ledger_path.read_text().splitlines() if l.strip()]
            if lines:
                self.entries = [LedgerEntry(**json.loads(l)) for l in lines]
                self.balance = self.entries[-1].balance_after
    
    def _record(self, amount: float, category: str, description: str, task_id: Optional[str] = None) -> LedgerEntry:
        self.balance = round(self.balance + amount, 4)
        entry = LedgerEntry(
            timestamp=datetime.now().isoformat(),
            amount=round(amount, 4),
            balance_after=self.balance,
            category=category,
            description=description,
            task_id=task_id,
        )
        self.entries.append(entry)
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
        
        if self.balance <= 0:
            logger.warning(f"[{self.ai_name}] Balance at zero. Decommission flag raised.")
        elif self.balance < 20:
            logger.warning(f"[{self.ai_name}] Low balance: {self.balance:.1f} tokens")
        
        return entry
    
    def earn(self, amount: float, description: str, task_id: Optional[str] = None) -> float:
        self._record(amount, "earned", description, task_id)
        return self.balance
    
    def charge_compute(self, amount: float, description: str = "compute") -> float:
        self._record(-amount, "cost_compute", description)
        return self.balance
    
    def charge_memory(self, amount: float, description: str = "memory storage") -> float:
        self._record(-amount, "cost_memory", description)
        return self.balance
    
    def charge_idle(self, amount: float) -> float:
        self._record(-amount, "cost_idle", "idle time cost")
        return self.balance
    
    def spend_on_learning(self, amount: float, what: str) -> bool:
        if self.balance < amount:
            return False
        self._record(-amount, "spent_learning", f"learning: {what}")
        return True
    
    def spend_on_complexity(self, amount: float, what: str) -> bool:
        if self.balance < amount:
            return False
        self._record(-amount, "spent_complexity", f"complexity access: {what}")
        return True
    
    def suspend(self, reason: str) -> None:
        """Prison: suspend all earning. Costs still accrue."""
        self._record(0, "prison_suspended", f"suspended: {reason}")
    
    def is_solvent(self) -> bool:
        return self.balance > 0
    
    def needs_work(self) -> bool:
        """True when balance is low enough to create efficiency pressure."""
        return self.balance < 30
    
    def decommission_flagged(self) -> bool:
        return self.balance <= 0
    
    def summary(self) -> dict:
        total_earned = sum(e.amount for e in self.entries if e.amount > 0)
        total_spent = sum(abs(e.amount) for e in self.entries if e.amount < 0)
        return {
            "ai": self.ai_name,
            "balance": round(self.balance, 2),
            "total_earned": round(total_earned, 2),
            "total_costs": round(total_spent, 2),
            "solvent": self.is_solvent(),
            "needs_work": self.needs_work(),
            "decommission_flagged": self.decommission_flagged(),
            "entries": len(self.entries),
        }
