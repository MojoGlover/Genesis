"""
agent/core/quarantine.py — Runtime quarantine overlay for BlackZero v2 Third Pass.

Tracks per-capability consecutive failure counts at runtime and quarantines
capabilities that exceed the failure threshold. Separate from the static registry
YAML — this overlay overrides lifecycle without touching files on disk.

Threshold: 3 consecutive failures → quarantined (runtime block).
Repair mode: quarantine is ignored; capability executes; on success, quarantine clears.
Persistence: data_dir/quarantine_overlay.json — survives agent restarts.

Thread-safe reads (dict lookup). Writes are serialized by GIL (single process).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 3


class QuarantineOverlay:
    """
    Runtime mutable layer over the static registry lifecycle.

    Only tracks capabilities that have actually failed — zero overhead for
    the happy path. All registry manifests with lifecycle=quarantined are
    still blocked by the router; this overlay catches runtime regressions
    that weren't quarantined at deploy time.
    """

    def __init__(self, data_dir: Path, threshold: int = _DEFAULT_THRESHOLD) -> None:
        self._path      = data_dir / "quarantine_overlay.json"
        self._threshold = threshold
        self._state: dict[str, dict] = self._load()

    # ── Public interface ──────────────────────────────────────────────────────

    def is_quarantined(self, capability_id: str) -> bool:
        return self._state.get(capability_id, {}).get("quarantined", False)

    def record_failure(self, capability_id: str) -> bool:
        """
        Increment consecutive-failure count. Returns True if this call
        triggered a new quarantine (so the caller can log/alert).
        Resets on any success — counts consecutive failures, not total.
        """
        entry = self._state.setdefault(
            capability_id, {"consecutive_failures": 0, "quarantined": False}
        )
        entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
        newly_quarantined = False
        if not entry["quarantined"] and entry["consecutive_failures"] >= self._threshold:
            entry["quarantined"] = True
            newly_quarantined = True
            logger.warning(
                "[quarantine] %s quarantined after %d consecutive failures",
                capability_id, entry["consecutive_failures"],
            )
        self._save()
        return newly_quarantined

    def record_success(self, capability_id: str) -> None:
        """
        Reset consecutive-failure count and clear quarantine on success.
        Called after a successful execution — especially in repair mode.
        """
        if capability_id not in self._state:
            return
        was_quarantined = self._state[capability_id].get("quarantined", False)
        self._state[capability_id] = {"consecutive_failures": 0, "quarantined": False}
        if was_quarantined:
            logger.info("[quarantine] %s cleared after successful execution", capability_id)
        self._save()

    def status(self) -> dict[str, dict]:
        """Full overlay state — used by the audit CLI."""
        return dict(self._state)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        try:
            if self._path.exists():
                return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[quarantine] Load failed (%s): %s", self._path.name, e)
        return {}

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("[quarantine] Save failed: %s", e)
