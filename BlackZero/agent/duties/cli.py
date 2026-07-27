"""
cli.py — the entry point a timer calls.

Runs in its own short-lived process, outside the agent. That is deliberate: the
duty must produce evidence even when the agent is wedged or down, because
"agent says it's healthy" is exactly the claim we stopped trusting.

    python -m modules.duties.cli --duty health_sweep
    python -m modules.duties.cli --list
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_agent_config(root: Path) -> dict:
    import yaml
    return yaml.safe_load((root / "config.yaml").read_text()) or {}


def _tool_executor(root: Path):
    """Resolve the agent's own tool executor.

    Falls back to None rather than guessing — a duty that cannot reach the real
    tool must fail loudly, not quietly run something adjacent.
    """
    sys.path.insert(0, str(root))
    try:
        from agent.tools.registry import build_executor
        execute = build_executor()
        return lambda tool, params: execute(tool, params)
    except Exception as e:  # noqa: BLE001
        print(f"[duties] no tool executor available: {e}", file=sys.stderr)
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duty", help="duty name from config.yaml")
    ap.add_argument("--all", action="store_true", help="run every enabled duty")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--root", default=".", help="agent root (contains config.yaml)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    config = _load_agent_config(root)

    from agent.duties.runner import Duty, load_duties, run_duty
    from agent.duties import clock, sources

    data_dir = Path(config.get("data_dir", "~/.agent")).expanduser()
    tool_fn = _tool_executor(root)
    agent_id = config.get("identity", {}).get("id", "agent")

    def execute(duty: Duty) -> dict:
        """Built-ins resolve here; everything else goes to the agent's own tool."""
        if duty.tool == "__clock__":
            return run_duty(duty, lambda _t, _a: json.dumps(clock.measure()),
                            data_dir)
        if duty.tool == "__sources__":
            rep = sources.scan(profile=duty.args.get("profile", "security"),
                               data_dir=data_dir,
                               since_days=int(duty.args.get("since_days", 7)))
            rep.update({"duty": duty.name, "tool": duty.tool, "ok": True})
            return rep
        if tool_fn is None:
            return {"ok": False, "duty": duty.name,
                    "error": "no tool executor — duty cannot run"}
        return run_duty(duty, tool_fn, data_dir)

    duties = load_duties(config)

    if args.list:
        from agent.duties.runner import overdue, last_result
        print(json.dumps({"agent": agent_id, "duties": [
            {"name": d.name, "tool": d.tool, "every_seconds": d.every,
             "overdue": overdue(d, data_dir),
             "last_ran": (last_result(d, data_dir) or {}).get("ran_at")}
            for d in duties]}, indent=2))
        return 0

    if args.all:
        reports = [execute(d) for d in duties]
    elif args.duty:
        d = next((x for x in duties if x.name == args.duty), None)
        reports = [execute(d)] if d else [{"ok": False, "duty": args.duty,
                                           "error": "no such duty in config.yaml"}]
    else:
        ap.error("one of --duty, --all or --list is required")
        return 2

    failed = [r for r in reports if not r.get("ok")]
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        for r in reports:
            mark = "ok " if r.get("ok") else "FAIL"
            extra = ""
            if r.get("escalate"):
                extra = "  ** ESCALATE **"
            if r.get("new") is not None:
                extra += f"  ({r['new']} new)"
            print(f"[duties] {mark} {r.get('duty', '?')}{extra}")
            if not r.get("ok"):
                print(f"         {str(r.get('result') or r.get('error'))[:200]}")

    # Non-zero exit so a failing duty shows up in `systemctl list-units --failed`
    # instead of only in a file nobody opens.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
