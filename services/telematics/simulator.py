"""Simulated fleet that drives Denizli delivery loops during working hours.

Positions are a pure function of time, so repeated polls return the same points and the
uniqueness constraint on (vehicle_id, recorded_at) absorbs overlaps.
"""

import bisect
import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import ClassVar

from backend.config import settings
from services.distance import haversine_km
from services.routing import RoutingError, fetch_road_route
from services.telematics.base import CredentialField, ExternalVehicle, PositionPoint, TelematicsAdapter

Coord = tuple[float, float]

DEPOT: Coord = (37.8000, 29.0500)
PLACES: dict[str, Coord] = {
    "saraylar": (37.7760, 29.0810),
    "sumer": (37.7640, 29.0630),
    "kinikli": (37.7440, 29.1010),
    "karahayit": (37.9620, 29.1000),
    "honaz": (37.7590, 29.2700),
    "tavas": (37.5730, 29.0700),
    "saraykoy": (37.9270, 28.9260),
}
VEHICLES: dict[str, tuple[str, list[str]]] = {
    "SIM-01": ("Simülasyon 1 (şehir içi)", ["saraylar", "sumer", "kinikli"]),
    "SIM-02": ("Simülasyon 2 (kuzey)", ["karahayit", "saraykoy"]),
    "SIM-03": ("Simülasyon 3 (güney)", ["honaz", "tavas"]),
    "SIM-04": ("Simülasyon 4 (doğu)", ["kinikli", "honaz"]),
}
SHIFT_START = time(8, 0)
SHIFT_END = time(18, 0)
SAMPLE_SECONDS = 60
DEPOT_DWELL_S = 30 * 60
STOP_DWELL_S = 20 * 60
START_STAGGER_S = 7 * 60
CITY_KMH = 35.0
ROAD_KMH = 65.0
CITY_LEG_KM = 12.0
MAX_WINDOW = timedelta(hours=36)


@dataclass
class _Path:
    points: list[Coord]
    cumulative_km: list[float]

    @property
    def length_km(self) -> float:
        return self.cumulative_km[-1]

    def locate(self, km: float) -> tuple[Coord, float]:
        km = min(max(km, 0.0), self.length_km)
        index = max(bisect.bisect_right(self.cumulative_km, km) - 1, 0)
        index = min(index, len(self.points) - 2)
        start, end = self.points[index], self.points[index + 1]
        span = self.cumulative_km[index + 1] - self.cumulative_km[index]
        ratio = 0.0 if span <= 0 else (km - self.cumulative_km[index]) / span
        position = (start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio)
        return position, _bearing(start, end)


@dataclass
class _Segment:
    duration_s: float
    dwell_at: Coord | None = None
    path: _Path | None = None
    cruise_kmh: float = 0.0


@dataclass
class _Plan:
    segments: list[_Segment]
    delay_s: float

    @property
    def cycle_s(self) -> float:
        return sum(segment.duration_s for segment in self.segments)


