"""
android_deploy/builder.py
Handles JS bundling (expo export:embed) and APK compilation (gradlew).
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .config import ProjectConfig


def _run(cmd: list[str], cwd: str, label: str, dry_run: bool = False) -> None:
    print(f"\n  → {label}")
    print(f"    {' '.join(cmd)}")
    if dry_run:
        print("    [DRY RUN — skipped]")
        return
    result = subprocess.run(cmd, cwd=cwd, capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed (exit {result.returncode})")


def check_prerequisites(project: ProjectConfig) -> list[str]:
    """Return list of missing prerequisites."""
    issues: list[str] = []

    if not os.path.isdir(project.root):
        issues.append(f"Project root not found: {project.root}")
        return issues  # Can't check further

    nm = os.path.join(project.root, "node_modules")
    if not os.path.isdir(nm):
        issues.append("node_modules missing — run: npm install")

    gradle_wrapper = os.path.join(project.root, "android", "gradlew")
    if not os.path.isfile(gradle_wrapper):
        issues.append("android/gradlew not found — run: npx expo prebuild")

    if not shutil.which("npx"):
        issues.append("npx not found — install Node.js")

    # Check Java (needed by gradlew)
    if not shutil.which("java"):
        issues.append("java not found — install JDK 17+")

    return issues


def bundle_js(project: ProjectConfig, dry_run: bool = False) -> None:
    """Run expo export:embed to produce the JS bundle."""
    assets_dir = os.path.join(project.root, "android", "app", "src", "main", "assets")
    os.makedirs(assets_dir, exist_ok=True)

    cmd = [
        "npx", "expo", "export:embed",
        "--platform", "android",
        "--entry-file", project.entry_file,
        "--bundle-output", project.bundle_output,
        "--assets-dest", project.assets_dest,
        "--dev", "false",
    ]
    _run(cmd, cwd=project.root, label="Bundle JS (expo export:embed)", dry_run=dry_run)


def build_apk(project: ProjectConfig, dry_run: bool = False) -> Path:
    """Run gradlew to compile the release APK. Returns path to APK."""
    gradle = "./gradlew" if os.name != "nt" else "gradlew.bat"
    cmd = [gradle, project.gradle_task, "--quiet"]
    android_dir = os.path.join(project.root, "android")
    _run(cmd, cwd=android_dir, label=f"Build APK (gradlew {project.gradle_task})", dry_run=dry_run)

    apk = Path(project.root) / project.apk_path
    if not dry_run and not apk.exists():
        raise FileNotFoundError(f"Expected APK not found after build: {apk}")
    return apk


def build(project: ProjectConfig, dry_run: bool = False, skip_bundle: bool = False) -> Optional[Path]:
    """Full build pipeline: bundle JS → compile APK. Returns APK path."""
    print(f"\n{'=' * 60}")
    print(f"  Building {project.name}")
    print(f"{'=' * 60}")
    t0 = time.time()

    issues = check_prerequisites(project)
    if issues:
        print("\n  ✗ Prerequisites missing:")
        for i in issues:
            print(f"    • {i}")
        sys.exit(1)

    if not skip_bundle:
        bundle_js(project, dry_run=dry_run)
    else:
        print("\n  → Bundle JS [SKIPPED — --skip-bundle]")

    apk = build_apk(project, dry_run=dry_run)

    elapsed = time.time() - t0
    if not dry_run:
        size_mb = apk.stat().st_size / (1024 * 1024)
        print(f"\n  ✓ APK ready: {apk}")
        print(f"    Size: {size_mb:.1f} MB  |  Time: {elapsed:.0f}s")
    else:
        print(f"\n  ✓ Dry run complete ({elapsed:.1f}s)")

    return apk
