#!/usr/bin/env python3
"""
stamp_agent.py — Stamp a new agent from the BlackZero template.

Usage:
    python stamp_agent.py --name Engineer0 --out /path/to/Engineer0
    python stamp_agent.py --name Cerberus --alias Guardian --role "Security Sentinel" --out /path/to/Cerberus

Options:
    --name        Agent designation (required), e.g. "Engineer0"
    --out         Output directory (required)
    --alias       Short name / display name (default: same as --name)
    --role        One-line role description (default: "Agent")
    --pronouns    Pronouns (default: "they/them")
    --data-dir    Data directory override (default: ~/.{slug})
    --no-rag      Skip rag/ directory
    --no-docker   Skip Dockerfile and docker-compose.yml
    --no-tests    Skip tests/ directory
    --force       Overwrite an existing non-empty output directory
    --capabilities  Comma-separated capabilities for PlugOps registration
                    e.g. "code,debug,deploy"
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

GENESIS_DIR = Path(__file__).resolve().parent.parent
BLACKZERO_DIR = GENESIS_DIR / "BlackZero"

# Extensions treated as text (substitution applied)
TEXT_EXTENSIONS = {
    ".py", ".md", ".yaml", ".yml", ".txt", ".example",
    ".json", ".sh", ".toml", ".cfg", ".ini",
}

# Always-excluded patterns
SKIP_NAMES = {"__pycache__", ".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

# Directories always copied from BlackZero
ALWAYS_COPY_DIRS = [
    "brain",
    "memory",
    "models",
    "modules",
    "tools",
    "conversation",
    "policies",
    "security",
    "diagnostics",
    "storage",
]

# Individual files always copied from BlackZero root
ALWAYS_COPY_FILES = [
    "loader.py",
    "main.py",
    "config.yaml",
    "config_loader.py",
    "requirements.txt",
    ".env.example",
    ".gitignore",
]

# Identity templates (always copied)
IDENTITY_FILES = [
    "identity/mission.md",
    "identity/personality.yaml",
]

# Optional directories/files
OPTIONAL_RAG = "rag"
OPTIONAL_DOCKER_FILES = ["Dockerfile", "docker-compose.yml"]
OPTIONAL_TESTS_DIR = "tests"


# ---------------------------------------------------------------------------
# Template substitution
# ---------------------------------------------------------------------------

def _build_substitutions(
    name: str,
    alias: str,
    role: str,
    slug: str,
    pronouns: str,
) -> dict[str, str]:
    return {
        "{AGENT_NAME}": name,
        "{AGENT_ALIAS}": alias,
        "{AGENT_ROLE}": role,
        "{agent_slug}": slug,
        "{AGENT_PRONOUNS}": pronouns,
        # Legacy lower-case variant used in the older stamp
        "{AGENT_NAME_LOWER}": slug,
    }


def _apply_substitutions(content: str, subs: dict[str, str]) -> str:
    for token, replacement in subs.items():
        content = content.replace(token, replacement)
    return content


def _rewrite_blackzero_imports(content: str) -> str:
    """Rewrite BlackZero-prefixed imports to local imports."""
    content = re.sub(r"from BlackZero\.", "from ", content)
    content = re.sub(r"import BlackZero\.", "import ", content)
    return content


def _rewrite_main_py(content: str) -> str:
    """
    Replace the dual sys.path / try-except import block with the single-path
    stamped form that has no fallback to BlackZero.

    Must be called BEFORE _rewrite_blackzero_imports so the original text
    is still present. Uses a regex to tolerate minor whitespace variation.
    """
    # Match the dual sys.path block + try/except regardless of trailing comments
    content = re.sub(
        r"_here = Path\(__file__\)\.resolve\(\)\.parent\n"
        r"sys\.path\.insert\(0, str\(_here\)\)[^\n]*\n"
        r"sys\.path\.insert\(0, str\(_here\.parent\)\)[^\n]*\n"
        r"\n"
        r"try:\n"
        r"    from loader import boot[^\n]*\n"
        r"except ImportError:\n"
        r"    from BlackZero\.loader import boot[^\n]*",
        "_here = Path(__file__).resolve().parent\n"
        "sys.path.insert(0, str(_here))\n"
        "\n"
        "from loader import boot",
        content,
    )
    return content


def _rename_agent_config_class(content: str, name: str) -> str:
    """
    Rename AgentConfig → {NAME}Config in class definitions and import lines only.
    Avoids clobbering docstring mentions that already contain the agent name
    (e.g. 'Rename class to TestAgentConfig' would become 'TestTestAgentConfig').
    """
    # class definition line: "class AgentConfig:"
    content = re.sub(r"\bclass AgentConfig\b", f"class {name}Config", content)
    # import statement: "from config_loader import AgentConfig"
    content = re.sub(r"\bimport AgentConfig\b", f"import {name}Config", content)
    # variable instantiation: "cfg = AgentConfig("
    content = re.sub(r"\bAgentConfig\(", f"{name}Config(", content)
    return content


def _rewrite_loader_docstring(content: str, name: str) -> str:
    """
    Replace the stamp ownership line in the loader docstring.
    Handles both the BlackZero original and any previously-stamped form.
    """
    content = re.sub(
        r"Stamped from BlackZero at creation\. This file belongs to \S+\.",
        f"Stamped from BlackZero at creation. This file belongs to {name}.",
        content,
    )
    return content


def _rewrite_docker_compose(content: str, slug: str) -> str:
    """Replace generic service/container names with the agent slug."""
    content = re.sub(r"\bservice:\s+agent\b", f"service: {slug}", content)
    # service name key (indented line like "  agent:")
    content = re.sub(r"^(\s+)agent(\s*:)", rf"\1{slug}\2", content, flags=re.MULTILINE)
    content = re.sub(r"\bcontainer_name:\s+agent\b", f"container_name: {slug}", content)
    return content


def _inject_capabilities(content: str, capabilities: list[str]) -> str:
    """
    Replace 'capabilities: []' in the plugops_bridge section with the
    actual capabilities list.
    """
    if not capabilities:
        return content
    cap_yaml = "[" + ", ".join(f'"{c}"' for c in capabilities) + "]"
    content = re.sub(
        r"(plugops_bridge:.*?capabilities:\s*)\[\]",
        rf"\g<1>{cap_yaml}",
        content,
        flags=re.DOTALL,
    )
    return content


def _rewrite_data_dir(content: str, slug: str) -> str:
    """Rewrite the blackzero default data_dir to the agent's slug."""
    content = content.replace('data_dir", "~/.blackzero"', f'data_dir", "~/.{slug}"')
    return content


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _is_text_file(path: Path) -> bool:
    """Return True if the file should have text substitution applied."""
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    # Dockerfile has no extension
    if path.name == "Dockerfile":
        return True
    return False


