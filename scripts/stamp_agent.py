#!/usr/bin/env python3
"""
Stamp a new agent from the BlackZero template.

Creates a COMPLETE, self-contained agent scaffold — brain, loader, tools,
models, policies, identity, conversation, memory, rag, storage, diagnostics,
voice, tests, and modules directory.

The resulting agent has ZERO runtime imports from GENESIS or BlackZero.
This is a hard rule (see Botico governance: brain_ownership.md).

Usage:
    python scripts/stamp_agent.py --name Cerberus --out ~/ai/Cerberus
    python scripts/stamp_agent.py --name Teacher  --out ~/ai/Teacher --overwrite

After stamping:
    1. Write identity/mission.md — the agent's fixed purpose
    2. Write identity/personality.yaml — tone, traits, boundaries
    3. Edit policies/permissions.md — add role-specific Section 5
    4. Create modules/ subdirectories with concrete providers
    5. Write config.yaml with agent-specific settings
    6. Run: python -m pytest tests/structure_tests.py
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

GENESIS_DIR = Path(__file__).resolve().parent.parent
BLACKZERO_DIR = GENESIS_DIR / "BlackZero"
PLACEHOLDER = "{AGENT_NAME}"

# Directories to copy verbatim (files inside get placeholder replacement)
COPY_DIRS = [
    "brain",
    "conversation",
    "diagnostics",
    "identity",
    "memory",
    "models",
    "policies",
    "rag",
    "storage",
    "tools",
]

# Files to copy from BlackZero root
COPY_ROOT_FILES = [
    "loader.py",
]

# Directories to create (empty, with .gitkeep or __init__.py)
CREATE_DIRS = [
    "modules",
    "voice",
    "tests",
    "wargames/scenarios",
    "wargames/playbooks",
    "wargames/results",
    "wargames/baselines",
]

# Extensions that get placeholder replacement
TEXT_EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".json", ".txt"}


def _replace_placeholders(content: str, agent_name: str) -> str:
    """Replace {AGENT_NAME} and derived placeholders."""
    content = content.replace(PLACEHOLDER, agent_name)
    content = content.replace("{AGENT_NAME_LOWER}", agent_name.lower())
    return content


def _rewrite_blackzero_imports(content: str) -> str:
    """Rewrite any BlackZero.X imports to local X imports in .py files."""
    # from BlackZero.brain.loop -> from brain.loop
    content = re.sub(r"from BlackZero\.(\w+)", r"from \1", content)
    # import BlackZero.brain.loop -> import brain.loop
    content = re.sub(r"import BlackZero\.(\w+)", r"import \1", content)
    return content


def _rewrite_loader(content: str, agent_name: str) -> str:
    """Rewrite BlackZero loader.py imports to be local."""
    agent_lower = agent_name.lower()

    # Rewrite docstring
    content = re.sub(
        r'""".*?"""',
        f'"""\nloader.py \u2014 {agent_name}\'s Module Loader\n\n'
        f'Stamped from BlackZero at creation. This file belongs to {agent_name}.\n'
        f'It references only {agent_name}\'s own brain files.\n\n'
        f'Boot sequence: config \u2192 discover \u2192 setup() \u2192 wire \u2192 CognitiveLoop\n\n'
        f'Every agent calls:\n'
        f'    from loader import boot\n'
        f'    loop = boot("config.yaml", "modules/")\n'
        f'    loop.run()\n\n'
        f'Module contract:\n'
        f'    Each module is a subdirectory in modules/ containing a module.py that exports:\n'
        f'        def setup(config: dict) -> dict\n'
        f'    The returned dict maps slot names to implementations.\n'
        f'"""',
        content,
        count=1,
        flags=re.DOTALL,
    )

    # Rewrite imports: BlackZero.brain.X -> brain.X, BlackZero.tools.X -> tools.X
    content = re.sub(r"from BlackZero\.brain\.", "from brain.", content)
    content = re.sub(r"from BlackZero\.tools\.", "from tools.", content)
    content = re.sub(r"from BlackZero\.", "from ", content)

    # Rewrite data_dir default
    content = content.replace('data_dir", "~/.blackzero"', f'data_dir", "~/.{agent_lower}"')

    return content


