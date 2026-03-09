"""
Location API - Receives GPS updates from phone (Shortcuts, Tasker, browser)
POST /location  — update location
GET  /location  — read current location
"""

from __future__ import annotations
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from agents.tools.location_tools import save_location, get_location

router = APIRouter(prefix="/location", tags=["location"])


class LocationUpdate(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    source: Optional[str] = "api"


@router.post("")
def update_location(payload: LocationUpdate) -> Dict[str, Any]:
    """Receive a GPS update from phone automation or browser."""
    result = save_location(
        lat=payload.latitude,
        lon=payload.longitude,
        accuracy=payload.accuracy,
        source=payload.source or "api",
    )
    return result


@router.get("")
def read_location() -> Dict[str, Any]:
    """Read the most recent stored location."""
    return get_location()
