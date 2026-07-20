"""
Auditor — CEO subordinate.

Forces proof before anything is marked done. Antidote to phantom-work: an
agent claiming "done" is not evidence of "done" — a matching artifact is.

Pipeline: claim intake -> artifact resolver -> match check -> status lock.
A task cannot close as `complete` without Auditor sign-off (close_task()
raises if the Auditor's verdict isn't "approved").

Run with: python main.py --claim claim.json [--config config.yaml]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parent

logger = logging.getLogger("auditor")
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)


# ── Chronicle logging (Chronicle-compatible schema; real POST if configured) ─
# Ingest protocol: PlugOps forwards to Chronicle's /api/tools/execute with
# {"tool": "chronicle_ingest", "params": {"key": ..., "events": [...]}}.
# CHRONICLE_INGEST_KEY is unset by default (feature-gated, like PlugOps' own
# emitter) — with no key, events are logged locally only, never dropped silently.

def log_event(*, kind: str, action: str, outcome: str = "ok", target: str = "",
              object: str = "", detail: str = "", duration_ms: int | None = None) -> None:
    event = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "actor": "auditor",
        "target": target,
        "object": object,
        "action": action,
        "outcome": outcome,
        "detail": detail[:200],
        "duration_ms": duration_ms,
    }
    logger.info(json.dumps(event))
    _emit_to_chronicle(event)


def _emit_to_chronicle(event: dict[str, Any]) -> None:
    key = os.environ.get("CHRONICLE_INGEST_KEY", "")
    if not key:
        return  # not configured — local log above is the only record
    url = os.environ.get("CHRONICLE_URL", "http://100.67.171.41:5010")
    try:
        httpx.post(
            f"{url}/api/tools/execute",
            json={"tool": "chronicle_ingest", "params": {"key": key, "events": [event]}},
            timeout=3.0,
        )
    except Exception as exc:
        logger.warning(json.dumps({"chronicle_emit_failed": str(exc)}))


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or (ROOT / "config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    if os.environ.get("ARTIFACT_ROOT"):
        config["artifact_root"] = os.environ["ARTIFACT_ROOT"]
    return config


# ── Claim intake ──────────────────────────────────────────────────────────────

REQUIRED_CLAIM_FIELDS = ("claim_id", "agent_id", "task_id", "claim_text", "artifact_path")


class ClaimIntakeError(ValueError):
    pass


def intake_claim(data: dict[str, Any]) -> dict[str, Any]:
    missing = [f for f in REQUIRED_CLAIM_FIELDS if not str(data.get(f, "")).strip()]
    if missing:
        raise ClaimIntakeError(f"done claim missing required field(s): {', '.join(missing)}")
    return {
        "claim_id": data["claim_id"],
        "agent_id": data["agent_id"],
        "task_id": data["task_id"],
        "claim_text": data["claim_text"],
        "artifact_path": data["artifact_path"],
        "expected_pattern": data.get("expected_pattern"),
    }


# ── Artifact resolver ─────────────────────────────────────────────────────────

class ArtifactResolver:
    """Confines lookups to artifact_root — a claim can't point outside it."""

    def __init__(self, artifact_root: str) -> None:
        self.root = Path(artifact_root).resolve()

    def resolve(self, artifact_path: str) -> Path | None:
        candidate = (self.root / artifact_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None  # escapes artifact_root — treat as unresolved, not an error
        return candidate if candidate.is_file() else None

    def read(self, artifact_path: str, max_bytes: int = 200_000) -> str | None:
        path = self.resolve(artifact_path)
        if path is None:
            return None
        return path.read_text(errors="replace")[:max_bytes]


# ── Match check ────────────────────────────────────────────────────────────────

_FAIL_MARKERS = re.compile(r"\b(FAILED|ERROR|Traceback|Exception|AssertionError)\b")
_PASS_MARKERS = re.compile(r"\b(passed|PASSED|OK|SUCCESS|All tests passed)\b")


@dataclass(frozen=True)
class AuditVerdict:
    status: str  # "approved" | "flagged" | "rejected"
    reason: str


def match_check(claim: dict[str, Any], resolver: ArtifactResolver) -> AuditVerdict:
    content = resolver.read(claim["artifact_path"])
    if content is None:
        return AuditVerdict("rejected", f"no artifact found at {claim['artifact_path']!r}")

    pattern = claim.get("expected_pattern")
    if pattern:
        if re.search(pattern, content):
            return AuditVerdict("approved", f"artifact matches expected_pattern {pattern!r}")
        return AuditVerdict("flagged", f"artifact does not match expected_pattern {pattern!r}")

    if _FAIL_MARKERS.search(content):
        return AuditVerdict("flagged", "artifact contains failure markers (FAILED/ERROR/Traceback)")
    if _PASS_MARKERS.search(content):
        return AuditVerdict("approved", "artifact contains pass markers, no failure markers")
    return AuditVerdict(
        "flagged",
        "artifact has neither pass nor failure markers — ambiguous, "
        "supply expected_pattern to disambiguate",
    )


def audit_claim(data: dict[str, Any], resolver: ArtifactResolver) -> AuditVerdict:
    claim = intake_claim(data)
    verdict = match_check(claim, resolver)
    log_event(
        kind="audit", action="claim_check", outcome=verdict.status,
        target=claim["task_id"], object=claim["agent_id"], detail=verdict.reason,
    )
    return verdict


# ── Status lock ────────────────────────────────────────────────────────────────

class StatusLockError(PermissionError):
    pass


def close_task(claim: dict[str, Any], verdict: AuditVerdict) -> None:
    """A task cannot close as complete without Auditor sign-off."""
    if verdict.status != "approved":
        raise StatusLockError(
            f"task {claim.get('task_id')} cannot close as complete: "
            f"Auditor verdict is {verdict.status!r} ({verdict.reason})"
        )
    log_event(kind="audit", action="close_task", outcome="ok",
              target=claim.get("task_id", ""), detail="Auditor sign-off recorded")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Auditor — CEO subordinate")
    parser.add_argument("--claim", type=Path, required=True, help="Path to a done-claim JSON file")
    parser.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    resolver = ArtifactResolver(config["artifact_root"])
    data = json.loads(args.claim.read_text())

    verdict = audit_claim(data, resolver)
    print(json.dumps(asdict(verdict), indent=2))
    sys.exit(0 if verdict.status == "approved" else 1)


if __name__ == "__main__":
    main()
