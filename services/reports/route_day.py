"""Turns a day's position track into stops, distances and durations."""

from dataclasses import dataclass, field
from datetime import datetime

from services.distance import haversine_km

STOP_SPEED_KMH = 3.0
STOP_MIN_MINUTES = 5.0
MATCH_RADIUS_M = 200.0
MAX_GAP_MINUTES = 10.0


@dataclass(frozen=True)
class TrackPoint:
    recorded_at: datetime
    latitude: float
    longitude: float
    speed_kmh: float
    ignition_on: bool | None = None


@dataclass(frozen=True)
class Place:
    name: str
    kind: str
    latitude: float
    longitude: float
    entity_id: int | None = None


@dataclass
class Stop:
    index: int
    start: datetime
    end: datetime
    latitude: float
    longitude: float
    place: Place | None = None
    distance_m: float | None = None
    planned: bool = False

    @property
    def duration_min(self) -> float:
        return round((self.end - self.start).total_seconds() / 60, 1)


@dataclass
class RouteDay:
    points: list[TrackPoint]
    stops: list[Stop] = field(default_factory=list)
    distance_km: float = 0.0
    driving_min: float = 0.0
    stopped_min: float = 0.0
    first_move: datetime | None = None
    last_move: datetime | None = None
    max_speed_kmh: float = 0.0
    missed_planned: list[str] = field(default_factory=list)


def _slow(point: TrackPoint) -> bool:
    return point.speed_kmh < STOP_SPEED_KMH


def detect_stop_runs(points: list[TrackPoint]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, point in enumerate(points):
        if _slow(point):
            if start is None:
                start = index
            continue
        if start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(points) - 1))
    return [
        (begin, end)
        for begin, end in runs
        if (points[end].recorded_at - points[begin].recorded_at).total_seconds() / 60 >= STOP_MIN_MINUTES
    ]


def _nearest(latitude: float, longitude: float, places: list[Place]) -> tuple[Place | None, float | None]:
    best: Place | None = None
    best_m: float | None = None
    for place in places:
        meters = haversine_km(latitude, longitude, place.latitude, place.longitude) * 1000
        if meters <= MATCH_RADIUS_M and (best_m is None or meters < best_m):
            best, best_m = place, meters
    return best, None if best_m is None else round(best_m)


def analyze_day(
    points: list[TrackPoint],
    places: list[Place] | None = None,
    planned: dict[int, str] | None = None,
) -> RouteDay:
    """planned maps entity_id to name for the day's shipments on this vehicle."""
    points = sorted(points, key=lambda item: item.recorded_at)
    places = places or []
    planned = planned or {}
    day = RouteDay(points=points)
    if not points:
        day.missed_planned = sorted(planned.values())
        return day

    for previous, current in zip(points, points[1:]):
        gap_min = (current.recorded_at - previous.recorded_at).total_seconds() / 60
        if not (_slow(previous) and _slow(current)):
            day.distance_km += haversine_km(previous.latitude, previous.longitude, current.latitude, current.longitude)
        if not _slow(previous):
            day.driving_min += min(gap_min, MAX_GAP_MINUTES)

    moving = [point for point in points if not _slow(point)]
    if moving:
        day.first_move = moving[0].recorded_at
        day.last_move = moving[-1].recorded_at
    day.max_speed_kmh = round(max(point.speed_kmh for point in points), 1)

    visited: set[int] = set()
    for number, (begin, end) in enumerate(detect_stop_runs(points), start=1):
        run = points[begin : end + 1]
        latitude = sum(point.latitude for point in run) / len(run)
        longitude = sum(point.longitude for point in run) / len(run)
        place, meters = _nearest(latitude, longitude, places)
        stop = Stop(
            index=number,
            start=run[0].recorded_at,
            end=run[-1].recorded_at,
            latitude=latitude,
            longitude=longitude,
            place=place,
            distance_m=meters,
            planned=bool(place and place.entity_id in planned),
        )
        if stop.planned:
            visited.add(place.entity_id)
        day.stops.append(stop)
        day.stopped_min += stop.duration_min

    day.distance_km = round(day.distance_km, 2)
    day.driving_min = round(day.driving_min, 1)
    day.stopped_min = round(day.stopped_min, 1)
    day.missed_planned = sorted(name for entity_id, name in planned.items() if entity_id not in visited)
    return day
