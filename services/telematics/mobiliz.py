"""Mobiliz connector.

Waiting for API access and documentation. When they arrive, implement list_vehicles and
fetch_positions here by mapping Mobiliz's vehicle id to ExternalVehicle.external_id and each
position report to PositionPoint (UTC time, lat/lng, km/h, heading, ignition). Nothing outside
this file needs to change.
"""

from datetime import datetime

from services.telematics.base import (
    CredentialField,
    ExternalVehicle,
    PositionPoint,
    TelematicsAdapter,
    TelematicsError,
)


class MobilizAdapter(TelematicsAdapter):
    provider = "mobiliz"
    label = "Mobiliz"
    credential_fields = (
        CredentialField("endpoint", "Servis adresi (URL)", placeholder="Mobiliz'in verdiği servis adresi"),
        CredentialField("api_token", "API anahtarı (token)", secret=True),
    )

    async def list_vehicles(self) -> list[ExternalVehicle]:
        self._not_connected()

    async def fetch_positions(self, since: datetime, until: datetime) -> list[PositionPoint]:
        self._not_connected()

    def _not_connected(self):
        self.validate()
        raise TelematicsError(
            "Mobiliz bağlayıcısı henüz tamamlanmadı: API erişimi ve dokümanı geldiğinde bağlanacak"
        )
