"""emulator/manager.py — AVD lifecycle management."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
from typing import Optional

from .config import ANDROID_HOME, EMULATOR_BIN, AVD_MANAGER, EMULATOR_CONFIG, DEFAULT_AVD


def _sdk_ok() -> bool:
    return os.path.isfile(EMULATOR_BIN)


def _check_sdk() -> None:
    if not _sdk_ok():
        print(f"  ✗ Android emulator not found at: {EMULATOR_BIN}")
        print(f"    Set ANDROID_HOME or install Android Studio.")
        sys.exit(1)


def list_avds() -> list[str]:
    """Return list of existing AVD names."""
    _check_sdk()
    result = subprocess.run(
        [EMULATOR_BIN, "-list-avds"],
        capture_output=True, text=True
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def start_avd(name: str = DEFAULT_AVD, wait: bool = True, dry_run: bool = False) -> Optional[subprocess.Popen]:
    """Start an AVD. Returns the Popen handle (background process)."""
    _check_sdk()
    existing = list_avds()
    if name not in existing:
        print(f"  ✗ AVD '{name}' not found. Available: {existing or 'none'}")
        print(f"    Run: python -m emulator --create --name {name}")
        sys.exit(1)

    cmd = [EMULATOR_BIN, "-avd", name, "-no-snapshot-save", "-gpu", "auto"]
    print(f"  → Starting AVD: {name}")
    print(f"    {' '.join(cmd)}")

    if dry_run:
        print("    [DRY RUN — skipped]")
        return None

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if wait:
        print("    Waiting for device to boot", end="", flush=True)
        for _ in range(60):
            time.sleep(2)
            result = subprocess.run(
                ["adb", "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True
            )
            if result.stdout.strip() == "1":
                print(" ✓")
                break
            print(".", end="", flush=True)
        else:
            print("\n  ⚠ Timed out waiting for boot — emulator may still be starting.")

    return proc


def stop_avd(name: Optional[str] = None, dry_run: bool = False) -> None:
    """Stop a running emulator (all if name is None)."""
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    emulators = [
        line.split()[0] for line in result.stdout.splitlines()[1:]
        if line.startswith("emulator-")
    ]
    if not emulators:
        print("  No running emulators found.")
        return
    for emu in emulators:
        print(f"  → Stopping {emu}")
        if not dry_run:
            subprocess.run(["adb", "-s", emu, "emu", "kill"], capture_output=True)
    if not dry_run:
        print("  ✓ Stopped")


def create_avd(name: str = DEFAULT_AVD, dry_run: bool = False) -> None:
    """Create a new AVD using the profile from config."""
    _check_sdk()
    profile = EMULATOR_CONFIG.get(name)
    if not profile:
        print(f"  ✗ No config profile for '{name}'.")
        print(f"    Known profiles: {list(EMULATOR_CONFIG.keys())}")
        sys.exit(1)

    cmd = [
        AVD_MANAGER, "create", "avd",
        "--name", name,
        "--device", profile["device"],
        "--package", f"system-images;android-{profile['api']};{profile['abi']}",
        "--force",
    ]
    print(f"  → Creating AVD '{name}' ({profile['description']})")
    print(f"    {' '.join(cmd)}")

    if dry_run:
        print("    [DRY RUN — skipped]")
        return

    result = subprocess.run(cmd, input="no\n", text=True, capture_output=False)
    if result.returncode != 0:
        raise RuntimeError(f"avdmanager create failed (exit {result.returncode})")
    print(f"  ✓ AVD '{name}' created")


def wipe_avd(name: str = DEFAULT_AVD, dry_run: bool = False) -> None:
    """Wipe AVD data (cold reset — useful after bad state)."""
    cmd = [EMULATOR_BIN, "-avd", name, "-wipe-data", "-no-window", "-no-audio"]
    print(f"  → Wiping AVD data: {name}")
    if dry_run:
        print("    [DRY RUN — skipped]")
        return
    subprocess.run(cmd + ["-quit-after-boot", "1"], capture_output=True)
    print("  ✓ Wiped")
