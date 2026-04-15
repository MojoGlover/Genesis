"""
module.py — GPSModule: main GPS class for PlugToo (Android) and PlugWan

Device detection:
  - Android/Termux: uses termux-location command (hardware GPS)
  - Any device:     falls back to IP geolocation (city-level)

Integrates with:
  - TripTracker for mileage logging
  - PlugOps location reporting endpoint
  - irs_forms_export for tax-ready mileage records

Usage (on PlugToo):
    from gps import GPSModule
    gps = GPSModule(device="plugtoo")
    loc = gps.get_location()
    gps.start_trip("Amazon Flex - Afternoon")
    ...
    trip = gps.stop_trip()
    print(trip.summary())
    print(gps.mileage_record(tax_year=2024))
"""

from __future__ import annotations
import os
import sys
import logging
from typing import Optional

from .providers.termux import TermuxGPSProvider
from .providers.ip_fallback import IPGeolocationProvider
from .tracker import TripTracker, Trip, IRS_MILEAGE_RATES
from .geocoder import reverse_geocode, distance_between

logger = logging.getLogger("gps.module")


class GPSModule:
    """
    Unified GPS interface. Auto-detects best provider for the current device.

    Provider priority:
      1. Termux (Android hardware GPS) — precise, <10m
      2. IP geolocation fallback       — city-level, ~5km
    """

    def __init__(
        self,
        device: str = "plugtoo",
        storage_path: str = "~/.mojo_gps_trips.json",
        plugops_url: Optional[str] = None,
        auto_detect_provider: bool = True,
    ):
        self.device = device
        self.plugops_url = plugops_url or os.environ.get(
            "PLUGOPS_URL", "https://plugops-581737577470.us-central1.run.app"
        )

        # Provider selection
        self._termux  = TermuxGPSProvider()
        self._ip      = IPGeolocationProvider()
        self._use_termux = (auto_detect_provider and self._termux.is_available())

        # Trip tracker
        self.tracker = TripTracker(storage_path=storage_path)

        logger.info(
            f"GPSModule init: device={device}, "
            f"provider={'termux' if self._use_termux else 'ip-fallback'}"
        )

    # ── Location ──────────────────────────────────────────────────────────────

    def get_location(self, geocode: bool = True) -> Optional[dict]:
        """
        Get current location. Returns enriched location dict or None.

        Args:
            geocode: If True, adds 'address' field via reverse geocoding.
        """
        loc = None

        if self._use_termux:
            loc = self._termux.get_location()
            if loc is None:
                logger.warning("Termux GPS failed, falling back to IP")
                loc = self._ip.get_location()
        else:
            loc = self._ip.get_location()

        if loc is None:
            logger.error("All GPS providers failed")
            return None

        loc["device"] = self.device

        # Reverse geocode if requested and we have hardware GPS (not IP)
        if geocode and loc.get("source") != "ip" and loc.get("accuracy", 9999) < 500:
            address = reverse_geocode(loc["latitude"], loc["longitude"])
            if address:
                loc["address"] = address

        # Feed waypoint to active trip
        if self.tracker.active_trip:
            self.tracker.add_waypoint(loc)

        return loc

    def get_coordinates(self) -> Optional[tuple]:
        """Quick (lat, lon) tuple. Returns None if unavailable."""
        loc = self.get_location(geocode=False)
        if loc:
            return (loc["latitude"], loc["longitude"])
        return None

    # ── Trip management ───────────────────────────────────────────────────────

    def start_trip(self, label: str = "Trip",
                   purpose: str = "business") -> Trip:
        trip = self.tracker.start_trip(label=label, purpose=purpose, device=self.device)
        # Capture starting point immediately
        loc = self.get_location(geocode=False)
        logger.info(f"Trip started: '{label}' | purpose={purpose}")
        return trip

    def stop_trip(self) -> Optional[Trip]:
        trip = self.tracker.stop_trip()
        if trip:
            logger.info(f"Trip stopped: '{trip.label}' | "
                        f"{trip.distance_miles:.2f} mi | "
                        f"{trip.duration_minutes:.0f} min")
        return trip

    def cancel_trip(self) -> None:
        self.tracker.cancel_trip()

    @property
    def active_trip(self) -> Optional[Trip]:
        return self.tracker.active_trip

    # ── Mileage / tax integration ─────────────────────────────────────────────

    def mileage_record(self, tax_year: Optional[int] = None) -> dict:
        """
        Returns MileageRecord-compatible dict for irs_forms_export.

        Example:
            from irs_forms_export import load_accountant_data
            agent_data["mileage"] = gps.mileage_record(tax_year=2024)
            tax_return = load_accountant_data(agent_data)
        """
        return self.tracker.to_mileage_record(tax_year=tax_year)

    def mileage_summary(self, tax_year: Optional[int] = None) -> str:
        """Human-readable mileage summary for Accountant agent."""
        return self.tracker.summary(tax_year=tax_year)

    # ── PlugOps reporting ────────────────────────────────────────────────────

    def report_to_plugops(self, location: Optional[dict] = None) -> bool:
        """
        POST current location to PlugOps /api/v1/location/report.
        Returns True on success.
        """
        import urllib.request
        import urllib.error
        import json
        from datetime import datetime, timezone

        loc = location or self.get_location(geocode=False)
        if not loc:
            return False

        payload = {
            "device":    self.device,
            "latitude":  loc["latitude"],
            "longitude": loc["longitude"],
            "altitude":  loc.get("altitude", 0),
            "accuracy":  loc.get("accuracy", 9999),
            "speed":     loc.get("speed", 0),
            "heading":   loc.get("heading", 0),
            "timestamp": loc.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "source":    loc.get("source", "unknown"),
        }

        try:
            url = f"{self.plugops_url}/api/v1/location/report"
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"PlugOps location report failed: {e}")
            return False

    # ── Utility ───────────────────────────────────────────────────────────────

    def distance_to(self, lat: float, lon: float) -> Optional[dict]:
        """Distance from current position to given coordinates."""
        coords = self.get_coordinates()
        if coords is None:
            return None
        return distance_between(coords[0], coords[1], lat, lon)

    def status(self) -> dict:
        """Module status dict — useful for Accountant/Janet status check."""
        loc = self.get_location(geocode=False)
        return {
            "device":       self.device,
            "provider":     "termux" if self._use_termux else "ip-fallback",
            "location":     loc,
            "active_trip":  self.tracker.active_trip.label if self.tracker.active_trip else None,
            "trips_logged": len(self.tracker.trips),
            "plugops_url":  self.plugops_url,
        }
