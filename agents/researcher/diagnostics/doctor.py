# doctor.py
# THE REPOSITORY HEALTH ENFORCER
#
# Responsibility:
#   Validates that the Genesis repository and BlackZero structure conform
#   to the rules defined in docs/genesis_rules.md.
#   This file is MANDATORY and must never be removed.
#
# Required checks (must all pass for repo to be considered organized):
#   1. Root structure validity
#      - Only approved root entries exist
#      - No stray files or folders at the root level
#
#   2. BlackZero presence
#      - BlackZero/ folder exists
#      - All required BlackZero subfolders exist:
#        brain/ identity/ memory/ storage/ rag/ tools/ models/ policies/ diagnostics/ tests/
#
#   3. Brain exact-file rule
#      - brain/ contains EXACTLY four files: loop.py, planner.py, executor.py, router.py
#      - No additional files, no subdirectories
#
#   4. Required folder existence
#      - modules/ agents/ builders/ evals/ datasets/ scripts/ configs/ docs/ docker/ pending/
#        all exist at the root
#
#   5. pending/ existence
#      - pending/ folder must always be present
#
# Output:
#   - PASS: print a green confirmation and exit 0
#   - FAIL: print each violation clearly and exit 1
#
# Usage:
#   python BlackZero/diagnostics/doctor.py

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

REQUIRED_ROOT_ENTRIES = {
    "BlackZero", "modules", "agents", "builders", "evals",
    "datasets", "scripts", "configs", "docs", "docker",
    "pending", "README.md", ".git", ".gitignore"
}

# Gitignored runtime artifacts — present locally but never committed.
# Doctor tolerates these so it does not fight the development environment.
TOLERATED_ROOT_ENTRIES = {
    ".env", ".DS_Store", "__pycache__", ".pytest_cache",
    ".gradio", ".history", ".spawn_logs",
    "brain_trainer",  # recreated by macOS LaunchAgent on every boot — gitignored
}

# Prefixes of gitignored runtime files (startswith check).
TOLERATED_ROOT_PREFIXES = (
    ".aider", ".claude", ".autonomous_state", ".engineer0_memory",
    ".location", ".session_heartbeat", ".session_state", ".spawn",
    ".engSS",
)

REQUIRED_BLACKZERO_FOLDERS = {
    "brain", "identity", "memory", "storage", "rag",
    "tools", "models", "policies", "diagnostics", "tests"
}

REQUIRED_BRAIN_FILES = {"loop.py", "planner.py", "executor.py", "router.py"}

violations = []


def check_root_structure():
    entries = set(os.listdir(REPO_ROOT))
    unexpected = entries - REQUIRED_ROOT_ENTRIES - TOLERATED_ROOT_ENTRIES
    for item in sorted(unexpected):
        if any(item.startswith(p) for p in TOLERATED_ROOT_PREFIXES):
            continue
        violations.append(f"ROOT: unexpected entry '{item}' (should be in pending/ or removed)")


def check_blackzero_presence():
    bz_path = os.path.join(REPO_ROOT, "BlackZero")
    if not os.path.isdir(bz_path):
        violations.append("BLACKZERO: BlackZero/ folder does not exist")
        return
    existing = set(os.listdir(bz_path))
    for folder in REQUIRED_BLACKZERO_FOLDERS:
        if folder not in existing:
            violations.append(f"BLACKZERO: missing required subfolder '{folder}'")


def check_brain_files():
    brain_path = os.path.join(REPO_ROOT, "BlackZero", "brain")
    if not os.path.isdir(brain_path):
        violations.append("BRAIN: brain/ does not exist")
        return
    contents = set(os.listdir(brain_path))
    missing = REQUIRED_BRAIN_FILES - contents
    extra = contents - REQUIRED_BRAIN_FILES - {"__pycache__"}
    for f in sorted(missing):
        violations.append(f"BRAIN: missing required file '{f}'")
    for f in sorted(extra):
        violations.append(f"BRAIN: unexpected file '{f}' (brain is locked to 4 files)")


def check_required_folders():
    required = REQUIRED_ROOT_ENTRIES - {"README.md", ".git", ".gitignore", "BlackZero"}
    for folder in sorted(required):
        path = os.path.join(REPO_ROOT, folder)
        if not os.path.exists(path):
            violations.append(f"STRUCTURE: required folder '{folder}/' does not exist")


def check_pending():
    pending_path = os.path.join(REPO_ROOT, "pending")
    if not os.path.isdir(pending_path):
        violations.append("PENDING: pending/ folder does not exist")


if __name__ == "__main__":
    check_root_structure()
    check_blackzero_presence()
    check_brain_files()
    check_required_folders()
    check_pending()

    if violations:
        print("\nDOCTOR: FAIL\n")
        for v in violations:
            print(f"  [X] {v}")
        print()
        sys.exit(1)
    else:
        print("\nDOCTOR: PASS — repository structure is healthy.\n")
        sys.exit(0)
