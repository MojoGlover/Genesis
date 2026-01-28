"""
Delivery Tools — Route optimization, OCR, EV charging for delivery drivers.
Supports up to 50 stops with per-leg drive times.
"""

import asyncio
import logging
import math
from typing import Dict, Any, List, Optional
import httpx

from .tool_registry import register_tool

logger = logging.getLogger(__name__)

# ── Geocoding ────────────────────────────────────────────────────

@register_tool(
    name="geocode_address",
    description="Convert a street address to latitude/longitude coordinates.",
    category="delivery",
    examples=["geocode_address(address='123 Main St, Austin, TX')"]
)
def geocode_address(address: str) -> Dict[str, Any]:
    """Forward geocode an address to coordinates using Nominatim."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": address, "format": "json", "limit": 1},
                headers={"User-Agent": "GENESIS-Delivery/1.0"},
            )
            data = resp.json()
            if not data:
                return {"success": False, "error": f"Address not found: {address}"}

            result = data[0]
            return {
                "success": True,
                "address": address,
                "lat": float(result["lat"]),
                "lon": float(result["lon"]),
                "display_name": result.get("display_name", address),
            }
    except Exception as e:
        logger.error(f"Geocode error: {e}")
        return {"success": False, "error": str(e)}


def geocode_addresses_batch(addresses: List[str]) -> List[Dict[str, Any]]:
    """Geocode multiple addresses (with rate limiting for Nominatim)."""
    import time
    results = []
    for addr in addresses:
        result = geocode_address(addr)
        results.append(result)
        time.sleep(1.1)  # Nominatim rate limit: 1 req/sec
    return results


# ── OSRM Routing ─────────────────────────────────────────────────

def _osrm_table(coords: List[tuple]) -> Optional[Dict]:
    """Get duration matrix from OSRM."""
    if len(coords) < 2:
        return None

    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = f"http://router.project-osrm.org/table/v1/driving/{coord_str}"

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params={"annotations": "duration,distance"})
            data = resp.json()
            if data.get("code") != "Ok":
                logger.error(f"OSRM error: {data}")
                return None
            return data
    except Exception as e:
        logger.error(f"OSRM table error: {e}")
        return None


def _osrm_route(coords: List[tuple]) -> Optional[Dict]:
    """Get route with geometry and per-leg durations from OSRM."""
    if len(coords) < 2:
        return None

    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = f"http://router.project-osrm.org/route/v1/driving/{coord_str}"

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params={
                "overview": "full",
                "geometries": "geojson",
                "steps": "true",
            })
            data = resp.json()
            if data.get("code") != "Ok":
                logger.error(f"OSRM route error: {data}")
                return None
            return data
    except Exception as e:
        logger.error(f"OSRM route error: {e}")
        return None


# ── Route Optimization (TSP) ─────────────────────────────────────

@register_tool(
    name="optimize_route",
    description="Optimize delivery route for up to 50 stops. Returns optimal order and per-leg drive times.",
    category="delivery",
    examples=["optimize_route(stops=[{'address': '123 Main St', 'lat': 30.27, 'lon': -97.74}, ...])"]
)
def optimize_route(
    stops: List[Dict[str, Any]],
    start_location: Optional[Dict[str, float]] = None,
    return_to_start: bool = False,
) -> Dict[str, Any]:
    """
    Optimize route for multiple delivery stops using Google OR-Tools.

    Args:
        stops: List of dicts with 'address', 'lat', 'lon' (and optional 'id', 'name')
        start_location: Optional starting point {'lat': x, 'lon': y}. If None, starts at first stop.
        return_to_start: Whether to return to starting point at end.

    Returns:
        Optimized route with per-leg durations and total time.
    """
    if len(stops) < 2:
        return {"success": False, "error": "Need at least 2 stops"}

    if len(stops) > 50:
        return {"success": False, "error": "Maximum 50 stops supported"}

    try:
        from ortools.constraint_solver import routing_enums_pb2, pywrapcp
    except ImportError:
        return {"success": False, "error": "OR-Tools not installed"}

    # Build coordinate list
    coords = []
    if start_location:
        coords.append((start_location["lat"], start_location["lon"]))

    for stop in stops:
        coords.append((stop["lat"], stop["lon"]))

    # Get duration matrix from OSRM
    osrm_data = _osrm_table(coords)
    if not osrm_data:
        return {"success": False, "error": "Failed to get routing data from OSRM"}

    durations = osrm_data.get("durations", [])
    if not durations:
        return {"success": False, "error": "No duration data from OSRM"}

    # Convert to integer seconds for OR-Tools
    n = len(coords)
    duration_matrix = [[int(durations[i][j]) for j in range(n)] for i in range(n)]

    # Create routing model
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)  # n nodes, 1 vehicle, depot=0
    routing = pywrapcp.RoutingModel(manager)

    def duration_callback(from_idx, to_idx):
        from_node = manager.IndexToNode(from_idx)
        to_node = manager.IndexToNode(to_idx)
        return duration_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(duration_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Solve
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 5  # Max 5 seconds to solve

    solution = routing.SolveWithParameters(search_params)

    if not solution:
        return {"success": False, "error": "No solution found"}

    # Extract optimized order
    optimized_order = []
    optimized_coords = []
    index = routing.Start(0)

    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        optimized_order.append(node)
        optimized_coords.append(coords[node])
        index = solution.Value(routing.NextVar(index))

    if return_to_start:
        optimized_order.append(0)
        optimized_coords.append(coords[0])

    # Get detailed route with per-leg times
    route_data = _osrm_route(optimized_coords)

    legs = []
    total_duration = 0
    total_distance = 0

    if route_data and route_data.get("routes"):
        route = route_data["routes"][0]
        total_duration = route.get("duration", 0)
        total_distance = route.get("distance", 0)

        for i, leg in enumerate(route.get("legs", [])):
            leg_duration = leg.get("duration", 0)
            leg_distance = leg.get("distance", 0)

            from_idx = optimized_order[i]
            to_idx = optimized_order[i + 1] if i + 1 < len(optimized_order) else optimized_order[0]

            # Map back to original stops
            if start_location:
                from_stop = None if from_idx == 0 else stops[from_idx - 1]
                to_stop = None if to_idx == 0 else stops[to_idx - 1]
            else:
                from_stop = stops[from_idx]
                to_stop = stops[to_idx]

            legs.append({
                "from": from_stop.get("address", "Start") if from_stop else "Start",
                "to": to_stop.get("address", "End") if to_stop else "End",
                "duration_seconds": int(leg_duration),
                "duration_display": _format_duration(leg_duration),
                "distance_meters": int(leg_distance),
                "distance_display": _format_distance(leg_distance),
            })

    # Build optimized stop list
    optimized_stops = []
    for i, node in enumerate(optimized_order):
        if start_location and node == 0:
            continue  # Skip depot

        stop_idx = node - 1 if start_location else node
        if 0 <= stop_idx < len(stops):
            stop = stops[stop_idx].copy()
            stop["sequence"] = len(optimized_stops) + 1
            optimized_stops.append(stop)

    return {
        "success": True,
        "stops": optimized_stops,
        "legs": legs,
        "total_duration_seconds": int(total_duration),
        "total_duration_display": _format_duration(total_duration),
        "total_distance_meters": int(total_distance),
        "total_distance_display": _format_distance(total_distance),
        "stop_count": len(optimized_stops),
    }


def _format_duration(seconds: float) -> str:
    """Format seconds as 'Xh Ym' or 'Xm'."""
    minutes = int(seconds / 60)
    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"
    return f"{minutes}m"


def _format_distance(meters: float) -> str:
    """Format meters as miles."""
    miles = meters / 1609.34
    return f"{miles:.1f} mi"


# ── EV Charging Stations ─────────────────────────────────────────

@register_tool(
    name="find_charging_stations",
    description="Find EV charging stations near a location.",
    category="delivery",
    examples=["find_charging_stations(lat=30.27, lon=-97.74, radius_miles=10)"]
)
def find_charging_stations(
    lat: float,
    lon: float,
    radius_miles: float = 10,
    limit: int = 10,
    connector_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Find EV charging stations using OpenChargeMap API.

    Args:
        lat, lon: Search center coordinates
        radius_miles: Search radius in miles
        limit: Max results
        connector_type: Filter by connector (e.g., 'Tesla', 'CCS', 'CHAdeMO')
    """
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "distance": radius_miles,
            "distanceunit": "miles",
            "maxresults": limit,
            "compact": "true",
            "verbose": "false",
        }

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                "https://api.openchargemap.io/v3/poi",
                params=params,
                headers={"User-Agent": "GENESIS-Delivery/1.0"},
            )
            stations = resp.json()

        results = []
        for station in stations:
            addr = station.get("AddressInfo", {})

            # Get connector types
            connections = station.get("Connections", [])
            connectors = []
            for conn in connections:
                conn_type = conn.get("ConnectionType", {})
                title = conn_type.get("Title", "Unknown")
                if title not in connectors:
                    connectors.append(title)

            # Filter by connector type if specified
            if connector_type:
                if not any(connector_type.lower() in c.lower() for c in connectors):
                    continue

            results.append({
                "name": addr.get("Title", "Charging Station"),
                "address": addr.get("AddressLine1", ""),
                "city": addr.get("Town", ""),
                "lat": addr.get("Latitude"),
                "lon": addr.get("Longitude"),
                "distance_miles": addr.get("Distance", 0),
                "connectors": connectors,
                "num_points": station.get("NumberOfPoints", 1),
                "operator": station.get("OperatorInfo", {}).get("Title", "Unknown"),
            })

        return {
            "success": True,
            "stations": results,
            "count": len(results),
            "search_center": {"lat": lat, "lon": lon},
            "radius_miles": radius_miles,
        }

    except Exception as e:
        logger.error(f"Charging station search error: {e}")
        return {"success": False, "error": str(e)}


