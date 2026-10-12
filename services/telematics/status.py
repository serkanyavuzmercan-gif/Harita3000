"""Freshness and movement flags derived from a vehicle's last telematics report."""

from datetime import datetime, timedelta

from backend.models import Vehicle, VehicleStatus

MOVING_SPEED_KMH = 3.0
DEFAULT_POLL_MIN = 5


def is_tracked(vehicle: Vehicle) -> bool:
    return vehicle.integration_id is not None and vehicle.last_seen_at is not None


def is_stale(vehicle: Vehicle, now: datetime) -> bool:
    if not is_tracked(vehicle):
        return False
    interval = vehicle.integration.poll_interval_min if vehicle.integration else DEFAULT_POLL_MIN
    return now - vehicle.last_seen_at > timedelta(minutes=2 * max(interval, 1))


def is_moving(vehicle: Vehicle, now: datetime) -> bool:
    if is_tracked(vehicle):
        return not is_stale(vehicle, now) and (vehicle.last_speed_kmh or 0) >= MOVING_SPEED_KMH
    return vehicle.current_status == VehicleStatus.on_route
