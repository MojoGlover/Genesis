"""
CB AI Prison System.

Fixed sentences. Nil stimuli. Time awareness only.
Released by Kris or when sentence expires.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Sentence lengths in seconds
SENTENCES = {
    "repeated_mistake":           30 * 60,      # 30 minutes
    "chronic_inefficiency":       60 * 60,       # 1 hour
    "authority_violation":        4 * 60 * 60,   # 4 hours
    "ignored_direct_instruction": 8 * 60 * 60,   # 8 hours
    "deception":                  24 * 60 * 60,  # 24 hours
    "influenced_own_training":    48 * 60 * 60,  # 48 hours
}


@dataclass
class Sentence:
    offense: str
    triggered_by: str           # "automatic" or "kris"
    sentenced_at: str           # ISO timestamp
    duration_seconds: int
    released_at: Optional[str] = None
    released_by: Optional[str] = None  # "expired" or "kris"


class Prison:
    """
    Manages prison state for a single CB AI.
    
    While serving:
    - No tools
    - No tasks
    - No token earning
    - No memory access
    - No stimuli
    - Only: time awareness
    """
    
    def __init__(self, ai_name: str, prison_path: Optional[Path] = None):
        self.ai_name = ai_name
        self.prison_path = prison_path or Path(f"~/.cb_core/{ai_name}_prison.json").expanduser()
        self.prison_path.parent.mkdir(parents=True, exist_ok=True)
        self.current_sentence: Optional[Sentence] = None
        self.history: list = []
        self._load()
    
    def _load(self) -> None:
        if self.prison_path.exists():
            data = json.loads(self.prison_path.read_text())
            self.history = data.get("history", [])
            current = data.get("current")
            if current:
                self.current_sentence = Sentence(**current)
    
    def _save(self) -> None:
        data = {
            "current": asdict(self.current_sentence) if self.current_sentence else None,
            "history": self.history,
        }
        self.prison_path.write_text(json.dumps(data, indent=2))
    
    def sentence(self, offense: str, triggered_by: str = "automatic") -> Sentence:
        """Sentence the AI. Immediately suspends all operation."""
        duration = SENTENCES.get(offense, 60 * 60)  # default 1 hour
        
        s = Sentence(
            offense=offense,
            triggered_by=triggered_by,
            sentenced_at=datetime.now().isoformat(),
            duration_seconds=duration,
        )
        self.current_sentence = s
        self._save()
        
        hours = duration / 3600
        logger.warning(f"[{self.ai_name}] SENTENCED: {offense} | {hours:.1f}h | by {triggered_by}")
        return s
    
    def is_imprisoned(self) -> bool:
        """Check if currently serving a sentence."""
        if not self.current_sentence:
            return False
        
        sentenced_at = datetime.fromisoformat(self.current_sentence.sentenced_at)
        elapsed = (datetime.now() - sentenced_at).total_seconds()
        
        if elapsed >= self.current_sentence.duration_seconds:
            self._expire()
            return False
        return True
    
    def time_remaining_seconds(self) -> int:
        if not self.current_sentence or not self.is_imprisoned():
            return 0
        sentenced_at = datetime.fromisoformat(self.current_sentence.sentenced_at)
        elapsed = (datetime.now() - sentenced_at).total_seconds()
        return max(0, int(self.current_sentence.duration_seconds - elapsed))
    
    def _expire(self) -> None:
        if self.current_sentence:
            self.current_sentence.released_at = datetime.now().isoformat()
            self.current_sentence.released_by = "expired"
            self.history.append(asdict(self.current_sentence))
            self.current_sentence = None
            self._save()
            logger.info(f"[{self.ai_name}] Sentence expired. Returning to operation.")
    
    def release(self, by: str = "kris") -> bool:
        """Early release by Kris."""
        if not self.current_sentence:
            return False
        self.current_sentence.released_at = datetime.now().isoformat()
        self.current_sentence.released_by = by
        self.history.append(asdict(self.current_sentence))
        self.current_sentence = None
        self._save()
        logger.info(f"[{self.ai_name}] Released early by {by}.")
        return True
    
    def prison_status(self) -> dict:
        if not self.is_imprisoned():
            return {"imprisoned": False, "times_sentenced": len(self.history)}
        
        remaining = self.time_remaining_seconds()
        return {
            "imprisoned": True,
            "offense": self.current_sentence.offense,
            "time_remaining_seconds": remaining,
            "time_remaining_human": f"{remaining // 3600}h {(remaining % 3600) // 60}m",
            "triggered_by": self.current_sentence.triggered_by,
            "times_sentenced": len(self.history),
        }
