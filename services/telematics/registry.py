"""Maps provider names to connector classes."""

from backend.models import FleetIntegration, TelematicsProvider
from services.telematics.arvento import ArventoAdapter
from services.telematics.base import TelematicsAdapter, TelematicsError
from services.telematics.crypto import decrypt_credentials
from services.telematics.mobiliz import MobilizAdapter
from services.telematics.simulator import SimulatorAdapter

ADAPTERS: dict[TelematicsProvider, type[TelematicsAdapter]] = {
    TelematicsProvider.simulator: SimulatorAdapter,
    TelematicsProvider.arvento: ArventoAdapter,
    TelematicsProvider.mobiliz: MobilizAdapter,
}


def adapter_class(provider: TelematicsProvider) -> type[TelematicsAdapter]:
    try:
        return ADAPTERS[provider]
    except KeyError:
        raise TelematicsError(f"Tanımsız sağlayıcı: {provider}") from None


def adapter_for(integration: FleetIntegration) -> TelematicsAdapter:
    credentials = decrypt_credentials(integration.credentials_encrypted)
    return adapter_class(integration.provider)(credentials)


def provider_catalog() -> list[dict]:
    return [
        {
            "provider": provider.value,
            "label": cls.label,
            "fields": [
                {
                    "key": field.key,
                    "label": field.label,
                    "secret": field.secret,
                    "required": field.required,
                    "placeholder": field.placeholder,
                }
                for field in cls.credential_fields
            ],
        }
        for provider, cls in ADAPTERS.items()
    ]
