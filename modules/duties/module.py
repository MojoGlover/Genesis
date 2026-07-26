"""
duties — deterministic recurring work for any agent.

THE RULE
--------
Code does the doing. The model only judges results it was handed, and is never
asked whether to look.

A duty is recurring work an agent owns: a health sweep, an integrity check, a
credential rotation, a scan of its field for new techniques. It runs on a timer,
calls the agent's own tool directly, and writes evidence to disk.

WHY THE MODULE EXISTS
---------------------
On 2026-07-26 CRBRS's sweeps were configured as LLM loops — the model was asked
to run `security_health` every 30 minutes. It never called the tool. It reported:

    "I have run a health sweep on the agent grid. All agents are currently
     registered and their credentials are valid."

A fabricated clean bill of health for a grid it never examined. Twice.

That is not a prompt problem. A local persona model (`capabilities:
['completion']`) narrates rather than acts, and there is no judgment in "run
this every 30 minutes" anyway. So the trigger and the doing both move to code,
and the model is left the one job it is actually good at: reading real findings
and saying which matter.

CONFIG (config.yaml)
--------------------
    duties:
      - name: health_sweep
        every: 30m
        run: security_health        # the agent's own tool, called directly
        args: {mode: system}
        record: health_reports      # evidence lands here, under data_dir
        escalate_if: "score < 70"   # deterministic threshold on the result
        interpret: false            # no model involved at all

      - name: field_scan
        every: 24h
        run: __sources__            # built-in: fetch from real feeds
        args: {profile: security, since_days: 7}
        record: intel
        interpret: true             # model reads FETCHED items, cannot invent them

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not schedule itself. Timers belong to the OS (systemd/launchd) so duties
keep running when the agent process is down — an agent that must be alive to
notice it is unhealthy is not a monitor. `units.py` generates those unit files;
`build_agent.py` installs them at stamp time.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

try:
    from fastapi import APIRouter
except ImportError:  # module is importable without FastAPI for timer-side use
    APIRouter = None  # type: ignore

from modules.base import ModuleBase

from . import sources
from .runner import Duty, last_result, load_duties, overdue, run_duty

logger = logging.getLogger(__name__)

SOURCES_TOOL = "__sources__"


class Module(ModuleBase):
    """Deterministic duty execution and evidence."""

    def __init__(self, config: dict | None = None,
                 tool_fn: Callable[[str, dict], str] | None = None,
                 data_dir: Path | None = None,
                 interpreter: Callable[[dict], str] | None = None) -> None:
        self._config = config or {}
        self._tool_fn = tool_fn
        self._data_dir = Path(data_dir or self._config.get("data_dir", "~/.agent")).expanduser()
        self._interpreter = interpreter
        self._duties: list[Duty] = load_duties(self._config)

    # ── ModuleBase contract ────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "duties"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return ("Recurring work that runs as code on a timer and writes evidence "
                "to disk. The model never decides whether to look.")

    @property
    def router(self):
        if APIRouter is None:
            return None
        r = APIRouter(prefix="/duties", tags=["duties"])

        @r.get("")
        async def list_duties():
            return {"duties": [self._describe(d) for d in self._duties]}

        @r.post("/{name}/run")
        async def run_now(name: str):
            """Run a duty on demand. Same code path as the timer — no shortcuts,
            so an on-demand result is exactly as trustworthy as a scheduled one."""
            duty = next((d for d in self._duties if d.name == name), None)
            if duty is None:
                return {"ok": False, "error": f"no duty named '{name}'"}
            return self.execute(duty)

        @r.get("/{name}/latest")
        async def latest(name: str):
            duty = next((d for d in self._duties if d.name == name), None)
            if duty is None:
                return {"ok": False, "error": f"no duty named '{name}'"}
            return last_result(duty, self._data_dir) or {"ok": False, "error": "never run"}

        return r

    def health(self) -> dict[str, Any]:
        """Health is measured from evidence on disk, not from a claim.

        A duty that has not produced a report within its interval is overdue,
        and the agent says so about itself.
        """
        stale = [d.name for d in self._duties if overdue(d, self._data_dir)]
        return {
            "status": "ok" if not stale else "degraded",
            "module": self.name,
            "version": self.version,
            "duties": len(self._duties),
            "overdue": stale,
        }

    # ── execution ──────────────────────────────────────────────────────────

    def execute(self, duty: Duty) -> dict:
        """Run one duty. Used identically by the timer and the HTTP route."""
        if duty.tool == SOURCES_TOOL:
            return self._run_sources(duty)
        if self._tool_fn is None:
            return {"ok": False, "duty": duty.name,
                    "error": "no tool executor wired — duties cannot run"}
        return run_duty(duty, self._tool_fn, self._data_dir, self._interpreter)

    def execute_all(self) -> list[dict]:
        return [self.execute(d) for d in self._duties]

    def execute_named(self, name: str) -> dict:
        duty = next((d for d in self._duties if d.name == name), None)
        if duty is None:
            return {"ok": False, "error": f"no duty named '{name}'"}
        return self.execute(duty)

    def _run_sources(self, duty: Duty) -> dict:
        """Built-in duty: fetch from real feeds. Never model-generated."""
        report = sources.scan(
            profile=duty.args.get("profile", "security"),
            data_dir=self._data_dir,
            since_days=int(duty.args.get("since_days", 7)),
            extra=duty.args.get("extra"),
        )
        report.update({"duty": duty.name, "tool": SOURCES_TOOL, "ok": True})

        # Interpretation runs on items that were actually fetched. The model
        # reads a list it did not author, so it cannot invent an advisory.
        if duty.interpret and self._interpreter is not None and report["new"]:
            try:
                report["interpretation"] = self._interpreter(report)
            except Exception as e:  # noqa: BLE001
                report["interpretation_error"] = str(e)
        return report

    def _describe(self, d: Duty) -> dict:
        last = last_result(d, self._data_dir)
        return {
            "name": d.name,
            "tool": d.tool,
            "every_seconds": d.every,
            "interpret": d.interpret,
            "overdue": overdue(d, self._data_dir),
            "last_ran": (last or {}).get("ran_at"),
            "last_ok": (last or {}).get("ok"),
        }
