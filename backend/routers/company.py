"""Company profile, logo and own locations (headquarters, branches, depots, factories)."""

import io
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.deps import get_current_user, require_roles
from backend.models import Company, CompanyLocation, Region, User
from backend.schemas import CompanyIn, CompanyOut, LocationIn, LocationOut, LocationUpdate

router = APIRouter()
LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024


async def get_company(db: AsyncSession) -> Company:
    company = await db.scalar(select(Company).order_by(Company.id).limit(1))
    if company is None:
        company = Company(name="Firmam")
        db.add(company)
        await db.commit()
        await db.refresh(company)
    return company


async def default_depot(db: AsyncSession) -> CompanyLocation | None:
    return await db.scalar(
        select(CompanyLocation)
        .where(CompanyLocation.is_default_depot.is_(True))
        .order_by(CompanyLocation.id)
        .limit(1)
    )


async def _get_location(db: AsyncSession, location_id: int) -> CompanyLocation:
    location = await db.get(CompanyLocation, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lokasyon bulunamadı")
    return location


async def _ensure_region(db: AsyncSession, region_id: int | None) -> None:
    if region_id is not None and await db.get(Region, region_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bölge bulunamadı")


async def _clear_default(db: AsyncSession, keep_id: int | None) -> None:
    stmt = update(CompanyLocation).values(is_default_depot=False)
    if keep_id is not None:
        stmt = stmt.where(CompanyLocation.id != keep_id)
    await db.execute(stmt)


@router.get("", response_model=CompanyOut)
async def read_company(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyOut:
    return CompanyOut.model_validate(await get_company(db))


@router.put("", response_model=CompanyOut)
async def update_company(
    payload: CompanyIn,
    _: User = Depends(require_roles()),
    db: AsyncSession = Depends(get_db),
) -> CompanyOut:
    company = await get_company(db)
    for key, value in payload.model_dump().items():
        setattr(company, key, value)
    await db.commit()
    await db.refresh(company)
    return CompanyOut.model_validate(company)


@router.post("/logo", response_model=CompanyOut)
async def upload_logo(
    file: UploadFile = File(...),
    _: User = Depends(require_roles()),
    db: AsyncSession = Depends(get_db),
) -> CompanyOut:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in LOGO_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Logo PNG, JPG veya WEBP olmalı")
    content = await file.read()
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Logo 2 MB sınırını aşıyor")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Logo dosyası okunamadı") from None

    company = await get_company(db)
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    filename = f"company_logo_{uuid4().hex}{extension}"
    try:
        (settings.upload_path / filename).write_bytes(content)
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Logo kaydedilemedi") from exc
    previous = company.logo_path
    company.logo_path = f"/uploads/{filename}"
    await db.commit()
    await db.refresh(company)
    if previous and previous.startswith("/uploads/"):
        (settings.upload_path / previous.removeprefix("/uploads/")).unlink(missing_ok=True)
    return CompanyOut.model_validate(company)


@router.get("/locations", response_model=list[LocationOut])
async def list_locations(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LocationOut]:
    locations = (await db.scalars(select(CompanyLocation).order_by(CompanyLocation.name))).all()
    return [LocationOut.model_validate(location) for location in locations]


@router.post("/locations", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
async def create_location(
    payload: LocationIn,
    _: User = Depends(require_roles()),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    await _ensure_region(db, payload.region_id)
    location = CompanyLocation(**payload.model_dump())
    db.add(location)
    await db.flush()
    if location.is_default_depot:
        await _clear_default(db, location.id)
    await db.commit()
    await db.refresh(location)
    return LocationOut.model_validate(location)


@router.put("/locations/{location_id}", response_model=LocationOut)
async def update_location(
    location_id: int,
    payload: LocationUpdate,
    _: User = Depends(require_roles()),
    db: AsyncSession = Depends(get_db),
) -> LocationOut:
    location = await _get_location(db, location_id)
    changes = payload.model_dump(exclude_unset=True)
    for required in ("name", "kind", "latitude", "longitude", "is_default_depot"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Zorunlu alan boş bırakılamaz")
    if "region_id" in changes:
        await _ensure_region(db, changes["region_id"])
    for key, value in changes.items():
        setattr(location, key, value)
    if changes.get("is_default_depot"):
        await _clear_default(db, location.id)
    await db.commit()
    await db.refresh(location)
    return LocationOut.model_validate(location)


@router.delete("/locations/{location_id}")
async def delete_location(
    location_id: int,
    _: User = Depends(require_roles()),
    db: AsyncSession = Depends(get_db),
) -> dict:
    location = await _get_location(db, location_id)
    await db.delete(location)
    await db.commit()
    return {"ok": True}
