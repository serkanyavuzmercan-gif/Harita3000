"""Arvento connector.

Waiting for API access and documentation. When they arrive, implement list_vehicles and
fetch_positions here by mapping Arvento's vehicle id to ExternalVehicle.external_id and each
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


class ArventoAdapter(TelematicsAdapter):
    provider = "arvento"
    label = "Arvento"
    credential_fields = (
        CredentialField("endpoint", "Servis adresi (URL)", placeholder="Arvento'nun verdiği servis adresi"),
        CredentialField("username", "Kullanıcı adı"),
        CredentialField("password", "Parola", secret=True),
        CredentialField("customer_code", "Müşteri kodu / PIN", secret=True, required=False),
    )

    async def list_vehicles(self) -> list[ExternalVehicle]:
        self._not_connected()

    async def fetch_positions(self, since: datetime, until: datetime) -> list[PositionPoint]:
        self._not_connected()

    def _not_connected(self):
        self.validate()
        raise TelematicsError(
            "Arvento bağlayıcısı henüz tamamlanmadı: API erişimi ve dokümanı geldiğinde bağlanacak"
        )
