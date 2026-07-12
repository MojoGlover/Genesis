"""
memory_sync — Cross-plug memory persistence and redundant backup.

Keeps agent memory consistent across nodes (PlugWan, PlugZero/GCP, PlugToo)
so agents don't regress when switching between Plugs.

Sync targets (in priority order):
  1. Primary  — Cerberus HTTP endpoint on PlugZero/GCP (configurable)
  2. Backup   — iCloud Drive or any local sync directory (configurable)

What gets synced (Tier 1 — growth-critical):
  - memory/        all .json files (facts, summaries, episodic memory)
  - brain/strategy_weights.json   (learned decision weights)
  - tasks/         most recent N task files (configurable)

What is NEVER synced (node-local):
  - cerberus.key, credentials/, cerberus_token.json
  - logs/, monitor/, watchdog/

On startup: pull from primary (or backup if primary down), merge with local.
On interval (default 5 min) + shutdown: push to primary AND backup.
On conflict: latest-write-wins by file mtime.

Config keys:
    modules.memory_sync.primary_url          Cerberus on PlugZero (e.g. http://plugzero:8200)
    modules.memory_sync.backup_dir           iCloud or any local sync folder
    modules.memory_sync.sync_interval_seconds  (default: 300)
    modules.memory_sync.tasks_limit          max task files to sync (default: 100)
    modules.memory_sync.enabled              (default: true)

Environment:
    MEMORY_SYNC_URL    overrides primary_url
    MEMORY_SYNC_DIR    overrides backup_dir
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST = {
    "name":                 "memory_sync",
    "description":          "Cross-plug memory sync — GCP primary + iCloud backup",
    "requires_credentials": [],
    "requires_config":      [],
    "provides":             ["memory_sync_client"],
    "capabilities":         ["memory_sync"],
}

# Files/dirs that must never leave the node
_EXCLUDED_NAMES = frozenset({
    "cerberus.key",
    "cerberus_token.json",
    "credentials",
    "logs",
    "monitor",
    "watchdog",
    "__pycache__",
})

# Directories eligible for sync
_SYNC_DIRS   = ("memory",)
_SYNC_FILES  = ("brain/strategy_weights.json",)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _file_checksum(path: Path) -> str:
    """SHA-256 of file contents — used to skip unchanged files."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_snapshot(data_dir: Path, tasks_limit: int = 100) -> dict[str, Any]:
    """
    Walk data_dir and collect sync-eligible files as a dict:
        { "relative/path.json": {"content": ..., "mtime": float} }
    """
    snapshot: dict[str, Any] = {}

    def _add(path: Path) -> None:
        rel = str(path.relative_to(data_dir))
        # Skip excluded names at any depth
        for part in path.parts:
            if part in _EXCLUDED_NAMES:
                return
        if not path.is_file():
            return
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
            snapshot[rel] = {"content": content, "mtime": path.stat().st_mtime}
        except (json.JSONDecodeError, OSError):
            pass  # skip non-JSON or unreadable files

    # Sync directories
    for dir_name in _SYNC_DIRS:
        d = data_dir / dir_name
        if d.is_dir():
            for p in sorted(d.rglob("*.json")):
                _add(p)

    # Sync individual files
    for rel_path in _SYNC_FILES:
        p = data_dir / rel_path
        if p.exists():
            _add(p)

    # Sync recent task files
    tasks_dir = data_dir / "tasks"
    if tasks_dir.is_dir():
        task_files = sorted(
            tasks_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:tasks_limit]
        for p in task_files:
            _add(p)

    return snapshot


def _apply_snapshot(data_dir: Path, snapshot: dict[str, Any]) -> int:
    """
    Write snapshot files to data_dir.
    Uses latest-write-wins: only overwrites if remote mtime > local mtime.
    Returns count of files written.
    """
    written = 0
    for rel, entry in snapshot.items():
        dest = data_dir / rel
        remote_mtime = entry.get("mtime", 0)

        # Skip if local file is newer
        if dest.exists() and dest.stat().st_mtime >= remote_mtime:
            continue

        # Skip if path escapes data_dir (safety)
        try:
            dest.resolve().relative_to(data_dir.resolve())
        except ValueError:
            logger.warning(f"memory_sync: skipping unsafe path '{rel}'")
            continue

        # Reject excluded names
        skip = False
        for part in dest.parts:
            if part in _EXCLUDED_NAMES:
                skip = True
                break
        if skip:
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_text(
                json.dumps(entry["content"], indent=2), encoding="utf-8"
            )
            written += 1
        except OSError as exc:
            logger.warning(f"memory_sync: could not write '{rel}': {exc}")

    return written


