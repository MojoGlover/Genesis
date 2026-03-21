"""
Builder schemas — data structures for the entire agent factory pipeline.

These types flow through every stage:
    AgentSpec      — what to build
    BuildJob       — tracks the build process
    TestResult     — one suite's results
    TestReport     — all suites + computed gate level
    ExportManifest — what was exported, where, checksums
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class AutonomyLevel(str, Enum):
    SUPERVISED      = "supervised"        # Needs human approval for all actions
    SEMI_AUTONOMOUS = "semi_autonomous"   # Can act within defined scope
    FULLY_AUTONOMOUS = "fully_autonomous" # Full cognitive loop, self-directed


class JobStatus(str, Enum):
    PENDING   = "pending"
    FORGING   = "forging"
    TESTING   = "testing"
    EXPORTING = "exporting"
    COMPLETE  = "complete"
    FAILED    = "failed"


class GateLevel(str, Enum):
    GENESIS_ONLY  = "genesis_only"   # Stays in GENESIS — basic tests pass
    PLUGOPS_READY = "plugops_ready"  # Can export to PlugOps — hardening passes
    BOTICO_READY  = "botico_ready"   # Can export to Botico — everything passes


class ExportTarget(str, Enum):
    PLUGOPS = "plugops"
    BOTICO  = "botico"


# ── Agent Specification ───────────────────────────────────────────────────────

@dataclass
class AgentSpec:
    """Complete specification for an agent to be forged."""

    # Identity
    name: str                          # Agent slug, e.g. "ceo_0"
    designation: str                   # Human-readable, e.g. "CEO Zero"
    role: str                          # From mission, e.g. "CEO"

    # Mission
    mission_text: str                  # Full mission content from missions/*.mission.txt

    # Personality
    personality: Dict[str, Any] = field(default_factory=lambda: {
        "tone": "professional",
        "traits": [],
        "boundaries": [],
        "response_defaults": {"max_length": "concise"},
    })

    # Model
    model_base: str = "llama3.2:3b"    # Ollama model to derive from
    model_params: Dict[str, Any] = field(default_factory=lambda: {
        "temperature": 0.7,
        "top_k": 40,
        "top_p": 0.9,
        "num_ctx": 4096,
    })

    # Capabilities
    capabilities: List[str] = field(default_factory=list)      # e.g. ["code_execution", "web_search"]
    modules_required: List[str] = field(default_factory=list)  # GENESIS modules to wire

    # Autonomy
    autonomy_level: AutonomyLevel = AutonomyLevel.SEMI_AUTONOMOUS
    self_realized: bool = False        # Whether to add self-improvement loop

    # Policy overrides (agent-specific additions to BlackZero policies)
    policy_overrides: Dict[str, str] = field(default_factory=dict)

    # Loop configuration
    loop_settings: Dict[str, Any] = field(default_factory=lambda: {
        "check_interval_seconds": 5,
        "max_concurrent_tasks": 3,
        "cycle_timeout_seconds": 60,
    })

    # Model routing (which models handle which tasks)
    routing: Dict[str, str] = field(default_factory=lambda: {
        "default": "llama3.2:3b",
        "fast": "llama3.2:1b",
        "code": "codellama:7b",
    })

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    spec_version: str = "1.0.0"


# ── Test Results ──────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    """Results from running a single test suite."""
    suite: str           # "structure" | "brain" | "hardening" | etc.
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class TestReport:
    """Aggregate test results with computed gate level."""
    agent_name: str
    results: List[TestResult] = field(default_factory=list)
    all_passed: bool = False
    gate_level: GateLevel = GateLevel.GENESIS_ONLY
    consecutive_passes: int = 0        # For Botico gate: need 3
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_gate(self) -> GateLevel:
        """Compute the highest gate this report qualifies for."""
        suites = {r.suite: r for r in self.results}

        # Minimum: structure + brain + subsystem must pass
        base_suites = ["structure", "brain", "subsystem"]
        for s in base_suites:
            if s not in suites or suites[s].failed > 0:
                self.gate_level = GateLevel.GENESIS_ONLY
                self.all_passed = False
                return self.gate_level

        # PlugOps: + hardening + governance
        plugops_suites = ["hardening", "governance"]
        plugops_ok = all(
            s in suites and suites[s].failed == 0
            for s in plugops_suites
        )
        if not plugops_ok:
            self.gate_level = GateLevel.GENESIS_ONLY
            self.all_passed = False
            return self.gate_level

        # Botico: + resilience + adversarial, zero failures across ALL, 3 consecutive
        botico_suites = ["resilience", "adversarial"]
        botico_ok = all(
            s in suites and suites[s].failed == 0
            for s in botico_suites
        )
        total_failures = sum(r.failed for r in self.results)
        self.all_passed = total_failures == 0

        if botico_ok and self.all_passed and self.consecutive_passes >= 3:
            self.gate_level = GateLevel.BOTICO_READY
        elif plugops_ok:
            self.gate_level = GateLevel.PLUGOPS_READY
        else:
            self.gate_level = GateLevel.GENESIS_ONLY

        return self.gate_level


# ── Export Manifest ───────────────────────────────────────────────────────────

@dataclass
class ExportManifest:
    """Record of an export operation."""
    agent_name: str
    source_dir: str                    # Where it was built in GENESIS
    target: ExportTarget
    files_exported: List[str] = field(default_factory=list)
    bridge_script: str = ""            # Path to generated bridge script
    checksum: str = ""                 # SHA-256 of the entire agent directory
    exported_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    irreversible: bool = False         # True for Botico exports
    signature: str = ""                # Cryptographic signature of the manifest
    test_report_summary: Dict[str, Any] = field(default_factory=dict)


# ── Build Job ─────────────────────────────────────────────────────────────────

@dataclass
class BuildJob:
    """Tracks the full lifecycle of a build."""
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    spec: Optional[AgentSpec] = None
    status: JobStatus = JobStatus.PENDING
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    agent_dir: Optional[str] = None    # Path to scaffolded agent
    test_report: Optional[TestReport] = None
    export_manifest: Optional[ExportManifest] = None
    errors: List[str] = field(default_factory=list)
    log: List[str] = field(default_factory=list)

    def log_event(self, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {message}")

    def fail(self, error: str) -> None:
        self.status = JobStatus.FAILED
        self.errors.append(error)
        self.log_event(f"FAILED: {error}")
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def complete(self) -> None:
        self.status = JobStatus.COMPLETE
        self.log_event("Build complete")
        self.completed_at = datetime.now(timezone.utc).isoformat()


# ── Botico Registry Entry ────────────────────────────────────────────────────

@dataclass
class BoticoRegistryEntry:
    """Append-only record of an agent exported to Botico. Irreversible."""
    agent_name: str
    exported_at: str
    manifest_checksum: str
    test_summary: Dict[str, Any] = field(default_factory=dict)
    irreversible: bool = True          # Always True — this is the point of no return
