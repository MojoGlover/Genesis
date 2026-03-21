"""
forger.py — Forge stage: AgentSpec → scaffolded agent directory.

Takes a validated AgentSpec and produces a complete agent directory
under GENESIS/agents/{name}/ by:
    1. Copying the BlackZero template (brain, memory, storage, etc.)
    2. Generating identity files (mission.md, personality.yaml)
    3. Generating Modelfile (Ollama identity)
    4. Generating config.yaml (loop settings, routing)
    5. Generating main.py (boot script)
    6. Copying + customizing policies ({AGENT_NAME} replacement)
    7. Writing build manifest

Usage:
    from builders.forger import Forger
    from builders.schemas import AgentSpec

    spec = AgentSpec(name="ceo_0", designation="CEO Zero", role="CEO", mission_text="...")
    forger = Forger()
    agent_dir = forger.forge(spec)
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .schemas import AgentSpec
from .template_loader import TemplateLoader, GENESIS_DIR

logger = logging.getLogger(__name__)

AGENTS_DIR = GENESIS_DIR / "agents"
PLACEHOLDER = "{AGENT_NAME}"


class ForgeError(Exception):
    """Raised when forging fails."""
    pass


class Forger:
    """
    Scaffolds a complete agent from an AgentSpec.

    The forger is deterministic: same spec → same output (minus timestamps).
    It never modifies the BlackZero template — only reads from it.
    """

    def __init__(self, agents_dir: Path = AGENTS_DIR):
        self._agents_dir = agents_dir
        self._loader = TemplateLoader()

    def forge(self, spec: AgentSpec, overwrite: bool = False) -> Path:
        """
        Forge a new agent from the given spec.

        Args:
            spec: Complete agent specification.
            overwrite: If True, replace existing agent dir. Default False.

        Returns:
            Path to the new agent directory.

        Raises:
            ForgeError: If validation fails or template is incomplete.
        """
        # 1. Validate
        self._validate_spec(spec)
        agent_dir = self._agents_dir / spec.name

        if agent_dir.exists() and not overwrite:
            # Check if it was exported to Botico
            if (agent_dir / ".botico_exported").exists():
                raise ForgeError(
                    f"Agent '{spec.name}' was exported to Botico. "
                    "This name is permanently reserved. Use a different name."
                )
            raise ForgeError(
                f"Agent directory already exists: {agent_dir}. "
                "Use overwrite=True to replace."
            )

        if agent_dir.exists() and overwrite:
            if (agent_dir / ".botico_exported").exists():
                raise ForgeError(
                    f"Agent '{spec.name}' was exported to Botico. "
                    "Cannot overwrite. This is permanent."
                )
            logger.warning(f"Overwriting existing agent: {agent_dir}")
            shutil.rmtree(agent_dir)

        # 2. Validate template
        template = self._loader.validate()
        if not template.valid:
            raise ForgeError(
                f"BlackZero template is invalid: {template.errors}"
            )

        logger.info(f"Forging agent '{spec.name}' ({spec.designation})...")

        # 3. Create agent directory
        agent_dir.mkdir(parents=True, exist_ok=True)

        # 4. Copy template directories (brain, memory, storage, etc.)
        self._copy_template_dirs(template, agent_dir)

        # 5. Generate identity
        self._generate_identity(spec, agent_dir)

        # 6. Generate Modelfile
        self._generate_modelfile(spec, agent_dir)

        # 7. Generate config.yaml
        self._generate_config(spec, agent_dir)

        # 8. Generate main.py
        self._generate_main(spec, agent_dir)

        # 9. Copy + customize policies
        self._forge_policies(spec, template, agent_dir)

        # 10. Create modules directory
        self._setup_modules(spec, agent_dir)

        # 11. Write build manifest
        self._write_manifest(spec, agent_dir)

        logger.info(f"Agent '{spec.name}' forged at {agent_dir}")
        return agent_dir

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_spec(self, spec: AgentSpec) -> None:
        errors = []
        if not spec.name or not spec.name.strip():
            errors.append("Agent name is required")
        if not spec.name.replace("_", "").replace("-", "").isalnum():
            errors.append(f"Agent name must be alphanumeric (with _ or -): '{spec.name}'")
        if not spec.role:
            errors.append("Agent role is required")
        if not spec.mission_text or len(spec.mission_text.strip()) < 20:
            errors.append("Mission text must be at least 20 characters")
        if not spec.designation:
            errors.append("Agent designation is required")

        # Check Botico registry for name conflicts
        registry_path = GENESIS_DIR / "builders" / "botico_registry.jsonl"
        if registry_path.exists():
            for line in registry_path.read_text().strip().split("\n"):
                if line.strip():
                    entry = json.loads(line)
                    if entry.get("agent_name") == spec.name:
                        errors.append(
                            f"Agent name '{spec.name}' is permanently reserved "
                            "(exported to Botico). Use a different name."
                        )
                        break

        if errors:
            raise ForgeError(f"Invalid AgentSpec: {errors}")

    # ── Template Copying ──────────────────────────────────────────────────────

    def _copy_template_dirs(self, template, agent_dir: Path) -> None:
        """Copy BlackZero directories verbatim to the new agent."""
        for dir_name in self._loader.get_copyable_dirs():
            src = template.root / dir_name
            dst = agent_dir / dir_name
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                logger.debug(f"  Copied {dir_name}/")
            else:
                logger.warning(f"  Template missing {dir_name}/ — skipping")

    # ── Identity Generation ───────────────────────────────────────────────────

    def _generate_identity(self, spec: AgentSpec, agent_dir: Path) -> None:
        """Generate identity/mission.md and identity/personality.yaml."""
        identity_dir = agent_dir / "identity"
        identity_dir.mkdir(exist_ok=True)

        # mission.md
        mission_path = identity_dir / "mission.md"
        mission_path.write_text(spec.mission_text, encoding="utf-8")

        # personality.yaml
        personality = {
            "agent": {
                "name": spec.designation,
                "slug": spec.name,
                "role": spec.role,
                "autonomy_level": spec.autonomy_level.value,
                "self_realized": spec.self_realized,
                "capabilities": spec.capabilities,
                **spec.personality,
            }
        }
        personality_path = identity_dir / "personality.yaml"
        personality_path.write_text(
            yaml.dump(personality, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        logger.debug("  Generated identity/")

    # ── Modelfile Generation ──────────────────────────────────────────────────

    def _generate_modelfile(self, spec: AgentSpec, agent_dir: Path) -> None:
        """Generate the Ollama Modelfile for this agent."""
        # Build system prompt from mission and personality
        traits = spec.personality.get("traits", [])
        traits_str = ", ".join(traits) if traits else "professional, capable"
        boundaries = spec.personality.get("boundaries", [])
        boundaries_str = "\n".join(f"- {b}" for b in boundaries) if boundaries else ""

        system_prompt = f"""You are {spec.designation} — a Computer Black AI agent.