def _generate_main_py(agent_name: str) -> str:
    """Generate a stub main.py for the new agent."""
    agent_lower = agent_name.lower()
    return f'''#!/usr/bin/env python3
"""{agent_name} main entry point."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# {agent_name}'s own directory must be on sys.path for local imports to resolve
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loader import boot
from config_loader import {agent_name}Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [{agent_name}] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="{agent_name} agent")
    parser.add_argument("--once", nargs="+", help="Run one cognitive cycle with the supplied prompt.")
    args = parser.parse_args()

    repo_root = Path(__file__).parent
    config = {agent_name}Config(repo_root / "config.yaml")

    config_path = str(repo_root / "config.yaml")
    modules_dir = str(repo_root / "modules")

    loop = boot(config_path, modules_dir)

    # --once mode: single cycle and exit
    if args.once:
        prompt = " ".join(args.once)
        result = loop.run_once(prompt)
        print(f"\\n[cycle {{result[\'cycle_id\']}}] {{result[\'outcome\']}} "
              f"(score={{result[\'score\']:.2f}}, {{result[\'duration_ms\']:.0f}}ms)")
        return

    # Interactive mode
    print(f"\\n{agent_name} online. Type to interact. Ctrl+C to stop.\\n")
    loop.run()


if __name__ == "__main__":
    main()
'''


def _generate_config_loader(agent_name: str) -> str:
    """Generate a config_loader.py for the new agent."""
    agent_lower = agent_name.lower()
    return f'''"""
config_loader.py \u2014 {agent_name} Configuration

Loads config.yaml and provides typed access to settings.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class {agent_name}Config:
    """Typed wrapper around config.yaml."""

    def __init__(self, config_path: str | Path):
        config_path = Path(config_path)
        if config_path.exists():
            with open(config_path) as f:
                self._raw = yaml.safe_load(f) or {{}}
        else:
            self._raw = {{}}

    @property
    def identity(self) -> dict:
        return self._raw.get("identity", {{}})

    @property
    def name(self) -> str:
        return self.identity.get("designation", "{agent_name}")

    @property
    def alias(self) -> str:
        return self.identity.get("alias", "{agent_name}")

    @property
    def models(self) -> dict:
        return self._raw.get("models", {{}})

    @property
    def tools(self) -> dict:
        return self._raw.get("tools", {{}})

    @property
    def modules(self) -> dict:
        return self._raw.get("modules", {{}})

    @property
    def data_dir(self) -> Path:
        return Path(self._raw.get("data_dir", "~/.{agent_lower}")).expanduser()

    def get(self, key: str, default: Any = None) -> Any:
        return self._raw.get(key, default)

    def get_module_config(self, module_name: str) -> dict:
        return self.modules.get(module_name, {{}})
'''


def _generate_config_yaml(agent_name: str) -> str:
    """Generate a skeleton config.yaml."""
    agent_lower = agent_name.lower()
    return f"""identity:
  designation: "{agent_name}"
  alias: "{agent_name}"
  role: "agent"
  pronouns: "they/them"
  owner: "Computer Black"

data_dir: "~/.{agent_lower}"

tools:
  ollama_api: "http://localhost:11434/api"

models:
  reasoning: "{agent_lower}:latest"
  fast: "{agent_lower}:latest"
  chat: "{agent_lower}:latest"
  code: "qwen2.5-coder:3b"

loop:
  check_interval_seconds: 10
  max_concurrent_tasks: 2
  task_timeout_seconds: 300

modules:
  ollama_provider:
    timeout: 60
  console_io: {{}}
"""


