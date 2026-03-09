"""
emulator — Android Virtual Device (AVD) manager for Computer Black.

Create, start, stop, wipe, and list Android emulators so you can
iterate on MadJanet without plugging in the Teklast every time.

Quick start:
    cd /Users/darnieglover/ai/GENESIS
    python -m emulator --help
    python -m emulator --list
    python -m emulator --start
    python -m emulator --create --name CB_Tablet --device "pixel_tablet"
"""
from .manager import list_avds, start_avd, stop_avd, create_avd, wipe_avd
from .config import DEFAULT_AVD, EMULATOR_CONFIG

__all__ = [
    "list_avds", "start_avd", "stop_avd",
    "create_avd", "wipe_avd",
    "DEFAULT_AVD", "EMULATOR_CONFIG",
]
