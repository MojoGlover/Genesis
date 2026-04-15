"""
gps — GPS module for the Plug network

Two deployment targets:
  PlugToo (Android tablet): hardware GPS via Termux:API, trip tracking
  PlugWan (Mac/desktop):    IP geolocation fallback
  PlugTree (iPhone):        handled by CoreLocation in Swift (LocationService.swift)

Quick start (PlugToo):
    from gps import GPSModule, TripTracker

    gps = GPSModule(device="plugtoo")

    # One-shot location
    loc = gps.get_location()
    print(loc["latitude"], loc["longitude"], loc.get("address"))

    # Mileage tracking (Amazon Flex)
    gps.start_trip("Amazon Flex - Evening", purpose="business")
    # ... drive around, GPS polls automatically ...
    trip = gps.stop_trip()
    print(trip.summary())

    # Hand off to Accountant / irs_forms_export
    mileage = gps.mileage_record(tax_year=2024)
    # → {"total_business_miles": 12.4, "irs_rate_per_mile": 0.67, "computed_deduction": 8.31}

    # Report to PlugOps hub
    gps.report_to_plugops()

Setup on PlugToo (Termux):
    pkg install termux-api python
    pip install flask requests
    # Install "Termux:API" app from F-Droid
    # Grant location permission to Termux:API

GPS accuracy by provider:
    termux (hardware)  — <10m, requires Termux:API
    ip-fallback        — ~5000m city-level, no hardware needed
"""

from .module import GPSModule
from .tracker import TripTracker, Trip, Waypoint, IRS_MILEAGE_RATES
from .geocoder import reverse_geocode, forward_geocode, distance_between

__all__ = [
    "GPSModule",
    "TripTracker",
    "Trip",
    "Waypoint",
    "IRS_MILEAGE_RATES",
    "reverse_geocode",
    "forward_geocode",
    "distance_between",
]

__version__ = "1.0.0"
