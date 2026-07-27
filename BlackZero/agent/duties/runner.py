"""
runner.py — deterministic duty execution.

A duty is recurring work an agent is responsible for. It runs as CODE on a
timer, calls the agent's own tool directly, and writes evidence to disk. No
model is involved in deciding whether to run it, what to call, or what happened.

WHY
---
On 2026-07-26, CRBRS's recurring security sweeps were configured as LLM loops —
the model was asked to run `security_health` every 30 minutes. It never called
the tool. Twice it returned:

    "I have run a health sweep on the agent grid. All agents are currently
     registered and their credentials are valid. No integrity issues were
     detected on any agent file."

A fabricated clean bill of health for a grid it never examined. For a security
agent that is worse than silence.

That was an architecture mistake, not a prompt problem. A local persona model
(`capabilities: ['completion']`, no native tool-calling) narrates rather than
acts. There is no judgment in "call security_health every 30 minutes", so no
model belongs in that path.

The rule this module enforces:
    code does the doing; the model only judges results it was handed,
    and is never asked whether to look.

Interpretation, when a duty asks for it, runs against a report that already
exists on disk. The model cannot report a sweep it was never asked to perform.
"""
from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

__all__ = ["Duty", "run_duty", "load_duties", "last_result", "overdue"]

_INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_every(value: str | int | float) -> int:
    """'30m' → 1800. Bare numbers are seconds."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if text and text[-1] in _INTERVAL_UNITS:
        return int(float(text[:-1]) * _INTERVAL_UNITS[text[-1]])
    return int(float(text))


class Duty:
    """One scheduled unit of deterministic work."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.name: str = spec["name"]
        self.tool: str = spec["run"]
        self.args: dict = spec.get("args", {}) or {}
        self.every: int = parse_every(spec.get("every", "1h"))
        self.record: str = spec.get("record", f"{self.name}_reports")
        # Deterministic threshold, evaluated against the tool's own output.
        # Kept as a simple expression on purpose — a duty that needs real
        # judgment should set interpret: true instead of growing a DSL here.
        self.escalate_if: str | None = spec.get("escalate_if")
        # interpret=true hands the FINISHED report to the model afterwards.
        # It never decides whether the duty runs.
        self.interpret: bool = bool(spec.get("interpret", False))
        self.enabled: bool = bool(spec.get("enabled", True))


def load_duties(config: dict) -> list[Duty]:
    return [Duty(d) for d in (config.get("duties") or []) if d.get("enabled", True)]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _evaluate(expr: str, result: Any) -> bool | None:
    """Evaluate a threshold against the tool's result.

    Restricted to comparisons over the result's own fields — no builtins, no
    imports, no attribute access. A duty threshold is configuration, and
    configuration must never become an execution path.
    """
    if not isinstance(result, dict):
        return None
    try:
        return bool(eval(expr, {"__builtins__": {}}, dict(result)))  # noqa: S307
    except Exception:
        return None


def run_duty(
    duty: Duty,
    tool_fn: Callable[[str, dict], str],
    data_dir: Path,
    interpreter: Callable[[dict], str] | None = None,
) -> dict:
    """Execute one duty. Always returns a report; never raises.

    tool_fn(tool_name, args) -> str  — the agent's own tool executor.
    interpreter(report) -> str       — optional, called ONLY on a finished report.
    """
    started = time.time()
    report: dict[str, Any] = {
        "duty": duty.name,
        "tool": duty.tool,
        "ran_at": _now(),
        "ok": False,
    }

    try:
        raw = tool_fn(duty.tool, duty.args)
        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            result = {"raw": str(raw)[:4000]}
        report["result"] = result
        report["ok"] = not (isinstance(result, dict) and "error" in result)
    except Exception as e:  # noqa: BLE001 — a failed duty must not kill the timer
        report["result"] = {"error": str(e)}
        report["traceback"] = traceback.format_exc()[-1500:]

    report["duration_seconds"] = round(time.time() - started, 3)

    if duty.escalate_if:
        report["escalate"] = _evaluate(duty.escalate_if, report.get("result"))
        report["escalate_if"] = duty.escalate_if

    # Interpretation runs on a report that already exists. This ordering is the
    # whole point: the model is handed findings, never asked to go get them.
    if duty.interpret and interpreter is not None:
        try:
            report["interpretation"] = interpreter(report)
        except Exception as e:  # noqa: BLE001
            report["interpretation_error"] = str(e)

    _write(report, duty, data_dir)
    return report


def _write(report: dict, duty: Duty, data_dir: Path) -> Path:
    out_dir = Path(data_dir).expanduser() / duty.record
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{duty.name}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2))
    (out_dir / "latest.json").write_text(json.dumps(report, indent=2))
    return path


def last_result(duty: Duty, data_dir: Path) -> dict | None:
    latest = Path(data_dir).expanduser() / duty.record / "latest.json"
    if not latest.exists():
        return None
    try:
        return json.loads(latest.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def overdue(duty: Duty, data_dir: Path, grace: float = 1.5) -> bool:
    """True if the duty hasn't produced evidence within its interval.

    This is how "is the agent actually doing its job" becomes answerable from
    disk rather than from the agent's own claim about itself.
    """
    latest = Path(data_dir).expanduser() / duty.record / "latest.json"
    if not latest.exists():
        return True
    return (time.time() - latest.stat().st_mtime) > duty.every * grace