def _should_skip(path: Path) -> bool:
    """Return True if this file/directory should never be copied."""
    for part in path.parts:
        if part in SKIP_NAMES:
            return True
    if path.suffix in SKIP_SUFFIXES:
        return True
    if path.name == ".env":
        return True
    return False


def _copy_file(
    src: Path,
    dst: Path,
    subs: dict[str, str],
    name: str,
    slug: str,
    capabilities: list[str],
    extra_transforms: list[str],  # which special rewrites to apply
) -> None:
    """Copy a single file, applying text transformations as needed."""
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not _is_text_file(src):
        shutil.copy2(src, dst)
        return

    try:
        content = src.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        # Binary file masquerading with a text extension — copy verbatim
        shutil.copy2(src, dst)
        return

    # 1. main.py sys.path rewrite MUST happen before import rewriting
    #    so the original "from BlackZero.loader import boot" text is still present.
    if "rewrite_main" in extra_transforms:
        content = _rewrite_main_py(content)

    # 2. Template variable substitution
    content = _apply_substitutions(content, subs)

    # 3. Python-specific import rewriting (after sys.path block is already fixed)
    if src.suffix == ".py":
        content = _rewrite_blackzero_imports(content)

    # 4. File-specific rewrites
    if "rewrite_main" in extra_transforms:
        content = _rename_agent_config_class(content, name)

    if "rewrite_config_loader" in extra_transforms:
        content = _rename_agent_config_class(content, name)

    if "rewrite_loader" in extra_transforms:
        content = _rewrite_loader_docstring(content, name)
        content = _rewrite_data_dir(content, slug)

    if "rewrite_docker_compose" in extra_transforms:
        content = _rewrite_docker_compose(content, slug)

    if "inject_capabilities" in extra_transforms:
        content = _inject_capabilities(content, capabilities)

    dst.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Directory walk helpers
