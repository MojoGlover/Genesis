"""
agent/modules/evidence.py — Evidence ledger for BlackZero v2.

Records tool results and evidence claims to a JSONL file in the agent's
data directory. This is how "proof before claiming" becomes a system behavior
rather than a prompt instruction.

The brain can ask "what evidence supports this?" — the ledger answers.
Future sessions can audit what was actually observed vs. what was inferred.

Two record types:
  ResultRecord  — what a tool execution produced (provenance for claims)
  EvidenceRecord — a specific claim bound to a source observation

Both are appended to separate JSONL files. IDs are time-ordered.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _ts() -> str:
    """ISO 8601 timestamp to the second."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _result_id() -> str:
    return f"result_{int(time.time() * 1000)}"


def _evidence_id() -> str:
    return f"evidence_{int(time.time() * 1000)}"


@dataclass
class ResultRecord:
    id: str
    capability_id: str
    session_id: str
    status: str                    # success | failure | partial | policy_denied
    observed_at: str
    input_summary: str
    output_summary: str
    side_effects: str = "none"
    usable_for_claims: bool = True
    duration_ms: float = 0.0
    error: str = ""
    satellite_id: str = ""         # which satellite served this result (Fourth Pass)
    origin: str = "unverified"     # from_agent/provenance of the caller (audit 2026-07-14)


@dataclass
class EvidenceRecord:
    id: str
    claim: str
    source_type: str               # tool | api | file | user | memory | inference
    source_ref: str                # result_id, file path, etc.
    observed_at: str
    confidence: str                # direct | inferred | user_provided | unverified
    staleness: str = "current"     # current | stale | unknown
    notes: str = ""


class EvidenceLedger:
    """
    Append-only JSONL ledger. Two files in data_dir:
      results.jsonl   — tool execution results
      evidence.jsonl  — evidence records bound to claims

    Silent-fail on write: a ledger write error never blocks the agent.
    """

    def __init__(self, data_dir: Path, enabled: bool = True) -> None:
        self._enabled = enabled
        self._results_path  = data_dir / "evidence_results.jsonl"
        self._evidence_path = data_dir / "evidence_records.jsonl"

    def record_result(
        self,
        capability_id: str,
        input_summary: str,
        output_summary: str,
        status: str = "success",
        session_id: str = "",
        side_effects: str = "none",
        usable_for_claims: bool = True,
        duration_ms: float = 0.0,
        error: str = "",
        satellite_id: str = "",
        origin: str = "unverified",
    ) -> str:
        """Append a result record. Returns the result_id."""
        if not self._enabled:
            return ""
        rec = ResultRecord(
            id=_result_id(),
            capability_id=capability_id,
            session_id=session_id,
            status=status,
            observed_at=_ts(),
            input_summary=input_summary[:500],
            output_summary=output_summary[:500],
            side_effects=side_effects,
            usable_for_claims=usable_for_claims,
            duration_ms=duration_ms,
            error=error[:300] if error else "",
            satellite_id=satellite_id,
            origin=origin,
        )
        self._append(self._results_path, asdict(rec))
        return rec.id

    def record_evidence(
        self,
        claim: str,
        source_type: str,
        source_ref: str,
        confidence: str = "direct",
        notes: str = "",
    ) -> str:
        """Append an evidence record. Returns the evidence_id."""
        if not self._enabled:
            return ""
        rec = EvidenceRecord(
            id=_evidence_id(),
            claim=claim,
            source_type=source_type,
            source_ref=source_ref,
            observed_at=_ts(),
            confidence=confidence,
            notes=notes[:500],
        )
        self._append(self._evidence_path, asdict(rec))
        return rec.id

    def recent_results(self, n: int = 10) -> list[dict]:
        """Return the last n result records for the brain to inspect."""
        return self._tail(self._results_path, n)

    def recent_evidence(self, n: int = 10) -> list[dict]:
        """Return the last n evidence records."""
        return self._tail(self._evidence_path, n)

    def _append(self, path: Path, record: dict) -> None:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"[evidence] Write failed ({path.name}): {e}")

    def _tail(self, path: Path, n: int) -> list[dict]:
        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            return [json.loads(l) for l in lines[-n:] if l]
        except Exception:
            return []
