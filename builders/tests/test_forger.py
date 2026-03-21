"""
Tests for builders/forger.py — agent scaffolding from spec.

Uses a temp directory to avoid touching real GENESIS/agents/.
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from builders.schemas import AgentSpec, AutonomyLevel
from builders.forger import Forger, ForgeError
from builders.template_loader import TemplateLoader


@pytest.fixture
def temp_agents_dir():
    """Create a temporary agents directory for testing."""
    d = tempfile.mkdtemp(prefix="genesis_test_agents_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_spec():
    """A minimal valid AgentSpec for testing."""
    return AgentSpec(
        name="test_agent_0",
        designation="Test Agent Zero",
        role="TESTER",
        mission_text=(
            "You are a test agent created by the GENESIS Builder test suite. "
            "Your purpose is to verify the forging pipeline works correctly."
        ),
        capabilities=["testing", "validation"],
        modules_required=[],
        autonomy_level=AutonomyLevel.SUPERVISED,
    )


class TestForgerValidation:
    def test_rejects_empty_name(self, temp_agents_dir):
        forger = Forger(agents_dir=temp_agents_dir)
        spec = AgentSpec(
            name="", designation="X", role="R",
            mission_text="A valid mission text for testing purposes",
        )
        with pytest.raises(ForgeError, match="Agent name"):
            forger.forge(spec)

    def test_rejects_short_mission(self, temp_agents_dir):
        forger = Forger(agents_dir=temp_agents_dir)
        spec = AgentSpec(
            name="valid_name", designation="X", role="R",
            mission_text="Too short",
        )
        with pytest.raises(ForgeError, match="Mission text"):
            forger.forge(spec)

    def test_rejects_invalid_name_chars(self, temp_agents_dir):
        forger = Forger(agents_dir=temp_agents_dir)
        spec = AgentSpec(
            name="invalid name!", designation="X", role="R",
            mission_text="A valid mission text for testing purposes",
        )
        with pytest.raises(ForgeError, match="alphanumeric"):
            forger.forge(spec)


class TestForgerScaffolding:
    def test_creates_agent_directory(self, temp_agents_dir, sample_spec):
        forger = Forger(agents_dir=temp_agents_dir)
        try:
            agent_dir = forger.forge(sample_spec)
            assert agent_dir.exists()
            assert agent_dir.name == "test_agent_0"
        except ForgeError as e:
            if "template is invalid" in str(e):
                pytest.skip("BlackZero template not available in test environment")
            raise

    def test_generates_identity(self, temp_agents_dir, sample_spec):
        forger = Forger(agents_dir=temp_agents_dir)
        try:
            agent_dir = forger.forge(sample_spec)
            assert (agent_dir / "identity" / "mission.md").exists()
            assert (agent_dir / "identity" / "personality.yaml").exists()

            mission = (agent_dir / "identity" / "mission.md").read_text()
            assert "test agent" in mission.lower()
        except ForgeError as e:
            if "template is invalid" in str(e):
                pytest.skip("BlackZero template not available in test environment")
            raise

    def test_generates_config(self, temp_agents_dir, sample_spec):
        forger = Forger(agents_dir=temp_agents_dir)
        try:
            agent_dir = forger.forge(sample_spec)
            config_path = agent_dir / "config.yaml"
            assert config_path.exists()

            import yaml
            config = yaml.safe_load(config_path.read_text())
            assert config["agent"]["name"] == "test_agent_0"
            assert config["agent"]["designation"] == "Test Agent Zero"
        except ForgeError as e:
            if "template is invalid" in str(e):
                pytest.skip("BlackZero template not available in test environment")
            raise

    def test_generates_modelfile(self, temp_agents_dir, sample_spec):
        forger = Forger(agents_dir=temp_agents_dir)
        try:
            agent_dir = forger.forge(sample_spec)
            modelfile = agent_dir / "Modelfile"
            assert modelfile.exists()
            content = modelfile.read_text()
            assert "FROM llama3.2:3b" in content
            assert "Test Agent Zero" in content
        except ForgeError as e:
            if "template is invalid" in str(e):
                pytest.skip("BlackZero template not available in test environment")
            raise

    def test_generates_main_py(self, temp_agents_dir, sample_spec):
        forger = Forger(agents_dir=temp_agents_dir)
        try:
            agent_dir = forger.forge(sample_spec)
            main = agent_dir / "main.py"
            assert main.exists()
            content = main.read_text()
            assert "BlackZero.loader" in content
            assert "boot" in content
        except ForgeError as e:
            if "template is invalid" in str(e):
                pytest.skip("BlackZero template not available in test environment")
            raise

    def test_writes_build_manifest(self, temp_agents_dir, sample_spec):
        forger = Forger(agents_dir=temp_agents_dir)
        try:
            agent_dir = forger.forge(sample_spec)
            manifest_path = agent_dir / ".build_manifest.json"
            assert manifest_path.exists()

            manifest = json.loads(manifest_path.read_text())
            assert manifest["spec"]["name"] == "test_agent_0"
            assert manifest["template"] == "BlackZero"
        except ForgeError as e:
            if "template is invalid" in str(e):
                pytest.skip("BlackZero template not available in test environment")
            raise

    def test_rejects_duplicate_without_overwrite(self, temp_agents_dir, sample_spec):
        forger = Forger(agents_dir=temp_agents_dir)
        try:
            forger.forge(sample_spec)
            with pytest.raises(ForgeError, match="already exists"):
                forger.forge(sample_spec)
        except ForgeError as e:
            if "template is invalid" in str(e):
                pytest.skip("BlackZero template not available in test environment")
            raise

    def test_allows_overwrite(self, temp_agents_dir, sample_spec):
        forger = Forger(agents_dir=temp_agents_dir)
        try:
            forger.forge(sample_spec)
            agent_dir = forger.forge(sample_spec, overwrite=True)
            assert agent_dir.exists()
        except ForgeError as e:
            if "template is invalid" in str(e):
                pytest.skip("BlackZero template not available in test environment")
            raise
