"""emulator/config.py — AVD profiles for Computer Black projects."""
import os

# Path to Android SDK — respects env override
ANDROID_HOME = os.environ.get("ANDROID_HOME") or os.environ.get(
    "ANDROID_SDK_ROOT", os.path.expanduser("~/Library/Android/sdk")
)
EMULATOR_BIN = os.path.join(ANDROID_HOME, "emulator", "emulator")
AVD_MANAGER   = os.path.join(ANDROID_HOME, "cmdline-tools", "latest", "bin", "avdmanager")
SDK_MANAGER   = os.path.join(ANDROID_HOME, "cmdline-tools", "latest", "bin", "sdkmanager")

# Default AVD — tablet profile matching Teklast form factor
DEFAULT_AVD = "CB_Tablet"

EMULATOR_CONFIG = {
    "CB_Tablet": {
        "device":    "pixel_tablet",        # 10.95" landscape tablet
        "api":       "34",                  # Android 14
        "abi":       "google_apis/x86_64",
        "ram_mb":    2048,
        "heap_mb":   512,
        "skin":      "1920x1200",
        "description": "Teklast-sized Android tablet (1920x1200, API 34)",
    },
    "CB_Phone": {
        "device":    "pixel_6",
        "api":       "34",
        "abi":       "google_apis/x86_64",
        "ram_mb":    2048,
        "heap_mb":   256,
        "skin":      "1080x2400",
        "description": "Phone layout test device",
    },
}
