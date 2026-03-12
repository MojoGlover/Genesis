#!/usr/bin/env python3
"""
scripts/run_tests.py — GENESIS unified test runner

Discovers and runs all test suites:
    - BlackZero/tests/brain_tests.py      (100 brain tests)
    - BlackZero/tests/hardening_tests.py  (failure-path + stress tests)
    - BlackZero/tests/structure_tests.py  (structure + doctor validation)
    - BlackZero/tests/subsystem_tests.py  (subsystem interface tests)
    - modules/teacher/tests/             (teacher module tests)
    - modules/tax/tests/                 (tax module tests)
    - modules/sdimport/tests/            (sdimport module tests)

Usage:
    python3 scripts/run_tests.py            # run everything
    python3 scripts/run_tests.py --brain    # brain tests only
    python3 scripts/run_tests.py --structure  # structure + doctor only
    python3 scripts/run_tests.py --subsystems # subsystem interface tests only
    python3 scripts/run_tests.py --modules  # module tests only
    python3 scripts/run_tests.py -v         # verbose pytest output

Exit code:
    0 = all tests passed
    1 = one or more suites failed
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

SUITES = {
    "brain": [
        "BlackZero/tests/brain_tests.py",
        "BlackZero/tests/hardening_tests.py",
    ],
    "structure": [
        "BlackZero/tests/structure_tests.py",
    ],
    "subsystems": [
        "BlackZero/tests/subsystem_tests.py",
    ],
    "modules": [
        "modules/teacher/tests/",
        "modules/tax/tests/",
        "modules/sdimport/tests/",
    ],
}


def run_suite(name: str, paths: list[str], verbose: bool) -> bool:
    """Run a pytest suite. Returns True if all tests passed."""
    print(f"\n{'='*60}")
    print(f"  Suite: {name}")
    print(f"{'='*60}")

    cmd = [sys.executable, "-m", "pytest"] + paths
    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")
    cmd.append("--tb=short")

    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="GENESIS unified test runner")
    parser.add_argument("--brain",      action="store_true", help="Run brain tests only")
    parser.add_argument("--structure",  action="store_true", help="Run structure tests only")
    parser.add_argument("--subsystems", action="store_true", help="Run subsystem tests only")
    parser.add_argument("--modules",    action="store_true", help="Run module tests only")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose pytest output")
    args = parser.parse_args()

    # Determine which suites to run
    selected = {k for k in SUITES if getattr(args, k.rstrip("s"), False) or getattr(args, k, False)}
    if not selected:
        selected = set(SUITES.keys())  # run everything if no filter

    results: dict[str, bool] = {}
    for suite_name in ("brain", "structure", "subsystems", "modules"):
        if suite_name not in selected:
            continue
        paths = SUITES[suite_name]
        # Only include paths that exist
        existing = [p for p in paths if (REPO_ROOT / p).exists()]
        if not existing:
            print(f"\n  [SKIP] {suite_name} — no test files found")
            continue
        results[suite_name] = run_suite(suite_name, existing, args.verbose)

    # Summary
    print(f"\n{'='*60}")
    print("  RESULTS")
    print(f"{'='*60}")
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print(f"  All {len(results)} suite(s) passed.")
        return 0
    else:
        failed = [n for n, p in results.items() if not p]
        print(f"  {len(failed)} suite(s) FAILED: {failed}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
