from datetime import datetime, time, timedelta, timezone

import pytest

from backend.config import settings
from services.telematics.base import TelematicsError
from services.telematics.crypto import decrypt_credentials, encrypt_credentials
from services.telematics.simulator import SHIFT_END, SHIFT_START, SimulatorAdapter


def _yesterday_window():
    day = datetime.now(settings.tz).date() - timedelta(days=1)
    since = datetime.combine(day, time(7, 0), settings.tz).astimezone(timezone.utc)
    until = datetime.combine(day, time(19, 0), settings.tz).astimezone(timezone.utc)
    return since, until


async def test_simulator_is_deterministic_and_unique():
    adapter = SimulatorAdapter({"use_roads": "false"})
    since, until = _yesterday_window()
    first = await adapter.fetch_positions(since, until)
    second = await adapter.fetch_positions(since, until)
    assert first and first == second

    keys = [(point.external_id, point.recorded_at) for point in first]
    assert len(keys) == len(set(keys))
    for point in first:
        local = point.recorded_at.astimezone(settings.tz).time()
        assert SHIFT_START <= local <= SHIFT_END
        assert point.recorded_at.tzinfo is not None


async def test_simulator_overlapping_windows_agree():
    adapter = SimulatorAdapter({"use_roads": "false"})
    since, until = _yesterday_window()
    middle = since + (until - since) / 2
    whole = {(p.external_id, p.recorded_at): p for p in await adapter.fetch_positions(since, until)}
    tail = await adapter.fetch_positions(middle - timedelta(minutes=5), until)
    assert tail
    for point in tail:
        assert whole[(point.external_id, point.recorded_at)] == point


async def test_simulator_never_returns_future_points():
    adapter = SimulatorAdapter({"use_roads": "false"})
    now = datetime.now(timezone.utc)
    points = await adapter.fetch_positions(now - timedelta(hours=1), now + timedelta(hours=5))
    assert all(point.recorded_at <= now for point in points)


def test_credentials_round_trip_and_ciphertext_hides_secret():
    token = encrypt_credentials({"username": "demo", "password": "çok-gizli-parola"})
    assert "çok-gizli-parola" not in token
    assert "gizli" not in token
    assert decrypt_credentials(token) == {"username": "demo", "password": "çok-gizli-parola"}


def test_tampered_credentials_raise_telematics_error():
    token = encrypt_credentials({"api_token": "abc"})
    with pytest.raises(TelematicsError):
        decrypt_credentials(token[:-4] + "AAAA")