# ── OCR / Address Extraction ─────────────────────────────────────

@register_tool(
    name="extract_addresses_from_image",
    description="Extract delivery addresses from an image using AI vision (LLaVA).",
    category="delivery",
    examples=["extract_addresses_from_image(image_path='/tmp/manifest.jpg')"]
)
def extract_addresses_from_image(image_path: str) -> Dict[str, Any]:
    """
    Use LLaVA (via Ollama) to extract addresses from an image.
    Works with photos of manifests, package labels, or delivery lists.
    """
    import base64
    import os

    if not os.path.exists(image_path):
        return {"success": False, "error": f"Image not found: {image_path}"}

    try:
        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Call Ollama with LLaVA
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llava",
                    "prompt": """Look at this image carefully. Extract ALL delivery addresses you can see.
Return ONLY a JSON array of addresses, one per line. Example format:
["123 Main Street, Austin, TX 78701", "456 Oak Avenue, Austin, TX 78702"]

If you cannot find any addresses, return an empty array: []
Do not include any other text, just the JSON array.""",
                    "images": [image_data],
                    "stream": False,
                },
            )
            data = resp.json()

        response_text = data.get("response", "[]")

        # Parse the JSON array
        import json
        try:
            # Find JSON array in response
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                addresses = json.loads(response_text[start:end])
            else:
                addresses = []
        except json.JSONDecodeError:
            # Try line-by-line extraction
            lines = response_text.strip().split("\n")
            addresses = [line.strip().strip('"').strip("'") for line in lines if line.strip()]

        return {
            "success": True,
            "addresses": addresses,
            "count": len(addresses),
            "raw_response": response_text[:500],
        }

    except Exception as e:
        logger.error(f"OCR error: {e}")
        return {"success": False, "error": str(e)}


