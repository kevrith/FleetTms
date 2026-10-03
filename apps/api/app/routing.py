"""Route suggestions (masterplan 5.12): how far and how long between two places, so a saved route does not have to be guessed. Uses
the Google Maps Routes API when GOOGLE_MAPS_API_KEY is set; otherwise a built-in estimate between the main Kenyan towns. Google's
times are for cars, so they are stretched for a loaded lorry."""

import logging
from typing import Protocol

import httpx

from app.config import settings
from app.gps_rules import haversine_km

log = logging.getLogger(__name__)
ROAD_FACTOR = 1.15  # roads are longer than the straight line (Mombasa to Nairobi: 440 km straight, 485 by road)
LORRY_KMH = 55  # a loaded lorry's average over a long haul
TOWNS = {
    "nairobi": (-1.2921, 36.8219), "mombasa": (-4.0435, 39.6682), "kisumu": (-0.0917, 34.7680), "nakuru": (-0.3031, 36.0800), "eldoret": (0.5143, 35.2698), "thika": (-1.0332, 37.0693),
    "naivasha": (-0.7172, 36.4310), "machakos": (-1.5177, 37.2634), "malindi": (-3.2192, 40.1169), "kitale": (1.0157, 35.0062), "nyeri": (-0.4201, 36.9476), "meru": (0.0470, 37.6490),
    "garissa": (-0.4532, 39.6461), "kisii": (-0.6817, 34.7667), "voi": (-3.3961, 38.5561), "kericho": (-0.3689, 35.2863), "busia": (0.4608, 34.1115), "namanga": (-2.5425, 36.7918),
}  # fmt: skip


class RouteError(Exception):
    """No route could be worked out. The text is safe to show."""


class RouteProvider(Protocol):
    async def suggest(self, origin: str, destination: str) -> dict: ...


def _town(name: str) -> tuple[float, float]:
    key = name.strip().lower().split(",")[0].strip()
    if key not in TOWNS:
        raise RouteError(f"The built-in estimate only knows {', '.join(t.title() for t in sorted(TOWNS))}. Set GOOGLE_MAPS_API_KEY to look up any place, or enter the distance by hand.")
    return TOWNS[key]


class EstimateRoutes:
    async def suggest(self, origin: str, destination: str) -> dict:
        a, b = _town(origin), _town(destination)
        km = round(haversine_km(*a, *b) * ROAD_FACTOR)
        return {"distance_km": km, "expected_hours": round(km / LORRY_KMH, 1), "summary": "Straight-line distance plus 15 percent for the roads", "provider": "estimate"}


class GoogleRoutes:
    URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

    async def suggest(self, origin: str, destination: str) -> dict:
        headers = {"X-Goog-Api-Key": settings.google_maps_api_key, "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.description"}
        body = {"origin": {"address": f"{origin}, Kenya"}, "destination": {"address": f"{destination}, Kenya"}, "travelMode": "DRIVE", "regionCode": "KE", "units": "METRIC"}
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                res = await http.post(self.URL, headers=headers, json=body)
                res.raise_for_status()
                route = res.json()["routes"][0]
                km = round(route["distanceMeters"] / 1000)
                hours = float(str(route["duration"]).rstrip("s")) / 3600
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            log.warning("Google Routes did not give a route")
            raise RouteError("Google Maps could not find a route between those places.") from None
        return {"distance_km": km, "expected_hours": round(hours * settings.route_lorry_factor, 1), "summary": route.get("description") or "Fastest route by road", "provider": "google"}


def get_routes() -> RouteProvider:
    return GoogleRoutes() if settings.google_maps_api_key else EstimateRoutes()

