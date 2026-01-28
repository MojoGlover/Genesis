"""
Delivery API — Route optimization, stop management, EV charging for delivery drivers.
Supports up to 50 stops with per-leg drive times.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel

from agents.tools.delivery_tools import (
    geocode_address,
    optimize_route,
    find_charging_stations,
    extract_addresses_from_image,
    plan_delivery_route,
)

router = APIRouter(prefix="/delivery", tags=["delivery"])


# ── Request models ──────────────────────────────────────────────

class AddressesRequest(BaseModel):
    addresses: List[str]
    start_address: Optional[str] = None


class StopsRequest(BaseModel):
    stops: List[Dict[str, Any]]  # [{address, lat, lon, ...}]
    start_location: Optional[Dict[str, float]] = None
    return_to_start: bool = False


class ChargingRequest(BaseModel):
    lat: float
    lon: float
    radius_miles: float = 10
    limit: int = 10
    connector_type: Optional[str] = None


class GeocodeRequest(BaseModel):
    address: str


# ── Endpoints ───────────────────────────────────────────────────

@router.post("/geocode")
async def geocode(req: GeocodeRequest) -> Dict[str, Any]:
    """Geocode a single address to coordinates."""
    return await asyncio.to_thread(geocode_address, req.address)


@router.post("/plan")
async def plan_route(req: AddressesRequest) -> Dict[str, Any]:
    """
    Full pipeline: geocode addresses → optimize route → return with times.
    Supports up to 50 addresses.
    """
    return await asyncio.to_thread(
        plan_delivery_route,
        req.addresses,
        req.start_address,
    )


@router.post("/optimize")
async def optimize(req: StopsRequest) -> Dict[str, Any]:
    """
    Optimize already-geocoded stops.
    Use this if you've already geocoded addresses separately.
    """
    return await asyncio.to_thread(
        optimize_route,
        req.stops,
        req.start_location,
        req.return_to_start,
    )


@router.post("/charging")
async def charging_stations(req: ChargingRequest) -> Dict[str, Any]:
    """Find EV charging stations near a location."""
    return await asyncio.to_thread(
        find_charging_stations,
        req.lat,
        req.lon,
        req.radius_miles,
        req.limit,
        req.connector_type,
    )


@router.post("/ocr")
async def ocr_addresses(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Extract addresses from an uploaded image (manifest, labels, etc).
    Uses LLaVA vision model.
    """
    import tempfile
    import os

    # Save uploaded file temporarily
    suffix = os.path.splitext(file.filename or "image.jpg")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = await asyncio.to_thread(extract_addresses_from_image, tmp_path)
        return result
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except:
            pass


@router.post("/reoptimize")
async def reoptimize(req: StopsRequest) -> Dict[str, Any]:
    """
    Re-optimize route after adding/removing/skipping stops.
    Same as /optimize but named for clarity.
    """
    return await asyncio.to_thread(
        optimize_route,
        req.stops,
        req.start_location,
        req.return_to_start,
    )