# ── Convenience: Full Pipeline ───────────────────────────────────

@register_tool(
    name="plan_delivery_route",
    description="Full pipeline: take addresses, geocode them, optimize route, return with times.",
    category="delivery",
    examples=["plan_delivery_route(addresses=['123 Main St, Austin', '456 Oak Ave, Austin'])"]
)
def plan_delivery_route(
    addresses: List[str],
    start_address: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Complete delivery planning pipeline.

    Args:
        addresses: List of delivery addresses (up to 50)
        start_address: Optional starting location
    """
    if len(addresses) > 50:
        return {"success": False, "error": "Maximum 50 addresses supported"}

    if len(addresses) < 2:
        return {"success": False, "error": "Need at least 2 addresses"}

    # Geocode all addresses
    geocoded = []
    failed = []

    for addr in addresses:
        result = geocode_address(addr)
        if result["success"]:
            geocoded.append({
                "address": addr,
                "lat": result["lat"],
                "lon": result["lon"],
                "display_name": result["display_name"],
            })
        else:
            failed.append({"address": addr, "error": result.get("error")})

        # Rate limit
        import time
        time.sleep(1.1)

    if len(geocoded) < 2:
        return {
            "success": False,
            "error": "Could not geocode enough addresses",
            "failed": failed,
        }

    # Geocode start if provided
    start_location = None
    if start_address:
        start_result = geocode_address(start_address)
        if start_result["success"]:
            start_location = {"lat": start_result["lat"], "lon": start_result["lon"]}

    # Optimize
    route_result = optimize_route(geocoded, start_location=start_location)

    if not route_result["success"]:
        return route_result

    route_result["failed_addresses"] = failed
    return route_result
