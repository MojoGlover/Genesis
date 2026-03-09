"""ios_deploy/config.py — iOS build config for Computer Black."""
import os

AI_ROOT = os.path.expanduser("~/ai")

IOS_CONFIG = {
    "madjanet": {
        "root":          os.path.join(AI_ROOT, "MadJanet"),
        "bundle_id":     "com.computerblack.madjanet",
        "display_name":  "MadJanet",
        "team_id":       None,   # Apple Developer Team ID — set when enrolled
        "apple_id":      None,   # Apple ID email — set for TestFlight submit
        "eas_profile":   "preview",
        "description":   "MadJanet voice assistant — iOS/iPadOS",
    },
}

# Sideload methods (no Apple Dev account needed for these)
SIDELOAD_METHODS = {
    "altserver": {
        "description": "AltStore via AltServer (free, 7-day cert)",
        "requires":    "AltServer running on Mac + AltStore on device",
        "cable":       True,
    },
    "sideloadly": {
        "description": "Sideloadly GUI tool (free Apple ID)",
        "requires":    "Sideloadly installed on Mac",
        "cable":       True,
    },
}
