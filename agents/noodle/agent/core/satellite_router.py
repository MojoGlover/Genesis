"""
agent/core/satellite_router.py — Satellite locality router for BlackZero v2 Fourth Pass.

Resolves model capabilities to the best available satellite (Ollama host).
Reads from registry/capabilities/satellites/ and registry/capabilities/models/
so the routing table lives in the registry, not in config.yaml.

Priority:
  1. always_on satellites (plugfoe) — guaranteed available, prefer first
  2. Non-always_on satellites in locality order (plugwan, then tablet)
  3. If no satellite has a resolvable env var → returns SatelliteDecision(found=False)

URL construction: satellite manifests reference env vars, not raw IPs.
  tailscale_ref: env.PLUGFOE_TAILSCALE → os.environ["PLUGFOE_TAILSCALE"] → "100.67.171.41"
  host_ref:      env.PLUGFOE_HOST      → os.environ["PLUGFOE_HOST"]      → "178.105.62.143"
Tailscale ref is preferred over host_ref (VPN mesh is lower latency and avoids
exposing the management port on the public internet).

Usage:
    router = SatelliteRouter(Path("registry/"))
    decision = router.resolve_model("model.agent.engineer0")
    if decision:
        # decision.ollama_url — "http://100.67.171.41:11434"
        # decision.satellite_id — "satellite.plugfoe"
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_OLLAMA_PORT = 11434


@dataclass
class SatelliteDecision:
    found:          bool
    satellite_id:   str  = ""
    satellite_name: str  = ""
    ollama_url:     str  = ""
    model_name:     str  = ""
    locality:       str  = ""
    always_on:      bool = False
    reason:         str  = ""

    def __bool__(self) -> bool:
        return self.found


class SatelliteRouter:
    """
    Maps model capability ids to Ollama URLs on available satellites.

    Constructed once at build_graph() time. All data comes from registry YAML
    files + environment variables — no network calls, no PlugOps dependency.

    Thread-safe: all state is read-only after __init__.
    """

    def __init__(self, registry_dir: Path, env: dict[str, str] | None = None) -> None:
        self._env       = env if env is not None else dict(os.environ)
        self._satellites: dict[str, dict] = {}   # satellite_id  → manifest
        self._models:     dict[str, dict] = {}   # model_id      → manifest
        self._by_stem:    dict[str, dict] = {}   # yaml filename → manifest (short name)
        self._load(registry_dir)

    # ── Public API ────────────────────────────────────────────────────────────

    def resolve_model(self, model_id: str, mode: str = "act") -> SatelliteDecision:
        """
        Return the best satellite for a model capability.

        model_id accepts:
          - full capability id    "model.agent.engineer0"
          - yaml filename stem    "engineer0" / "qwen_coder_7b"
          - Ollama model_name     "engineer0:latest"
        """
        manifest = (
            self._models.get(model_id)
            or self._by_stem.get(model_id)
            or self._find_by_model_name(model_id)
        )
        if not manifest:
            return SatelliteDecision(
                found=False,
                reason=f"No model manifest found for '{model_id}'",
            )

        locality_names: list[str] = manifest.get("locality", [])
        if not locality_names:
            return SatelliteDecision(
                found=False,
                reason=f"Model '{manifest['id']}' has no locality list in manifest",
            )

        model_name = manifest.get("model_name", "")
        candidates = self._rank_satellites(locality_names)

        for sat in candidates:
            url = self._ollama_url(sat)
            if not url:
                logger.debug(
                    "[satellite_router] %s: env vars not set — skipping",
                    sat["id"],
                )
                continue
            logger.debug(
                "[satellite_router] %s → %s (%s)", manifest["id"], sat["id"], url
            )
            return SatelliteDecision(
                found=True,
                satellite_id=sat["id"],
                satellite_name=sat.get("name", sat["id"]),
                ollama_url=url,
                model_name=model_name,
                locality=sat.get("locality", "unknown"),
                always_on=sat.get("always_on", False),
                reason=(
                    f"satellite={sat['id']}, "
                    f"always_on={sat.get('always_on', False)}, "
                    f"locality={sat.get('locality', 'unknown')}"
                ),
            )

        return SatelliteDecision(
            found=False,
            reason=(
                f"No satellite available for '{model_id}' "
                f"(locality={locality_names}, none had required env vars set)"
            ),
        )

    def list_satellites(self) -> list[dict]:
        """All satellite manifests sorted by priority (always_on first)."""
        return sorted(
            self._satellites.values(),
            key=lambda s: (0 if s.get("always_on") else 1, s.get("locality", "z")),
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self, registry_dir: Path) -> None:
        caps_dir = registry_dir / "capabilities"

        sat_dir = caps_dir / "satellites"
        if sat_dir.exists():
            for f in sat_dir.glob("*.yaml"):
                try:
                    m = yaml.safe_load(f.read_text(encoding="utf-8"))
                    if m and m.get("id"):
                        self._satellites[m["id"]] = m
                except Exception as e:
                    logger.warning("[satellite_router] Load failed %s: %s", f.name, e)

        mod_dir = caps_dir / "models"
        if mod_dir.exists():
            for f in mod_dir.glob("*.yaml"):
                try:
                    m = yaml.safe_load(f.read_text(encoding="utf-8"))
                    if m and m.get("id"):
                        self._models[m["id"]] = m
                        self._by_stem[f.stem] = m
                except Exception as e:
                    logger.warning("[satellite_router] Load failed %s: %s", f.name, e)

        logger.debug(
            "[satellite_router] Loaded %d satellites, %d models",
            len(self._satellites), len(self._models),
        )

    def _find_by_model_name(self, model_name: str) -> dict | None:
        """Match against manifest model_name field (e.g., 'engineer0:latest')."""
        for m in self._models.values():
            if m.get("model_name") == model_name:
                return m
        return None

    def _rank_satellites(self, locality_names: list[str]) -> list[dict]:
        """
        Map locality short names → satellite manifests, sorted by priority.
        always_on satellites come first; otherwise, locality_names order is preserved.
        """
        sats = []
        for name in locality_names:
            sat = self._satellites.get(f"satellite.{name}")
            if sat:
                sats.append(sat)
            else:
                logger.debug(
                    "[satellite_router] No manifest for 'satellite.%s'", name
                )
        return sorted(sats, key=lambda s: (0 if s.get("always_on") else 1))

    def _ollama_url(self, sat_manifest: dict) -> str | None:
        """
        Build Ollama base URL from env var refs in the satellite manifest.
        Prefers tailscale_ref (VPN mesh) over host_ref (public IP).
        Returns None if the required env var is not set.
        """
        for ref_key in ("tailscale_ref", "host_ref"):
            ref = sat_manifest.get(ref_key, "")
            if not ref:
                continue
            if ref.startswith("env."):
                host = self._env.get(ref[4:], "")  # strip "env." prefix
                if host:
                    return f"http://{host}:{_OLLAMA_PORT}"
        return None
