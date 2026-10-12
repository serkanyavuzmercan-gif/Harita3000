"""Background loop: polls due fleet integrations, archives daily reports, purges old positions."""

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import select

from backend.config import settings
from backend.database import SessionLocal
from backend.models import FleetIntegration, utcnow
from services.reports.service import archive_day, purge_old_positions
from services.telematics.base import TelematicsError
from services.telematics.sync import is_due, sync_integration

logger = logging.getLogger("harita3000.scheduler")


async def poll_due_integrations(now: datetime | None = None) -> int:
    now = now or utcnow()
    async with SessionLocal() as db:
        integrations = (await db.scalars(select(FleetIntegration).where(FleetIntegration.is_active.is_(True)))).all()
        due_ids = [integration.id for integration in integrations if is_due(integration, now)]
    synced = 0
    for integration_id in due_ids:
        async with SessionLocal() as db:
            integration = await db.get(FleetIntegration, integration_id)
            if integration is None:
                continue
            try:
                result = await sync_integration(db, integration, now)
                synced += 1
                logger.info("%s: %d yeni konum", integration.name, result.inserted)
            except TelematicsError as exc:
                logger.warning("Entegrasyon %s senkronize edilemedi: %s", integration_id, exc)
    return synced


async def run_daily_jobs(last_run: date | None) -> date | None:
    local_now = datetime.now(settings.tz)
    today = local_now.date()
    if last_run == today:
        return last_run
    if (local_now.hour, local_now.minute) < (settings.daily_report_hour, settings.daily_report_minute):
        return last_run
    async with SessionLocal() as db:
        written = await archive_day(db, today)
        purged = await purge_old_positions(db, settings.position_retention_days)
    logger.info("Gün sonu: %d rapor arşivlendi, %d eski konum silindi", written, purged)
    return today


async def run_scheduler(stop: asyncio.Event) -> None:
    last_daily: date | None = None
    logger.info("Zamanlayıcı başladı (%ss aralık)", settings.scheduler_tick_seconds)
    while not stop.is_set():
        try:
            await poll_due_integrations()
        except Exception:
            logger.exception("Entegrasyon taraması başarısız")
        try:
            last_daily = await run_daily_jobs(last_daily)
        except Exception:
            logger.exception("Gün sonu işleri başarısız")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.scheduler_tick_seconds)
        except TimeoutError:
            pass
