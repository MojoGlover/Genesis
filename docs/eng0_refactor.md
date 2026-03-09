# eng0 refactor from Genesis outline

Because `engineer0/eng0` is not part of this repository, use the helper script below against that target repository path.

## Command

```bash
./scripts/refactor_eng0_from_genesis_template.sh /path/to/engineer0/eng0
```

## What it does

1. Deletes all repository contents except `.git`.
2. Recreates a Genesis-style top-level outline.
3. Seeds starter files: `.gitignore`, `README.md`, `requirements.txt`, `config.yaml`, and `main.py`.
