#!/usr/bin/env python3
"""
Fork a new agent from the BlackZero template.

Copies all policy files from BlackZero/policies/ to the target directory,
replacing {AGENT_NAME} placeholder with the actual agent name.

Usage:
    python scripts/fork_agent.py --name Engineer0 --out /ai/Engineer0/policies
    python scripts/fork_agent.py --name Teacher   --out /ai/Teacher/policies
    python scripts/fork_agent.py --name Researcher --out /ai/Researcher/policies

After forking:
    - Edit <out>/permissions.md to add role-specific permissions
    - Edit <out>/governance.md if the agent has domain-specific scope rules
    - Commit both the fork output AND the template (so diffs are traceable)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

GENESIS_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = GENESIS_DIR / "BlackZero" / "policies"

PLACEHOLDER = "{AGENT_NAME}"


def fork_policies(agent_name: str, out_dir: Path, overwrite: bool = False) -> None:
    if not TEMPLATE_DIR.exists():
        print(f"ERROR: Template directory not found: {TEMPLATE_DIR}", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    policy_files = sorted(TEMPLATE_DIR.glob("*.md"))
    if not policy_files:
        print(f"ERROR: No .md files found in {TEMPLATE_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"\nForking BlackZero → {agent_name}")
    print(f"Output: {out_dir}\n")

    created = []
    skipped = []
    for src in policy_files:
        dest = out_dir / src.name
        if dest.exists() and not overwrite:
            skipped.append(src.name)
            print(f"  SKIP   {src.name}  (exists — use --overwrite to replace)")
            continue

        content = src.read_text(encoding="utf-8")
        content = content.replace(PLACEHOLDER, agent_name)

        # Verify all placeholders replaced
        if PLACEHOLDER in content:
            print(f"  WARN   {src.name}  — unreplaced placeholder remaining", file=sys.stderr)

        dest.write_text(content, encoding="utf-8")
        created.append(src.name)
        print(f"  CREATE {src.name}")

    print(f"\n  {len(created)} files created, {len(skipped)} skipped.")

    if created:
        print(f"\nNext steps:")
        print(f"  1. Edit {out_dir}/permissions.md — add {agent_name}-specific permissions")
        print(f"  2. Edit {out_dir}/governance.md  — add {agent_name} domain scope (if needed)")
        print(f"  3. Commit the new policies alongside the agent's Modelfile")
        print(f"  4. Run governance tests against the new agent's policy dir\n")


def verify_template_clean() -> bool:
    """Verify the template itself still has {AGENT_NAME} placeholders (sanity check)."""
    for f in TEMPLATE_DIR.glob("*.md"):
        if PLACEHOLDER in f.read_text():
            return True
    print("WARNING: BlackZero template has no {AGENT_NAME} placeholders — check template integrity",
          file=sys.stderr)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fork BlackZero policy template for a new agent"
    )
    parser.add_argument("--name", required=True, help="Agent name (e.g. Engineer0, Teacher)")
    parser.add_argument("--out", required=True, help="Output directory for policy files")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing files in output dir")
    parser.add_argument("--verify-template", action="store_true",
                        help="Just verify template has placeholders, then exit")
    args = parser.parse_args()

    if args.verify_template:
        ok = verify_template_clean()
        sys.exit(0 if ok else 1)

    fork_policies(
        agent_name=args.name,
        out_dir=Path(args.out).expanduser().resolve(),
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
