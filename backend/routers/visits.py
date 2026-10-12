"""Field visit planning, check-in and form capture."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.deps import get_current_user
from backend.models import Entity, FieldVisit, Role, User, utcnow
from backend.schemas import VisitFormIn, VisitIn, VisitOut

router = APIRouter()


def _visit_out(visit: FieldVisit) -> VisitOut:
    payload = VisitOut.model_validate(visit)
    if visit.user is not None:
        payload.user_name = visit.user.full_name or visit.user.username
    if visit.entity is not None:
        payload.entity_name = visit.entity.name
    return payload


async def _load_visit(db: AsyncSession, visit_id: int) -> FieldVisit:
    visit = await db.scalar(
        select(FieldVisit)
        .options(selectinload(FieldVisit.user), selectinload(FieldVisit.entity))
        .where(FieldVisit.id == visit_id)
    )
    if visit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ziyaret bulunamadı")
    return visit


def _can_write(user: User, visit: FieldVisit) -> bool:
    if user.role == Role.admin:
        return True
    return user.role == Role.marketer and visit.user_id == user.id


@router.get("", response_model=list[VisitOut])
async def list_visits(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VisitOut]:
    stmt = (
        select(FieldVisit)
        .options(selectinload(FieldVisit.user), selectinload(FieldVisit.entity))
        .order_by(FieldVisit.created_at.desc())
    )
    if user.role == Role.marketer:
        stmt = stmt.where(FieldVisit.user_id == user.id)
    visits = (await db.scalars(stmt)).all()
    return [_visit_out(visit) for visit in visits]


@router.post("", response_model=VisitOut, status_code=status.HTTP_201_CREATED)
async def create_visit(
    payload: VisitIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitOut:
    if user.role not in {Role.admin, Role.marketer}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok")
    entity = await db.get(Entity, payload.entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cari bulunamadı")
    assignee_id = user.id
    if user.role == Role.admin and payload.user_id is not None:
        assignee = await db.get(User, payload.user_id)
        if assignee is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Personel bulunamadı")
        assignee_id = assignee.id
    visit = FieldVisit(
        user_id=assignee_id,
        entity_id=payload.entity_id,
        visit_type=payload.visit_type,
        notes=payload.notes,
        form_data_json=payload.form_data_json or {},
    )
    db.add(visit)
    await db.commit()
    return _visit_out(await _load_visit(db, visit.id))


@router.post("/{visit_id}/check-in", response_model=VisitOut)
async def check_in(
    visit_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitOut:
    visit = await _load_visit(db, visit_id)
    if not _can_write(user, visit):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu ziyaret size ait değil")
    if visit.check_in_time is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ziyaret zaten başlamış")
    visit.check_in_time = utcnow()
    await db.commit()
    return _visit_out(await _load_visit(db, visit.id))


@router.post("/{visit_id}/check-out", response_model=VisitOut)
async def check_out(
    visit_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitOut:
    visit = await _load_visit(db, visit_id)
    if not _can_write(user, visit):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu ziyaret size ait değil")
    if visit.check_in_time is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Önce check-in yapılmalı")
    if visit.check_out_time is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ziyaret zaten kapanmış")
    visit.check_out_time = utcnow()
    await db.commit()
    return _visit_out(await _load_visit(db, visit.id))


@router.put("/{visit_id}/form", response_model=VisitOut)
async def save_form(
    visit_id: int,
    payload: VisitFormIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VisitOut:
    visit = await _load_visit(db, visit_id)
    if not _can_write(user, visit):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu ziyaret size ait değil")
    if payload.notes is not None:
        visit.notes = payload.notes
    if payload.form_data_json is not None:
        visit.form_data_json = payload.form_data_json
    await db.commit()
    return _visit_out(await _load_visit(db, visit.id))
