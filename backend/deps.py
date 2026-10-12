"""Authentication dependencies and role gates."""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.models import Role, User
from backend.security import decode_token, hash_password

bearer_scheme = HTTPBearer(auto_error=False)
LOCAL_ADMIN_USERNAME = "yonetici"


async def local_admin(db: AsyncSession) -> User:
    """The account every request acts as when login is switched off."""
    user = await db.scalar(
        select(User).where(User.role == Role.admin, User.is_active.is_(True)).order_by(User.id).limit(1)
    )
    if user is None:
        user = User(
            username=LOCAL_ADMIN_USERNAME,
            hashed_password=hash_password(secrets.token_urlsafe(24)),
            role=Role.admin,
            full_name="Yönetici",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def _user_from_token(token: str, db: AsyncSession) -> User:
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub", "0"))
    except (InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya süresi dolmuş oturum",
        ) from None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı bulunamadı veya pasif",
        )
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else ""
    if not settings.auth_required:
        if token:
            try:
                return await _user_from_token(token, db)
            except HTTPException:
                pass
        return await local_admin(db)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Oturum gerekli")
    return await _user_from_token(token, db)


def require_roles(*roles: Role):
    allowed = set(roles)

    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role != Role.admin and user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok")
        return user

    return checker