# ── Primary backend — Cerberus HTTP ───────────────────────────────────────────

class _CerberusBackend:
    """Push/pull snapshots via Cerberus memory_store HTTP endpoint."""

    def __init__(self, base_url: str, agent_name: str) -> None:
        self._url   = base_url.rstrip("/")
        self._agent = agent_name

    def push(self, snapshot: dict) -> bool:
        try:
            import urllib.request
            payload = json.dumps({
                "agent":    self._agent,
                "snapshot": snapshot,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self._url}/memory/{self._agent}",
                data=payload,
                method="PUT",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.warning(f"memory_sync primary push failed: {exc}")
            return False

    def pull(self) -> dict | None:
        try:
            import urllib.request
            with urllib.request.urlopen(
                f"{self._url}/memory/{self._agent}", timeout=10
            ) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8")).get("snapshot")
        except Exception as exc:
            logger.warning(f"memory_sync primary pull failed: {exc}")
        return None


# ── Secondary backend — local directory (iCloud / Dropbox / any) ──────────────

class _LocalDirBackend:
    """
    Push/pull snapshots to/from a local directory that a cloud service
    (iCloud Drive, Dropbox, etc.) mirrors to the cloud automatically.

    Layout: backup_dir/botico_memory/<agent_name>/snapshot.json
    """

    def __init__(self, backup_dir: Path, agent_name: str) -> None:
        self._dir   = Path(backup_dir).expanduser() / "botico_memory" / agent_name
        self._file  = self._dir / "snapshot.json"

    def push(self, snapshot: dict) -> bool:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps({"snapshot": snapshot, "ts": time.time()}, indent=2),
                encoding="utf-8",
            )
            logger.debug(f"memory_sync backup pushed → {self._file}")
            return True
        except OSError as exc:
            logger.warning(f"memory_sync backup push failed: {exc}")
            return False

    def pull(self) -> dict | None:
        if not self._file.exists():
            return None
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return data.get("snapshot")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"memory_sync backup pull failed: {exc}")
            return None


# ── MemorySyncClient ──────────────────────────────────────────────────────────

class MemorySyncClient:
    """
    Manages periodic memory sync across plugs with redundant backup.

    Usage (automatic via setup()):
        client.start()           — begin background sync loop
        client.push_now()        — force immediate push to all backends
        client.pull_now()        — force immediate pull from primary (or backup)
        client.stop()            — flush final push and stop loop
        client.status()          — return sync state dict
    """

    def __init__(
        self,
        data_dir:        Path,
        agent_name:      str,
        primary:         _CerberusBackend | None,
        backup:          _LocalDirBackend | None,
        sync_interval:   int  = 300,
        tasks_limit:     int  = 100,
    ) -> None:
        self._data_dir      = Path(data_dir).expanduser().resolve()
        self._agent_name    = agent_name
        self._primary       = primary
        self._backup        = backup
        self._interval      = sync_interval
        self._tasks_limit   = tasks_limit
        self._running       = False
        self._thread: threading.Thread | None = None
        self._last_push:    float = 0.0
        self._last_pull:    float = 0.0
        self._push_count:   int   = 0
        self._pull_count:   int   = 0
        self._last_error:   str   = ""

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Pull latest snapshot from primary (or backup), then start sync loop."""
        logger.info(f"memory_sync: starting for {self._agent_name}")
        self.pull_now()  # hydrate before loop begins
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"memory-sync-{self._agent_name}"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop sync loop and push one final snapshot."""
        self._running = False
        logger.info("memory_sync: stopping — final push")
        self.push_now()

    def push_now(self) -> dict:
        """Collect current snapshot and push to all available backends."""
        snapshot = _collect_snapshot(self._data_dir, self._tasks_limit)
        results  = {"files": len(snapshot), "primary": False, "backup": False}

        if self._primary:
            results["primary"] = self._primary.push(snapshot)
        if self._backup:
            results["backup"] = self._backup.push(snapshot)

        if results["primary"] or results["backup"]:
            self._last_push  = time.time()
            self._push_count += 1
            logger.info(
                f"memory_sync: pushed {len(snapshot)} files "
                f"(primary={results['primary']}, backup={results['backup']})"
            )
        else:
            self._last_error = "push failed — all backends unavailable"
            logger.warning(f"memory_sync: {self._last_error}")

        return results

    def pull_now(self) -> dict:
        """Pull snapshot from primary; fall back to backup if primary is down."""
        snapshot = None
        source   = "none"

        if self._primary:
            snapshot = self._primary.pull()
            if snapshot:
                source = "primary"

        if snapshot is None and self._backup:
            snapshot = self._backup.pull()
            if snapshot:
                source = "backup"
                logger.info("memory_sync: primary unreachable — restoring from backup")

        if snapshot is None:
            logger.info("memory_sync: no remote snapshot found — starting from local state")
            return {"source": "local", "written": 0}

        written = _apply_snapshot(self._data_dir, snapshot)
        self._last_pull  = time.time()
        self._pull_count += 1
        logger.info(f"memory_sync: pulled from {source} — {written} files updated")
        return {"source": source, "written": written}

    def status(self) -> dict:
        return {
            "agent":      self._agent_name,
            "running":    self._running,
            "last_push":  self._last_push,
            "last_pull":  self._last_pull,
            "push_count": self._push_count,
            "pull_count": self._pull_count,
            "primary_url": self._primary._url if self._primary else None,
            "backup_dir":  str(self._backup._dir.parent.parent) if self._backup else None,
            "last_error":  self._last_error,
        }

    # ── Internal loop ──────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._interval)
            if self._running:
                try:
                    self.push_now()
                except Exception as exc:
                    self._last_error = str(exc)
                    logger.warning(f"memory_sync loop error: {exc}")


