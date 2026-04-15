"""
geocoder.py — Reverse geocoding via OpenStreetMap Nominatim

Free, no API key required. Rate limit: 1 request/second.
Converts (lat, lon) → human-readable address string.

Also provides forward geocoding (address → coordinates).
"""

from __future__ import annotations
import json
import time
import urllib.request
import urllib.parse
from typing import Optional


_NOMINATIM_URL = "https://nominatim.openstreetmap.org"
_LAST_REQUEST  = 0.0
_MIN_INTERVAL  = 1.1   # Nominatim rate limit: 1 req/sec with buffer


def _throttle() -> None:
    global _LAST_REQUEST
    now = time.time()
    wait = _MIN_INTERVAL - (now - _LAST_REQUEST)
    if wait > 0:
        time.sleep(wait)
    _LAST_REQUEST = time.time()


def reverse_geocode(lat: float, lon: float,
                    timeout: int = 10) -> Optional[str]:
    """
    Convert (lat, lon) to a human-readable address.
    Returns string like "123 Main St, Tampa, FL 33601, United States"
    or None if lookup fails.
    """
    _throttle()
    params = urllib.parse.urlencode({
        "lat":    lat,
        "lon":    lon,
        "format": "json",
        "addressdetails": 1,
    })
    url = f"{_NOMINATIM_URL}/reverse?{params}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "MojoGPS/1.0 (PlugOps agent system)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("display_name")
    except Exception:
        return None


def reverse_geocode_structured(lat: float, lon: float,
                                timeout: int = 10) -> Optional[dict]:
    """
    Returns full structured address dict from Nominatim.
    Keys: house_number, road, suburb, city, state, postcode, country, etc.
    """
    _throttle()
    params = urllib.parse.urlencode({
        "lat":    lat,
        "lon":    lon,
        "format": "json",
        "addressdetails": 1,
    })
    url = f"{_NOMINATIM_URL}/reverse?{params}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "MojoGPS/1.0 (PlugOps agent system)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("address")
    except Exception:
        return None


def forward_geocode(address: str, timeout: int = 10) -> Optional[dict]:
    """
    Convert address string → (lat, lon) + display_name.
    Returns dict with 'latitude', 'longitude', 'display_name', or None.
    """
    _throttle()
    params = urllib.parse.urlencode({
        "q":       address,
        "format":  "json",
        "limit":   1,
        "addressdetails": 1,
    })
    url = f"{_NOMINATIM_URL}/search?{params}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "MojoGPS/1.0 (PlugOps agent system)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            results = json.loads(resp.read())
            if not results:
                return None
            r = results[0]
            return {
                "latitude":    float(r["lat"]),
                "longitude":   float(r["lon"]),
                "display_name": r.get("display_name", ""),
                "address":     r.get("address", {}),
            }
    except Exception:
        return None


def distance_between(lat1: float, lon1: float,
                     lat2: float, lon2: float) -> dict:
    """
    Compute distance between two points.
    Returns dict with 'miles', 'km', 'meters'.
    """
    import math
    R_miles = 3958.8
    R_km    = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return {
        "miles":  round(R_miles * c, 3),
        "km":     round(R_km    * c, 3),
        "meters": round(R_km * c * 1000, 1),
    }
