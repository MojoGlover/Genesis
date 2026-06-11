"""
test_architecture.py — BlackZero v2 contract tests.

These tests enforce architecture, not function output.
A failing test here means the codebase has drifted from the BlackZero constitution.

Run with: pytest tests/test_architecture.py -v
Or via:   python -m blackzero audit (once Third Pass is complete)

Contract categories:
  1. Hardwiring — no location-sensitive values baked into source
  2. Brain/tool boundary — brain never imports providers or calls tools directly
  3. Registry — every manifest has required fields; no duplicate ids
  4. Tool manifest coverage — every tool in agent/tools/ has a registry manifest
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterator

import yaml
import pytest

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT      = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"
REG_DIR   = ROOT / "registry"

BRAIN_MODULES = [
    AGENT_DIR / "core" / "graph.py",
    AGENT_DIR / "core" / "mission.py",
    AGENT_DIR / "core" / "state.py",
    AGENT_DIR / "core" / "loops.py",
]

TOOL_ADAPTERS = list((AGENT_DIR / "tools").glob("*.py"))
ALL_SOURCE    = list(ROOT.rglob("*.py"))

# Exclude virtual envs and caches
def _is_live(p: Path) -> bool:
    parts = p.parts
    return not any(x in parts for x in (".venv", "__pycache__", ".git", "tests"))

LIVE_SOURCE = [p for p in ALL_SOURCE if _is_live(p)]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. HARDWIRING TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestHardwiring:
    """Fail if location-sensitive values are baked directly into source code."""

    # Tailscale IPs are assigned by the network — they belong in shared.env / config,
    # not in source files. When a device is re-enrolled its IP changes.
    TAILSCALE_PATTERN = re.compile(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

    # Bare Hetzner / public IPs likewise.
    BARE_IP_PATTERN   = re.compile(r"\b178\.\d+\.\d+\.\d+\b")

    # Cloud Run service IDs change when a project is recreated.
    CLOUD_RUN_PATTERN = re.compile(r"plugzero-[a-z0-9]+-[a-z0-9]+\.run\.app")

    # Absolute paths rooted at a specific user's home directory.
    USER_PATH_PATTERN = re.compile(r"/Users/[a-zA-Z0-9_]+/")

    def _violations(self, pattern: re.Pattern, exclude_files: list[str] = None) -> list[str]:
        exclude_files = exclude_files or []
        hits = []
        for path in LIVE_SOURCE:
            if any(ex in str(path) for ex in exclude_files):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                # Skip pure comment lines and inline comments after #
                if stripped.startswith("#"):
                    continue
                # Skip docstring/comment example lines (→ marks example output)
                if "# →" in line or "→" in line or "# e.g." in line or "# example" in line.lower():
                    continue
                # Only the non-comment portion needs to match
                code_part = line.split("#")[0]
                if pattern.search(code_part):
                    hits.append(f"{path.relative_to(ROOT)}:{lineno}  {stripped}")
        return hits

    def test_no_hardcoded_tailscale_ips(self):
        """Tailscale IPs belong in shared.env / config.yaml, not in .py files."""
        violations = self._violations(self.TAILSCALE_PATTERN)
        assert not violations, (
            "Hardcoded Tailscale IPs found in source — move to config/env:\n"
            + "\n".join(violations)
        )

    def test_no_hardcoded_bare_ips(self):
        """Bare public IPs (Hetzner etc.) belong in shared.env, not source."""
        violations = self._violations(self.BARE_IP_PATTERN)
        assert not violations, (
            "Hardcoded public IPs found in source — move to config/env:\n"
            + "\n".join(violations)
        )

    def test_no_hardcoded_cloud_run_urls(self):
        """Cloud Run service URLs belong in config.yaml / env, not in source."""
        violations = self._violations(self.CLOUD_RUN_PATTERN)
        assert not violations, (
            "Hardcoded Cloud Run URLs found in source — move to config/env:\n"
            + "\n".join(violations)
        )

    def test_no_hardcoded_user_paths(self):
        """Absolute user-home paths belong in config / env, not source."""
        violations = self._violations(self.USER_PATH_PATTERN,
                                      exclude_files=["test_architecture.py"])
        assert not violations, (
            "Hardcoded user-home paths found in source — use Path.home() or config:\n"
            + "\n".join(violations)
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BRAIN / TOOL BOUNDARY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestBrainToolBoundary:
    """The brain must not import provider SDKs or call tools directly."""

    PROVIDER_IMPORTS = [
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import ollama",         # direct ollama SDK (not httpx calls to the API)
    ]

    def test_brain_does_not_import_provider_sdks(self):
        violations = []
        for path in BRAIN_MODULES:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                stripped = line.strip()
                for pat in self.PROVIDER_IMPORTS:
                    if stripped.startswith(pat):
                        violations.append(f"{path.name}: {stripped}")
        assert not violations, (
            "Brain modules must not import provider SDKs directly — route through gateway:\n"
            + "\n".join(violations)
        )

    def test_brain_does_not_import_tool_adapters_directly(self):
        """Brain modules must not import from agent.tools.* directly.
        Tool calls go through the tool bus / graph dispatch, not direct imports.

        KNOWN EXCEPTION (Second Pass): graph.py currently imports agent.tools.registry
        for LangGraph tool dispatch. This will be migrated to the tool bus in Second Pass.
        Until then, registry imports from graph.py are permitted.
        """
        tool_import_pattern = re.compile(r"from agent\.tools\.\w+ import|import agent\.tools\.")
        # registry is the LangGraph dispatch shim — permitted until Second Pass tool bus migration
        PERMITTED = {"from agent.tools.registry import"}
        violations = []
        for path in BRAIN_MODULES:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if tool_import_pattern.search(stripped):
                    if any(stripped.startswith(p) for p in PERMITTED):
                        continue
                    violations.append(f"{path.name}:{lineno}  {stripped}")
        assert not violations, (
            "Brain modules must not import tool adapters directly:\n"
            + "\n".join(violations)
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REGISTRY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def _load_manifests(kind: str) -> list[dict]:
    folder = REG_DIR / "capabilities" / kind
    if not folder.exists():
        return []
    manifests = []
    for f in folder.glob("*.yaml"):
        with open(f) as fh:
            manifests.append(yaml.safe_load(fh))
    return manifests


class TestRegistry:
    """Registry manifests must be well-formed and internally consistent."""

    REQUIRED_FIELDS = ["id", "kind", "name", "status", "lifecycle"]

    def test_all_manifests_have_required_fields(self):
        violations = []
        for kind in ("models", "tools", "endpoints", "satellites", "memory"):
            for m in _load_manifests(kind):
                for field in self.REQUIRED_FIELDS:
                    if field not in m:
                        violations.append(f"{m.get('id', '?')} missing field: {field}")
        assert not violations, "Manifest field violations:\n" + "\n".join(violations)

    def test_no_duplicate_capability_ids(self):
        all_ids = []
        for kind in ("models", "tools", "endpoints", "satellites", "memory"):
            for m in _load_manifests(kind):
                if "id" in m:
                    all_ids.append(m["id"])
        duplicates = [i for i in all_ids if all_ids.count(i) > 1]
        assert not duplicates, f"Duplicate capability ids: {set(duplicates)}"

    def test_all_lifecycle_values_are_valid(self):
        valid = {"active", "experimental", "quarantined", "retired", "archived", "repairable"}
        violations = []
        for kind in ("models", "tools", "endpoints", "satellites", "memory"):
            for m in _load_manifests(kind):
                lc = m.get("lifecycle", "")
                if lc not in valid:
                    violations.append(f"{m.get('id', '?')} has invalid lifecycle: {lc!r}")
        assert not violations, "Invalid lifecycle values:\n" + "\n".join(violations)

    def test_active_tools_have_adapter_field(self):
        violations = []
        for m in _load_manifests("tools"):
            if m.get("lifecycle") == "active" and "adapter" not in m:
                violations.append(m.get("id", "?"))
        assert not violations, (
            "Active tool manifests must declare an adapter:\n" + "\n".join(violations)
        )

    def test_side_effecting_tools_have_policy(self):
        no_side_effect = {"none"}
        violations = []
        for m in _load_manifests("tools"):
            if m.get("side_effects", "none") not in no_side_effect:
                if "policy" not in m:
                    violations.append(m.get("id", "?"))
        assert not violations, (
            "Tools with side effects must declare a policy block:\n"
            + "\n".join(violations)
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TOOL MANIFEST COVERAGE
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolCoverage:
    """Every non-trivial tool module should have a registry manifest."""

    # registry.py is the LangGraph tool dispatch layer, not a capability adapter.
    # It will be migrated to the tool bus in Second Pass.
    # base_tool.py is a base class, not a capability adapter.
    SKIP = {"__init__.py", "helper.py", "base_adapter.py", "base_tool.py", "registry.py"}

    def test_every_tool_module_has_a_manifest(self):
        tool_dir = AGENT_DIR / "tools"
        if not tool_dir.exists():
            pytest.skip("agent/tools/ not found")

        manifests = _load_manifests("tools")
        # Derive expected logical name from adapter field (last component)
        covered_adapters = {
            m["adapter"].split(".")[-1] for m in manifests if "adapter" in m
        }

        missing = []
        for pyfile in tool_dir.glob("*.py"):
            if pyfile.name in self.SKIP:
                continue
            module_stem = pyfile.stem  # e.g. "shell", "git_tool", "web_browser"
            if module_stem not in covered_adapters:
                missing.append(f"agent/tools/{pyfile.name} has no registry manifest")

        assert not missing, (
            "Tool modules without registry manifests (add to registry/capabilities/tools/):\n"
            + "\n".join(missing)
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. THIRD PASS — MODE, QUARANTINE, AUDIT
# ═══════════════════════════════════════════════════════════════════════════════

class TestThirdPass:
    """Third Pass contracts: mode threading, quarantine overlay, audit CLI."""

    def test_mode_is_threaded_to_tool_bus(self):
        """
        graph.py tool node must pass mode= kwarg from graph state to the bus.
        Without this, the router's mode-aware lifecycle filtering has no effect.
        """
        graph_src = (AGENT_DIR / "core" / "graph.py").read_text(encoding="utf-8")
        assert 'mode=mode' in graph_src or 'mode=state.get("mode"' in graph_src, (
            'graph.py tool node must pass mode= from state to local_tool_bus.execute(). '
            'Add: mode = state.get("mode", "act") and pass mode=mode to execute().'
        )

    def test_quarantine_overlay_module_exists(self):
        """agent/core/quarantine.py must exist and export QuarantineOverlay."""
        q_path = AGENT_DIR / "core" / "quarantine.py"
        assert q_path.exists(), "agent/core/quarantine.py not found — Third Pass requires it"
        src = q_path.read_text(encoding="utf-8")
        assert "class QuarantineOverlay" in src, (
            "quarantine.py must define QuarantineOverlay"
        )

    def test_quarantine_overlay_threshold_behavior(self, tmp_path):
        """QuarantineOverlay quarantines at threshold and clears on success."""
        import importlib.util, sys as _sys
        spec = importlib.util.spec_from_file_location(
            "quarantine", AGENT_DIR / "core" / "quarantine.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        QuarantineOverlay = mod.QuarantineOverlay

        overlay = QuarantineOverlay(tmp_path, threshold=3)
        cap = "tool.local.shell"

        assert not overlay.is_quarantined(cap)
        overlay.record_failure(cap)
        overlay.record_failure(cap)
        assert not overlay.is_quarantined(cap)          # 2 failures, not yet
        triggered = overlay.record_failure(cap)
        assert triggered, "Third failure should trigger quarantine"
        assert overlay.is_quarantined(cap)

        overlay.record_success(cap)
        assert not overlay.is_quarantined(cap), "Success in repair mode should clear quarantine"

    def test_quarantine_overlay_persists(self, tmp_path):
        """State written by one instance is readable by a new instance."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "quarantine2", AGENT_DIR / "core" / "quarantine.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        QuarantineOverlay = mod.QuarantineOverlay

        cap = "tool.local.python_repl"
        o1 = QuarantineOverlay(tmp_path, threshold=2)
        o1.record_failure(cap)
        o1.record_failure(cap)
        assert o1.is_quarantined(cap)

        o2 = QuarantineOverlay(tmp_path, threshold=2)
        assert o2.is_quarantined(cap), "Quarantine state must persist across instances"

    def test_tool_bus_accepts_quarantine_param(self):
        """LocalToolBus.__init__ must accept a quarantine= kwarg (optional)."""
        bus_src = (AGENT_DIR / "core" / "local_tool_bus.py").read_text(encoding="utf-8")
        assert "quarantine" in bus_src, (
            "local_tool_bus.py must accept a quarantine parameter — Third Pass requires it"
        )

    def test_tool_bus_checks_quarantine_before_execute(self):
        """LocalToolBus.execute() must check quarantine before calling the executor."""
        bus_src = (AGENT_DIR / "core" / "local_tool_bus.py").read_text(encoding="utf-8")
        assert "is_quarantined" in bus_src, (
            "local_tool_bus.execute() must check quarantine.is_quarantined() — "
            "quarantined capabilities must be blocked before reaching the executor"
        )

    def test_audit_module_exists(self):
        """agent/core/audit.py must exist and be importable as a CLI module."""
        audit_path = AGENT_DIR / "core" / "audit.py"
        assert audit_path.exists(), (
            "agent/core/audit.py not found — Third Pass requires the audit CLI"
        )
        src = audit_path.read_text(encoding="utf-8")
        assert "def run_audit" in src, "audit.py must define run_audit(data_dir, registry_dir)"
        assert "__main__" in src, "audit.py must be runnable as python3 -m agent.core.audit"

    def test_audit_runs_on_empty_data_dir(self, tmp_path, capsys):
        """Audit CLI should not crash when data dir exists but has no evidence yet."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "audit", AGENT_DIR / "core" / "audit.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        registry_dir = ROOT / "registry"
        # Should not raise.
        mod.run_audit(tmp_path, registry_dir)
        captured = capsys.readouterr()
        assert "No evidence data found" in captured.out or captured.out == ""


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FOURTH PASS — SATELLITE LOCALITY ROUTING + EVIDENCE PROVENANCE
# ═══════════════════════════════════════════════════════════════════════════════

class TestFourthPass:
    """Fourth Pass contracts: satellite router, locality routing, evidence provenance."""

    def test_satellite_router_module_exists(self):
        """agent/core/satellite_router.py must exist and export SatelliteRouter."""
        sr_path = AGENT_DIR / "core" / "satellite_router.py"
        assert sr_path.exists(), (
            "agent/core/satellite_router.py not found — Fourth Pass requires it"
        )
        src = sr_path.read_text(encoding="utf-8")
        assert "class SatelliteRouter" in src
        assert "class SatelliteDecision" in src

    def _load_satellite_router(self, module_alias: str):
        """
        Load satellite_router.py via importlib, registering in sys.modules first.
        Required because @dataclass + from __future__ import annotations needs
        the module registered so annotation strings can be resolved at class
        definition time.
        """
        import importlib.util, sys as _sys
        spec = importlib.util.spec_from_file_location(
            module_alias, AGENT_DIR / "core" / "satellite_router.py"
        )
        mod = importlib.util.module_from_spec(spec)
        _sys.modules[module_alias] = mod   # register before exec
        spec.loader.exec_module(mod)
        return mod

    def test_satellite_router_prefers_always_on(self, tmp_path):
        """SatelliteRouter must return the always_on satellite first."""
        mod = self._load_satellite_router("_sr_test_always_on")
        SatelliteRouter = mod.SatelliteRouter

        # Inject fake env so we don't need real Tailscale IPs.
        fake_env = {
            "PLUGFOE_TAILSCALE": "10.0.0.1",
            "PLUGWAN_TAILSCALE":  "10.0.0.2",
        }
        router = SatelliteRouter(ROOT / "registry", env=fake_env)
        # engineer0 has locality: [plugfoe, plugwan]
        decision = router.resolve_model("engineer0")
        assert decision.found, f"Expected a satellite decision, got: {decision.reason}"
        assert decision.always_on, (
            f"Expected always_on satellite (plugfoe) first, got: {decision.satellite_id}"
        )
        assert decision.satellite_id == "satellite.plugfoe"

    def test_satellite_router_skips_missing_env_vars(self, tmp_path):
        """SatelliteRouter must skip satellites whose env vars are not set."""
        mod = self._load_satellite_router("_sr_test_skip_missing")
        SatelliteRouter = mod.SatelliteRouter

        # Only plugwan env var is set — plugfoe is skipped, plugwan is chosen.
        fake_env = {"PLUGWAN_TAILSCALE": "10.0.0.2"}
        router = SatelliteRouter(ROOT / "registry", env=fake_env)
        decision = router.resolve_model("engineer0")
        assert decision.found, f"Expected fallback to plugwan: {decision.reason}"
        assert decision.satellite_id == "satellite.plugwan"

    def test_satellite_router_returns_not_found_when_no_env(self, tmp_path):
        """SatelliteRouter must return found=False when NO env vars are set."""
        mod = self._load_satellite_router("_sr_test_not_found")
        SatelliteRouter = mod.SatelliteRouter

        router = SatelliteRouter(ROOT / "registry", env={})
        decision = router.resolve_model("engineer0")
        assert not decision.found
        assert not decision  # __bool__ must reflect found

    def test_routing_decision_has_satellite_id_field(self):
        """RoutingDecision must have a satellite_id field (added in Fourth Pass)."""
        router_src = (AGENT_DIR / "core" / "router.py").read_text(encoding="utf-8")
        assert "satellite_id" in router_src, (
            "RoutingDecision in router.py must have a satellite_id field — Fourth Pass"
        )

    def test_result_record_has_satellite_id_field(self):
        """ResultRecord in evidence.py must have a satellite_id field."""
        evidence_src = (AGENT_DIR.parent / "agent" / "modules" / "evidence.py").read_text(
            encoding="utf-8"
        )
        assert "satellite_id" in evidence_src, (
            "ResultRecord must have satellite_id — evidence provenance requires it (Fourth Pass)"
        )

    def test_evidence_ledger_record_result_accepts_satellite_id(self):
        """EvidenceLedger.record_result() must accept satellite_id kwarg."""
        evidence_src = (AGENT_DIR.parent / "agent" / "modules" / "evidence.py").read_text(
            encoding="utf-8"
        )
        # The param must appear in the record_result signature
        assert "satellite_id" in evidence_src
        # And it must be threaded through to the ResultRecord constructor
        assert "satellite_id=satellite_id" in evidence_src

    def test_tool_bus_wires_satellite_router(self):
        """LocalToolBus must accept and use a satellite_router parameter."""
        bus_src = (AGENT_DIR / "core" / "local_tool_bus.py").read_text(encoding="utf-8")
        assert "satellite_router" in bus_src, (
            "LocalToolBus must accept satellite_router — Fourth Pass wiring"
        )
        assert "SatelliteRouter" in bus_src

    def test_satellite_router_resolves_by_model_name(self, tmp_path):
        """SatelliteRouter must accept Ollama model_name as lookup key."""
        mod = self._load_satellite_router("_sr_test_by_model_name")
        SatelliteRouter = mod.SatelliteRouter

        fake_env = {"PLUGFOE_TAILSCALE": "10.0.0.1"}
        router = SatelliteRouter(ROOT / "registry", env=fake_env)
        # Resolve by Ollama model_name string, not capability id
        decision = router.resolve_model("engineer0:latest")
        assert decision.found, f"Expected found by model_name: {decision.reason}"
        assert decision.model_name == "engineer0:latest"