# ── iCloud auto-detect ─────────────────────────────────────────────────────────

def _detect_icloud_dir() -> Path | None:
    """Return iCloud Drive path if accessible on this machine, else None."""
    candidates = [
        Path("~/Library/Mobile Documents/com~apple~CloudDocs").expanduser(),
        # Android / Linux fallback paths can be added here
    ]
    for p in candidates:
        if p.exists() and os.access(p, os.W_OK):
            return p
    return None


# ── Module entry point ─────────────────────────────────────────────────────────

def setup(config: dict) -> dict:
    """Module entry point. Called by the loader."""
    try:
        from modules.module_manifest import registry
        registry.register("memory_sync", MANIFEST, status="active")
    except Exception:
        pass

    mod_cfg    = config.get("modules", {}).get("memory_sync", {})
    enabled    = mod_cfg.get("enabled", True)

    if not enabled:
        logger.info("memory_sync: disabled by config")
        return {}

    identity   = config.get("identity", {})
    agent_name = identity.get("designation", "Agent")
    data_dir   = Path(
        os.environ.get("DATA_DIR") or config.get("data_dir", "~/.agent")
    ).expanduser()

    interval     = mod_cfg.get("sync_interval_seconds", 300)
    tasks_limit  = mod_cfg.get("tasks_limit", 100)

    # Primary: Cerberus on PlugZero
    primary_url = (
        os.environ.get("MEMORY_SYNC_URL")
        or mod_cfg.get("primary_url", "")
    )
    primary = _CerberusBackend(primary_url, agent_name) if primary_url else None
    if not primary:
        logger.info("memory_sync: no primary_url configured — primary sync disabled")

    # Backup: iCloud or config-specified dir
    backup_dir_raw = (
        os.environ.get("MEMORY_SYNC_DIR")
        or mod_cfg.get("backup_dir", "")
    )
    if backup_dir_raw:
        backup_path = Path(backup_dir_raw).expanduser()
    else:
        backup_path = _detect_icloud_dir()

    backup = _LocalDirBackend(backup_path, agent_name) if backup_path else None
    if backup_path:
        logger.info(f"memory_sync: backup dir → {backup_path}")
    else:
        logger.info("memory_sync: no backup dir found (iCloud not detected, backup disabled)")

    if not primary and not backup:
        logger.warning("memory_sync: no backends configured — sync disabled")
        return {}

    client = MemorySyncClient(
        data_dir=data_dir,
        agent_name=agent_name,
        primary=primary,
        backup=backup,
        sync_interval=interval,
        tasks_limit=tasks_limit,
    )
    client.start()

    logger.info(
        f"memory_sync: active for {agent_name} "
        f"(interval={interval}s, primary={'yes' if primary else 'no'}, "
        f"backup={'yes' if backup else 'no'})"
    )

    return {"memory_sync_client": client}
