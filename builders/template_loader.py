"""
template_loader.py — Reads the BlackZero template and validates its completeness.

The template loader is the first thing the forger calls. It reads the
entire BlackZero directory structure, validates that all required files
and directories exist per genesis_rules.md, and returns a structured
manifest that the forger uses to scaffold new agents.

Usage:
    from builders.template_loader import TemplateLoader

    loader = TemplateLoader()
    template = loader.load()           # returns TemplateManifest
    loader.validate()                  # raises if incomplete
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

logger = logging.getLogger(__name__)

GENESIS_DIR = Path(__file__).resolve().parent.parent
BLACKZERO_DIR = GENESIS_DIR / "BlackZero"

# ── Required structure per genesis_rules.md ───────────────────────────────────

REQUIRED_DIRS = [
    "brain",
    "identity",
    "memory",
    "storage",
    "rag",
    "tools",
    "models",
    "policies",
    "diagnostics",
    "tests",
]

# Brain is locked to exactly these 4 files
BRAIN_FILES = ["loop.py", "planner.py", "executor.py", "router.py"]

# Required identity files
IDENTITY_FILES = ["mission.md", "personality.yaml"]

# Required memory files
MEMORY_FILES = ["memory_manager.py", "memory_schema.py"]

# Required storage files
STORAGE_FILES = ["sqlite_store.py", "vector_store.py"]

# Required RAG files
RAG_FILES = ["embedding_router.py", "indexer.py", "retriever.py"]

# Required tools files
TOOLS_FILES = ["base_tool.py", "tool_registry.py"]

# Required models files
MODELS_FILES = ["model_router.py", "provider_adapter.py"]

# Required diagnostics files
DIAGNOSTICS_FILES = ["doctor.py", "healthcheck.py"]

# Policy files (all .md files in policies/)
# These contain {AGENT_NAME} placeholders

# Loader.py itself (framework boot sequence)
FRAMEWORK_FILES = ["loader.py"]


@dataclass
class TemplateFile:
    """A file in the BlackZero template."""
    relative_path: str       # e.g. "brain/loop.py"
    absolute_path: Path
    content: str = ""
    has_placeholder: bool = False  # Contains {AGENT_NAME}

    def load_content(self) -> str:
        self.content = self.absolute_path.read_text(encoding="utf-8")
        self.has_placeholder = "{AGENT_NAME}" in self.content
        return self.content


@dataclass
class TemplateManifest:
    """Complete manifest of the BlackZero template."""
    root: Path
    directories: List[str] = field(default_factory=list)
    files: Dict[str, TemplateFile] = field(default_factory=dict)
    policy_files: List[str] = field(default_factory=list)
    test_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    valid: bool = False

    def get_dir_files(self, directory: str) -> List[TemplateFile]:
        """Get all files in a specific template directory."""
        prefix = f"{directory}/"
        return [f for k, f in self.files.items() if k.startswith(prefix)]


class TemplateLoader:
    """
    Reads and validates the BlackZero template.

    The loader scans the entire BlackZero directory, verifies structural
    integrity per genesis_rules.md, and produces a TemplateManifest that
    the forger uses to scaffold new agents.
    """

    def __init__(self, blackzero_dir: Path = BLACKZERO_DIR):
        self._root = blackzero_dir

    def load(self) -> TemplateManifest:
        """Load the full BlackZero template into a manifest."""
        manifest = TemplateManifest(root=self._root)

        if not self._root.exists():
            manifest.errors.append(f"BlackZero directory not found: {self._root}")
            return manifest

        # Scan directories
        for d in REQUIRED_DIRS:
            dir_path = self._root / d
            if dir_path.exists() and dir_path.is_dir():
                manifest.directories.append(d)
            else:
                manifest.errors.append(f"Missing required directory: {d}/")

        # Scan and load all Python and Markdown files
        for dir_name in REQUIRED_DIRS:
            dir_path = self._root / dir_name
            if not dir_path.exists():
                continue
            for file_path in sorted(dir_path.rglob("*")):
                if file_path.is_file() and not file_path.name.startswith("."):
                    if file_path.suffix in (".py", ".md", ".yaml", ".yml", ".json"):
                        rel = str(file_path.relative_to(self._root))
                        tf = TemplateFile(
                            relative_path=rel,
                            absolute_path=file_path,
                        )
                        tf.load_content()
                        manifest.files[rel] = tf

                        # Track policy and test files separately
                        if rel.startswith("policies/") and file_path.suffix == ".md":
                            manifest.policy_files.append(rel)
                        elif rel.startswith("tests/"):
                            manifest.test_files.append(rel)

        # Load framework files (loader.py at BlackZero root)
        for fname in FRAMEWORK_FILES:
            fpath = self._root / fname
            if fpath.exists():
                rel = fname
                tf = TemplateFile(relative_path=rel, absolute_path=fpath)
                tf.load_content()
                manifest.files[rel] = tf

        return manifest

    def validate(self) -> TemplateManifest:
        """Load and validate the template. Raises ValueError if invalid."""
        manifest = self.load()
        errors = list(manifest.errors)  # Start with any load errors

        # Validate brain lock: exactly 4 files, correct names
        brain_dir = self._root / "brain"
        if brain_dir.exists():
            brain_contents = [f.name for f in brain_dir.iterdir()
                              if f.is_file() and not f.name.startswith("__")]
            expected = set(BRAIN_FILES)
            actual = set(brain_contents)

            missing = expected - actual
            extra = actual - expected
            if missing:
                errors.append(f"Brain missing files: {missing}")
            if extra:
                errors.append(f"Brain has extra files (violation): {extra}")
        else:
            errors.append("brain/ directory missing entirely")

        # Validate required files in each directory
        checks = [
            ("identity", IDENTITY_FILES),
            ("memory", MEMORY_FILES),
            ("storage", STORAGE_FILES),
            ("rag", RAG_FILES),
            ("tools", TOOLS_FILES),
            ("models", MODELS_FILES),
            ("diagnostics", DIAGNOSTICS_FILES),
        ]
        for dir_name, required_files in checks:
            for fname in required_files:
                key = f"{dir_name}/{fname}"
                if key not in manifest.files:
                    errors.append(f"Missing required file: {key}")

        # Validate policies have at least safety.md
        if "policies/safety.md" not in manifest.files:
            errors.append("Missing required policy: policies/safety.md")

        # Validate tests have at least brain_tests.py and structure_tests.py
        for test_file in ["tests/brain_tests.py", "tests/structure_tests.py"]:
            if test_file not in manifest.files:
                errors.append(f"Missing required test: {test_file}")

        manifest.errors = errors
        manifest.valid = len(errors) == 0

        if not manifest.valid:
            logger.error(f"Template validation failed with {len(errors)} errors:")
            for e in errors:
                logger.error(f"  - {e}")
        else:
            file_count = len(manifest.files)
            dir_count = len(manifest.directories)
            logger.info(
                f"Template valid: {dir_count} dirs, {file_count} files, "
                f"{len(manifest.policy_files)} policies, {len(manifest.test_files)} tests"
            )

        return manifest

    def get_copyable_dirs(self) -> List[str]:
        """
        Return the list of directories that should be copied verbatim
        when forging a new agent.
        """
        return [
            "brain",        # Locked — copy verbatim, never modify
            "memory",
            "storage",
            "rag",
            "tools",
            "models",
            "diagnostics",
            "tests",
        ]

    def get_generated_dirs(self) -> List[str]:
        """
        Return directories where the forger generates content
        (not copied from template).
        """
        return [
            "identity",     # Generated from AgentSpec
            "policies",     # Copied + placeholder replacement
            "modules",      # Wired based on spec.modules_required
        ]
