"""Whole-database backup and restore as a single ZIP (data.json plus uploaded and archived files)."""

import enum
import io
import json
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import IO, Any

from sqlalchemy import Date, DateTime, Table, func, select, text
from sqlalchemy.engine import Connection

from backend.config import settings
from backend.database import Base, engine
from backend.models import UTCDateTime

FORMAT = "harita3000-backup"
FORMAT_VERSION = 1
DATA_FILE = "data.json"
POSITIONS_TABLE = "vehicle_positions"
INSERT_CHUNK = 1000
MAX_UNCOMPRESSED_BYTES = 2 * 1024**3


class BackupError(Exception):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _column_parser(column):
    if isinstance(column.type, UTCDateTime):
        return _utc_datetime
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat
    if isinstance(column.type, Date):
        return date.fromisoformat
    return None


def _schema_revision(conn: Connection) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _dump_tables(conn: Connection, include_positions: bool) -> dict:
    tables: dict[str, list[dict]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name == POSITIONS_TABLE and not include_positions:
            continue
        query = select(table)
        if "id" in table.c:
            query = query.order_by(table.c.id)
        tables[table.name] = [
            {key: _json_value(value) for key, value in row._mapping.items()} for row in conn.execute(query)
        ]
    return {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "schema_revision": _schema_revision(conn),
        "created_at": datetime.now(settings.tz).isoformat(timespec="seconds"),
        "includes_positions": include_positions,
        "tables": tables,
    }


def _add_folder(archive: zipfile.ZipFile, folder: Path, prefix: str) -> int:
    if not folder.is_dir():
        return 0
    count = 0
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.name != ".gitkeep":
            archive.write(path, f"{prefix}/{path.relative_to(folder).as_posix()}")
            count += 1
    return count


async def export_backup(include_positions: bool = True) -> bytes:
    async with engine.connect() as conn:
        data = await conn.run_sync(_dump_tables, include_positions)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(DATA_FILE, json.dumps(data, ensure_ascii=False))
        _add_folder(archive, settings.upload_path, "uploads")
        _add_folder(archive, settings.report_path, "reports")
    return buffer.getvalue()


def _safe_target(base: Path, relative: str) -> Path | None:
    parts = PurePosixPath(relative).parts
    if not parts or any(part in ("..", "") for part in parts) or PurePosixPath(relative).is_absolute():
        return None
    target = (base / Path(*parts)).resolve()
    return target if target.is_relative_to(base.resolve()) else None


def _read_archive(source: IO[bytes]) -> tuple[zipfile.ZipFile, dict]:
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile:
        raise BackupError("Dosya geçerli bir Harita3000 yedeği (ZIP) değil") from None
    if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
        raise BackupError("Yedek dosyası çok büyük")
    try:
        data = json.loads(archive.read(DATA_FILE).decode("utf-8"))
    except KeyError:
        raise BackupError("Yedekte data.json bulunamadı") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BackupError("Yedekteki veri dosyası okunamadı") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("Dosya bir Harita3000 yedeği değil")
    if data.get("version") != FORMAT_VERSION:
        raise BackupError("Bu yedek biçim sürümü desteklenmiyor")
    if not isinstance(data.get("tables"), dict):
        raise BackupError("Yedekte tablo verisi yok")
    return archive, data


def _prepare_rows(table: Table, rows: list) -> list[dict]:
    parsers = {column.name: _column_parser(column) for column in table.columns}
    prepared = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise BackupError(f"{table.name} tablosunda {index}. kayıt bozuk")
        clean = {}
        for key, value in row.items():
            if key not in parsers:
                continue
            parser = parsers[key]
            if parser is not None and isinstance(value, str):
                try:
                    value = parser(value)
                except ValueError:
                    raise BackupError(f"{table.name}.{key} alanında geçersiz tarih: {value}") from None
            clean[key] = value
        prepared.append(clean)
    return prepared


def _replace_tables(conn: Connection, data: dict) -> dict[str, int]:
    current = _schema_revision(conn)
    if data.get("schema_revision") != current:
        raise BackupError(
            f"Yedek farklı bir veritabanı sürümünden ({data.get('schema_revision')}); bu kurulum {current} sürümünde"
        )
    payload = data["tables"]
    prepared = {table.name: _prepare_rows(table, payload.get(table.name) or []) for table in Base.metadata.sorted_tables}
    for table in reversed(Base.metadata.sorted_tables):
        conn.execute(table.delete())
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        rows = prepared[table.name]
        for start in range(0, len(rows), INSERT_CHUNK):
            conn.execute(table.insert(), rows[start : start + INSERT_CHUNK])
        counts[table.name] = len(rows)
        if settings.is_postgres and "id" in table.c and rows:
            top = conn.execute(select(func.max(table.c.id))).scalar_one()
            conn.execute(
                text("SELECT setval(pg_get_serial_sequence(:name, 'id'), :value)"),
                {"name": table.name, "value": top},
            )
    return counts


def _restore_files(archive: zipfile.ZipFile) -> int:
    roots = {"uploads": settings.upload_path, "reports": settings.report_path}
    written = 0
    for info in archive.infolist():
        if info.is_dir() or info.filename == DATA_FILE:
            continue
        prefix, _, relative = info.filename.partition("/")
        base = roots.get(prefix)
        target = _safe_target(base, relative) if base else None
        if target is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(info))
        written += 1
    return written


async def restore_backup(source: IO[bytes]) -> dict:
    archive, data = _read_archive(source)
    with archive:
        async with engine.begin() as conn:
            counts = await conn.run_sync(_replace_tables, data)
        files = _restore_files(archive)
    return {
        "counts": counts,
        "files": files,
        "created_at": data.get("created_at"),
        "includes_positions": bool(data.get("includes_positions", True)),
    }