# ---------------------------------------------------------------------------

def _copy_dir(
    src_dir: Path,
    dst_dir: Path,
    subs: dict[str, str],
    name: str,
    slug: str,
    capabilities: list[str],
    extra_map: dict[str, list[str]],  # filename -> extra_transforms
) -> list[Path]:
    """Recursively copy src_dir to dst_dir. Returns list of files created."""
    if not src_dir.exists():
        return []

    created = []
    for src_file in sorted(src_dir.rglob("*")):
        if not src_file.is_file():
            continue
        if _should_skip(src_file):
            continue

        rel = src_file.relative_to(src_dir)
        dst_file = dst_dir / rel

        transforms = extra_map.get(src_file.name, [])
        _copy_file(src_file, dst_file, subs, name, slug, capabilities, transforms)
        created.append(dst_file)

    return created


# ---------------------------------------------------------------------------
# Main stamp logic
# ---------------------------------------------------------------------------

def stamp_agent(
    name: str,
    out: Path,
    alias: str,
    role: str,
    pronouns: str,
    data_dir_override: str | None,
    no_rag: bool,
    no_docker: bool,
    no_tests: bool,
    capabilities: list[str],
    force: bool,
) -> None:

    if not BLACKZERO_DIR.exists():
        print(f"ERROR: BlackZero template not found: {BLACKZERO_DIR}", file=sys.stderr)
        sys.exit(1)

    # Derived values
    slug = name.lower().replace(" ", "").replace("-", "")
    data_dir = data_dir_override or f"~/.{slug}"

    # Guard against stomping an existing non-empty directory
    if out.exists() and any(out.iterdir()) and not force:
        print(
            f"ERROR: Output directory is non-empty: {out}\n"
            f"       Pass --force to overwrite.",
            file=sys.stderr,
        )
        sys.exit(1)

    out.mkdir(parents=True, exist_ok=True)

    subs = _build_substitutions(name, alias, role, slug, pronouns)
    # Also substitute the data_dir token if it appears literally
    subs["~/.{agent_slug}"] = data_dir

    file_count = 0

    print(f"\nStamping BlackZero -> {name}")
    print(f"  alias={alias}  role={role}  slug={slug}")
    print(f"  output={out}\n")

    # ------------------------------------------------------------------
    # 1. Copy always-copied directories
    # ------------------------------------------------------------------
    for dirname in ALWAYS_COPY_DIRS:
        src_dir = BLACKZERO_DIR / dirname
        if not src_dir.exists():
            print(f"  WARN   {dirname}/ not found in BlackZero, skipping")
            continue
        dst_dir = out / dirname
        created = _copy_dir(src_dir, dst_dir, subs, name, slug, capabilities, {})
        for f in created:
            print(f"  COPY   {f.relative_to(out)}")
        file_count += len(created)

    # ------------------------------------------------------------------
    # 2. Copy identity templates
    # ------------------------------------------------------------------
    for rel_str in IDENTITY_FILES:
        src_file = BLACKZERO_DIR / rel_str
        if not src_file.exists():
            print(f"  WARN   {rel_str} not found in BlackZero, skipping")
            continue
        dst_file = out / rel_str
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        _copy_file(src_file, dst_file, subs, name, slug, capabilities, [])
        print(f"  COPY   {rel_str}")
        file_count += 1

    # ------------------------------------------------------------------
    # 3. Copy root files with targeted rewrites
    # ------------------------------------------------------------------
    file_transforms: dict[str, list[str]] = {
        "main.py": ["rewrite_main"],
        "config_loader.py": ["rewrite_config_loader"],
        "loader.py": ["rewrite_loader"],
        "config.yaml": ["inject_capabilities"],
    }

    for filename in ALWAYS_COPY_FILES:
        src_file = BLACKZERO_DIR / filename
        if not src_file.exists():
            print(f"  WARN   {filename} not found in BlackZero, skipping")
            continue
        dst_file = out / filename
        transforms = file_transforms.get(filename, [])
        _copy_file(src_file, dst_file, subs, name, slug, capabilities, transforms)
        print(f"  COPY   {filename}")
        file_count += 1

    # ------------------------------------------------------------------
    # 4. Optional: rag/
    # ------------------------------------------------------------------
    if not no_rag:
        src_rag = BLACKZERO_DIR / OPTIONAL_RAG
        if src_rag.exists():
            created = _copy_dir(src_rag, out / OPTIONAL_RAG, subs, name, slug, capabilities, {})
            for f in created:
                print(f"  COPY   {f.relative_to(out)}")
            file_count += len(created)
        else:
            print(f"  WARN   rag/ not found in BlackZero, skipping")

    # ------------------------------------------------------------------
    # 5. Optional: Dockerfile + docker-compose.yml
    # ------------------------------------------------------------------
    if not no_docker:
        for filename in OPTIONAL_DOCKER_FILES:
            src_file = BLACKZERO_DIR / filename
            if not src_file.exists():
                print(f"  WARN   {filename} not found in BlackZero, skipping")
                continue
            transforms = ["rewrite_docker_compose"] if filename == "docker-compose.yml" else []
            dst_file = out / filename
            _copy_file(src_file, dst_file, subs, name, slug, capabilities, transforms)
            print(f"  COPY   {filename}")
            file_count += 1

    # ------------------------------------------------------------------
    # 6. Optional: tests/
    # ------------------------------------------------------------------
    if not no_tests:
        src_tests = BLACKZERO_DIR / OPTIONAL_TESTS_DIR
        if src_tests.exists():
            created = _copy_dir(
                src_tests, out / OPTIONAL_TESTS_DIR, subs, name, slug, capabilities, {}
            )
            for f in created:
                print(f"  COPY   {f.relative_to(out)}")
            file_count += len(created)
        else:
            print(f"  WARN   tests/ not found in BlackZero, skipping")

    # ------------------------------------------------------------------
    # 7. Make main.py executable
    # ------------------------------------------------------------------
    main_py = out / "main.py"
    if main_py.exists():
        main_py.chmod(main_py.stat().st_mode | 0o111)

    # ------------------------------------------------------------------
    # 8. Summary
    # ------------------------------------------------------------------
    rag_note = "" if not no_rag else ", rag disabled"
    cap_display = ", ".join(capabilities) if capabilities else "(none)"

    print(f"\n  Stamped {name} at {out}")
    print(f"  Files:    {file_count}")
    print(f"  Identity: {name} ({alias}) — {role}")
    print(f"  Data dir: {data_dir}")
    print(f"  Model:    {slug}:latest")
    print(f"  Modules:  console_io, memory, ollama_provider, plugops_bridge{rag_note}")
    print(f"  Caps:     {cap_display}")
    print()
    print("Next steps:")
    print(f"  1. Create your Modelfile and run: ollama create {slug} -f Modelfile")
    print(f"  2. Edit config.yaml to fill in any remaining details")
    print(f"  3. Copy .env.example to .env and add API keys (optional)")
    print(f"  4. python main.py")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stamp a new standalone agent from the BlackZero template.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--name", required=True,
                        help='Agent designation, e.g. "Engineer0"')
    parser.add_argument("--out", required=True,
                        help="Output directory path")
    parser.add_argument("--alias", default=None,
                        help="Short display name (default: same as --name)")
    parser.add_argument("--role", default="Agent",
                        help='One-line role description (default: "Agent")')
    parser.add_argument("--pronouns", default="they/them",
                        help='Pronouns (default: "they/them")')
    parser.add_argument("--data-dir", dest="data_dir", default=None,
                        help="Data directory override (default: ~/.{slug})")
    parser.add_argument("--no-rag", action="store_true",
                        help="Skip rag/ directory")
    parser.add_argument("--no-docker", action="store_true",
                        help="Skip Dockerfile and docker-compose.yml")
    parser.add_argument("--no-tests", action="store_true",
                        help="Skip tests/ directory")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing non-empty output directory")
    parser.add_argument("--capabilities", default=None,
                        help='Comma-separated capabilities, e.g. "code,debug,deploy"')
    args = parser.parse_args()

    capabilities = (
        [c.strip() for c in args.capabilities.split(",") if c.strip()]
        if args.capabilities
        else []
    )

    stamp_agent(
        name=args.name,
        out=Path(args.out).expanduser().resolve(),
        alias=args.alias or args.name,
        role=args.role,
        pronouns=args.pronouns,
        data_dir_override=args.data_dir,
        no_rag=args.no_rag,
        no_docker=args.no_docker,
        no_tests=args.no_tests,
        capabilities=capabilities,
        force=args.force,
    )


if __name__ == "__main__":
    main()
