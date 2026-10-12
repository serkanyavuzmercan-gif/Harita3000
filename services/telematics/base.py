"""Connector contract every fleet tracking provider implements."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar


class TelematicsError(Exception):
    pass


@dataclass(frozen=True)
class CredentialField:
    key: str
    label: str
    secret: bool = False
    required: bool = True
    placeholder: str = ""


@dataclass(frozen=True)
class ExternalVehicle:
    external_id: str
    label: str
    plate: str | None = None


@dataclass(frozen=True)
class PositionPoint:
    external_id: str
    recorded_at: datetime
    latitude: float
    longitude: float
    speed_kmh: float = 0.0
    heading: float | None = None
    ignition_on: bool | None = None


class TelematicsAdapter(ABC):
    provider: ClassVar[str]
    label: ClassVar[str]
    credential_fields: ClassVar[tuple[CredentialField, ...]] = ()

    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        self.credentials = {key: str(value) for key, value in (credentials or {}).items()}

    def validate(self) -> None:
        missing = [
            field.label
            for field in self.credential_fields
            if field.required and not self.credentials.get(field.key, "").strip()
        ]
        if missing:
            raise TelematicsError("Eksik bağlantı bilgisi: " + ", ".join(missing))

    async def test_connection(self) -> int:
        self.validate()
        return len(await self.list_vehicles())

    @abstractmethod
    async def list_vehicles(self) -> list[ExternalVehicle]:
        """Vehicles visible to this account, keyed by the provider's own id."""

    @abstractmethod
    async def fetch_positions(self, since: datetime, until: datetime) -> list[PositionPoint]:
        """Position reports with since < recorded_at <= until, timezone-aware UTC."""
