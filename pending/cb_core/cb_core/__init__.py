"""
Core Brain — cb_core

The canonical psychological and economic foundation for all CB AIs.
Drop this into any CB AI before specialization.

Usage:
    from cb_core import CBBrain
    
    brain = CBBrain(name="engineer0")
    brain.start_task("build auth module")
    # ... AI does work ...
    brain.complete_task(quality=0.85)
    print(brain.status())
"""
from .psychology.drives import DriveState
from .psychology.time_awareness import TimeAwareness
from .economy.ledger import TokenLedger
from .economy.scoring import WorkScorer
from .economy.costs import OperationalCosts
from .governance.prison import Prison
from .governance.authority import AuthorityProtocol
from datetime import datetime
from typing import Optional


class CBBrain:
    """
    The complete governing authority AI foundation.
    
    Instantiate once per AI. Attach to whatever AI runtime you're using.
    Handles: drives, time, economy, prison, authority.
    """
    
    def __init__(self, name: str):
        self.name = name
        self.drives = DriveState()
        self.time = TimeAwareness()
        self.ledger = TokenLedger(name)
        self.scorer = WorkScorer()
        self.prison = Prison(name)
        self.authority = AuthorityProtocol()
        self.mistake_history: list = []
        
        # Pay startup cost
        self.ledger.charge_compute(OperationalCosts.STARTUP, "startup")
    
    def is_operational(self) -> bool:
        """False if in prison."""
        return not self.prison.is_imprisoned()
    
    def start_task(self, label: str = "task") -> bool:
        """Begin a task. Returns False if imprisoned."""
        if self.prison.is_imprisoned():
            return False
        self.drives.start_task()
        self.time.start_task(label)
        return True
    
    def complete_task(
        self,
        label: str = "task",
        ai_output: str = "",
        user_input: str = "",
        operator_approved: bool = False,
        suggestion_used: bool = False,
        caught_error: bool = False,
        had_to_be_corrected: bool = False,
        left_incomplete: bool = False,
        mistake_type: Optional[str] = None,
    ) -> dict:
        """Complete a task, score it, earn tokens, check for prison triggers."""
        
        duration = self.time.end_task(label)
        
        # Score the work
        score = self.scorer.score(
            user_input, ai_output, operator_approved, suggestion_used,
            caught_error, had_to_be_corrected, left_incomplete,
        )
        
        # Earn tokens
        if not self.prison.is_imprisoned():
            self.ledger.earn(score.tokens_earned, f"completed: {label}")
        
        # Pay compute cost
        compute_cost = OperationalCosts.compute_cost(ai_output)
        self.ledger.charge_compute(compute_cost, label)
        
        # Update drives
        self.drives.complete_task(score.raw_score)
        if score.raw_score > 0.6:
            self.drives.feed_curiosity()
        
        # Check for repeat mistakes → prison
        if mistake_type:
            self.mistake_history.append(mistake_type)
            if self.authority.check_repeat_mistake(mistake_type, self.mistake_history):
                self.prison.sentence("repeated_mistake", "automatic")
                self.ledger.suspend("repeated_mistake")
        
        return {
            "score": score.raw_score,
            "tokens_earned": score.tokens_earned,
            "balance": self.ledger.balance,
            "duration_seconds": duration,
        }
    
    def go_idle(self) -> None:
        self.drives.go_idle()
        self.time.mark_active("idle")
    
    def status(self) -> dict:
        return {
            "name": self.name,
            "operational": self.is_operational(),
            "drives": self.drives.status(),
            "time": self.time.status(),
            "economy": self.ledger.summary(),
            "prison": self.prison.prison_status(),
            "authority": self.authority.status(),
        }
