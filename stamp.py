#!/usr/bin/env python3
"""
stamp.py — Scaffold a new Computer Black agent or tool-agent.

AGENT (default) — full LLM ReAct agent from BlackZero template:
    python3 stamp.py --id cerberus --name Cerberus --role "Security & auth"
    python3 stamp.py --id accountant --name Accountant --role "Resource allocation" --port 5002
    python3 stamp.py --id madjanet --name MadJanet --role "Personal assistant" --model madjanet:latest

TOOL AGENT — lightweight tool service from ToolZero template (no LLM):
    python3 stamp.py --type tool --id tax_tool --name TaxTool --role "TurboTax file parser" --port 5010
    python3 stamp.py --type tool --id browser_tool --name BrowserTool --role "Playwright web browser" --port 5011

Templates:
    BlackZero → GENESIS/BlackZero/   (LLM agent: ReAct loop, mission file, memory)
    ToolZero  → GENESIS/ToolZero/    (tool service: /execute endpoint, no LLM)

Note: If you improve the graph, tools, or core — update the template first, not a stamped agent.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

AGENT_TEMPLATE_DIR = Path(__file__).parent / "GENESIS" / "BlackZero"
TOOL_TEMPLATE_DIR  = Path(__file__).parent / "GENESIS" / "ToolZero"
CMPTRBLK_DIR       = Path(__file__).parent


def stamp(
    agent_id: str,
    agent_name: str,
    agent_role: str,
    agent_type: str = "agent",   # "agent" or "tool"
    port: int = 5001,
    model: str | None = None,
    out_dir: Path | None = None,
) -> Path:
    is_tool = agent_type == "tool"
    template_dir = TOOL_TEMPLATE_DIR if is_tool else AGENT_TEMPLATE_DIR
    default_port = 5099 if is_tool else 5001

    dest = out_dir or (CMPTRBLK_DIR / agent_name)

    if dest.exists():
        print(f"✗  Destination already exists: {dest}")
        print(f"   Remove it first or choose a different name.")
        sys.exit(1)

    if not template_dir.exists():
        print(f"✗  Template not found: {template_dir}")
        sys.exit(1)

    tag = "tool-agent" if is_tool else "LLM agent"
    print(f"\n{'━'*50}")
    print(f"  Stamping: {agent_name}  (id={agent_id})  [{tag}]")
    print(f"  Role:     {agent_role}")
    print(f"  Port:     {port}")
    print(f"  Template: {template_dir.name}")
    print(f"  Dest:     {dest}")
    print(f"{'━'*50}\n")

    # 1. Copy template
    steps = 4 if is_tool else 5
    print(f"  [1/{steps}] Copying template...")
    shutil.copytree(template_dir, dest, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".git", "*.db", "*.log",
        "*.egg-info", "dist", "build", ".venv", "venv",
    ))

    # 2. Update config.yaml
    print(f"  [2/{steps}] Writing config.yaml...")
    cfg_path = dest / "config.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    cfg["identity"]["designation"] = agent_name
    cfg["identity"]["alias"]       = agent_id
    cfg["identity"]["role"]        = agent_role
    cfg["port"]                    = port

    if not is_tool:
        cfg["data_dir"] = f"~/.{agent_id}"
        resolved_model = model or f"{agent_id}:latest"
        if "models" not in cfg:
            cfg["models"] = {}
        cfg["models"]["chat"]      = resolved_model
        cfg["models"]["reasoning"] = resolved_model
        cfg["models"]["fast"]      = resolved_model

    with open(cfg_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # 3. Patch port in entry point
    entry = "main_tool.py" if is_tool else "main_agent.py"
    print(f"  [3/{steps}] Patching port {port} in {entry}...")
    main_py = dest / entry
    if main_py.exists():
        text = main_py.read_text()
        text = text.replace("port=5099", f"port={port}").replace("port=5001", f"port={port}")
        main_py.write_text(text)

    # 4. Clear mission files (agent only)
    if not is_tool:
        print(f"  [4/{steps}] Clearing missions dir...")
        missions_dir = dest / "missions"
        if missions_dir.exists():
            for f in missions_dir.glob("*.txt"):
                f.unlink()

    # 5. Init fresh git
    print(f"  [{steps}/{steps}] Initializing git repo...")
    subprocess.run(["git", "init"], cwd=dest, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=dest, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"Initial stamp: {agent_name} ({tag})"],
        cwd=dest, check=True, capture_output=True
    )

    if is_tool:
        print(f"""
{'━'*50}
  ✅ {agent_name} (tool-agent) stamped at:
     {dest}

  Next steps:
  ─────────────────────────────────────────────
  1. Add your tools to:
       {dest}/agent/tools/registry.py

  2. Add git remote and push:
       cd {dest}
       git remote add origin https://github.com/MojoGlover/{agent_id}.git
       git push -u origin main

  3. Start:
       cd {dest}
       ./start.sh

  4. Verify:
       curl http://localhost:{port}/health
       python3 test_tool.py --port {port}
{'━'*50}
""")
    else:
        resolved_model = model or f"{agent_id}:latest"
        mission_name = f"{agent_id.upper()}.mission.txt"
        print(f"""
{'━'*50}
  ✅ {agent_name} (LLM agent) stamped at:
     {dest}

  Next steps:
  ─────────────────────────────────────────────
  1. Write the mission file:
       {dest}/missions/{mission_name}
     Or drop it in GENESIS/missions/{mission_name}

  2. Pull the Ollama model (if not already there):
       ollama pull {resolved_model}

  3. Add git remote and push:
       cd {dest}
       git remote add origin https://github.com/MojoGlover/{agent_id}.git
       git push -u origin main

  4. Start:
       cd {dest}
       ./start.sh

  5. Verify:
       curl http://localhost:{port}/health
       python3 test_agent.py
{'━'*50}
""")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stamp a new Computer Black agent or tool-agent."
    )
    parser.add_argument("--id",    required=True,  help="Agent ID (lowercase, underscores ok): tax_tool")
    parser.add_argument("--name",  required=True,  help="Agent display name: TaxTool")
    parser.add_argument("--role",  required=True,  help="Agent role description")
    parser.add_argument("--type",  default="agent", choices=["agent", "tool"],
                        help="agent = LLM ReAct agent (default); tool = lightweight tool service")
    parser.add_argument("--port",  type=int, default=None,
                        help="HTTP port (default: 5001 for agents, 5099 for tools)")
    parser.add_argument("--model", default=None,   help="Ollama model (LLM agents only, default: <id>:latest)")
    parser.add_argument("--out",   default=None,   help="Output directory (default: cmptrblk/<name>)")

    args = parser.parse_args()

    is_tool = args.type == "tool"
    port = args.port or (5099 if is_tool else 5001)
    out_dir = Path(args.out) if args.out else None

    stamp(
        agent_id   = args.id,
        agent_name = args.name,
        agent_role = args.role,
        agent_type = args.type,
        port       = port,
        model      = args.model,
        out_dir    = out_dir,
    )


if __name__ == "__main__":
    main()
