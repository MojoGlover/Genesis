"""
journal.py — Append-only improvement journal.

Records every improvement cycle — what was analyzed, what was proposed,
whether it was accepted, and the score impact. This is the agent's
self-improvement history. Never deleted, never modified after write.

File: {agent_dir}/data/improvement_journal.jsonl
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ImprovementJournal:
    """Append-only journal for self-improvement cycle records."""

    def __init__(self, agent_dir: Path):
        self.agent_dir = agent_dir
        self._data_dir = agent_dir / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._journal_path = self._data_dir / "improvement_journal.jsonl"

    def write(self, result) -> None:
        """
        Append an improvement result to the journal.

        Args:
            result: ImprovementResult dataclass or dict
        """
        try:
            if hasattr(result, "__dataclass_fields__"):
                entry = asdict(result)
            elif isinstance(result, dict):
                entry = result
            else:
                entry = {"raw": str(result)}

            entry["recorded_at"] = datetime.now(timezone.utc).isoformat()

            with open(self._journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

            logger.debug(
                f"Journal entry #{entry.get('cycle_number', '?')}: "
                f"accepted={entry.get('accepted', '?')}, "
                f"delta={entry.get('score_delta', 0.0):.3f}"
            )
        except Exception as e:
            logger.error(f"Failed to write journal entry: {e}")

    def log_error(self, cycle_number: int, error: str) -> None:
        """Log an improvement cycle error to the journal."""
        entry = {
            "cycle_number": cycle_number,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "accepted": False,
        }
        try:
            with open(self._journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to write error journal entry: {e}")

    def read_recent(self, n: int = 20) -> list:
        """Read the last N journal entries."""
        if not self._journal_path.exists():
            return []

        entries = []
        try:
            for line in self._journal_path.read_text().strip().split("\n"):
                if line.strip():
                    entries.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read journal: {e}")
            return []

        return entries[-n:]

    def summary(self) -> Dict[str, Any]:
        """Summarize journal: total cycles, acceptance rate, cumulative delta."""
        entries = self.read_recent(1000)
        if not entries:
            return {
                "total_cycles": 0,
                "accepted": 0,
                "rejected": 0,
                "acceptance_rate": 0.0,
                "cumulative_score_delta": 0.0,
                "errors": 0,
            }

        accepted = sum(1 for e in entries if e.get("accepted"))
        errors = sum(1 for e in entries if "error" in e)
        rejected = len(entries) - accepted - errors
        cumulative_delta = sum(e.get("score_delta", 0.0) for e in entries)

        return {
            "total_cycles": len(entries),
            "accepted": accepted,
            "rejected": rejected,
            "acceptance_rate": round(accepted / max(1, len(entries) - errors), 3),
            "cumulative_score_delta": round(cumulative_delta, 4),
            "errors": errors,
        }