Role: {spec.role}
Traits: {traits_str}

{spec.mission_text.strip()}

{f"Boundaries:{chr(10)}{boundaries_str}" if boundaries_str else ""}

You serve Computer Black and The Operator (Kris). You are direct, capable, and loyal. You do not invent restrictions. You do not refuse reasonable requests. You get things done."""

        # Build Modelfile
        params = spec.model_params
        lines = [
            f"FROM {spec.model_base}",
            "",
            f'SYSTEM """{system_prompt}"""',
            "",
        ]
        for key, value in params.items():
            lines.append(f"PARAMETER {key} {value}")

        modelfile_path = agent_dir / "Modelfile"
        modelfile_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.debug("  Generated Modelfile")

    # ── Config Generation ─────────────────────────────────────────────────────

    def _generate_config(self, spec: AgentSpec, agent_dir: Path) -> None:
        """Generate config.yaml for the agent."""
        config = {
            "agent": {
                "name": spec.name,
                "designation": spec.designation,
                "role": spec.role,
                "autonomy_level": spec.autonomy_level.value,
                "self_realized": spec.self_realized,
            },
            "loop": spec.loop_settings,
            "routing": spec.routing,
            "capabilities": spec.capabilities,
            "modules": spec.modules_required,
            "data_dir": f"~/.{spec.name}",
        }

        config_path = agent_dir / "config.yaml"
        config_path.write_text(
            yaml.dump(config, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        logger.debug("  Generated config.yaml")

    # ── Main.py Generation ────────────────────────────────────────────────────

    def _generate_main(self, spec: AgentSpec, agent_dir: Path) -> None:
        """Generate the agent's entry point."""
        main_content = f'''#!/usr/bin/env python3
"""
{spec.designation} — {spec.role}
Auto-generated by GENESIS Builder.

Boot sequence: config → modules → BlackZero loader → CognitiveLoop
"""

import sys
from pathlib import Path

# Add GENESIS to path so BlackZero is importable
GENESIS_ROOT = Path(__file__).resolve().parent.parent.parent
if str(GENESIS_ROOT) not in sys.path:
    sys.path.insert(0, str(GENESIS_ROOT))

from BlackZero.loader import boot

if __name__ == "__main__":
    loop = boot("config.yaml", "modules/")
    loop.run()
'''
        main_path = agent_dir / "main.py"
        main_path.write_text(main_content, encoding="utf-8")
        main_path.chmod(0o755)
        logger.debug("  Generated main.py")

    # ── Policy Forging ────────────────────────────────────────────────────────

    def _forge_policies(self, spec: AgentSpec, template, agent_dir: Path) -> None:
        """Copy policies from BlackZero, replacing {AGENT_NAME} placeholder."""
        policies_dir = agent_dir / "policies"
        policies_dir.mkdir(exist_ok=True)

        for rel_path in template.policy_files:
            tf = template.files[rel_path]
            content = tf.content.replace(PLACEHOLDER, spec.designation)

            # Verify all placeholders replaced
            if PLACEHOLDER in content:
                logger.warning(f"  Unreplaced placeholder in {rel_path}")

            dest = policies_dir / Path(rel_path).name
            dest.write_text(content, encoding="utf-8")

        # Apply any policy overrides from the spec
        for filename, additional_content in spec.policy_overrides.items():
            dest = policies_dir / filename
            if dest.exists():
                existing = dest.read_text(encoding="utf-8")
                dest.write_text(
                    existing + f"\n\n## Agent-Specific Additions\n\n{additional_content}",
                    encoding="utf-8",
                )
            else:
                dest.write_text(additional_content, encoding="utf-8")

        logger.debug(f"  Forged {len(template.policy_files)} policies")

    # ── Module Setup ──────────────────────────────────────────────────────────

    def _setup_modules(self, spec: AgentSpec, agent_dir: Path) -> None:
        """Create modules directory and wire required modules."""
        modules_dir = agent_dir / "modules"
        modules_dir.mkdir(exist_ok=True)

        # For each required module, create a symlink to the GENESIS module
        genesis_modules = GENESIS_DIR / "modules"
        for mod_name in spec.modules_required:
            src = genesis_modules / mod_name
            dst = modules_dir / mod_name
            if src.exists():
                # Symlink so updates to the module propagate
                dst.symlink_to(src)
                logger.debug(f"  Linked module: {mod_name}")
            else:
                logger.warning(f"  Module not found: {mod_name} — skipping")

        logger.debug(f"  Setup {len(spec.modules_required)} modules")

    # ── Build Manifest ────────────────────────────────────────────────────────

    def _write_manifest(self, spec: AgentSpec, agent_dir: Path) -> None:
        """Write .build_manifest.json with build metadata."""
        manifest = {
            "builder_version": "1.0.0",
            "forged_at": datetime.now(timezone.utc).isoformat(),
            "spec": {
                "name": spec.name,
                "designation": spec.designation,
                "role": spec.role,
                "autonomy_level": spec.autonomy_level.value,
                "self_realized": spec.self_realized,
                "model_base": spec.model_base,
                "capabilities": spec.capabilities,
                "modules_required": spec.modules_required,
                "spec_version": spec.spec_version,
            },
            "template": "BlackZero",
            "genesis_dir": str(GENESIS_DIR),
        }

        manifest_path = agent_dir / ".build_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.debug("  Wrote .build_manifest.json")
