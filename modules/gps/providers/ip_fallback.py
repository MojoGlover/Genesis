"""
ip_fallback.py — IP-based geolocation fallback

Used when:
  - GPS hardware is unavailable / denied
  - Device is PlugWan (desktop, no GPS hardware)
  - Quick location estimate is acceptable

Providers tried in order:
  1. ipapi.co  — free, 1000 req/day, city-level accuracy
  2. ip-api.com — free, 45 req/min, city-level accuracy
  3. ipinfo.io  — free tier, requires no key for basic use

This is city-level accuracy only (~1-10 km). Not suitable for mileage tracking.
"""

from __future__ import annotations
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional


class IPGeolocationProvider:
    """
    City-level location from public IP.
    Use as fallback only — not for mileage tracking.
    """

    ACCURACY_METERS = 5000.0  # city-level, ~5km

    def get_location(self, timeout: int = 10) -> Optional[dict]:
        """Try providers in order, return first success."""
        for provider_fn in [self._ipapi_co, self._ip_api_com, self._ipinfo_io]:
            result = provider_fn(timeout)
            if result:
                return result
        return None

    def _ipapi_co(self, timeout: int) -> Optional[dict]:
        try:
            with urllib.request.urlopen(
                "https://ipapi.co/json/", timeout=timeout
            ) as resp:
                raw = json.loads(resp.read())
                if raw.get("error"):
                    return None
                return self._build(
                    lat=float(raw.get("latitude", 0)),
                    lon=float(raw.get("longitude", 0)),
                    city=raw.get("city", ""),
                    region=raw.get("region", ""),
                    country=raw.get("country_name", ""),
                    ip=raw.get("ip", ""),
                    source="ipapi.co",
                )
        except Exception:
            return None

    def _ip_api_com(self, timeout: int) -> Optional[dict]:
        try:
            with urllib.request.urlopen(
                "http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country,query",
                timeout=timeout,
            ) as resp:
                raw = json.loads(resp.read())
                if raw.get("status") != "success":
                    return None
                return self._build(
                    lat=float(raw.get("lat", 0)),
                    lon=float(raw.get("lon", 0)),
                    city=raw.get("city", ""),
                    region=raw.get("regionName", ""),
                    country=raw.get("country", ""),
                    ip=raw.get("query", ""),
                    source="ip-api.com",
                )
        except Exception:
            return None

    def _ipinfo_io(self, timeout: int) -> Optional[dict]:
        try:
            with urllib.request.urlopen(
                "https://ipinfo.io/json", timeout=timeout
            ) as resp:
                raw = json.loads(resp.read())
                loc = raw.get("loc", "0,0").split(",")
                city = raw.get("city", "")
                region = raw.get("region", "")
                return self._build(
                    lat=float(loc[0]),
                    lon=float(loc[1]),
                    city=city,
                    region=region,
                    country=raw.get("country", ""),
                    ip=raw.get("ip", ""),
                    source="ipinfo.io",
                )
        except Exception:
            return None

    def _build(self, lat: float, lon: float, city: str, region: str,
               country: str, ip: str, source: str) -> dict:
        address = ", ".join(p for p in [city, region, country] if p)
        return {
            "latitude":  lat,
            "longitude": lon,
            "altitude":  0.0,
            "accuracy":  self.ACCURACY_METERS,
            "speed":     0.0,
            "heading":   0.0,
            "provider":  "ip",
            "address":   address,
            "ip":        ip,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source":    source,
            "note":      "IP geolocation — city-level accuracy only",
        }
