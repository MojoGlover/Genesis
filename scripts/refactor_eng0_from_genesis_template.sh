#!/usr/bin/env bash
set -euo pipefail

TARGET_REPO_PATH="${1:-/workspace/engineer0/eng0}"

if [[ ! -d "$TARGET_REPO_PATH" ]]; then
  echo "error: target path '$TARGET_REPO_PATH' does not exist" >&2
  exit 1
fi

if [[ ! -d "$TARGET_REPO_PATH/.git" ]]; then
  echo "error: '$TARGET_REPO_PATH' is not a git repository (missing .git directory)" >&2
  exit 1
fi

echo "[1/3] Cleaning repository contents (preserving .git)..."
find "$TARGET_REPO_PATH" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

echo "[2/3] Rebuilding repository with Genesis template outline..."
mkdir -p \
  "$TARGET_REPO_PATH/agents" \
  "$TARGET_REPO_PATH/api" \
  "$TARGET_REPO_PATH/brain_trainer" \
  "$TARGET_REPO_PATH/cb_core" \
  "$TARGET_REPO_PATH/config" \
  "$TARGET_REPO_PATH/core" \
  "$TARGET_REPO_PATH/scripts" \
  "$TARGET_REPO_PATH/static" \
  "$TARGET_REPO_PATH/tests" \
  "$TARGET_REPO_PATH/tools" \
  "$TARGET_REPO_PATH/ui"

cat > "$TARGET_REPO_PATH/.gitignore" <<'GITIGNORE'
# Python
__pycache__/
*.py[cod]
*.pyo
.venv/
venv/

# Env / secrets
.env

# Build artifacts
build/
dist/
*.egg-info/

# Logs and data
*.log
*.db

# OS/editor
.DS_Store
.vscode/
.idea/
GITIGNORE

cat > "$TARGET_REPO_PATH/README.md" <<'README'
# eng0

This repository was refactored using the Genesis project layout template.

## Top-level layout
- `agents/` - agent implementations and orchestration
- `api/` - service/API entry points
- `brain_trainer/` - model prep/training assets
- `cb_core/` - shared core package(s)
- `config/` - runtime configuration
- `core/` - application core logic
- `scripts/` - operational scripts and helpers
- `static/` - static assets
- `tests/` - automated tests
- `tools/` - custom tools/utilities
- `ui/` - frontend/UI components

## Quick start
1. Create a Python virtual environment.
2. Install dependencies from `requirements.txt`.
3. Start the main entrypoint once implemented.
README

cat > "$TARGET_REPO_PATH/requirements.txt" <<'REQ'
# Add project dependencies here
REQ

cat > "$TARGET_REPO_PATH/config.yaml" <<'YAML'
# Base configuration for eng0
app_name: eng0
environment: development
YAML

cat > "$TARGET_REPO_PATH/main.py" <<'PY'
"""Main entrypoint for eng0."""


def main() -> None:
    print("eng0 scaffold initialized")


if __name__ == "__main__":
    main()
PY

echo "[3/3] Done. Repository '$TARGET_REPO_PATH' now follows the Genesis template outline." 
