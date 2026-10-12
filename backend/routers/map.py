"""Map pins, public map configuration and dashboard counters."""

from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.database import get_db
from backend.deps import get_current_user
from backend.models import (
    CompanyLocation,
    Entity,
    EntityCategory,
    EntityStatus,
    EntityType,
    FieldVisit,
    Region,
    Shipment,
    ShipmentStatus,
    User,
    Vehicle,
    VehicleStatus,
    utcnow,
)
from backend.routers.company import default_depot
from backend.schemas import (
    DashboardSummary,
    LastShipment,
    LocationOut,
    MapConfig,
    MapData,
    MapEntityPin,
    MapVehiclePin,
    PlaceOut,
    PlaceSearchOut,
    RegionOut,
    ReverseGeocodeOut,
)
from services.geocoding import reverse_geocode, search_places
from services.telematics.status import is_moving, is_stale, is_tracked

router = APIRouter()


@router.get("/regions", response_model=list[RegionOut])
async def list_regions(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RegionOut]:
    regions = (await db.scalars(select(Region).order_by(Region.name))).all()
    return [RegionOut.model_validate(region) for region in regions]


@router.get("/geocode/reverse", response_model=ReverseGeocodeOut)
async def reverse(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    _: User = Depends(get_current_user),
) -> ReverseGeocodeOut:
    result = await reverse_geocode(lat, lng)
    return ReverseGeocodeOut(address=result.address, warning=result.warning)


@router.get("/geocode/search", response_model=PlaceSearchOut)
async def search(
    q: str = Query(min_length=1, max_length=200),
    lat: float = Query(default=settings.map_center_lat, ge=-90, le=90),
    lng: float = Query(default=settings.map_center_lng, ge=-180, le=180),
    _: User = Depends(get_current_user),
) -> PlaceSearchOut:
    result = await search_places(q, lat, lng)
    return PlaceSearchOut(
        provider=result.provider,
        results=[
            PlaceOut(name=place.name, address=place.address, latitude=place.latitude, longitude=place.longitude)
            for place in result.places
        ],
        warning=result.warning,
    )


