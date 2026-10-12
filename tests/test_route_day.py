from datetime import datetime, timedelta, timezone

import pytest

from services.distance import haversine_km
from services.reports.route_day import Place, TrackPoint, analyze_day, detect_stop_runs

START = datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc)


def _drive(points, minute, minutes, lat, lng, step_lat):
    for _ in range(minutes):
        points.append(TrackPoint(START + timedelta(minutes=minute), lat, lng, 40.0))
        lat += step_lat
        minute += 1
    return minute, lat


def _park(points, minute, minutes, lat, lng):
    for _ in range(minutes):
        points.append(TrackPoint(START + timedelta(minutes=minute), lat, lng, 0.0))
        minute += 1
    return minute


def _sample_day():
    points: list[TrackPoint] = []
    lat, lng = 37.80, 29.05
    minute, lat = _drive(points, 0, 10, lat, lng, 0.005)
    minute = _park(points, minute, 15, lat, lng)
    stop_lat = lat
    minute, lat = _drive(points, minute, 10, lat, lng, 0.005)
    minute = _park(points, minute, 3, lat, lng)
    minute, lat = _drive(points, minute, 5, lat, lng, 0.005)
    return points, stop_lat, lng


def test_short_halts_are_not_stops():
    points, _, _ = _sample_day()
    runs = detect_stop_runs(points)
    assert len(runs) == 1


def test_stop_place_distance_and_planned_comparison():
    points, stop_lat, stop_lng = _sample_day()
    places = [
        Place("Saraylar Market", "Müşteri", stop_lat + 0.0005, stop_lng, entity_id=1),
        Place("Uzak Market", "Müşteri", 38.5, 29.9, entity_id=2),
    ]
    day = analyze_day(points, places, planned={1: "Saraylar Market", 2: "Uzak Market"})

    assert len(day.stops) == 1
    stop = day.stops[0]
    assert stop.place is not None and stop.place.name == "Saraylar Market"
    assert stop.planned is True
    assert stop.duration_min == pytest.approx(14.0)
    assert day.missed_planned == ["Uzak Market"]

    moving_km = sum(
        haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)
        for a, b in zip(points, points[1:])
        if not (a.speed_kmh < 3 and b.speed_kmh < 3)
    )
    assert day.distance_km == pytest.approx(round(moving_km, 2))
    assert day.first_move == START
    assert day.max_speed_kmh == 40.0


def test_empty_day_reports_all_planned_as_missed():
    day = analyze_day([], [], planned={5: "Tavas Kooperatif Market"})
    assert day.stops == []
    assert day.distance_km == 0
    assert day.missed_planned == ["Tavas Kooperatif Market"]
