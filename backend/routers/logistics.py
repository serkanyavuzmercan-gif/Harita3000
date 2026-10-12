"""Fleet assignment, shipment queue and stop ordering."""

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.database import get_db
from backend.deps import get_current_user, require_roles
from backend.models import Entity, Role, Shipment, ShipmentStatus, User, Vehicle, VehicleStatus
from backend.schemas import (
    OptimizeIn,
    OptimizeOut,
    OptimizeStopOut,
    RouteIn,
    RouteOut,
    ShipmentIn,
    ShipmentOut,
    ShipmentUpdate,
    UserOut,
    VehicleIn,
    VehicleOut,
    VehicleUpdate,
)
from services.routing import RoutingError, Stop, fetch_road_route, order_stops

router = APIRouter()
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _shipment_out(shipment: Shipment) -> ShipmentOut:
    payload = ShipmentOut.model_validate(shipment)
    if shipment.entity is not None:
        payload.entity_name = shipment.entity.name
        payload.entity_latitude = shipment.entity.latitude
        payload.entity_longitude = shipment.entity.longitude
    if shipment.vehicle is not None:
        payload.vehicle_plate = shipment.vehicle.plate_number
    if shipment.driver is not None:
        payload.driver_name = shipment.driver.full_name or shipment.driver.username
    return payload


async def _load_shipment(db: AsyncSession, shipment_id: int) -> Shipment:
    shipment = await db.scalar(
        select(Shipment)
        .options(
            selectinload(Shipment.entity),
            selectinload(Shipment.vehicle),
            selectinload(Shipment.driver),
        )
        .where(Shipment.id == shipment_id)
    )
    if shipment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sevkiyat bulunamadı")
    return shipment


async def _sync_vehicle_status(db: AsyncSession, vehicle_id: int | None) -> None:
    if vehicle_id is None:
        return
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.current_status == VehicleStatus.maintenance:
        return
    active = await db.scalar(
        select(func.count())
        .select_from(Shipment)
        .where(Shipment.vehicle_id == vehicle_id, Shipment.status == ShipmentStatus.on_route)
    )
    vehicle.current_status = VehicleStatus.on_route if active else VehicleStatus.available


