"""eas_build/config.py — EAS project config for Computer Black apps."""
import os

AI_ROOT = os.path.expanduser("~/ai")

EAS_CONFIG = {
    "madjanet": {
        "root":       os.path.join(AI_ROOT, "MadJanet"),
        "slug":       "madjanet",
        "owner":      "computerblack",   # Expo account username
        "project_id": None,              # Set after: eas init
    },
}

# EAS build profiles (must match eas.json in project root)
PROFILES = {
    "preview": {
        "android": {"buildType": "apk"},    # Direct APK, no signing needed
        "ios":     {"simulator": False},
        "description": "Shareable APK/IPA for testing",
    },
    "production": {
        "android": {"buildType": "aab"},    # Play Store bundle
        "ios":     {"simulator": False},
        "description": "Production-signed build",
    },
    "simulator": {
        "ios": {"simulator": True},
        "description": "iOS Simulator build (no device needed)",
    },
}

DEFAULT_PROFILE = "preview"