class SimulatorAdapter(TelematicsAdapter):
    provider = "simulator"
    label = "Simülatör (deneme verisi)"
    credential_fields = (
        CredentialField("use_roads", "Gerçek yol geometrisi kullan (true/false)", required=False, placeholder="true"),
    )
    _geometry_cache: ClassVar[dict[tuple[Coord, Coord, bool], list[Coord]]] = {}

    @property
    def use_roads(self) -> bool:
        return self.credentials.get("use_roads", "true").strip().lower() not in {"false", "0", "hayir", "hayır", "no"}

    async def list_vehicles(self) -> list[ExternalVehicle]:
        return [ExternalVehicle(external_id=key, label=label) for key, (label, _) in VEHICLES.items()]

    async def fetch_positions(self, since: datetime, until: datetime) -> list[PositionPoint]:
        until = min(until, datetime.now(timezone.utc))
        since = max(since, until - MAX_WINDOW)
        if since >= until:
            return []
        plans = await self._plans()
        tz = settings.tz
        epoch = int(since.timestamp()) // SAMPLE_SECONDS * SAMPLE_SECONDS + SAMPLE_SECONDS
        points: list[PositionPoint] = []
        cursor = datetime.fromtimestamp(epoch, tz=timezone.utc)
        while cursor <= until:
            local = cursor.astimezone(tz)
            shift_start = datetime.combine(local.date(), SHIFT_START, tz)
            shift_end = datetime.combine(local.date(), SHIFT_END, tz)
            if shift_start <= local <= shift_end:
                elapsed = (local - shift_start).total_seconds()
                for external_id, plan in plans.items():
                    lat, lng, speed, heading, ignition = _state_at(plan, elapsed)
                    points.append(
                        PositionPoint(
                            external_id=external_id,
                            recorded_at=cursor,
                            latitude=round(lat, 6),
                            longitude=round(lng, 6),
                            speed_kmh=round(speed, 1),
                            heading=None if heading is None else round(heading, 1),
                            ignition_on=ignition,
                        )
                    )
            cursor += timedelta(seconds=SAMPLE_SECONDS)
        return points

    async def _plans(self) -> dict[str, _Plan]:
        plans: dict[str, _Plan] = {}
        for index, (external_id, (_, stop_keys)) in enumerate(VEHICLES.items()):
            stops = [PLACES[key] for key in stop_keys]
            waypoints = [DEPOT, *stops, DEPOT]
            segments = [_Segment(duration_s=DEPOT_DWELL_S, dwell_at=DEPOT)]
            for leg_index in range(len(waypoints) - 1):
                start, end = waypoints[leg_index], waypoints[leg_index + 1]
                path = await self._path(start, end)
                cruise = CITY_KMH if path.length_km < CITY_LEG_KM else ROAD_KMH
                drive_s = max(path.length_km / cruise * 3600, SAMPLE_SECONDS)
                segments.append(_Segment(duration_s=drive_s, path=path, cruise_kmh=cruise))
                if end != DEPOT:
                    segments.append(_Segment(duration_s=STOP_DWELL_S, dwell_at=end))
            plans[external_id] = _Plan(segments=segments, delay_s=index * START_STAGGER_S)
        return plans

    async def _path(self, start: Coord, end: Coord) -> _Path:
        key = (start, end, self.use_roads)
        coords = self._geometry_cache.get(key)
        if coords is None:
            coords = [start, end]
            if self.use_roads:
                try:
                    route = await fetch_road_route([start, end])
                    if len(route.coordinates) >= 2:
                        coords = list(route.coordinates)
                except RoutingError:
                    pass
            self._geometry_cache[key] = coords
        cumulative = [0.0]
        for previous, current in zip(coords, coords[1:]):
            cumulative.append(cumulative[-1] + haversine_km(previous[0], previous[1], current[0], current[1]))
        if cumulative[-1] <= 0:
            coords = [start, end]
            cumulative = [0.0, max(haversine_km(start[0], start[1], end[0], end[1]), 0.001)]
        return _Path(points=coords, cumulative_km=cumulative)


def _state_at(plan: _Plan, elapsed_s: float) -> tuple[float, float, float, float | None, bool]:
    if elapsed_s < plan.delay_s:
        return DEPOT[0], DEPOT[1], 0.0, None, False
    offset = (elapsed_s - plan.delay_s) % plan.cycle_s
    for segment in plan.segments:
        if offset < segment.duration_s:
            if segment.dwell_at is not None:
                return segment.dwell_at[0], segment.dwell_at[1], 0.0, None, False
            ratio = offset / segment.duration_s
            (lat, lng), heading = segment.path.locate(ratio * segment.path.length_km)
            speed = segment.cruise_kmh * (0.9 + 0.1 * math.sin(offset / 37.0))
            return lat, lng, speed, heading, True
        offset -= segment.duration_s
    return DEPOT[0], DEPOT[1], 0.0, None, False


def _bearing(start: Coord, end: Coord) -> float:
    phi1, phi2 = math.radians(start[0]), math.radians(end[0])
    d_lambda = math.radians(end[1] - start[1])
    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(x, y)) + 360) % 360
