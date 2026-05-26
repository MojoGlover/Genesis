#!/usr/bin/env python3
"""
stamp.py — Stamp this BlackZero template into a new agent.

Usage (from cmptrblk/ root or here):
    python3 GENESIS/BlackZero/stamp.py \
        --id goldberg --name Goldberg --role "AI art assistant" \
        --port 5006 --model blackzero-hardened:latest \
        --plugops ws://localhost:9000/ws \
        --out GENESIS/agents/goldberg

Slots replaced in every text file:
    {{AGENT_ID}}     → agent id (lowercase, e.g. goldberg)
    {{AGENT_NAME}}   → display name (e.g. Goldberg)
    {{AGENT_ROLE}}   → short role description
    {{AGENT_PORT}}   → HTTP port (integer, e.g. 5006)
    {{AGENT_MODEL}}  → Ollama model tag (e.g. goldberg:latest)
    {{PLUGOPS_URL}}  → WebSocket URL (e.g. ws://localhost:9000/ws)

The missions/ directory is cleared — write your own mission file before starting.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent  # GENESIS/BlackZero/
CMPTRBLK_DIR = TEMPLATE_DIR.parent.parent  # ai/cmptrblk/

_TEXT_SUFFIXES = {
    ".py", ".yaml", ".yml", ".txt", ".md", ".sh", ".toml", ".cfg", ".ini", ".json"
}

_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "dist", "build", "*.egg-info",
}


def _replace_slots(text: str, slots: dict[str, str]) -> str:
    for key, val in slots.items():
        text = text.replace(f"{{{{{key}}}}}", val)
    return text


def stamp(
    agent_id:    str,
    agent_name:  str,
    agent_role:  str,
    port:        int,
    model:       str,
    plugops_url: str,
    dest:        Path,
) -> None:
    if dest.exists():
        print(f"✗  Destination already exists: {dest}")
        print(f"   Remove it first or choose a different name.")
        sys.exit(1)

    slots = {
        "AGENT_ID":    agent_id,
        "AGENT_NAME":  agent_name,
        "AGENT_ROLE":  agent_role,
        "AGENT_PORT":  str(port),
        "AGENT_MODEL": model,
        "PLUGOPS_URL": plugops_url,
    }

    print(f"\n{'━'*52}")
    print(f"  Stamping {agent_name}  (id={agent_id})")
    print(f"  Role:    {agent_role}")
    print(f"  Port:    {port}")
    print(f"  Model:   {model}")
    print(f"  PlugOps: {plugops_url}")
    print(f"  Dest:    {dest}")
    print(f"{'━'*52}\n")

    # 1. Copy template (exclude runtime junk)
    print("  [1/4] Copying template...")
    shutil.copytree(
        TEMPLATE_DIR, dest,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".git", "*.db", "*.log",
            "*.egg-info", "dist", "build", ".venv", "venv",
            "stamp.py",  # don't ship the stamper itself
        ),
    )

    # 2. Replace slots in all text files
    print("  [2/4] Replacing slots...")
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") or part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            original = path.read_text(encoding="utf-8")
            replaced = _replace_slots(original, slots)
            if replaced != original:
                path.write_text(replaced, encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            pass  # binary or unreadable — skip

    # 3. Clear missions dir (agent writes its own)
    print("  [3/4] Clearing missions dir...")
    missions_dir = dest / "missions"
    if missions_dir.exists():
        for f in missions_dir.glob("*.txt"):
            f.unlink()
    else:
        missions_dir.mkdir(parents=True, exist_ok=True)

    # 4. Fresh git repo
    print("  [4/4] Initializing git repo...")
    subprocess.run(["git", "init"], cwd=dest, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=dest, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"Initial stamp: {agent_name}"],
        cwd=dest, check=True, capture_output=True,
    )

    mission_file = f"{agent_id.upper()}.mission.txt"
    print(f"""
{'━'*52}
  ✅  {agent_name} stamped at:
      {dest}

  Next steps:
  ────────────────────────────────────────────────
  1. Write the mission file:
       {dest}/missions/{mission_file}

  2. Pull the model (if not already present):
       ollama pull {model}

  3. Add a git remote and push:
       cd {dest}
       git remote add origin https://github.com/MojoGlover/{agent_id}.git
       git push -u origin main

  4. Start the agent:
       cd {dest}
       python3 main.py

  5. Verify:
       curl http://localhost:{port}/health
{'━'*52}
""")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stamp a BlackZero agent.")
    parser.add_argument("--id",      required=True, help="Agent id: goldberg")
    parser.add_argument("--name",    required=True, help="Display name: Goldberg")
    parser.add_argument("--role",    required=True, help="Short role description")
    parser.add_argument("--port",    type=int, default=5001, help="HTTP port (default: 5001)")
    parser.add_argument("--model",   default=None,
                        help="Ollama model tag (default: <id>:latest)")
    parser.add_argument("--plugops", default="ws://localhost:9000/ws",
                        help="PlugOps WebSocket URL")
    parser.add_argument("--out",     default=None,
                        help="Output directory (default: GENESIS/agents/<id>)")
    args = parser.parse_args()

    model = args.model or f"{args.id}:latest"
    dest  = Path(args.out) if args.out else (CMPTRBLK_DIR / "GENESIS" / "agents" / args.id)

    stamp(
        agent_id    = args.id,
        agent_name  = args.name,
        agent_role  = args.role,
        port        = args.port,
        model       = model,
        plugops_url = args.plugops,
        dest        = dest,
    )


if __name__ == "__main__":
    main()
