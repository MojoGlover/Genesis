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

    from modules.duties.module import Module
    mod = Module(
        config=config,
        tool_fn=_tool_executor(root),
        data_dir=Path(config.get("data_dir", "~/.agent")).expanduser(),
    )

    if args.list:
        print(json.dumps(mod.health(), indent=2))
        return 0

    if args.all:
        reports = mod.execute_all()
    elif args.duty:
        reports = [mod.execute_named(args.duty)]
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
