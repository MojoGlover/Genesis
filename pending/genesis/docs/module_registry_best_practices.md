# Module Registry Engineering Policy

## Core Principles

### Discovery ≠ Trust
A module being discoverable does not grant it any execution rights.
Discovery is a read-only scan. Enablement is a separate, explicit act.
A module found on disk but absent from the allowlist is inert — it is
not imported, not instantiated, not mounted.

### Manifest-Based Registration (`module.json`)
Every module must declare a `module.json` at its root before it can be
considered for registration. The registry reads only this file during
discovery — no Python is executed at this stage.

Required fields:
```json
{
  "name": "flex.package_audit",
  "version": "1.0.0",
  "description": "Single-sentence description.",
  "entry": "module.py",
  "permissions": ["read:packages"],
  "tags": ["audit", "flex"]
}
```

### Zero Side Effects on Import
Module code must not execute logic at import time.
Prohibited at module scope: network calls, filesystem writes, thread
spawning, registry mutations, print/logging output.
All initialization belongs in `on_startup()`.

### Deterministic Discovery Order
The registry scans `modules/` in lexicographic order by directory name.
Module load order is logged in the registry snapshot. Any run producing
a different order than the snapshot is flagged as non-reproducible.

### Allowlist Enablement
Modules are enabled only if their `name` and version constraint appear
in `policies/registry_allowlist.json`. The registry rejects any module
whose version does not satisfy the declared constraint (semver `^` rules).
The allowlist is the single source of trust — it is code-reviewed and
version-controlled.

### Lazy Imports
Module-level imports of heavy dependencies (ML models, DB drivers, large
SDKs) must be deferred to `on_startup()` or to the first call that
requires them. This keeps discovery fast and prevents import-time
failures from blocking unrelated modules.

### Pydantic I/O Validation
All HTTP request bodies and response payloads must be typed with Pydantic
models. No `dict` or `Any` at API boundaries. Validation errors return
422 with structured detail — never 500.

### Registry Snapshot Logging
At the end of `mount_all()`, the registry writes a JSON snapshot:
```json
{
  "timestamp": "<iso8601>",
  "modules": [
    {"name": "flex.package_audit", "version": "1.0.0", "status": "mounted"}
  ]
}
```
Snapshot path: `data/registry_snapshot.json`.
Used for reproducibility audits and diff-based change detection.

### Permissions per Module
Each module declares required permissions in its `module.json`.
The registry validates declared permissions against a known permission
vocabulary before mounting. Unknown permissions cause mount failure.

Known permissions:
- `read:packages`
- `write:packages`
- `read:filesystem`
- `write:filesystem`
- `read:network`
- `write:network`
- `read:memory`
- `write:memory`
- `execute:process`
