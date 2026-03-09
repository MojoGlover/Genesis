"""
eas_build — Expo Application Services cloud build wrapper.

Trigger EAS cloud builds for Android (APK/AAB) or iOS (IPA)
without needing a local Android/iOS SDK. Results download automatically.

Quick start:
    cd /Users/darnieglover/ai/GENESIS
    python -m eas_build --help
    python -m eas_build --platform android --profile preview
    python -m eas_build --platform ios --profile production
    python -m eas_build --status          # check latest build
    python -m eas_build --download        # download latest artifact
"""
from .builder import trigger_build, get_build_status, download_artifact
from .config import EAS_CONFIG, PROFILES

__all__ = [
    "trigger_build", "get_build_status",
    "download_artifact", "EAS_CONFIG", "PROFILES",
]
