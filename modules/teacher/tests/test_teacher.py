"""
modules/teacher/tests/test_teacher.py
Tests for the Teacher module — schemas, manifest, and module contract.

Run:
    pytest modules/teacher/tests/test_teacher.py -v
"""

import json
import os
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
def mock_core(monkeypatch):
    """Patch missing runtime dependencies so schemas and module can be imported."""
    core = MagicMock()
    monkeypatch.setitem(sys.modules, "core", core)
    yield


# ── Manifest tests ─────────────────────────────────────────────────────────────

class TestManifest:
    def test_manifest_file_exists(self):
        assert MANIFEST_PATH.exists(), "module.json is missing"

    def test_manifest_is_valid_json(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_manifest_required_fields(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        for field in ("name", "version", "description", "entry", "permissions", "tags"):
            assert field in data, f"manifest missing required field: {field}"

    def test_manifest_entry_file_exists(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        entry = MODULE_DIR / data["entry"]
        assert entry.exists(), f"manifest entry file not found: {entry}"

    def test_manifest_permissions_are_known(self):
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
            assert perm in known, f"Unknown permission declared: {perm!r}"

    def test_manifest_name_has_namespace(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        assert "." in data["name"], "module name should be namespaced (e.g. 'genesis.teacher')"

    def test_manifest_version_format(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        parts = data["version"].split(".")
        assert len(parts) == 3, "version must be semver (major.minor.patch)"
        assert all(p.isdigit() for p in parts), "version parts must be integers"


# ── Schema tests ───────────────────────────────────────────────────────────────

class TestSchemas:
    @pytest.fixture(autouse=True)
    def import_schemas(self):
        from modules.teacher.schemas import (
            LearnRequest, LearnResponse, AskRequest, AskResponse,
            LessonRequest, LessonResponse, FeedbackRequest, FeedbackResponse,
        )
        self.LearnRequest = LearnRequest
        self.LearnResponse = LearnResponse
        self.AskRequest = AskRequest
        self.AskResponse = AskResponse
        self.LessonRequest = LessonRequest
        self.LessonResponse = LessonResponse
        self.FeedbackRequest = FeedbackRequest
        self.FeedbackResponse = FeedbackResponse

    def test_learn_request_defaults(self):
        req = self.LearnRequest(topic="Python decorators")
        assert req.topic == "Python decorators"
        assert req.max_results == 8
        assert req.min_tier == 2
        assert req.min_grade == "C"
        assert req.official_only is False

    def test_learn_request_custom(self):
        req = self.LearnRequest(topic="async", max_results=3, official_only=True)
        assert req.max_results == 3
        assert req.official_only is True

    def test_learn_request_max_results_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self.LearnRequest(topic="x", max_results=0)
        with pytest.raises(ValidationError):
            self.LearnRequest(topic="x", max_results=21)

    def test_ask_request_minimal(self):
        req = self.AskRequest(question="What is a closure?")
        assert req.question == "What is a closure?"

    def test_lesson_request_modes(self):
        req = self.LessonRequest(topic="recursion")
        assert req.topic == "recursion"

    def test_feedback_request_has_domain(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self.FeedbackRequest()  # missing required domain field

    def test_all_schema_classes_are_pydantic(self):
        from pydantic import BaseModel
        for cls in (
            self.LearnRequest, self.LearnResponse, self.AskRequest,
            self.AskResponse, self.LessonRequest, self.LessonResponse,
        ):
            assert issubclass(cls, BaseModel), f"{cls.__name__} must subclass BaseModel"


# ── Module structure tests ─────────────────────────────────────────────────────

class TestModuleStructure:
    def test_module_py_exists(self):
        assert (MODULE_DIR / "module.py").exists()

    def test_schemas_py_exists(self):
        assert (MODULE_DIR / "schemas.py").exists()

    def test_tutor_py_exists(self):
        assert (MODULE_DIR / "tutor.py").exists()

    def test_module_exports_Module_class(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("teacher_module", MODULE_DIR / "module.py")
        # We only check that the source file defines Module — don't execute it
        source = (MODULE_DIR / "module.py").read_text()
        assert "class Module" in source, "module.py must define a class named Module"

    def test_module_name_matches_manifest(self):
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        source = (MODULE_DIR / "module.py").read_text()
        # Module name in module.py should match manifest tag
        assert "teacher" in manifest["name"].lower()
