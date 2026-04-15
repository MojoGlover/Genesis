"""
termux.py — GPS provider for Android/Termux (PlugToo)

Uses the Termux:API plugin to access Android hardware GPS.
Requires: pkg install termux-api (in Termux)
          Install "Termux:API" app from F-Droid or Play Store

termux-location command returns JSON:
  {
    "latitude": 27.9506,
    "longitude": -82.4572,
    "altitude": 15.0,
    "accuracy": 5.0,
    "bearing": 0.0,
    "speed": 0.0,
    "elapsedMs": 1200,
    "provider": "gps"     // "gps" | "network" | "passive"
  }
"""

from __future__ import annotations
import json
import subprocess
from typing import Optional
from datetime import datetime, timezone


class TermuxGPSProvider:
    """
    Wraps the termux-location command.
    Works on Android with Termux + Termux:API installed.
    """

    PROVIDERS = ["gps", "network", "passive"]

    def __init__(self, preferred_provider: str = "gps", timeout: int = 30):
        self.preferred_provider = preferred_provider
        self.timeout = timeout

    def is_available(self) -> bool:
        """Check if termux-location is installed."""
        try:
            result = subprocess.run(
                ["which", "termux-location"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_location(self, provider: Optional[str] = None) -> Optional[dict]:
        """
        Call termux-location and return structured location dict.
        Falls through providers: gps → network → passive.
        Returns None if all providers fail.
        """
        providers_to_try = (
            [provider] if provider
            else [self.preferred_provider, "network", "passive"]
        )

        for prov in providers_to_try:
            result = self._call_termux(prov)
            if result:
                return result

        return None

    def _call_termux(self, provider: str) -> Optional[dict]:
        try:
            proc = subprocess.run(
                ["termux-location", "-p", provider, "-r", "once"],
                capture_output=True, text=True,
                timeout=self.timeout,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return None

            raw = json.loads(proc.stdout)

            # termux-location returns an error object if unavailable
            if "error" in raw:
                return None

            return {
                "latitude":  float(raw.get("latitude",  0)),
                "longitude": float(raw.get("longitude", 0)),
                "altitude":  float(raw.get("altitude",  0)),
                "accuracy":  float(raw.get("accuracy",  9999)),
                "speed":     float(raw.get("speed",     0)),
                "heading":   float(raw.get("bearing",   0)),
                "provider":  raw.get("provider", provider),
                "elapsed_ms": int(raw.get("elapsedMs", 0)),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source":    "termux",
            }

        except subprocess.TimeoutExpired:
            return None
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
        except Exception:
            return None

    def get_location_updates(self, callback, interval_seconds: int = 30,
                              max_updates: int = 0):
        """
        Poll for location updates.
        callback(location: dict) is called for each fix.
        max_updates=0 means run indefinitely.
        """
        import time
        count = 0
        while True:
            loc = self.get_location()
            if loc:
                callback(loc)
                count += 1
            if max_updates > 0 and count >= max_updates:
                break
            time.sleep(interval_seconds)
