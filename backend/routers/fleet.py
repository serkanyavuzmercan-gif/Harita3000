"""Fleet tracking integrations, vehicle linking, live positions and daily tracks."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.deps import require_roles
from backend.models import FleetIntegration, Role, User, Vehicle, utcnow
from backend.schemas import (
    ExternalVehicleOut,
    IntegrationIn,
    IntegrationOut,
    IntegrationTestOut,
    IntegrationUpdate,
    LiveVehicleOut,
    SyncOut,
    TrackOut,
    TrackPointOut,
    TrackStopOut,
    TrackSummaryOut,
    VehicleLinkIn,
)
from services.reports.service import build_document
from services.telematics.base import TelematicsError
from services.telematics.crypto import decrypt_credentials, encrypt_credentials
from services.telematics.registry import adapter_class, adapter_for, provider_catalog
from services.telematics.status import is_moving, is_stale, is_tracked
from services.telematics.sync import sync_integration

router = APIRouter()
admin_only = require_roles()
fleet_staff = require_roles(Role.logistics)


def _clean(credentials: dict[str, str]) -> dict[str, str]:
    return {key: value.strip() for key, value in credentials.items() if value is not None and value.strip()}


async def _integration_out(db: AsyncSession, integration: FleetIntegration) -> IntegrationOut:
    count = await db.scalar(select(func.count()).select_from(Vehicle).where(Vehicle.integration_id == integration.id))
    try:
        configured = sorted(decrypt_credentials(integration.credentials_encrypted))
    except TelematicsError:
        configured = []
    return IntegrationOut(
        id=integration.id,
        provider=integration.provider,
        name=integration.name,
        poll_interval_min=integration.poll_interval_min,
        is_active=integration.is_active,
        last_sync_at=integration.last_sync_at,
        last_error=integration.last_error,
        vehicle_count=int(count or 0),
        configured_fields=configured,
    )


async def _get_integration(db: AsyncSession, integration_id: int) -> FleetIntegration:
    integration = await db.get(FleetIntegration, integration_id)
    if integration is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entegrasyon bulunamadı")
    return integration


@router.get("/providers")
async def providers(_: User = Depends(admin_only)) -> list[dict]:
    return provider_catalog()


@router.get("/integrations", response_model=list[IntegrationOut])
async def list_integrations(
    _: User = Depends(fleet_staff),
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationOut]:
    integrations = (await db.scalars(select(FleetIntegration).order_by(FleetIntegration.name))).all()
    return [await _integration_out(db, integration) for integration in integrations]


@router.post("/integrations", response_model=IntegrationOut, status_code=status.HTTP_201_CREATED)
async def create_integration(
    payload: IntegrationIn,
    _: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> IntegrationOut:
    credentials = _clean(payload.credentials)
    try:
        adapter_class(payload.provider)(credentials).validate()
    except TelematicsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    integration = FleetIntegration(
        provider=payload.provider,
        name=payload.name.strip(),
        poll_interval_min=payload.poll_interval_min,
        is_active=payload.is_active,
        credentials_encrypted=encrypt_credentials(credentials),
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    return await _integration_out(db, integration)


@router.put("/integrations/{integration_id}", response_model=IntegrationOut)
async def update_integration(
    integration_id: int,
    payload: IntegrationUpdate,
    _: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> IntegrationOut:
    integration = await _get_integration(db, integration_id)
    changes = payload.model_dump(exclude_unset=True)
    if "credentials" in changes and changes["credentials"] is not None:
        try:
            current = decrypt_credentials(integration.credentials_encrypted)
        except TelematicsError:
            current = {}
        merged = {**current, **_clean(changes.pop("credentials"))}
        try:
            adapter_class(integration.provider)(merged).validate()
        except TelematicsError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
        integration.credentials_encrypted = encrypt_credentials(merged)
    else:
        changes.pop("credentials", None)
    for key, value in changes.items():
        if value is not None:
            setattr(integration, key, value)
    await db.commit()
    await db.refresh(integration)
    return await _integration_out(db, integration)


@router.delete("/integrations/{integration_id}")
async def delete_integration(
    integration_id: int,
    _: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> dict:
    integration = await _get_integration(db, integration_id)
    vehicles = (await db.scalars(select(Vehicle).where(Vehicle.integration_id == integration.id))).all()
    for vehicle in vehicles:
        vehicle.integration_id = None
        vehicle.external_id = None
    await db.delete(integration)
    await db.commit()
    return {"ok": True}


@router.post("/integrations/{integration_id}/test", response_model=IntegrationTestOut)
async def test_integration(
    integration_id: int,
    _: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> IntegrationTestOut:
    integration = await _get_integration(db, integration_id)
    try:
        count = await adapter_for(integration).test_connection()
    except TelematicsError as exc:
        return IntegrationTestOut(ok=False, message=str(exc))
    return IntegrationTestOut(ok=True, vehicle_count=count, message=f"Bağlantı başarılı, {count} araç görüldü")


@router.post("/integrations/{integration_id}/sync", response_model=SyncOut)
async def sync_now(
    integration_id: int,
    _: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> SyncOut:
    integration = await _get_integration(db, integration_id)
    try:
        result = await sync_integration(db, integration)
    except TelematicsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    return SyncOut(
        inserted=result.inserted,
        matched_vehicles=result.matched_vehicles,
        unmatched_ids=result.unmatched_ids,
    )


@router.get("/integrations/{integration_id}/external-vehicles", response_model=list[ExternalVehicleOut])
async def external_vehicles(
    integration_id: int,
    _: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> list[ExternalVehicleOut]:
    integration = await _get_integration(db, integration_id)
    try:
        remote = await adapter_for(integration).list_vehicles()
    except TelematicsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    linked = {
        vehicle.external_id: vehicle.id
        for vehicle in (await db.scalars(select(Vehicle).where(Vehicle.integration_id == integration.id))).all()
    }
    return [
        ExternalVehicleOut(
            external_id=item.external_id,
            label=item.label,
            plate=item.plate,
            linked_vehicle_id=linked.get(item.external_id),
        )
        for item in remote
    ]


@router.put("/vehicles/{vehicle_id}/link", response_model=LiveVehicleOut)
async def link_vehicle(
    vehicle_id: int,
    payload: VehicleLinkIn,
    _: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> LiveVehicleOut:
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Araç bulunamadı")
    external_id = (payload.external_id or "").strip() or None
    if payload.integration_id is None or external_id is None:
        vehicle.integration_id = None
        vehicle.external_id = None
    else:
        await _get_integration(db, payload.integration_id)
        clash = await db.scalar(
            select(Vehicle).where(
                Vehicle.integration_id == payload.integration_id,
                Vehicle.external_id == external_id,
                Vehicle.id != vehicle.id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Bu harici araç zaten {clash.plate_number} plakasına bağlı",
            )
        vehicle.integration_id = payload.integration_id
        vehicle.external_id = external_id
    await db.commit()
    vehicle = await db.scalar(select(Vehicle).options(selectinload(Vehicle.integration)).where(Vehicle.id == vehicle_id))
    return _live(vehicle)


def _live(vehicle: Vehicle) -> LiveVehicleOut:
    now = utcnow()
    return LiveVehicleOut(
        id=vehicle.id,
        plate_number=vehicle.plate_number,
        vehicle_type=vehicle.vehicle_type,
        current_status=vehicle.current_status,
        integration_id=vehicle.integration_id,
        integration_name=vehicle.integration.name if vehicle.integration else None,
        external_id=vehicle.external_id,
        latitude=vehicle.last_latitude,
        longitude=vehicle.last_longitude,
        speed_kmh=vehicle.last_speed_kmh,
        heading=vehicle.last_heading,
        ignition_on=vehicle.ignition_on,
        last_seen_at=vehicle.last_seen_at,
        tracked=is_tracked(vehicle),
        moving=is_moving(vehicle, now),
        stale=is_stale(vehicle, now),
    )


@router.get("/live", response_model=list[LiveVehicleOut])
async def live(
    _: User = Depends(fleet_staff),
    db: AsyncSession = Depends(get_db),
) -> list[LiveVehicleOut]:
    vehicles = (
        await db.scalars(select(Vehicle).options(selectinload(Vehicle.integration)).order_by(Vehicle.plate_number))
    ).all()
    return [_live(vehicle) for vehicle in vehicles]


@router.get("/vehicles/{vehicle_id}/track", response_model=TrackOut)
async def track(
    vehicle_id: int,
    day: date = Query(alias="date"),
    _: User = Depends(fleet_staff),
    db: AsyncSession = Depends(get_db),
) -> TrackOut:
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Araç bulunamadı")
    doc = await build_document(db, vehicle, day)
    route = doc.route
    return TrackOut(
        vehicle_id=vehicle.id,
        plate_number=vehicle.plate_number,
        date=day,
        points=[
            TrackPointOut(t=point.recorded_at, lat=point.latitude, lng=point.longitude, speed=point.speed_kmh)
            for point in route.points
        ],
        stops=[
            TrackStopOut(
                index=stop.index,
                start=stop.start,
                end=stop.end,
                latitude=stop.latitude,
                longitude=stop.longitude,
                duration_min=stop.duration_min,
                place_name=stop.place.name if stop.place else None,
                place_kind=stop.place.kind if stop.place else None,
                planned=stop.planned,
            )
            for stop in route.stops
        ],
        summary=TrackSummaryOut(
            distance_km=route.distance_km,
            driving_min=route.driving_min,
            stopped_min=route.stopped_min,
            first_move=route.first_move,
            last_move=route.last_move,
            max_speed_kmh=route.max_speed_kmh,
        ),
        missed_planned=route.missed_planned,
    )
