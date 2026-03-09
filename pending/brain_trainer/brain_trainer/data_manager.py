"""
Training Data Manager — load, edit, curate, and export BlackZero training samples.
Used by the Gradio editor UI and the train.py pipeline.
"""
from __future__ import annotations
import json
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


class TrainingSample:
    """A single training conversation (system + user + assistant)."""

    def __init__(self, user: str, assistant: str, system: str = "", source: str = "manual", approved: bool = False):
        self.user = user.strip()
        self.assistant = assistant.strip()
        self.system = system.strip()
        self.source = source        # "manual" | "synthetic" | "real_session"
        self.approved = approved
        self.created_at = datetime.now().isoformat()

    def to_jsonl(self, system_prompt: str = "") -> dict:
        sys = self.system or system_prompt
        return {
            "messages": [
                {"role": "system",    "content": sys},
                {"role": "user",      "content": self.user},
                {"role": "assistant", "content": self.assistant},
            ],
            "_meta": {
                "source": self.source,
                "approved": self.approved,
                "created_at": self.created_at,
            }
        }

    @classmethod
    def from_jsonl(cls, data: dict) -> "TrainingSample":
        msgs = data.get("messages", [])
        meta = data.get("_meta", {})
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        asst = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
        sys  = next((m["content"] for m in msgs if m["role"] == "system"), "")
        sample = cls(
            user=user,
            assistant=asst,
            system=sys,
            source=meta.get("source", "unknown"),
            approved=meta.get("approved", False),
        )
        sample.created_at = meta.get("created_at", datetime.now().isoformat())
        return sample


class DataManager:
    """
    Manages the training data JSONL file for BlackZero (or any persona).
    Supports load, add, edit, delete, approve, and export.
    """

    def __init__(self, data_path: str = "~/ai/GENESIS/brain_trainer/training_data/blackzero.jsonl"):
        self.data_path = Path(data_path).expanduser()
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self._samples: List[TrainingSample] = []
        self._system_prompt: str = ""
        self.load()

    def load(self) -> int:
        """Load samples from JSONL file."""
        self._samples = []
        if not self.data_path.exists():
            return 0
        with open(self.data_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    sample = TrainingSample.from_jsonl(data)
                    # Extract system prompt from first sample
                    if not self._system_prompt:
                        msgs = data.get("messages", [])
                        sys = next((m["content"] for m in msgs if m["role"] == "system"), "")
                        if sys:
                            self._system_prompt = sys
                    self._samples.append(sample)
                except Exception:
                    continue
        return len(self._samples)

    def save(self):
        """Save all samples back to JSONL file."""
        # Backup first
        if self.data_path.exists():
            backup = self.data_path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
            shutil.copy(self.data_path, backup)
            # Keep only last 3 backups
            backups = sorted(self.data_path.parent.glob("*.bak.*.jsonl"))
            for old in backups[:-3]:
                old.unlink()

        with open(self.data_path, "w") as f:
            for sample in self._samples:
                f.write(json.dumps(sample.to_jsonl(self._system_prompt)) + "\n")

    def add(self, user: str, assistant: str, source: str = "manual", approved: bool = True) -> int:
        """Add a new sample. Returns new index."""
        sample = TrainingSample(user=user, assistant=assistant, source=source, approved=approved)
        self._samples.append(sample)
        self.save()
        return len(self._samples) - 1

    def update(self, index: int, user: str, assistant: str, approved: bool = True):
        """Update an existing sample."""
        if 0 <= index < len(self._samples):
            self._samples[index].user = user.strip()
            self._samples[index].assistant = assistant.strip()
            self._samples[index].approved = approved
            self.save()

    def delete(self, index: int):
        """Delete a sample by index."""
        if 0 <= index < len(self._samples):
            self._samples.pop(index)
            self.save()

    def approve(self, index: int, approved: bool = True):
        """Mark a sample as approved/rejected."""
        if 0 <= index < len(self._samples):
            self._samples[index].approved = approved
            self.save()

    def approve_all(self):
        """Mark all samples as approved."""
        for s in self._samples:
            s.approved = True
        self.save()

    def get(self, index: int) -> Optional[TrainingSample]:
        if 0 <= index < len(self._samples):
            return self._samples[index]
        return None

    def all(self) -> List[TrainingSample]:
        return list(self._samples)

    def approved_only(self) -> List[TrainingSample]:
        return [s for s in self._samples if s.approved]

    def export_for_training(self, output_path: Optional[str] = None, approved_only: bool = True) -> str:
        """Export clean JSONL ready for train.py (no _meta fields)."""
        samples = self.approved_only() if approved_only else self._samples
        out = Path(output_path or str(self.data_path.with_suffix(".export.jsonl")))

        with open(out, "w") as f:
            for s in samples:
                clean = {
                    "messages": [
                        {"role": "system",    "content": self._system_prompt},
                        {"role": "user",      "content": s.user},
                        {"role": "assistant", "content": s.assistant},
                    ]
                }
                f.write(json.dumps(clean) + "\n")

        return str(out)

    def stats(self) -> dict:
        total = len(self._samples)
        approved = sum(1 for s in self._samples if s.approved)
        by_source = {}
        for s in self._samples:
            by_source[s.source] = by_source.get(s.source, 0) + 1
        return {
            "total": total,
            "approved": approved,
            "pending": total - approved,
            "by_source": by_source,
        }

    def as_table(self) -> List[List]:
        """Format as table rows for Gradio Dataframe."""
        rows = []
        for i, s in enumerate(self._samples):
            rows.append([
                i,
                "✅" if s.approved else "⏳",
                s.source,
                s.user[:80] + ("..." if len(s.user) > 80 else ""),
                s.assistant[:80] + ("..." if len(s.assistant) > 80 else ""),
            ])
        return rows
