"""Full backup download and restore."""

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.deps import require_roles
from backend.models import FleetIntegration, User
from backend.schemas import RestoreOut
from services.backup import BackupError, export_backup, restore_backup
from services.telematics.base import TelematicsError
from services.telematics.crypto import decrypt_credentials

router = APIRouter()
admin_only = require_roles()
MAX_BACKUP_BYTES = 1024**3


@router.get("/export")
async def export(
    positions: bool = Query(default=True, description="Araç konum geçmişini dahil et"),
    _: User = Depends(admin_only),
) -> Response:
    content = await export_backup(include_positions=positions)
    stamp = datetime.now(settings.tz).strftime("%Y-%m-%d_%H%M")
    filename = f"harita3000_yedek_{stamp}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/import", response_model=RestoreOut)
async def restore(
    file: UploadFile = File(...),
    _: User = Depends(admin_only),
    db: AsyncSession = Depends(get_db),
) -> RestoreOut:
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Harita3000 yedek dosyası (.zip) seçin")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > MAX_BACKUP_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Yedek dosyası 1 GB sınırını aşıyor")
    await db.rollback()
    try:
        result = await restore_backup(file.file)
    except BackupError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    warnings: list[str] = []
    unreadable = 0
    for integration in (await db.scalars(select(FleetIntegration))).all():
        try:
            decrypt_credentials(integration.credentials_encrypted)
        except TelematicsError:
            unreadable += 1
    if unreadable:
        warnings.append(
            f"{unreadable} filo entegrasyonunun şifresi bu kurulumda açılamıyor (INTEGRATION_SECRET farklı); "
            "kimlik bilgilerini Filo sekmesinden yeniden girin"
        )
    if not result["includes_positions"]:
        warnings.append("Yedek araç konum geçmişi içermiyordu; konum geçmişi boş")
    return RestoreOut(
        counts=result["counts"],
        files=result["files"],
        backup_created_at=result["created_at"],
        warnings=warnings,
    )
