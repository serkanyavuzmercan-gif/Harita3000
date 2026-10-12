import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="harita3000-test-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(TMP / 'test.db').as_posix()}"
os.environ["REPORT_DIR"] = str(TMP / "reports")
os.environ["UPLOAD_DIR"] = str(TMP / "uploads")
os.environ["TELEMATICS_POLLER_ENABLED"] = "false"
os.environ["AUTH_REQUIRED"] = "true"
os.environ["INTEGRATION_SECRET"] = "test-integration-secret"
os.environ["JWT_SECRET"] = "test-jwt-secret-that-is-long-enough-for-hs256"

from httpx import ASGITransport, AsyncClient  # noqa: E402

import services.static_map as static_map  # noqa: E402
import services.telematics.simulator as simulator  # noqa: E402
from backend.main import app  # noqa: E402
from backend.seed import seed  # noqa: E402
from services.routing import RoutingError  # noqa: E402


async def _no_tile(*_args, **_kwargs):
    return None


async def _no_roads(*_args, **_kwargs):
    raise RoutingError("offline test")


@pytest.fixture(scope="session", autouse=True)
def offline_seeded_db():
    patcher = pytest.MonkeyPatch()
    patcher.setattr(static_map, "_fetch_tile", _no_tile)
    patcher.setattr(simulator, "fetch_road_route", _no_roads)
    simulator.SimulatorAdapter._geometry_cache.clear()
    asyncio.run(seed())
    yield
    patcher.undo()
    shutil.rmtree(TMP, ignore_errors=True)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def auth_headers(client: AsyncClient, username: str) -> dict[str, str]:
    response = await client.post("/api/auth/login", json={"username": username, "password": "admin123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
