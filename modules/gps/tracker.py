"""
tracker.py — Trip and mileage tracker

Tracks trips (start/stop/waypoints) and computes:
  - Distance via Haversine formula
  - IRS-deductible mileage amount
  - Trip log exportable to irs_forms_export mileage format

Persists trips to ~/.mojo_gps_trips.json
"""

from __future__ import annotations
import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4


# ─── IRS mileage rates ────────────────────────────────────────────────────────

IRS_MILEAGE_RATES = {
    2024: 0.67,
    2025: 0.70,
    2026: 0.70,   # Projected; update when IRS announces
}

TRIP_PURPOSES = ["business", "personal", "commute", "medical", "charity"]


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Waypoint:
    lat:       float
    lon:       float
    altitude:  float = 0.0
    accuracy:  float = 9999.0
    speed:     float = 0.0
    timestamp: str   = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Trip:
    id:           str   = field(default_factory=lambda: str(uuid4()))
    label:        str   = "Trip"
    purpose:      str   = "business"
    device:       str   = "plugtoo"
    start_time:   str   = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time:     Optional[str] = None
    waypoints:    List[Waypoint] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.end_time is None

    @property
    def distance_miles(self) -> float:
        if len(self.waypoints) < 2:
            return 0.0
        total = 0.0
        for i in range(1, len(self.waypoints)):
            total += _haversine_miles(
                self.waypoints[i-1].lat, self.waypoints[i-1].lon,
                self.waypoints[i].lat,   self.waypoints[i].lon,
            )
        return round(total, 3)

    @property
    def duration_minutes(self) -> float:
        end = self.end_time or datetime.now(timezone.utc).isoformat()
        try:
            s = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end.replace("Z", "+00:00"))
            return (e - s).total_seconds() / 60.0
        except Exception:
            return 0.0

    def irs_deduction(self, tax_year: Optional[int] = None) -> float:
        """IRS-deductible amount for business trips."""
        if self.purpose != "business":
            return 0.0
        year = tax_year or datetime.now().year
        rate = IRS_MILEAGE_RATES.get(year, IRS_MILEAGE_RATES[2024])
        return round(self.distance_miles * rate, 2)

    def to_mileage_record(self, tax_year: Optional[int] = None) -> dict:
        """Convert to irs_forms_export MileageRecord format."""
        year = tax_year or datetime.now().year
        rate = IRS_MILEAGE_RATES.get(year, IRS_MILEAGE_RATES[2024])
        return {
            "total_business_miles": self.distance_miles,
            "irs_rate_per_mile":    rate,
            "computed_deduction":   self.irs_deduction(year),
        }

    def summary(self) -> str:
        deduction = self.irs_deduction()
        lines = [
            f"Trip:     {self.label}",
            f"Purpose:  {self.purpose}",
            f"Distance: {self.distance_miles:.2f} miles",
            f"Duration: {self.duration_minutes:.0f} minutes",
            f"Waypoints:{len(self.waypoints)}",
        ]
        if self.purpose == "business" and deduction > 0:
            year = datetime.now().year
            rate = IRS_MILEAGE_RATES.get(year, IRS_MILEAGE_RATES[2024])
            lines.append(f"IRS deduction ({year}): ${deduction:.2f} @ ${rate}/mi")
        return "\n".join(lines)


# ─── TripTracker ──────────────────────────────────────────────────────────────

