"""
modules/tax/tests/test_tax.py
Tests for the Tax module — schemas, manifest, engine logic, and year coverage.

Run:
    pytest modules/tax/tests/test_tax.py -v
"""

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
def mock_core(monkeypatch):
    """Patch missing runtime dependencies."""
    core = MagicMock()
    monkeypatch.setitem(sys.modules, "core", core)


@pytest.fixture(scope="session")
def tax_engine_path(tmp_path_factory):
    """
    Add the tax engine directory to sys.path under the alias tax_engine,
    so calculator.py can resolve 'from tax_engine.years import get_year'.
    """
    engine_dir = str(MODULE_DIR)
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    # Alias engine/* as tax_engine.*
    import importlib, types
    if "tax_engine" not in sys.modules:
        tax_engine = types.ModuleType("tax_engine")
        tax_engine.__path__ = [str(MODULE_DIR / "engine")]
        tax_engine.__package__ = "tax_engine"
        sys.modules["tax_engine"] = tax_engine
    yield


# ── Manifest tests ─────────────────────────────────────────────────────────────

class TestManifest:
    def test_manifest_file_exists(self):
        assert MANIFEST_PATH.exists()

    def test_manifest_valid_json(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_manifest_required_fields(self):
        with open(MANIFEST_PATH) as f:
            data = json.load(f)
        for field in ("name", "version", "description", "entry", "permissions", "tags"):
            assert field in data, f"missing field: {field}"

    def test_manifest_entry_exists(self):
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


# ── Year file structure tests ──────────────────────────────────────────────────

class TestYearFiles:
    YEARS_DIR = MODULE_DIR / "engine" / "years"

    def test_years_directory_exists(self):
        assert self.YEARS_DIR.is_dir()

    def test_expected_year_files_present(self):
        for year in ("y2024", "y2025", "y2026"):
            assert (self.YEARS_DIR / f"{year}.py").exists(), f"Missing year file: {year}.py"

    def test_base_year_file_exists(self):
        assert (self.YEARS_DIR / "base.py").exists()

    def test_year_files_define_TaxYear_class(self):
        for year in ("y2024", "y2025", "y2026"):
            source = (self.YEARS_DIR / f"{year}.py").read_text()
            assert "class TaxYear" in source, f"{year}.py must define a TaxYear class"

    def test_years_registry_has_three_years(self):
        source = (self.YEARS_DIR / "__init__.py").read_text()
        for year in (2024, 2025, 2026):
            assert str(year) in source, f"Year {year} not in registry"


# ── Engine logic tests (with tax_engine alias) ─────────────────────────────────

class TestTaxEngine:
    @pytest.fixture(autouse=True)
    def setup_engine(self, tax_engine_path):
        """Ensure the tax_engine alias is set up before engine tests."""
        pass

    def test_base_module_importable(self):
        from modules.tax.engine.years.base import BracketResult
        assert BracketResult is not None

    def test_bracket_result_is_dataclass(self):
        from modules.tax.engine.years.base import BracketResult
        import dataclasses
        assert dataclasses.is_dataclass(BracketResult)

    def test_year_files_import_independently(self):
        """Each year file should be parseable Python."""
        import ast
        years_dir = MODULE_DIR / "engine" / "years"
        for year in ("y2024", "y2025", "y2026"):
            source = (years_dir / f"{year}.py").read_text()
            try:
                ast.parse(source)
            except SyntaxError as e:
                pytest.fail(f"{year}.py has a syntax error: {e}")

    def test_concepts_file_exists_and_nonempty(self):
        concepts_file = MODULE_DIR / "engine" / "concepts.py"
        assert concepts_file.exists()
        assert len(concepts_file.read_text()) > 100, "concepts.py appears to be empty"


# ── Module structure tests ─────────────────────────────────────────────────────

class TestModuleStructure:
    def test_module_py_exists(self):
        assert (MODULE_DIR / "module.py").exists()

    def test_engine_directory_exists(self):
        assert (MODULE_DIR / "engine").is_dir()

    def test_engine_forms_directory_exists(self):
        assert (MODULE_DIR / "engine" / "forms").is_dir()

    def test_schedule_c_file_exists(self):
        assert (MODULE_DIR / "engine" / "forms" / "schedule_c.py").exists()

    def test_module_defines_Module_class(self):
        source = (MODULE_DIR / "module.py").read_text()
        assert "class Module" in source

    def test_module_inline_pydantic_models(self):
        source = (MODULE_DIR / "module.py").read_text()
        assert "BaseModel" in source, "module.py should define Pydantic request/response models"

    def test_supported_years_in_source(self):
        source = (MODULE_DIR / "module.py").read_text()
        for year in ("2024", "2025", "2026"):
            assert year in source, f"Year {year} not referenced in module.py"
