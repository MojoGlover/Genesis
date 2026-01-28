"""
Location Tools Module
Provides GPS/location capabilities for the autonomous agent.
Location data comes from:
  - Phone browser (Gradio JS geolocation)
  - Phone automation (iOS Shortcuts / Tasker POST to /api/location)
"""

import json
import logging
import math
import time
from pathlib import Path
from typing import Dict, Any, Optional
from .tool_registry import register_tool

logger = logging.getLogger(__name__)

# Shared location store — written by API/UI, read by agent tools
_LOCATION_FILE = Path.home() / "ai" / "genesis" / ".location.json"


def _read_location() -> Optional[Dict[str, Any]]:
    """Read the latest stored location"""
    try:
        if _LOCATION_FILE.exists():
            data = json.loads(_LOCATION_FILE.read_text())
            return data
    except Exception as e:
        logger.error(f"Error reading location: {e}")
    return None


def save_location(lat: float, lon: float, accuracy: Optional[float] = None,
                  source: str = "unknown") -> Dict[str, Any]:
    """Save a location update (called by API and Gradio JS handler)"""
    try:
        _LOCATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "latitude": lat,
            "longitude": lon,
            "accuracy_meters": accuracy,
            "source": source,
            "timestamp": time.time(),
        }
        _LOCATION_FILE.write_text(json.dumps(data, indent=2))
        logger.info(f"Location saved: {lat}, {lon} (source={source})")
        return {"success": True, **data}
    except Exception as e:
        logger.error(f"Error saving location: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_location",
    description="Get the user's current GPS location (latitude, longitude, accuracy).",
    category="location",
    examples=[
        "get_location()",
    ]
)
def get_location() -> Dict[str, Any]:
    """
    Get the most recent GPS location from the user's phone.

    Returns:
        dict with 'success', 'latitude', 'longitude', 'accuracy_meters',
        'source', 'timestamp', and 'age_seconds'
    """
    loc = _read_location()

    if not loc:
        return {
            "success": False,
            "error": "No location data available. Open GENESIS on your phone "
                     "and tap the location button, or set up an iOS Shortcut "
                     "to POST to /api/location.",
        }

    age = time.time() - loc.get("timestamp", 0)

    return {
        "success": True,
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "accuracy_meters": loc.get("accuracy_meters"),
        "source": loc.get("source", "unknown"),
        "timestamp": loc.get("timestamp"),
        "age_seconds": round(age, 1),
    }


@register_tool(
    name="get_distance",
    description="Calculate distance in km between current location and a target lat/lon.",
    category="location",
    examples=[
        "get_distance(target_lat=40.7128, target_lon=-74.0060)",
        "get_distance(target_lat=34.0522, target_lon=-118.2437)",
    ]
)
def get_distance(target_lat: float, target_lon: float) -> Dict[str, Any]:
    """
    Calculate the distance from current location to a target point.

    Args:
        target_lat: Target latitude
        target_lon: Target longitude

    Returns:
        dict with 'success', 'distance_km', 'distance_miles'
    """
    loc = _read_location()

    if not loc:
        return {
            "success": False,
            "error": "No location data available.",
        }

    lat1 = math.radians(loc["latitude"])
    lon1 = math.radians(loc["longitude"])
    lat2 = math.radians(target_lat)
    lon2 = math.radians(target_lon)

    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    km = 6371 * c

    return {
        "success": True,
        "from": {"latitude": loc["latitude"], "longitude": loc["longitude"]},
        "to": {"latitude": target_lat, "longitude": target_lon},
        "distance_km": round(km, 2),
        "distance_miles": round(km * 0.621371, 2),
    }


@register_tool(
    name="reverse_geocode",
    description="Convert GPS coordinates to a human-readable address using web lookup.",
    category="location",
    examples=[
        "reverse_geocode()",
        "reverse_geocode(lat=40.7128, lon=-74.0060)",
    ]
)
def reverse_geocode(lat: Optional[float] = None, lon: Optional[float] = None) -> Dict[str, Any]:
    """
    Convert coordinates to a street address using Nominatim (OpenStreetMap).
    If no coordinates given, uses the stored location.

    Args:
        lat: Latitude (optional, uses stored location if omitted)
        lon: Longitude (optional, uses stored location if omitted)

    Returns:
        dict with 'success', 'address', 'latitude', 'longitude'
    """
    if lat is None or lon is None:
        loc = _read_location()
        if not loc:
            return {"success": False, "error": "No location data and no coordinates provided."}
        lat = loc["latitude"]
        lon = loc["longitude"]

    try:
        import httpx

        resp = httpx.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "GENESIS-Agent/1.0"},
            timeout=10,
        )
        data = resp.json()
        return {
            "success": True,
            "latitude": lat,
            "longitude": lon,
            "address": data.get("display_name", "Unknown"),
            "details": data.get("address", {}),
        }
    except Exception as e:
        logger.error(f"Reverse geocode error: {e}")
        return {"success": False, "error": str(e)}
