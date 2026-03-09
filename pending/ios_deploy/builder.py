"""ios_deploy/builder.py — iOS build and deploy logic."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import IOS_CONFIG, SIDELOAD_METHODS


def _check_tool(name: str, install_hint: str) -> None:
    if not shutil.which(name):
        print(f"  ✗ '{name}' not found.")
        print(f"    {install_hint}")
        sys.exit(1)


def build_ios(project_key: str = "madjanet",
              profile: str = "preview",
              dry_run: bool = False) -> None:
    """Trigger an EAS iOS build (requires EAS account + Apple Developer)."""
    _check_tool("eas", "npm install -g eas-cli  then: eas login")

    cfg = IOS_CONFIG.get(project_key)
    if not cfg:
        print(f"  ✗ Unknown project: {project_key}")
        sys.exit(1)

    if not cfg.get("team_id") or not cfg.get("apple_id"):
        print("  ⚠  Apple Developer credentials not configured.")
        print("     Set team_id and apple_id in ios_deploy/config.py")
        print("     Requires: Apple Developer Program enrollment ($99/yr)")
        print()
        print("  Alternative: use --sideload for free cable-based install")
        sys.exit(0)

    cmd = ["eas", "build", "--platform", "ios", "--profile", profile, "--non-interactive"]
    print(f"  → EAS iOS build: {project_key} ({profile})")
    print(f"    {' '.join(cmd)}")
    if dry_run:
        print("    [DRY RUN — skipped]")
        return
    result = subprocess.run(cmd, cwd=cfg["root"])
    if result.returncode != 0:
        raise RuntimeError("EAS iOS build failed")


def submit_testflight(project_key: str = "madjanet",
                      build_url: str = "",
                      dry_run: bool = False) -> None:
    """Submit a completed IPA to TestFlight via EAS Submit."""
    _check_tool("eas", "npm install -g eas-cli")

    cfg = IOS_CONFIG.get(project_key, {})
    cmd = ["eas", "submit", "--platform", "ios", "--non-interactive"]
    if build_url:
        cmd += ["--url", build_url]

    print(f"  → Submitting to TestFlight: {project_key}")
    print(f"    {' '.join(cmd)}")
    if dry_run:
        print("    [DRY RUN — skipped]")
        return
    subprocess.run(cmd, cwd=cfg.get("root", "."))


def sideload(project_key: str = "madjanet",
             ipa_path: str = "",
             method: str = "altserver",
             dry_run: bool = False) -> None:
    """
    Sideload an IPA via AltServer or Sideloadly (free, no Dev account).
    These are GUI tools — we launch them and print instructions.
    """
    method_cfg = SIDELOAD_METHODS.get(method)
    if not method_cfg:
        print(f"  ✗ Unknown sideload method: {method}")
        print(f"    Available: {', '.join(SIDELOAD_METHODS.keys())}")
        sys.exit(1)

    print(f"\n  ── Sideload via {method} ─────────────────────────────────────")
    print(f"  {method_cfg['description']}")
    print(f"  Requires: {method_cfg['requires']}")
    print(f"  Cable:    {'Required' if method_cfg['cable'] else 'Not required'}")

    if method == "altserver":
        print("""
  Steps:
    1. Run AltServer on this Mac (menu bar icon)
    2. Connect iPhone/iPad via USB
    3. Open AltStore on device → tap '+' → select IPA
    4. IPA refreshes every 7 days (run AltServer on same WiFi)
""")
    elif method == "sideloadly":
        print("""
  Steps:
    1. Open Sideloadly on this Mac
    2. Connect device via USB
    3. Drag IPA into Sideloadly window
    4. Enter your Apple ID → Install
    5. Trust cert: Settings → General → VPN & Device Mgmt
""")

    if ipa_path and os.path.isfile(ipa_path):
        print(f"  IPA: {ipa_path}")
        if method == "sideloadly" and shutil.which("open"):
            if not dry_run:
                subprocess.run(["open", "-a", "Sideloadly"])
