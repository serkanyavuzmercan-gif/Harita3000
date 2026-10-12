"""Loads a vehicle day from the database and produces report files."""

import logging
import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.models import (
    Company,
    CompanyLocation,
    DailyRouteReport,
    Entity,
    EntityType,
    Shipment,
    ShipmentStatus,
    Vehicle,
    VehiclePosition,
    utcnow,
)
from services.reports.documents import RouteDayDocument, fleet_day_pdf, route_day_pdf, route_day_xlsx
from services.reports.route_day import Place, TrackPoint, analyze_day
from services.static_map import render_track

logger = logging.getLogger("harita3000.reports")

ENTITY_KIND = {
    EntityType.customer: "Müşteri",
    EntityType.supplier: "Tedarikçi",
    EntityType.competitor: "Rakip",
    EntityType.other: "Diğer",
}


class ReportError(Exception):
    pass


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, settings.tz)
    return start, start + timedelta(days=1)


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "arac"


async def day_points(db: AsyncSession, vehicle_id: int, day: date) -> list[TrackPoint]:
    start, end = local_day_bounds(day)
    rows = (
        await db.scalars(
            select(VehiclePosition)
            .where(
                VehiclePosition.vehicle_id == vehicle_id,
                VehiclePosition.recorded_at >= start,
                VehiclePosition.recorded_at < end,
            )
            .order_by(VehiclePosition.recorded_at)
        )
    ).all()
    return [
        TrackPoint(
            recorded_at=row.recorded_at,
            latitude=row.latitude,
            longitude=row.longitude,
            speed_kmh=row.speed_kmh or 0.0,
            ignition_on=row.ignition_on,
        )
        for row in rows
    ]


async def known_places(db: AsyncSession) -> list[Place]:
    places = [
        Place(name=location.name, kind=location.kind.value, latitude=location.latitude, longitude=location.longitude)
        for location in (await db.scalars(select(CompanyLocation))).all()
    ]
    entities = (
        await db.scalars(select(Entity).where(Entity.latitude.is_not(None), Entity.longitude.is_not(None)))
    ).all()
    places += [
        Place(
            name=entity.name,
            kind=ENTITY_KIND.get(entity.type, "Cari"),
            latitude=entity.latitude,
            longitude=entity.longitude,
            entity_id=entity.id,
        )
        for entity in entities
    ]
    return places


async def build_document(
    db: AsyncSession,
    vehicle: Vehicle,
    day: date,
    places: list[Place] | None = None,
) -> RouteDayDocument:
    points = await day_points(db, vehicle.id, day)
    shipments = (
        await db.scalars(
            select(Shipment)
            .options(selectinload(Shipment.entity), selectinload(Shipment.driver))
            .where(
                Shipment.vehicle_id == vehicle.id,
                Shipment.delivery_date == day,
                Shipment.status != ShipmentStatus.cancelled,
            )
        )
    ).all()
    planned = {shipment.entity_id: shipment.entity.name for shipment in shipments if shipment.entity}
    drivers = sorted(
        {shipment.driver.full_name or shipment.driver.username for shipment in shipments if shipment.driver}
    )
    route = analyze_day(points, places if places is not None else await known_places(db), planned)
    company = await db.scalar(select(Company).order_by(Company.id).limit(1))
    logo_file = None
    if company and company.logo_path and company.logo_path.startswith("/uploads/"):
        logo_file = settings.upload_path / company.logo_path.removeprefix("/uploads/")
    return RouteDayDocument(
        company_name=company.name if company else settings.app_name,
        logo_file=logo_file,
        vehicle_plate=vehicle.plate_number,
        vehicle_type=vehicle.vehicle_type.value,
        day=day,
        route=route,
        drivers=drivers,
    )


async def attach_map(doc: RouteDayDocument, with_tiles: bool = True) -> None:
    if not doc.route.points:
        return
    track = [(point.latitude, point.longitude) for point in doc.route.points]
    stops = [(stop.latitude, stop.longitude, str(stop.index)) for stop in doc.route.stops]
    try:
        doc.map_png = await render_track(track, stops, with_tiles=with_tiles)
    except Exception:
        logger.exception("Rapor haritası çizilemedi")
        doc.map_png = None


async def _vehicle(db: AsyncSession, vehicle_id: int) -> Vehicle:
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise ReportError("Araç bulunamadı")
    return vehicle


async def route_day_file(db: AsyncSession, vehicle_id: int, day: date, fmt: str) -> tuple[bytes, str, str]:
    vehicle = await _vehicle(db, vehicle_id)
    doc = await build_document(db, vehicle, day)
    stem = f"rota_{safe_name(vehicle.plate_number)}_{day.isoformat()}"
    if fmt == "xlsx":
        return (
            route_day_xlsx(doc),
            f"{stem}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    await attach_map(doc)
    return route_day_pdf(doc), f"{stem}.pdf", "application/pdf"


async def vehicles_with_data(db: AsyncSession, day: date) -> list[Vehicle]:
    start, end = local_day_bounds(day)
    ids = select(VehiclePosition.vehicle_id).where(
        VehiclePosition.recorded_at >= start,
        VehiclePosition.recorded_at < end,
    )
    return list((await db.scalars(select(Vehicle).where(Vehicle.id.in_(ids)).order_by(Vehicle.plate_number))).all())


async def fleet_day_file(db: AsyncSession, day: date) -> tuple[bytes, str, str]:
    places = await known_places(db)
    docs = []
    for vehicle in await vehicles_with_data(db, day):
        doc = await build_document(db, vehicle, day, places)
        await attach_map(doc)
        docs.append(doc)
    company = await db.scalar(select(Company).order_by(Company.id).limit(1))
    content = fleet_day_pdf(company.name if company else settings.app_name, day, docs)
    return content, f"filo_rota_{day.isoformat()}.pdf", "application/pdf"


async def archive_day(db: AsyncSession, day: date) -> int:
    folder = settings.report_path / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    places = await known_places(db)
    written = 0
    for vehicle in await vehicles_with_data(db, day):
        doc = await build_document(db, vehicle, day, places)
        await attach_map(doc)
        stem = safe_name(vehicle.plate_number)
        pdf_path = folder / f"{stem}.pdf"
        xlsx_path = folder / f"{stem}.xlsx"
        pdf_path.write_bytes(route_day_pdf(doc))
        xlsx_path.write_bytes(route_day_xlsx(doc))
        record = await db.scalar(
            select(DailyRouteReport).where(
                DailyRouteReport.vehicle_id == vehicle.id,
                DailyRouteReport.report_date == day,
            )
        )
        if record is None:
            record = DailyRouteReport(vehicle_id=vehicle.id, report_date=day, file_pdf="", file_xlsx="")
            db.add(record)
        record.distance_km = doc.route.distance_km
        record.file_pdf = pdf_path.relative_to(settings.report_path).as_posix()
        record.file_xlsx = xlsx_path.relative_to(settings.report_path).as_posix()
        record.created_at = utcnow()
        written += 1
    await db.commit()
    return written


async def purge_old_positions(db: AsyncSession, retention_days: int) -> int:
    cutoff = utcnow() - timedelta(days=retention_days)
    result = await db.execute(delete(VehiclePosition).where(VehiclePosition.recorded_at < cutoff))
    await db.commit()
    return int(result.rowcount or 0)