async def _apply_shipment_update(
    db: AsyncSession,
    shipment: Shipment,
    payload: ShipmentUpdate,
    user: User,
) -> Shipment:
    changes = payload.model_dump(exclude_unset=True)
    if user.role == Role.marketer:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok")
    if user.role == Role.driver:
        if shipment.driver_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu sevkiyat size atanmış değil")
        blocked = set(changes) - {"status", "notes"}
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sürücü yalnızca durum ve not güncelleyebilir",
            )
    if user.role not in {Role.admin, Role.logistics, Role.driver}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok")

    previous_vehicle_id = shipment.vehicle_id
    next_vehicle_id = changes["vehicle_id"] if "vehicle_id" in changes else shipment.vehicle_id
    next_driver_id = changes["driver_id"] if "driver_id" in changes else shipment.driver_id
    next_status = changes.get("status", shipment.status)

    if next_vehicle_id is not None:
        vehicle = await db.get(Vehicle, next_vehicle_id)
        if vehicle is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Araç bulunamadı")
        if vehicle.current_status == VehicleStatus.maintenance and next_status == ShipmentStatus.on_route:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bakımdaki araç yola çıkamaz")
    if next_driver_id is not None:
        driver = await db.get(User, next_driver_id)
        if driver is None or driver.role != Role.driver:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sürücü bulunamadı")
    if next_status == ShipmentStatus.on_route and (next_vehicle_id is None or next_driver_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yola çıkmak için araç ve sürücü gerekli",
        )

    for key, value in changes.items():
        setattr(shipment, key, value)
    await db.flush()
    await _sync_vehicle_status(db, previous_vehicle_id)
    await _sync_vehicle_status(db, shipment.vehicle_id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Sevkiyat kaydı çakışıyor") from None
    return await _load_shipment(db, shipment.id)


@router.get("/vehicles", response_model=list[VehicleOut])
async def list_vehicles(
    _: User = Depends(require_roles(Role.logistics)),
    db: AsyncSession = Depends(get_db),
) -> list[VehicleOut]:
    vehicles = (await db.scalars(select(Vehicle).order_by(Vehicle.plate_number))).all()
    return [VehicleOut.model_validate(vehicle) for vehicle in vehicles]


@router.post("/vehicles", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    payload: VehicleIn,
    _: User = Depends(require_roles(Role.logistics)),
    db: AsyncSession = Depends(get_db),
) -> VehicleOut:
    if (payload.last_latitude is None) ^ (payload.last_longitude is None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enlem ve boylam birlikte gönderilmeli")
    vehicle = Vehicle(**payload.model_dump())
    vehicle.plate_number = vehicle.plate_number.strip().upper()
    db.add(vehicle)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bu plaka zaten kayıtlı") from None
    await db.refresh(vehicle)
    return VehicleOut.model_validate(vehicle)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdate,
    _: User = Depends(require_roles(Role.logistics)),
    db: AsyncSession = Depends(get_db),
) -> VehicleOut:
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Araç bulunamadı")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("plate_number"):
        changes["plate_number"] = changes["plate_number"].strip().upper()
    for key, value in changes.items():
        setattr(vehicle, key, value)
    if (vehicle.last_latitude is None) ^ (vehicle.last_longitude is None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enlem ve boylam birlikte gönderilmeli")
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bu plaka zaten kayıtlı") from None
    await db.refresh(vehicle)
    return VehicleOut.model_validate(vehicle)


@router.get("/drivers", response_model=list[UserOut])
async def list_drivers(
    _: User = Depends(require_roles(Role.logistics)),
    db: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    drivers = (
        await db.scalars(select(User).where(User.role == Role.driver, User.is_active.is_(True)).order_by(User.full_name))
    ).all()
    return [UserOut.model_validate(driver) for driver in drivers]


@router.get("/shipments", response_model=list[ShipmentOut])
async def list_shipments(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ShipmentOut]:
    stmt = select(Shipment).options(
        selectinload(Shipment.entity),
        selectinload(Shipment.vehicle),
        selectinload(Shipment.driver),
    )
    if user.role == Role.driver:
        stmt = stmt.where(Shipment.driver_id == user.id)
    stmt = stmt.order_by(Shipment.created_at.desc())
    shipments = (await db.scalars(stmt)).all()
    return [_shipment_out(shipment) for shipment in shipments]


@router.post("/shipments", response_model=ShipmentOut, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    payload: ShipmentIn,
    user: User = Depends(require_roles(Role.logistics)),
    db: AsyncSession = Depends(get_db),
) -> ShipmentOut:
    entity = await db.get(Entity, payload.entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cari bulunamadı")
    shipment = Shipment(
        entity_id=payload.entity_id,
        vehicle_id=payload.vehicle_id,
        driver_id=payload.driver_id,
        status=ShipmentStatus.pending,
        items_json=[item.model_dump() for item in payload.items_json],
        delivery_date=payload.delivery_date,
        notes=payload.notes,
    )
    db.add(shipment)
    await db.flush()
    updated = await _apply_shipment_update(
        db,
        shipment,
        ShipmentUpdate(
            vehicle_id=payload.vehicle_id,
            driver_id=payload.driver_id,
            status=payload.status,
        ),
        user,
    )
    return _shipment_out(updated)


@router.post("/shipments/{shipment_id}/assign", response_model=ShipmentOut)
async def assign_shipment(
    shipment_id: int,
    payload: ShipmentUpdate,
    user: User = Depends(require_roles(Role.logistics)),
    db: AsyncSession = Depends(get_db),
) -> ShipmentOut:
    shipment = await _load_shipment(db, shipment_id)
    updated = await _apply_shipment_update(db, shipment, payload, user)
    return _shipment_out(updated)


@router.patch("/shipments/{shipment_id}", response_model=ShipmentOut)
async def update_shipment(
    shipment_id: int,
    payload: ShipmentUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShipmentOut:
    shipment = await _load_shipment(db, shipment_id)
    updated = await _apply_shipment_update(db, shipment, payload, user)
    return _shipment_out(updated)


@router.post("/optimize", response_model=OptimizeOut)
async def optimize_route(
    payload: OptimizeIn,
    _: User = Depends(require_roles(Role.logistics)),
    db: AsyncSession = Depends(get_db),
) -> OptimizeOut:
    stops = [Stop(id=item.id, latitude=item.latitude, longitude=item.longitude, label=item.label) for item in payload.stops]
    try:
        ordered, total = await order_stops(db, payload.origin_lat, payload.origin_lng, stops)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rota sıralanamadı") from exc
    return OptimizeOut(
        total_km=total,
        stops=[
            OptimizeStopOut(
                id=stop.id,
                latitude=stop.latitude,
                longitude=stop.longitude,
                label=stop.label,
                leg_km=leg,
            )
            for stop, leg in ordered
        ],
    )


@router.post("/route", response_model=RouteOut)
async def road_route(
    payload: RouteIn,
    _: User = Depends(require_roles(Role.logistics)),
) -> RouteOut:
    try:
        result = await fetch_road_route([(point.latitude, point.longitude) for point in payload.points])
    except RoutingError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    return RouteOut(
        coordinates=result.coordinates,
        distance_km=result.distance_km,
        duration_min=result.duration_min,
    )


@router.post("/shipments/{shipment_id}/proof", response_model=ShipmentOut)
async def upload_proof(
    shipment_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShipmentOut:
    shipment = await _load_shipment(db, shipment_id)
    if user.role == Role.driver and shipment.driver_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu sevkiyat size atanmış değil")
    if user.role not in {Role.admin, Role.logistics, Role.driver}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok")
    extension = Path(file.filename or "").suffix.lower()
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if extension not in IMAGE_EXTENSIONS or (
        content_type and content_type not in IMAGE_TYPES and content_type != "application/octet-stream"
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Yalnızca görsel teslim kanıtı yüklenebilir")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Dosya 5 MB sınırını aşıyor")
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    filename = f"pod_{shipment_id}_{uuid4().hex}{extension}"
    try:
        (settings.upload_path / filename).write_bytes(content)
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Dosya kaydedilemedi") from exc
    shipment.proof_of_delivery_img = f"/uploads/{filename}"
    await db.commit()
    return _shipment_out(await _load_shipment(db, shipment.id))