class TripTracker:
    """
    Manages active trip and persists completed trips.

    Usage:
        tracker = TripTracker()
        tracker.start_trip("Amazon Flex - Morning", purpose="business")
        tracker.add_waypoint({"latitude": 27.95, "longitude": -82.46, ...})
        trip = tracker.stop_trip()
        print(trip.summary())

        # All trips for tax export
        miles = tracker.total_business_miles(tax_year=2024)
        record = tracker.to_mileage_record(tax_year=2024)
    """

    def __init__(self, storage_path: str = "~/.mojo_gps_trips.json"):
        self.storage_path = os.path.expanduser(storage_path)
        self.active_trip: Optional[Trip] = None
        self.trips: List[Trip] = []
        self._load()

    # ── Trip lifecycle ────────────────────────────────────────────────────────

    def start_trip(self, label: str = "Trip",
                   purpose: str = "business",
                   device: str = "plugtoo") -> Trip:
        """Start a new trip. Stops any active trip first."""
        if self.active_trip:
            self.stop_trip()

        if purpose not in TRIP_PURPOSES:
            raise ValueError(f"purpose must be one of {TRIP_PURPOSES}")

        self.active_trip = Trip(label=label, purpose=purpose, device=device)
        return self.active_trip

    def add_waypoint(self, location: dict) -> None:
        """Add a location fix to the active trip."""
        if not self.active_trip:
            return
        wp = Waypoint(
            lat=float(location.get("latitude", 0)),
            lon=float(location.get("longitude", 0)),
            altitude=float(location.get("altitude", 0)),
            accuracy=float(location.get("accuracy", 9999)),
            speed=float(location.get("speed", 0)),
            timestamp=location.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )
        self.active_trip.waypoints.append(wp)

    def stop_trip(self) -> Optional[Trip]:
        """Stop active trip, save it, return it."""
        if not self.active_trip:
            return None
        self.active_trip.end_time = datetime.now(timezone.utc).isoformat()
        completed = self.active_trip
        self.trips.insert(0, completed)
        self.active_trip = None
        self._save()
        return completed

    def cancel_trip(self) -> None:
        """Discard the active trip without saving."""
        self.active_trip = None

    # ── Mileage summary ───────────────────────────────────────────────────────

    def total_business_miles(self, tax_year: Optional[int] = None) -> float:
        year = tax_year or datetime.now().year
        # Include completed + active business trips
        trips = [t for t in self.trips if t.purpose == "business"]
        if self.active_trip and self.active_trip.purpose == "business":
            trips.append(self.active_trip)
        return round(sum(t.distance_miles for t in trips), 3)

    def total_irs_deduction(self, tax_year: Optional[int] = None) -> float:
        year = tax_year or datetime.now().year
        trips = [t for t in self.trips if t.purpose == "business"]
        return round(sum(t.irs_deduction(year) for t in trips), 2)

    def to_mileage_record(self, tax_year: Optional[int] = None) -> dict:
        """
        Returns a dict compatible with irs_forms_export.MileageRecord.
        Use this to feed mileage data into the tax module.
        """
        year = tax_year or datetime.now().year
        rate = IRS_MILEAGE_RATES.get(year, IRS_MILEAGE_RATES[2024])
        miles = self.total_business_miles(year)
        return {
            "total_business_miles": miles,
            "irs_rate_per_mile":    rate,
            "computed_deduction":   round(miles * rate, 2),
        }

    def trips_for_year(self, year: int) -> List[Trip]:
        return [
            t for t in self.trips
            if t.start_time.startswith(str(year))
        ]

    def summary(self, tax_year: Optional[int] = None) -> str:
        year = tax_year or datetime.now().year
        business = [t for t in self.trips if t.purpose == "business"]
        rate     = IRS_MILEAGE_RATES.get(year, IRS_MILEAGE_RATES[2024])
        miles    = self.total_business_miles(year)
        deduction = self.total_irs_deduction(year)
        lines = [
            f"=== Mileage Summary ({year}) ===",
            f"Total trips logged:     {len(self.trips)}",
            f"Business trips:         {len(business)}",
            f"Total business miles:   {miles:.2f}",
            f"IRS rate ({year}):      ${rate}/mile",
            f"Total IRS deduction:    ${deduction:.2f}",
        ]
        if self.active_trip:
            lines.append(f"\nActive trip: '{self.active_trip.label}' "
                         f"({self.active_trip.distance_miles:.2f} mi so far)")
        return "\n".join(lines)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            data = [asdict(t) for t in self.trips]
            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            pass  # Non-fatal — trips held in memory

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path) as f:
                raw = json.load(f)
            for t_dict in raw:
                waypoints = [Waypoint(**w) for w in t_dict.pop("waypoints", [])]
                trip = Trip(**t_dict, waypoints=waypoints)
                self.trips.append(trip)
        except Exception:
            self.trips = []


# ─── Haversine helper ─────────────────────────────────────────────────────────

def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
