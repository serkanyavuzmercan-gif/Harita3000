"""Login and current-user endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.deps import get_current_user
from backend.models import User
from backend.schemas import LoginIn, TokenOut, UserOut
from backend.security import create_access_token, verify_password

router = APIRouter()


def _user_out(user: User) -> UserOut:
    payload = UserOut.model_validate(user)
    payload.region_name = user.region.name if user.region else None
    return payload


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    user = await db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı adı veya parola hatalı",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hesap pasif")
    token = create_access_token(user_id=user.id, username=user.username, role=user.role.value)
    return TokenOut(
        access_token=token,
        role=user.role,
        username=user.username,
        full_name=user.full_name,
    )


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> UserOut:
    user = await db.scalar(select(User).options(selectinload(User.region)).where(User.id == current.id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanıcı bulunamadı")
    return _user_out(user)
