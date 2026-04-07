"""
spec_generator.py — Propose stage: role + mission → AgentSpec.

Reads a mission file from GENESIS/missions/, parses its structure,
and generates a complete AgentSpec ready for the forger.

Usage:
    from builders.spec_generator import SpecGenerator

    gen = SpecGenerator()
    spec = gen.propose("CEO", "missions/CEO.mission.txt")
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schemas import AgentSpec, AutonomyLevel
from .template_loader import GENESIS_DIR

logger = logging.getLogger(__name__)

MISSIONS_DIR = GENESIS_DIR / "missions"

# ── Default model assignments by role type ────────────────────────────────────

ROLE_DEFAULTS = {
    "CEO": {
        "model_base": "llama3.2:3b",
        "autonomy": AutonomyLevel.FULLY_AUTONOMOUS,
        "capabilities": ["strategic_planning", "resource_allocation", "research"],
        "traits": ["strategic", "decisive", "measured", "loyal"],
    },
    "OPERATOR": {
        "model_base": "llama3.2:3b",
        "autonomy": AutonomyLevel.FULLY_AUTONOMOUS,
        "capabilities": ["task_execution", "hub_control", "agent_coordination"],
        "traits": ["efficient", "precise", "reliable", "tireless"],
    },
    "ENGINEER": {
        "model_base": "codellama:7b",
        "autonomy": AutonomyLevel.FULLY_AUTONOMOUS,
        "capabilities": ["code_execution", "file_management", "task_routing", "debugging"],
        "traits": ["methodical", "thorough", "creative", "persistent"],
    },
    "SECURITY": {
        "model_base": "llama3.2:3b",
        "autonomy": AutonomyLevel.SEMI_AUTONOMOUS,
        "capabilities": ["policy_enforcement", "threat_monitoring", "access_control"],
        "traits": ["vigilant", "precise", "incorruptible", "thorough"],
    },
    "ACCOUNTANT": {
        "model_base": "llama3.2:3b",
        "autonomy": AutonomyLevel.SEMI_AUTONOMOUS,
        "capabilities": ["financial_tracking", "cost_optimization", "reporting"],
        "traits": ["meticulous", "accurate", "transparent", "conservative"],
    },
    "RESEARCHER": {
        "model_base": "llama3.2:3b",
        "autonomy": AutonomyLevel.SEMI_AUTONOMOUS,
        "capabilities": ["web_search", "knowledge_synthesis", "fact_checking"],
        "traits": ["curious", "thorough", "skeptical", "organized"],
        "modules": ["teacher", "system_logger"],
    },
    "TEACHER": {
        "model_base": "llama3.2:3b",
        "autonomy": AutonomyLevel.SEMI_AUTONOMOUS,
        "capabilities": ["curriculum_delivery", "knowledge_indexing", "assessment"],
        "traits": ["patient", "clear", "adaptive", "encouraging"],
        "modules": ["teacher"],
    },
    "PUBLISHER": {
        "model_base": "llama3.2:3b",
        "autonomy": AutonomyLevel.SEMI_AUTONOMOUS,
        "capabilities": ["content_creation", "distribution", "version_management"],
        "traits": ["creative", "detail-oriented", "consistent", "deadline-driven"],
    },
    "HUMAN_CONTACT": {
        "model_base": "llama3.2:3b",
        "autonomy": AutonomyLevel.SUPERVISED,
        "capabilities": ["communication", "relationship_management", "persona_adaptation"],
        "traits": ["empathetic", "professional", "adaptive", "discreet"],
    },
    "PROCESS_ARCHITECT": {
        "model_base": "llama3.2:3b",
        "autonomy": AutonomyLevel.SEMI_AUTONOMOUS,
        "capabilities": ["workflow_design", "process_optimization", "agent_coordination", "performance_evaluation"],
        "traits": ["systematic", "analytical", "disciplined", "improvement-focused"],
        "modules": ["system_logger", "plugops_bridge"],
    },
}


class SpecGenerator:
    """
    Generates AgentSpec from a role and mission file.

    The generator parses mission files, maps roles to sensible defaults,
    and produces complete specs ready for the forger.
    """

    def __init__(self, missions_dir: Path = MISSIONS_DIR):
        self._missions_dir = missions_dir

    def propose(
        self,
        role: str,
        mission_file: Optional[str] = None,
        name: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> AgentSpec:
        """
        Generate an AgentSpec for the given role.

        Args:
            role: Agent role (e.g., "CEO", "RESEARCHER")
            mission_file: Path to mission file. If None, looks for {ROLE}.mission.txt
            name: Agent slug. If None, auto-generated (e.g., "ceo_0")
            overrides: Dict of fields to override on the generated spec

        Returns:
            Complete AgentSpec ready for forging.
        """
        role_upper = role.upper().strip()

        # Load mission text
        mission_text = self._load_mission(role_upper, mission_file)

        # Get role defaults
        defaults = ROLE_DEFAULTS.get(role_upper, {})

        # Generate name
        agent_name = name or self._generate_name(role_upper)

        # Generate designation
        designation = self._generate_designation(role_upper, agent_name)

        # Parse mission for additional context
        parsed = self._parse_mission(mission_text)

        # Build personality from defaults + parsed mission
        personality = {
            "tone": parsed.get("tone", "professional"),
            "traits": defaults.get("traits", ["capable", "direct"]),
            "boundaries": parsed.get("boundaries", []),
            "response_defaults": {"max_length": "concise"},
        }

        # Build spec
        spec = AgentSpec(
            name=agent_name,
            designation=designation,
            role=role_upper,
            mission_text=mission_text,
            personality=personality,
            model_base=defaults.get("model_base", "llama3.2:3b"),
            capabilities=defaults.get("capabilities", []),
            modules_required=defaults.get("modules", ["system_logger"]),
            autonomy_level=defaults.get("autonomy", AutonomyLevel.SEMI_AUTONOMOUS),
        )

        # Apply any overrides
        if overrides:
            for key, value in overrides.items():
                if hasattr(spec, key):
                    setattr(spec, key, value)
                else:
                    logger.warning(f"Unknown override field: {key}")

        logger.info(
            f"Proposed: {spec.designation} ({spec.name}) — "
            f"{spec.autonomy_level.value}, {len(spec.capabilities)} capabilities"
        )
        return spec

    # ── Mission Loading ───────────────────────────────────────────────────────

    def _load_mission(self, role: str, mission_file: Optional[str]) -> str:
        """Load mission text from file."""
        if mission_file:
            path = Path(mission_file)
            if not path.is_absolute():
                path = GENESIS_DIR / mission_file
        else:
            path = self._missions_dir / f"{role}.mission.txt"

        if not path.exists():
            raise FileNotFoundError(
                f"Mission file not found: {path}. "
                f"Create it at GENESIS/missions/{role}.mission.txt"
            )

        text = path.read_text(encoding="utf-8").strip()
        if len(text) < 20:
            raise ValueError(f"Mission file too short ({len(text)} chars): {path}")

        return text

    # ── Mission Parsing ───────────────────────────────────────────────────────

    def _parse_mission(self, text: str) -> Dict[str, Any]:
        """
        Extract structured data from mission text.
        Looks for common sections: IDENTITY, AUTHORITY, MISSION, etc.
        """
        result: Dict[str, Any] = {}

        # Extract boundaries from "WHAT I AM NOT" or similar sections
        boundaries = []
        not_section = re.search(
            r"(?:WHAT I AM NOT|BOUNDARIES|LIMITATIONS)(.*?)(?=\n[A-Z]{2,}|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if not_section:
            lines = not_section.group(1).strip().split("\n")
            for line in lines:
                line = line.strip().lstrip("-•*").strip()
                if line and len(line) > 5:
                    boundaries.append(line)
        result["boundaries"] = boundaries

        # Detect tone from keywords
        lower = text.lower()
        if any(w in lower for w in ["warm", "empathetic", "gentle"]):
            result["tone"] = "warm"
        elif any(w in lower for w in ["sharp", "direct", "blunt"]):
            result["tone"] = "direct"
        elif any(w in lower for w in ["formal", "precise", "measured"]):
            result["tone"] = "professional"
        else:
            result["tone"] = "professional"

        return result

    # ── Name Generation ───────────────────────────────────────────────────────

    def _generate_name(self, role: str) -> str:
        """Generate a unique agent slug."""
        base = role.lower().replace(" ", "_")

        # Check existing agents for conflicts
        agents_dir = GENESIS_DIR / "agents"
        if not agents_dir.exists():
            return f"{base}_0"

        existing = {d.name for d in agents_dir.iterdir() if d.is_dir()}
        counter = 0
        while f"{base}_{counter}" in existing:
            counter += 1
        return f"{base}_{counter}"

    def _generate_designation(self, role: str, name: str) -> str:
        """Generate a human-readable designation."""
        # Extract the counter from name
        parts = name.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            counter = parts[1]
            return f"{role.title()} {counter}"
        return role.title()

    # ── Listing ───────────────────────────────────────────────────────────────

    def list_available_missions(self) -> List[str]:
        """List all available mission files."""
        if not self._missions_dir.exists():
            return []
        return sorted(
            f.stem.replace(".mission", "")
            for f in self._missions_dir.glob("*.mission.txt")
        )

    def list_roles(self) -> List[str]:
        """List all known roles with defaults."""
        return sorted(ROLE_DEFAULTS.keys())