def _generate_structure_tests(agent_name: str) -> str:
    """Generate structure validation tests."""
    return f'''"""
Structure validation tests for {agent_name}.

Ensures the agent scaffold is correct and has zero GENESIS imports.
"""
import re
import unittest
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent


class TestAgentStructure(unittest.TestCase):
    """Validate {agent_name} directory structure."""

    REQUIRED_DIRS = [
        "brain", "tools", "models", "policies", "identity",
        "conversation", "memory", "rag", "storage", "diagnostics",
        "modules", "voice",
    ]

    BRAIN_FILES = {{"loop.py", "planner.py", "executor.py", "router.py"}}

    REQUIRED_POLICIES = [
        "governance.md", "safety.md", "permissions.md",
        "escalation_protocol.md",
    ]

    def test_required_folders_exist(self):
        for d in self.REQUIRED_DIRS:
            self.assertTrue(
                (AGENT_ROOT / d).is_dir(),
                f"Missing required directory: {{d}}/",
            )

    def test_brain_files_locked(self):
        brain_dir = AGENT_ROOT / "brain"
        actual = {{f.name for f in brain_dir.glob("*.py")}}
        self.assertEqual(actual, self.BRAIN_FILES,
                         f"Brain must contain exactly {{self.BRAIN_FILES}}, got {{actual}}")

    def test_no_genesis_imports(self):
        violations = []
        for py_file in AGENT_ROOT.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            content = py_file.read_text(errors="replace")
            for pattern in [r"from BlackZero\\b", r"from GENESIS\\b",
                            r"import BlackZero\\b", r"import GENESIS\\b"]:
                if re.search(pattern, content):
                    violations.append(f"{{py_file.relative_to(AGENT_ROOT)}}: matches {{pattern}}")
        self.assertEqual(violations, [],
                         f"GENESIS/BlackZero imports found:\\n" + "\\n".join(violations))

    def test_identity_files_exist(self):
        self.assertTrue((AGENT_ROOT / "identity" / "mission.md").exists())
        self.assertTrue((AGENT_ROOT / "identity" / "personality.yaml").exists())

    def test_policies_complete(self):
        for p in self.REQUIRED_POLICIES:
            self.assertTrue(
                (AGENT_ROOT / "policies" / p).exists(),
                f"Missing policy: {{p}}",
            )

    def test_loader_stamped(self):
        loader = AGENT_ROOT / "loader.py"
        self.assertTrue(loader.exists(), "loader.py missing")
        content = loader.read_text()
        self.assertIn("Stamped from BlackZero", content,
                       "loader.py missing stamp header")
        self.assertIn("{agent_name}", content,
                       "loader.py not stamped for {agent_name}")


if __name__ == "__main__":
    unittest.main()
'''


