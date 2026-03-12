"""
modules/sdimport/tests/test_sdimport.py
Tests for the SDImport module — schemas, manifest, extractor, and structure.

Run:
    pytest modules/sdimport/tests/test_sdimport.py -v
"""

import ast
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Locate module root ─────────────────────────────────────────────────────────
MODULE_DIR = Path(__file__).parent.parent
GENESIS_ROOT = MODULE_DIR.parent.parent
MANIFEST_PATH = MODULE_DIR / "module.json"


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_dependencies(monkeypatch):
    """Patch runtime dependencies not available outside the full agent environment."""
    for mod in ("agents", "agents.tools", "agents.tools.tool_registry"):
        monkeypatch.setitem(sys.modules, mod, MagicMock())
    # register_tool must be a no-op decorator
    sys.modules["agents.tools.tool_registry"].register_tool = (
        lambda **kw: (lambda fn: fn)
    )


# ── Manifest tests ─────────────────────────────────────────────────────────────

class TestManifest:
    def test_manifest_exists(self):
        assert MANIFEST_PATH.exists()

    def test_manifest_valid_json(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_manifest_required_fields(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        for field in ("name", "version", "description", "entry", "permissions", "tags"):
            assert field in data

    def test_manifest_entry_file_exists(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        assert (MODULE_DIR / data["entry"]).exists()

    def test_manifest_permissions_known(self):
        known = {
            "read:packages", "write:packages",
            "read:filesystem", "write:filesystem",
            "read:network", "write:network",
            "read:memory", "write:memory",
            "execute:process",
        }
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        for perm in data.get("permissions", []):
            assert perm in known, f"Unknown permission: {perm!r}"

    def test_manifest_has_correct_name_prefix(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        assert data["name"].startswith("genesis.")


# ── Schema tests ───────────────────────────────────────────────────────────────

class TestSchemas:
    @pytest.fixture(autouse=True)
    def import_schemas(self):
        from modules.sdimport.schemas import (
            ImportRequest, ImportResponse, SaveRequest, SaveResponse
        )
        self.ImportRequest = ImportRequest
        self.ImportResponse = ImportResponse
        self.SaveRequest = SaveRequest
        self.SaveResponse = SaveResponse

    def test_import_request_requires_source(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self.ImportRequest()  # source is required

    def test_import_request_defaults_build_workflow(self):
        req = self.ImportRequest(source="https://civitai.com/images/12345")
        assert req.build_workflow is True

    def test_import_request_can_disable_workflow(self):
        req = self.ImportRequest(source="/path/to/image.png", build_workflow=False)
        assert req.build_workflow is False

    def test_import_response_all_fields(self):
        response = self.ImportResponse(
            source_type="url",
            source_url="https://example.com/img.png",
            positive="a dog in a field",
            negative="blurry",
            model="dreamshaper",
            steps=20,
            cfg=7.0,
            seed=42,
            sampler="euler",
            scheduler="normal",
            width=512,
            height=512,
        )
        assert response.positive == "a dog in a field"
        assert response.workflow is None  # optional

    def test_import_response_with_workflow(self):
        response = self.ImportResponse(
            source_type="png",
            source_url="/path/img.png",
            positive="test",
            negative="",
            model="sd15",
            steps=15,
            cfg=6.5,
            seed=0,
            sampler="dpm",
            scheduler="karras",
            width=768,
            height=768,
            workflow={"node_1": {"type": "CLIPTextEncode"}},
        )
        assert isinstance(response.workflow, dict)

    def test_save_request_requires_workflow(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self.SaveRequest()

    def test_save_request_optional_filename(self):
        req = self.SaveRequest(workflow={"test": "data"})
        assert req.filename is None
        assert req.output_dir is None

    def test_save_response_fields(self):
        r = self.SaveResponse(saved_path="/tmp/test.json", filename="test.json")
        assert r.saved_path == "/tmp/test.json"

    def test_all_schemas_are_pydantic(self):
        from pydantic import BaseModel
        for cls in (self.ImportRequest, self.ImportResponse,
                    self.SaveRequest, self.SaveResponse):
            assert issubclass(cls, BaseModel)


# ── Extractor syntax + structure tests ────────────────────────────────────────

class TestExtractor:
    EXTRACTOR_PATH = MODULE_DIR / "extractor.py"

    def test_extractor_file_exists(self):
        assert self.EXTRACTOR_PATH.exists()

    def test_extractor_has_valid_syntax(self):
        source = self.EXTRACTOR_PATH.read_text()
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"extractor.py has a syntax error: {e}")

    def test_extractor_defines_extract_function(self):
        source = self.EXTRACTOR_PATH.read_text()
        assert "def extract" in source, "extractor.py must define an extract() function"

    def test_extractor_defines_build_workflow(self):
        source = self.EXTRACTOR_PATH.read_text()
        assert "def build_comfyui_workflow" in source

    def test_extractor_handles_supported_source_types(self):
        source = self.EXTRACTOR_PATH.read_text()
        # Should reference key platforms
        for platform in ("civitai", "png"):
            assert platform.lower() in source.lower(), f"extractor should handle {platform}"


# ── Module structure tests ─────────────────────────────────────────────────────

class TestModuleStructure:
    def test_module_py_exists(self):
        assert (MODULE_DIR / "module.py").exists()

    def test_schemas_py_exists(self):
        assert (MODULE_DIR / "schemas.py").exists()

    def test_extractor_py_exists(self):
        assert (MODULE_DIR / "extractor.py").exists()

    def test_module_defines_Module_class(self):
        source = (MODULE_DIR / "module.py").read_text()
        assert "class Module" in source

    def test_module_defines_endpoints(self):
        source = (MODULE_DIR / "module.py").read_text()
        assert "/sdimport/import" in source
        assert "/sdimport/save" in source
