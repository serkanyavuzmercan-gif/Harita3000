"""Pull positions from a connector and store them against local vehicles."""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import FleetIntegration, Vehicle, VehiclePosition, utcnow
from services.telematics.base import PositionPoint, TelematicsError
from services.telematics.registry import adapter_for

logger = logging.getLogger("harita3000.telematics")

FIRST_SYNC_LOOKBACK = timedelta(hours=2)
MAX_LOOKBACK = timedelta(hours=24)
OVERLAP = timedelta(minutes=2)


@dataclass
class SyncResult:
    inserted: int = 0
    matched_vehicles: int = 0
    unmatched_ids: list[str] = field(default_factory=list)


async def store_positions(
    db: AsyncSession,
    integration: FleetIntegration,
    points: list[PositionPoint],
) -> SyncResult:
    vehicles = (
        await db.scalars(
            select(Vehicle).where(Vehicle.integration_id == integration.id, Vehicle.external_id.is_not(None))
        )
    ).all()
    by_external = {vehicle.external_id: vehicle for vehicle in vehicles}
    grouped: dict[str, list[PositionPoint]] = defaultdict(list)
    for point in points:
        grouped[point.external_id].append(point)

    result = SyncResult()
    for external_id, vehicle_points in grouped.items():
        vehicle = by_external.get(external_id)
        if vehicle is None:
            result.unmatched_ids.append(external_id)
            continue
        result.matched_vehicles += 1
        vehicle_points.sort(key=lambda item: item.recorded_at)
        first, last = vehicle_points[0].recorded_at, vehicle_points[-1].recorded_at
        existing = set(
            (
                await db.scalars(
                    select(VehiclePosition.recorded_at).where(
                        VehiclePosition.vehicle_id == vehicle.id,
                        VehiclePosition.recorded_at >= first,
                        VehiclePosition.recorded_at <= last,
                    )
                )
            ).all()
        )
        seen: set[datetime] = set()
        for point in vehicle_points:
            if point.recorded_at in existing or point.recorded_at in seen:
                continue
            seen.add(point.recorded_at)
            db.add(
                VehiclePosition(
                    vehicle_id=vehicle.id,
                    recorded_at=point.recorded_at,
                    latitude=point.latitude,
                    longitude=point.longitude,
                    speed_kmh=point.speed_kmh,
                    heading=point.heading,
                    ignition_on=point.ignition_on,
                )
            )
            result.inserted += 1
        latest = vehicle_points[-1]
        if vehicle.last_seen_at is None or latest.recorded_at >= vehicle.last_seen_at:
            vehicle.last_seen_at = latest.recorded_at
            vehicle.last_latitude = latest.latitude
            vehicle.last_longitude = latest.longitude
            vehicle.last_speed_kmh = latest.speed_kmh
            vehicle.last_heading = latest.heading
            vehicle.ignition_on = latest.ignition_on
    result.unmatched_ids.sort()
    return result


async def sync_integration(
    db: AsyncSession,
    integration: FleetIntegration,
    now: datetime | None = None,
) -> SyncResult:
    now = now or utcnow()
    name = integration.name
    if integration.last_sync_at is not None:
        since = integration.last_sync_at - OVERLAP
    else:
        since = now - FIRST_SYNC_LOOKBACK
    since = max(since, now - MAX_LOOKBACK)
    try:
        adapter = adapter_for(integration)
        adapter.validate()
        points = await adapter.fetch_positions(since, now)
        result = await store_positions(db, integration, points)
    except TelematicsError as exc:
        await db.rollback()
        integration.last_error = str(exc)
        await db.commit()
        raise
    except Exception as exc:
        logger.exception("Senkronizasyon hatası: %s", name)
        await db.rollback()
        integration.last_error = "Beklenmeyen hata, sunucu kaydına bakın"
        await db.commit()
        raise TelematicsError(integration.last_error) from exc
    integration.last_sync_at = now
    integration.last_error = None
    await db.commit()
    return result


def is_due(integration: FleetIntegration, now: datetime) -> bool:
    if not integration.is_active:
        return False
    if integration.last_sync_at is None:
        return True
    return now - integration.last_sync_at >= timedelta(minutes=max(integration.poll_interval_min, 1))
