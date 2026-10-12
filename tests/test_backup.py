import io
import json
import zipfile

from openpyxl import load_workbook
from sqlalchemy import func, select

from backend.config import settings
from backend.database import SessionLocal
from backend.models import Entity, VehiclePosition
from backend.routers.entities import _rows_from_csv, _rows_from_xlsx
from tests.conftest import auth_headers


async def _counts() -> tuple[int, int]:
    async with SessionLocal() as db:
        entities = await db.scalar(select(func.count()).select_from(Entity))
        positions = await db.scalar(select(func.count()).select_from(VehiclePosition))
    return entities, positions


async def test_login_is_optional_when_auth_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_required", False)
    health = (await client.get("/api/health")).json()
    assert health["auth_required"] is False

    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["role"] == "admin"
    protected = await client.get("/api/fleet/providers")
    assert protected.status_code == 200

    stale = await client.get("/api/auth/me", headers={"Authorization": "Bearer bozuk-token"})
    assert stale.status_code == 200 and stale.json()["role"] == "admin"


async def test_login_is_enforced_when_auth_is_on(client):
    assert (await client.get("/api/health")).json()["auth_required"] is True
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_entity_export_reimports_with_same_columns(client):
    headers = await auth_headers(client, "admin")
    xlsx = await client.get("/api/entities/export?format=xlsx", headers=headers)
    assert xlsx.status_code == 200
    assert "cariler_" in xlsx.headers["content-disposition"]
    sheet = load_workbook(io.BytesIO(xlsx.content)).active
    assert [cell.value for cell in sheet[1]][:3] == ["Unvan", "Tip", "Kategori"]

    rows = _rows_from_xlsx(xlsx.content)
    saraylar = next(row for row in rows if row["name"] == "Saraylar Market")
    assert saraylar["type"] == "Müşteri"
    assert saraylar["category"] == "VIP"
    assert saraylar["region_code"] == "Merkezefendi"
    assert float(saraylar["latitude"]) == 37.776
    assert {"email", "tax_number", "current_balance", "status"} <= saraylar.keys()

    csv = await client.get("/api/entities/export?format=csv", headers=headers)
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbf")
    assert any(row["name"] == "Ege Dağıtım (Rakip)" and row["type"] == "Rakip" for row in _rows_from_csv(csv.content))


async def test_backup_round_trip_restores_data_and_files(client):
    headers = await auth_headers(client, "admin")
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    logo = settings.upload_path / "yedek_test_logo.png"
    logo.write_bytes(b"logo-bytes")
    entities_before, positions_before = await _counts()
    assert positions_before > 0

    backup = await client.get("/api/backup/export", headers=headers)
    assert backup.status_code == 200
    assert "harita3000_yedek_" in backup.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(backup.content)) as archive:
        names = archive.namelist()
        data = json.loads(archive.read("data.json"))
    assert "uploads/yedek_test_logo.png" in names
    assert data["schema_revision"] == "0002"
    assert len(data["tables"]["entities"]) == entities_before

    created = await client.post(
        "/api/entities", json={"name": "Yedekten sonra eklenen", "type": "customer", "category": "Aktif"}, headers=headers
    )
    assert created.status_code == 201
    logo.unlink()

    restored = await client.post(
        "/api/backup/import", files={"file": ("yedek.zip", backup.content, "application/zip")}, headers=headers
    )
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["counts"]["entities"] == entities_before
    assert body["warnings"] == []
    assert await _counts() == (entities_before, positions_before)
    assert logo.read_bytes() == b"logo-bytes"
    names_now = [item["name"] for item in (await client.get("/api/entities?limit=1000", headers=headers)).json()]
    assert "Yedekten sonra eklenen" not in names_now

    login_again = await client.get("/api/auth/me", headers=await auth_headers(client, "lojistik"))
    assert login_again.status_code == 200


async def test_backup_without_positions_then_full_restore(client):
    headers = await auth_headers(client, "admin")
    full = (await client.get("/api/backup/export", headers=headers)).content
    light = await client.get("/api/backup/export?positions=false", headers=headers)
    assert len(light.content) < len(full)

    restored = await client.post(
        "/api/backup/import", files={"file": ("hafif.zip", light.content, "application/zip")}, headers=headers
    )
    assert restored.status_code == 200
    assert any("konum geçmişi" in warning for warning in restored.json()["warnings"])
    assert (await _counts())[1] == 0

    again = await client.post(
        "/api/backup/import", files={"file": ("tam.zip", full, "application/zip")}, headers=headers
    )
    assert again.status_code == 200
    assert (await _counts())[1] > 0


async def test_invalid_backups_are_rejected_without_changes(client):
    headers = await auth_headers(client, "admin")
    before = await _counts()

    not_zip = await client.post(
        "/api/backup/import", files={"file": ("yedek.zip", b"bu bir zip degil", "application/zip")}, headers=headers
    )
    assert not_zip.status_code == 400

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "data.json",
            json.dumps({"format": "harita3000-backup", "version": 1, "schema_revision": "0001", "tables": {}}),
        )
        archive.writestr("uploads/../../kacak.txt", "x")
    old_schema = await client.post(
        "/api/backup/import", files={"file": ("eski.zip", buffer.getvalue(), "application/zip")}, headers=headers
    )
    assert old_schema.status_code == 400
    assert "sürüm" in old_schema.json()["detail"]
    assert await _counts() == before

    marketer = await auth_headers(client, "pazarlamaci")
    forbidden = await client.get("/api/backup/export", headers=marketer)
    assert forbidden.status_code == 403
