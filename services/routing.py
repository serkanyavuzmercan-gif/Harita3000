"""Nearest-neighbor stop ordering and OSRM road geometry."""

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from services.distance import distance_km
from services.http import SSL_CONTEXT


class RoutingError(Exception):
    pass


@dataclass
class Stop:
    id: int
    latitude: float
    longitude: float
    label: str = ""


@dataclass
class RoadRoute:
    coordinates: list[tuple[float, float]]
    distance_km: float
    duration_min: float


async def order_stops(
    session: AsyncSession,
    origin_lat: float,
    origin_lng: float,
    stops: list[Stop],
) -> tuple[list[tuple[Stop, float]], float]:
    remaining = list(stops)
    ordered: list[tuple[Stop, float]] = []
    total = 0.0
    current_lat = origin_lat
    current_lng = origin_lng
    while remaining:
        best_index = 0
        best_distance: float | None = None
        for index, stop in enumerate(remaining):
            leg = await distance_km(session, current_lat, current_lng, stop.latitude, stop.longitude)
            if best_distance is None or leg < best_distance:
                best_distance = leg
                best_index = index
        chosen = remaining.pop(best_index)
        leg_km = round(best_distance or 0.0, 2)
        total += leg_km
        ordered.append((chosen, leg_km))
        current_lat = chosen.latitude
        current_lng = chosen.longitude
    return ordered, round(total, 2)


async def fetch_road_route(points: list[tuple[float, float]]) -> RoadRoute:
    if len(points) < 2:
        raise RoutingError("Rota için en az iki nokta gerekli")
    path = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
    url = f"{settings.osrm_url.rstrip('/')}/route/v1/driving/{path}"
    try:
        async with httpx.AsyncClient(
            timeout=15,
            verify=SSL_CONTEXT,
            headers={"User-Agent": settings.geocoder_user_agent},
        ) as client:
            response = await client.get(url, params={"overview": "full", "geometries": "geojson"})
    except httpx.HTTPError:
        raise RoutingError("Rota servisine ulaşılamadı") from None
    try:
        payload = response.json()
    except ValueError:
        raise RoutingError(f"Rota servisi yanıt vermedi (HTTP {response.status_code})") from None

    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise RoutingError(f"Rota bulunamadı ({payload.get('code', 'bilinmiyor')})")
    route = payload["routes"][0]
    try:
        coordinates = [(float(lat), float(lng)) for lng, lat in route["geometry"]["coordinates"]]
        return RoadRoute(
            coordinates=coordinates,
            distance_km=round(float(route["distance"]) / 1000, 2),
            duration_min=round(float(route["duration"]) / 60, 1),
        )
    except (KeyError, TypeError, ValueError):
        raise RoutingError("Rota geometrisi okunamadı") from None
