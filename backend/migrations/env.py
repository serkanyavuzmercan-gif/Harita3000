"""Alembic environment. Uses the app's async engine settings."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from backend import models  # noqa: F401
from backend.config import settings
from backend.database import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        literal_binds=connection is None,
    )


def run_offline() -> None:
    _configure(url=settings.resolved_database_url)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(settings.resolved_database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
        await connection.commit()
    await engine.dispose()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_sync(connection)
        return
    asyncio.run(_run_async())


if context.is_offline_mode():
    run_offline()
else:
    run_online()
