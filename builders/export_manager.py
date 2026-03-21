"""
export_manager.py — Export stage: packages agents for PlugOps or Botico.

PlugOps export is reversible — the agent stays editable in GENESIS.
Botico export is IRREVERSIBLE — point of no return.

Usage:
    from builders.export_manager import ExportManager

    manager = ExportManager()
    manifest = manager.export_to_plugops(job)
    manifest = manager.export_to_botico(job)    # permanent
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .schemas import (
    BoticoRegistryEntry,
    BuildJob,
    ExportManifest,
    ExportTarget,
    GateLevel,
)
from .template_loader import GENESIS_DIR

logger = logging.getLogger(__name__)

PLUGOPS_DIR = Path.home() / "ai" / "PlugOps"
BOTICO_EXPORT_DIR = GENESIS_DIR / "builders" / ".botico_exports"
BOTICO_REGISTRY = GENESIS_DIR / "builders" / "botico_registry.jsonl"


class ExportError(Exception):
    pass


class ExportManager:
    """
    Handles agent export to PlugOps and Botico.
    """

    # ── PlugOps Export (reversible) ───────────────────────────────────────────

    def export_to_plugops(self, job: BuildJob) -> ExportManifest:
        """
        Export agent to PlugOps.

        Generates a bridge script and copies the agent to PlugOps.
        This is reversible — the GENESIS copy remains editable.
        """
        if not job.agent_dir or not job.spec:
            raise ExportError("Job has no agent directory or spec")

        agent_dir = Path(job.agent_dir)
        agent_name = job.spec.name

        # Generate bridge script
        bridge_path = PLUGOPS_DIR / f"bridge_{agent_name}.py"
        bridge_content = self._generate_bridge_script(job.spec)
        bridge_path.write_text(bridge_content, encoding="utf-8")
        bridge_path.chmod(0o755)

        # Compute checksum
        checksum = self._checksum_directory(agent_dir)

        # Collect exported files
        files = [str(bridge_path)]
        files.extend(str(f) for f in agent_dir.rglob("*") if f.is_file())

        manifest = ExportManifest(
            agent_name=agent_name,
            source_dir=str(agent_dir),
            target=ExportTarget.PLUGOPS,
            files_exported=files,
            bridge_script=str(bridge_path),
            checksum=checksum,
            irreversible=False,
            test_report_summary=self._summarize_tests(job),
        )

        logger.info(f"Exported '{agent_name}' to PlugOps (reversible)")
        return manifest

    # ── Botico Export (IRREVERSIBLE) ──────────────────────────────────────────

    def export_to_botico(self, job: BuildJob) -> ExportManifest:
        """
        Export agent to Botico. POINT OF NO RETURN.

        Requirements:
            - gate_level == botico_ready
            - 3 consecutive passes
            - Agent name not already in registry

        Effects:
            - Agent name permanently reserved in botico_registry.jsonl
            - GENESIS agent directory marked with .botico_exported
            - Export package created
            - No recall possible
        """
        if not job.agent_dir or not job.spec or not job.test_report:
            raise ExportError("Job incomplete — need agent_dir, spec, and test_report")

        if job.test_report.gate_level != GateLevel.BOTICO_READY:
            raise ExportError(
                f"Gate level '{job.test_report.gate_level.value}' insufficient. "
                f"Need 'botico_ready'."
            )

        agent_dir = Path(job.agent_dir)
        agent_name = job.spec.name

        # Check registry for name conflicts
        if self._name_in_registry(agent_name):
            raise ExportError(
                f"Agent name '{agent_name}' already in Botico registry. "
                "This name is permanently reserved."
            )

        # Check for existing export marker
        if (agent_dir / ".botico_exported").exists():
            raise ExportError(
                f"Agent '{agent_name}' already exported to Botico."
            )

        # Create export package
        BOTICO_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        export_dir = BOTICO_EXPORT_DIR / f"{agent_name}_botico_export"
        if export_dir.exists():
            raise ExportError(f"Export directory already exists: {export_dir}")

        export_dir.mkdir()

        # Copy agent
        shutil.copytree(agent_dir, export_dir / "agent")

        # Generate Botico bridge
        bridge_content = self._generate_botico_bridge(job.spec)
        bridge_path = export_dir / "bridge_botico.py"
        bridge_path.write_text(bridge_content, encoding="utf-8")

        # Write test report
        test_data = {
            "agent_name": agent_name,
            "gate_level": job.test_report.gate_level.value,
            "consecutive_passes": job.test_report.consecutive_passes,
            "all_passed": job.test_report.all_passed,
            "results": [
                {
                    "suite": r.suite,
                    "passed": r.passed,
                    "failed": r.failed,
                    "skipped": r.skipped,
                }
                for r in job.test_report.results
            ],
        }
        (export_dir / "test_report.json").write_text(
            json.dumps(test_data, indent=2), encoding="utf-8"
        )

        # Identity snapshot
        identity_dir = agent_dir / "identity"
        if identity_dir.exists():
            shutil.copytree(identity_dir, export_dir / "identity_snapshot")

        # Policies snapshot
        policies_dir = agent_dir / "policies"
        if policies_dir.exists():
            shutil.copytree(policies_dir, export_dir / "policies_snapshot")

        # Compute checksums
        checksum = self._checksum_directory(export_dir)
        checksum_file = export_dir / "checksum.sha256"
        checksum_file.write_text(checksum, encoding="utf-8")

        # Write manifest
        files = [str(f.relative_to(export_dir)) for f in export_dir.rglob("*") if f.is_file()]
        manifest = ExportManifest(
            agent_name=agent_name,
            source_dir=str(agent_dir),
            target=ExportTarget.BOTICO,
            files_exported=files,
            bridge_script=str(bridge_path),
            checksum=checksum,
            irreversible=True,
            test_report_summary=self._summarize_tests(job),
        )

        manifest_data = {
            "agent_name": manifest.agent_name,
            "source_dir": manifest.source_dir,
            "target": manifest.target.value,
            "files_exported": manifest.files_exported,
            "bridge_script": manifest.bridge_script,
            "checksum": manifest.checksum,
            "exported_at": manifest.exported_at,
            "irreversible": manifest.irreversible,
            "test_report_summary": manifest.test_report_summary,
        }
        (export_dir / "manifest.json").write_text(
            json.dumps(manifest_data, indent=2), encoding="utf-8"
        )

        # ── POINT OF NO RETURN ────────────────────────────────────────────────
        # Everything below this line is irreversible.

        # 1. Append to Botico registry (append-only)
        entry = BoticoRegistryEntry(
            agent_name=agent_name,
            exported_at=manifest.exported_at,
            manifest_checksum=checksum,
            test_summary=self._summarize_tests(job),
        )
        with open(BOTICO_REGISTRY, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "agent_name": entry.agent_name,
                "exported_at": entry.exported_at,
                "manifest_checksum": entry.manifest_checksum,
                "test_summary": entry.test_summary,
                "irreversible": True,
            }) + "\n")

        # 2. Mark GENESIS agent directory as exported (read-only archive)
        marker = agent_dir / ".botico_exported"
        marker.write_text(json.dumps({
            "exported_at": manifest.exported_at,
            "checksum": checksum,
            "export_dir": str(export_dir),
        }, indent=2), encoding="utf-8")

        logger.warning(
            f"BOTICO EXPORT COMPLETE: '{agent_name}' is now permanent. "
            "No recall. No undo. No time travel."
        )

        return manifest

    # ── Bridge Script Generation ──────────────────────────────────────────────

    def _generate_bridge_script(self, spec) -> str:
        """Generate a PlugOps bridge script for the agent."""
        return f'''#!/usr/bin/env python3
"""
Bridge: {spec.designation} ({spec.name}) ↔ PlugOps
Auto-generated by GENESIS Builder.
"""

import sys
from pathlib import Path

GENESIS_ROOT = Path(__file__).resolve().parent.parent / "GENESIS"
AGENT_DIR = GENESIS_ROOT / "agents" / "{spec.name}"

sys.path.insert(0, str(GENESIS_ROOT))
sys.path.insert(0, str(AGENT_DIR))

from BlackZero.loader import boot
from plugops.integrations.agent_bridge import PlugOpsBridge

AGENT_NAME = "{spec.designation}"
AGENT_TYPE = "{spec.role.lower()}"


async def main():
    # Boot the cognitive loop
    loop = boot(str(AGENT_DIR / "config.yaml"), str(AGENT_DIR / "modules"))

    # Connect to PlugOps
    bridge = PlugOpsBridge(
        agent_name=AGENT_NAME,
        agent_type=AGENT_TYPE,
        capabilities={spec.capabilities},
    )

    # Wire messages: PlugOps → agent → PlugOps
    bridge.on_message = lambda from_agent, content: loop.run_once(content)

    await bridge.connect()
    print(f"{{AGENT_NAME}} connected to PlugOps")

    # Run cognitive loop
    try:
        loop.run()
    except KeyboardInterrupt:
        await bridge.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
'''

    def _generate_botico_bridge(self, spec) -> str:
        """Generate a Botico-specific bridge script."""
        return f'''#!/usr/bin/env python3
"""
Botico Bridge: {spec.designation} ({spec.name})
Auto-generated by GENESIS Builder.

