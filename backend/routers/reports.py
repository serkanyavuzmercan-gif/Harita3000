"""Downloadable end-of-day route reports and the nightly archive."""

from datetime import date
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import settings
from backend.database import get_db
from backend.deps import require_roles
from backend.models import DailyRouteReport, Role, User
from backend.schemas import ArchiveItemOut
from services.reports.service import ReportError, archive_day, fleet_day_file, route_day_file

router = APIRouter()
report_staff = require_roles(Role.logistics)


def _download(content: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/route-day")
async def route_day(
    vehicle_id: int,
    day: date = Query(alias="date"),
    fmt: Literal["pdf", "xlsx"] = Query(default="pdf", alias="format"),
    _: User = Depends(report_staff),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        content, filename, media_type = await route_day_file(db, vehicle_id, day, fmt)
    except ReportError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    return _download(content, filename, media_type)


@router.get("/fleet-day")
async def fleet_day(
    day: date = Query(alias="date"),
    _: User = Depends(report_staff),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content, filename, media_type = await fleet_day_file(db, day)
    return _download(content, filename, media_type)


@router.post("/archive")
async def archive_now(
    day: date = Query(alias="date"),
    _: User = Depends(require_roles()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    written = await archive_day(db, day)
    return {"written": written}


@router.get("/archive", response_model=list[ArchiveItemOut])
async def archive_list(
    limit: int = Query(default=60, ge=1, le=500),
    _: User = Depends(report_staff),
    db: AsyncSession = Depends(get_db),
) -> list[ArchiveItemOut]:
    records = (
        await db.scalars(
            select(DailyRouteReport)
            .options(selectinload(DailyRouteReport.vehicle))
            .order_by(DailyRouteReport.report_date.desc(), DailyRouteReport.vehicle_id)
            .limit(limit)
        )
    ).all()
    return [
        ArchiveItemOut(
            id=record.id,
            vehicle_id=record.vehicle_id,
            plate_number=record.vehicle.plate_number if record.vehicle else "",
            report_date=record.report_date,
            distance_km=record.distance_km,
            created_at=record.created_at,
        )
        for record in records
    ]


@router.get("/archive/{record_id}/{kind}")
async def archive_file(
    record_id: int,
    kind: Literal["pdf", "xlsx"],
    _: User = Depends(report_staff),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    record = await db.get(DailyRouteReport, record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arşiv kaydı bulunamadı")
    relative = record.file_pdf if kind == "pdf" else record.file_xlsx
    base = settings.report_path.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rapor dosyası bulunamadı")
    return FileResponse(path, filename=path.name)
