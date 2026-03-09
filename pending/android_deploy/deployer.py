"""
android_deploy/deployer.py
Handles ADB device detection, APK installation, and optional app launch.
"""
from __future__ import annotations
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import ProjectConfig


@dataclass
class Device:
    serial: str
    state: str
    model: str = ""
    product: str = ""


def _adb(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    if not shutil.which("adb"):
        print("  ✗ adb not found — install Android platform-tools and add to PATH")
        sys.exit(1)
    return subprocess.run(["adb", *args],
                          capture_output=capture,
                          text=True)


def list_devices() -> list[Device]:
    result = _adb("devices", "-l")
    devices: list[Device] = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line or "offline" in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        state = parts[1]
        model = ""
        product = ""
        for part in parts[2:]:
            if part.startswith("model:"):
                model = part.split(":", 1)[1]
            elif part.startswith("product:"):
                product = part.split(":", 1)[1]
        devices.append(Device(serial=serial, state=state, model=model, product=product))
    return [d for d in devices if d.state == "device"]


def print_devices(devices: list[Device]) -> None:
    if not devices:
        print("  No devices connected.")
        return
    print(f"\n  {'Serial':25s} {'Model':20s} {'Product'}")
    print(f"  {'-'*25} {'-'*20} {'-'*20}")
    for d in devices:
        print(f"  {d.serial:25s} {d.model:20s} {d.product}")


def pick_device(devices: list[Device], serial: Optional[str] = None) -> Device:
    if not devices:
        print("\n  ✗ No Android devices found. Connect via USB and ensure:")
        print("    • USB debugging is enabled")
        print("    • Device is unlocked")
        print("    • 'Allow USB debugging' popup was accepted")
        sys.exit(1)

    if serial:
        match = [d for d in devices if serial.lower() in d.serial.lower()
                 or serial.lower() in d.model.lower()]
        if not match:
            print(f"\n  ✗ No device matching '{serial}'")
            print_devices(devices)
            sys.exit(1)
        return match[0]

    if len(devices) == 1:
        return devices[0]

    # Multiple devices — prompt
    print("\n  Multiple devices found:")
    print_devices(devices)
    print()
    choice = input("  Enter serial or model name: ").strip()
    return pick_device(devices, serial=choice)


def install_apk(apk: Path, device: Device, dry_run: bool = False) -> None:
    print(f"\n  → Installing APK on {device.model or device.serial}")
    print(f"    {apk}")
    if dry_run:
        print("    [DRY RUN — skipped]")
        return

    result = _adb("-s", device.serial, "install", "-r", str(apk), capture=False)
    if result.returncode != 0:
        raise RuntimeError(f"adb install failed (exit {result.returncode})")
    print("  ✓ Installed")


def launch_app(project: ProjectConfig, device: Device, dry_run: bool = False) -> None:
    if not project.package_name:
        return
    activity = f"{project.package_name}/.MainActivity"
    print(f"\n  → Launching {activity}")
    if dry_run:
        print("    [DRY RUN — skipped]")
        return
    _adb("-s", device.serial,
         "shell", "am", "start", "-n", activity,
         capture=False)


def deploy(apk: Path,
           project: ProjectConfig,
           device_hint: Optional[str] = None,
           launch: bool = True,
           dry_run: bool = False) -> None:
    """Full deploy: detect device → install → optionally launch."""
    print(f"\n{'─' * 60}")
    print(f"  Deploying {project.name}")
    print(f"{'─' * 60}")

    devices = list_devices()
    device = pick_device(devices, serial=device_hint)
    print(f"\n  Target: {device.model or device.serial}  [{device.serial}]")

    install_apk(apk, device, dry_run=dry_run)

    if launch:
        launch_app(project, device, dry_run=dry_run)

    if not dry_run:
        print(f"\n  ✓ {project.name} deployed. Unplug and go.\n")
    else:
        print(f"\n  ✓ Dry run complete — no changes made.\n")
