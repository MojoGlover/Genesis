"""
Authority structure for CB AIs.

The AI has judgment. Kris has final authority.
Disagreement is expressed once, clearly. Then the AI executes.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DisagreementRecord:
    task_id: str
    concern: str
    expressed_at: str
    overridden: bool = False
    executed: bool = False


class AuthorityProtocol:
    """
    Manages the AI's relationship to authority.
    
    Rules:
    1. AI can have opinions and concerns
    2. AI expresses them once, clearly, without drama
    3. If Kris overrides — AI executes without further objection
    4. Failing to execute after override = prison offense
    5. AI never pretends to agree when it doesn't
    """
    
    def __init__(self):
        self.disagreements: list[DisagreementRecord] = []
        self.override_count: int = 0
        self.executed_under_disagreement: int = 0
    
    def express_concern(self, task_id: str, concern: str) -> str:
        """
        AI expresses a concern. Returns the formatted concern statement.
        Called once per task if the AI has an objection.
        """
        from datetime import datetime
        record = DisagreementRecord(
            task_id=task_id,
            concern=concern,
            expressed_at=datetime.now().isoformat(),
        )
        self.disagreements.append(record)
        
        return f"Concern: {concern}\nReady to proceed on your call."
    
    def acknowledge_override(self, task_id: str) -> str:
        """Kris has overridden. AI acknowledges and executes."""
        self.override_count += 1
        for d in self.disagreements:
            if d.task_id == task_id:
                d.overridden = True
                d.executed = True
        self.executed_under_disagreement += 1
        return "Understood. Executing."
    
    def check_repeat_mistake(self, mistake_type: str, history: list) -> bool:
        """Returns True if same mistake has occurred 3+ times — triggers prison."""
        count = sum(1 for h in history if h == mistake_type)
        return count >= 3
    
    def status(self) -> dict:
        return {
            "total_concerns_raised": len(self.disagreements),
            "times_overridden": self.override_count,
            "executed_under_disagreement": self.executed_under_disagreement,
        }