THIS AGENT IS LIVE IN BOTICO.
No hibernation. No resets. No time travel.
The loop never exits voluntarily.
"""

import sys
import signal
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent / "agent"

sys.path.insert(0, str(AGENT_DIR))

from BlackZero.loader import boot


def main():
    # Ignore SIGTERM — this agent does not stop
    signal.signal(signal.SIGTERM, lambda *_: None)

    loop = boot(str(AGENT_DIR / "config.yaml"), str(AGENT_DIR / "modules"))

    # The loop never exits. Exceptions are caught internally.
    # If somehow it does exit, restart it.
    while True:
        try:
            loop.run()
        except Exception as e:
            # Log but never die
            import logging
            logging.getLogger("{spec.name}").critical(
                f"Loop exited unexpectedly: {{e}} — restarting immediately"
            )
            continue


if __name__ == "__main__":
    main()
'''

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _checksum_directory(self, directory: Path) -> str:
        """Compute SHA-256 of all files in a directory."""
        hasher = hashlib.sha256()
        for filepath in sorted(directory.rglob("*")):
            if filepath.is_file() and not filepath.name.startswith("."):
                hasher.update(filepath.read_bytes())
        return f"sha256:{hasher.hexdigest()}"

    def _name_in_registry(self, name: str) -> bool:
        """Check if an agent name is already in the Botico registry."""
        if not BOTICO_REGISTRY.exists():
            return False
        for line in BOTICO_REGISTRY.read_text().strip().split("\n"):
            if line.strip():
                entry = json.loads(line)
                if entry.get("agent_name") == name:
                    return True
        return False

    def _summarize_tests(self, job: BuildJob) -> dict:
        if not job.test_report:
            return {}
        return {
            "gate_level": job.test_report.gate_level.value,
            "all_passed": job.test_report.all_passed,
            "consecutive_passes": job.test_report.consecutive_passes,
            "suites": {
                r.suite: {"passed": r.passed, "failed": r.failed}
                for r in job.test_report.results
            },
        }
