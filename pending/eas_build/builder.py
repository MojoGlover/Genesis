"""eas_build/builder.py — EAS cloud build trigger and artifact download."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

from .config import EAS_CONFIG, PROFILES, DEFAULT_PROFILE


def _eas_ok() -> bool:
    return bool(shutil.which("eas"))


def _check_eas() -> None:
    if not _eas_ok():
        print("  ✗ eas CLI not found.")
        print("    Install: npm install -g eas-cli")
        print("    Then login: eas login")
        sys.exit(1)


def _run(cmd: list[str], cwd: str, dry_run: bool = False) -> subprocess.CompletedProcess:
    print(f"  → {' '.join(cmd)}")
    if dry_run:
        print("    [DRY RUN — skipped]")
        return subprocess.CompletedProcess(cmd, 0)
    return subprocess.run(cmd, cwd=cwd)


def trigger_build(project_key: str = "madjanet",
                  platform: str = "android",
                  profile: str = DEFAULT_PROFILE,
                  dry_run: bool = False) -> None:
    """Trigger an EAS cloud build."""
    _check_eas()
    cfg = EAS_CONFIG.get(project_key)
    if not cfg:
        print(f"  ✗ Unknown project: {project_key}")
        sys.exit(1)

    print(f"\n  ── EAS Build ────────────────────────────────────────────────")
    print(f"  Project  : {project_key}")
    print(f"  Platform : {platform}")
    print(f"  Profile  : {profile}  ({PROFILES.get(profile, {}).get('description', '')})")
    print()

    cmd = [
        "eas", "build",
        "--platform", platform,
        "--profile", profile,
        "--non-interactive",
    ]
    result = _run(cmd, cwd=cfg["root"], dry_run=dry_run)
    if result.returncode != 0:
        raise RuntimeError(f"EAS build failed (exit {result.returncode})")

    if not dry_run:
        print(f"\n  ✓ Build submitted. Monitor at: https://expo.dev/accounts/{cfg.get('owner', 'you')}/projects/{cfg.get('slug', project_key)}/builds")


def get_build_status(project_key: str = "madjanet",
                     platform: str = "android") -> None:
    """Show latest build status via EAS CLI."""
    _check_eas()
    cfg = EAS_CONFIG.get(project_key, {})
    cmd = ["eas", "build:list", "--platform", platform, "--limit", "3", "--json"]
    result = subprocess.run(cmd, cwd=cfg.get("root", "."),
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ Could not get build list: {result.stderr.strip()}")
        return
    try:
        builds = json.loads(result.stdout)
        print(f"\n  Latest builds ({platform}):")
        for b in builds:
            status    = b.get("status", "?")
            created   = b.get("createdAt", "?")[:16].replace("T", " ")
            artifact  = b.get("artifacts", {}).get("buildUrl", "—")
            print(f"    {status:12s}  {created}  {artifact}")
    except Exception:
        print(result.stdout)


def download_artifact(url: str, dest: Optional[str] = None) -> Path:
    """Download a build artifact (APK/IPA) from EAS."""
    filename = url.split("/")[-1].split("?")[0] or "build-artifact"
    dest_path = Path(dest or os.path.expanduser(f"~/Downloads/{filename}"))
    print(f"  → Downloading: {filename}")
    print(f"    → {dest_path}")
    urllib.request.urlretrieve(url, dest_path)
    size_mb = dest_path.stat().st_size / (1024 * 1024)
    print(f"  ✓ {size_mb:.1f} MB saved to {dest_path}")
    return dest_path