@router.get("/map/config", response_model=MapConfig)
async def map_config(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MapConfig:
    provider = settings.active_map_provider
    depot = await default_depot(db)
    return MapConfig(
        app_name=settings.app_name,
        provider=provider,
        google_maps_api_key=settings.google_maps_api_key if provider == "google" else "",
        tile_url=settings.tile_url,
        tile_attribution=settings.tile_attribution,
        center_lat=settings.map_center_lat,
        center_lng=settings.map_center_lng,
        zoom=settings.map_zoom,
        depot_lat=depot.latitude if depot else settings.depot_lat,
        depot_lng=depot.longitude if depot else settings.depot_lng,
        depot_label=depot.name if depot else settings.depot_label,
        vehicle_refresh_seconds=settings.vehicle_refresh_seconds,
    )


@router.get("/map/data", response_model=MapData)
async def map_data(
    region_id: int | None = None,
    category: EntityCategory | None = None,
    status_filter: EntityStatus | None = Query(default=None, alias="status"),
    entity_type: EntityType | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MapData:
    stmt = select(Entity)
    count_stmt = select(func.count()).select_from(Entity)
    if region_id is not None:
        stmt = stmt.where(Entity.region_id == region_id)
        count_stmt = count_stmt.where(Entity.region_id == region_id)
    if category is not None:
        stmt = stmt.where(Entity.category == category)
        count_stmt = count_stmt.where(Entity.category == category)
    if status_filter is not None:
        stmt = stmt.where(Entity.status == status_filter)
        count_stmt = count_stmt.where(Entity.status == status_filter)
    if entity_type is not None:
        stmt = stmt.where(Entity.type == entity_type)
        count_stmt = count_stmt.where(Entity.type == entity_type)

    entities = (await db.scalars(stmt.order_by(Entity.name))).all()
    located = [entity for entity in entities if entity.latitude is not None and entity.longitude is not None]
    total = await db.scalar(count_stmt) or 0

    latest_rows = (
        await db.execute(
            select(Shipment.entity_id, func.max(Shipment.id).label("max_id")).group_by(Shipment.entity_id)
        )
    ).all()
    latest_ids = [row.max_id for row in latest_rows]
    latest: dict[int, Shipment] = {}
    if latest_ids:
        shipments = (await db.scalars(select(Shipment).where(Shipment.id.in_(latest_ids)))).all()
        latest = {shipment.entity_id: shipment for shipment in shipments}

    pins = []
    for entity in located:
        shipment = latest.get(entity.id)
        pins.append(
            MapEntityPin(
                id=entity.id,
                name=entity.name,
                type=entity.type,
                category=entity.category,
                address=entity.address,
                latitude=entity.latitude,
                longitude=entity.longitude,
                phone=entity.phone,
                current_balance=entity.current_balance,
                status=entity.status,
                region_id=entity.region_id,
                last_shipment=(
                    LastShipment(
                        id=shipment.id,
                        status=shipment.status,
                        delivery_date=shipment.delivery_date,
                    )
                    if shipment is not None
                    else None
                ),
            )
        )

    vehicle_stmt = (
        select(Vehicle)
        .options(selectinload(Vehicle.integration))
        .where(
            or_(Vehicle.current_status != VehicleStatus.available, Vehicle.last_seen_at.is_not(None)),
            Vehicle.last_latitude.is_not(None),
            Vehicle.last_longitude.is_not(None),
        )
    )
    if region_id is not None:
        vehicle_stmt = vehicle_stmt.where(Vehicle.region_id == region_id)
    vehicles = (await db.scalars(vehicle_stmt)).all()
    now = utcnow()
    vehicle_pins = [
        MapVehiclePin(
            id=vehicle.id,
            plate_number=vehicle.plate_number,
            vehicle_type=vehicle.vehicle_type,
            current_status=vehicle.current_status,
            latitude=vehicle.last_latitude,
            longitude=vehicle.last_longitude,
            region_id=vehicle.region_id,
            tracked=is_tracked(vehicle),
            moving=is_moving(vehicle, now),
            stale=is_stale(vehicle, now),
            speed_kmh=vehicle.last_speed_kmh,
            last_seen_at=vehicle.last_seen_at,
        )
        for vehicle in vehicles
        if vehicle.last_latitude is not None and vehicle.last_longitude is not None
    ]

    location_stmt = select(CompanyLocation).order_by(CompanyLocation.name)
    if region_id is not None:
        location_stmt = location_stmt.where(CompanyLocation.region_id == region_id)
    locations = (await db.scalars(location_stmt)).all()
    return MapData(
        entities=pins,
        vehicles=vehicle_pins,
        company_locations=[LocationOut.model_validate(location) for location in locations],
        unlocated_count=max(int(total) - len(located), 0),
    )


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    today = datetime.now(settings.tz).date()
    # SQLite stores these columns as naive UTC wall-clock time, so the bounds must be UTC as well.
    day_start = datetime.combine(today, time.min, settings.tz).astimezone(timezone.utc)
    completed = await db.scalar(
        select(func.count())
        .select_from(FieldVisit)
        .where(
            FieldVisit.check_out_time >= day_start,
            FieldVisit.check_out_time < day_start + timedelta(days=1),
        )
    )
    on_route = await db.scalar(
        select(func.count()).select_from(Shipment).where(Shipment.status == ShipmentStatus.on_route)
    )
    urgent = await db.scalar(
        select(func.count())
        .select_from(Shipment)
        .where(
            Shipment.status.in_([ShipmentStatus.pending, ShipmentStatus.on_route]),
            Shipment.delivery_date.is_not(None),
            Shipment.delivery_date <= today,
        )
    )
    pending = await db.scalar(
        select(func.count()).select_from(Shipment).where(Shipment.status == ShipmentStatus.pending)
    )
    return DashboardSummary(
        completed_visits_today=int(completed or 0),
        shipments_on_route=int(on_route or 0),
        urgent_deliveries=int(urgent or 0),
        pending_shipments=int(pending or 0),
    )
