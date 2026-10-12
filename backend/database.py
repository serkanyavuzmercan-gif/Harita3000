"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncIterator

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from backend.config import ROOT_DIR, settings

# Databases created by the old create_all bootstrap match this revision.
BASE_REVISION = "0001"

# SQLite batch migrations need named constraints.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
if settings.resolved_database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.resolved_database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def _alembic_config():
    from alembic.config import Config

    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.attributes["configure_logger"] = False
    return config


def _upgrade(connection) -> None:
    from alembic import command

    config = _alembic_config()
    config.attributes["connection"] = connection
    tables = set(inspect(connection).get_table_names())
    if "regions" in tables and "alembic_version" not in tables:
        command.stamp(config, BASE_REVISION)
    command.upgrade(config, "head")


async def init_db() -> None:
    async with engine.begin() as conn:
        if settings.is_postgres:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(_upgrade)