def stamp_agent(agent_name: str, out_dir: Path, overwrite: bool = False) -> None:
    """Create a full agent scaffold from the BlackZero template."""

    if not BLACKZERO_DIR.exists():
        print(f"ERROR: BlackZero template not found: {BLACKZERO_DIR}", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nStamping BlackZero \u2192 {agent_name}")
    print(f"Output: {out_dir}\n")

    created = 0
    skipped = 0

    # --- Copy directories ---
    for dirname in COPY_DIRS:
        src_dir = BLACKZERO_DIR / dirname
        dst_dir = out_dir / dirname
        if not src_dir.exists():
            print(f"  WARN   {dirname}/ not found in template, skipping")
            continue

        dst_dir.mkdir(parents=True, exist_ok=True)

        for src_file in sorted(src_dir.rglob("*")):
            if not src_file.is_file():
                continue
            if "__pycache__" in str(src_file) or src_file.name == ".DS_Store":
                continue

            rel = src_file.relative_to(src_dir)
            dst_file = dst_dir / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            if dst_file.exists() and not overwrite:
                skipped += 1
                continue

            if src_file.suffix in TEXT_EXTENSIONS:
                content = src_file.read_text(encoding="utf-8")
                content = _replace_placeholders(content, agent_name)
                if src_file.suffix == ".py":
                    content = _rewrite_blackzero_imports(content)
                dst_file.write_text(content, encoding="utf-8")
            else:
                shutil.copy2(src_file, dst_file)
            created += 1
            print(f"  COPY   {dirname}/{rel}")

    # --- Copy and rewrite loader.py ---
    loader_src = BLACKZERO_DIR / "loader.py"
    loader_dst = out_dir / "loader.py"
    if loader_dst.exists() and not overwrite:
        print(f"  SKIP   loader.py (exists)")
        skipped += 1
    else:
        content = loader_src.read_text(encoding="utf-8")
        content = _rewrite_loader(content, agent_name)
        content = _replace_placeholders(content, agent_name)
        loader_dst.write_text(content, encoding="utf-8")
        created += 1
        print(f"  CREATE loader.py (rewritten for {agent_name})")

    # --- Generate main.py ---
    main_dst = out_dir / "main.py"
    if main_dst.exists() and not overwrite:
        print(f"  SKIP   main.py (exists)")
        skipped += 1
    else:
        main_dst.write_text(_generate_main_py(agent_name), encoding="utf-8")
        created += 1
        print(f"  CREATE main.py")

    # --- Generate config_loader.py ---
    cl_dst = out_dir / "config_loader.py"
    if cl_dst.exists() and not overwrite:
        print(f"  SKIP   config_loader.py (exists)")
        skipped += 1
    else:
        cl_dst.write_text(_generate_config_loader(agent_name), encoding="utf-8")
        created += 1
        print(f"  CREATE config_loader.py")

    # --- Generate config.yaml ---
    cfg_dst = out_dir / "config.yaml"
    if cfg_dst.exists() and not overwrite:
        print(f"  SKIP   config.yaml (exists)")
        skipped += 1
    else:
        cfg_dst.write_text(_generate_config_yaml(agent_name), encoding="utf-8")
        created += 1
        print(f"  CREATE config.yaml")

    # --- Create empty directories ---
    for dirname in CREATE_DIRS:
        d = out_dir / dirname
        d.mkdir(parents=True, exist_ok=True)
        init = d / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")

    # --- Generate voice stub ---
    voice_profile = out_dir / "voice" / "profile.py"
    if not voice_profile.exists() or overwrite:
        voice_profile.write_text(
            f'"""\nvoice/profile.py \u2014 {agent_name}\'s voice profile.\n\n'
            f'Subclass VoiceProfile here to define {agent_name}\'s personality.\n"""\n'
            f'from __future__ import annotations\n\n'
            f'from conversation.voice_profile import VoiceProfile\n\n\n'
            f'class {agent_name}Voice(VoiceProfile):\n'
            f'    """Override with {agent_name}-specific personality."""\n\n'
            f'    def __init__(self) -> None:\n'
            f'        super().__init__(name="{agent_name}")\n\n\n'
            f'{agent_name.lower()}_voice = {agent_name}Voice()\n',
            encoding="utf-8",
        )
        created += 1
        print(f"  CREATE voice/profile.py")

    # --- Generate tests ---
    tests_init = out_dir / "tests" / "__init__.py"
    if not tests_init.exists():
        tests_init.write_text("", encoding="utf-8")
    struct_tests = out_dir / "tests" / "structure_tests.py"
    if not struct_tests.exists() or overwrite:
        struct_tests.write_text(_generate_structure_tests(agent_name), encoding="utf-8")
        created += 1
        print(f"  CREATE tests/structure_tests.py")

    # --- Summary ---
    print(f"\n  {created} files created, {skipped} skipped.")
    print(f"\nNext steps:")
    print(f"  1. Write identity/mission.md \u2014 {agent_name}'s fixed purpose")
    print(f"  2. Write identity/personality.yaml \u2014 tone, traits, boundaries")
    print(f"  3. Edit policies/permissions.md \u2014 add Section 5 for {agent_name}")
    print(f"  4. Create modules/ with concrete providers (ollama_provider, console_io, etc.)")
    print(f"  5. Customize config.yaml")
    print(f"  6. Run: python -m pytest tests/structure_tests.py -v\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stamp a full agent scaffold from the BlackZero template"
    )
    parser.add_argument("--name", required=True, help="Agent name (e.g. Cerberus, Teacher)")
    parser.add_argument("--out", required=True, help="Output directory for the agent")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    stamp_agent(
        agent_name=args.name,
        out_dir=Path(args.out).expanduser().resolve(),
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
