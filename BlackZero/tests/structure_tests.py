# structure_tests.py
# REPOSITORY STRUCTURE TESTS
#
# Responsibility:
#   Verifies that the full Genesis repository structure is valid
#   and that doctor.py passes cleanly.
#
# Expected tests:
#   - test_required_root_folders_exist()
#       Assert all required root folders are present
#   - test_pending_exists()
#       Assert pending/ is present
#   - test_blackzero_exists()
#       Assert BlackZero/ is present
#   - test_blackzero_subfolders_exist()
#       Assert all required BlackZero subfolders are present
#   - test_docs_required_files_exist()
#       Assert genesis_rules.md, architecture.md, blackzero_spec.md exist in docs/
#   - test_doctor_passes()
#       Run doctor.py as a subprocess and assert exit code 0
#
# Run with:
#   python -m pytest BlackZero/tests/structure_tests.py
#   or
#   python BlackZero/tests/structure_tests.py

import os
import sys
import subprocess

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))

REQUIRED_ROOT_FOLDERS = [
    "BlackZero", "modules", "agents", "builders", "evals",
    "datasets", "scripts", "configs", "docs", "docker", "pending"
]

REQUIRED_BLACKZERO_FOLDERS = [
    "brain", "identity", "memory", "storage", "rag",
    "tools", "models", "policies", "diagnostics", "tests"
]

REQUIRED_DOCS = ["genesis_rules.md", "architecture.md", "blackzero_spec.md"]


def test_required_root_folders_exist():
    for folder in REQUIRED_ROOT_FOLDERS:
        path = os.path.join(REPO_ROOT, folder)
        assert os.path.isdir(path), f"Missing required root folder: {folder}/"


def test_pending_exists():
    assert os.path.isdir(os.path.join(REPO_ROOT, "pending")), "pending/ does not exist"


def test_blackzero_exists():
    assert os.path.isdir(os.path.join(REPO_ROOT, "BlackZero")), "BlackZero/ does not exist"


def test_blackzero_subfolders_exist():
    for folder in REQUIRED_BLACKZERO_FOLDERS:
        path = os.path.join(REPO_ROOT, "BlackZero", folder)
        assert os.path.isdir(path), f"Missing BlackZero subfolder: {folder}/"


def test_docs_required_files_exist():
    for doc in REQUIRED_DOCS:
        path = os.path.join(REPO_ROOT, "docs", doc)
        assert os.path.isfile(path), f"Missing required doc: docs/{doc}"


def test_doctor_passes():
    doctor_path = os.path.join(REPO_ROOT, "BlackZero", "diagnostics", "doctor.py")
    result = subprocess.run([sys.executable, doctor_path], capture_output=True, text=True)
    assert result.returncode == 0, f"doctor.py failed:\n{result.stdout}\n{result.stderr}"


if __name__ == "__main__":
    failures = []
    for test in [
        test_required_root_folders_exist,
        test_pending_exists,
        test_blackzero_exists,
        test_blackzero_subfolders_exist,
        test_docs_required_files_exist,
        test_doctor_passes,
    ]:
        try:
            test()
            print(f"  [PASS] {test.__name__}")
        except AssertionError as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            failures.append(test.__name__)

    if failures:
        sys.exit(1)
    else:
        print("\nAll structure tests passed.")
        sys.exit(0)
