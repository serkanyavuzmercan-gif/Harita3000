"""Encryption of integration credentials at rest."""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from backend.config import settings
from services.telematics.base import TelematicsError


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.integration_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(credentials: dict[str, str]) -> str:
    if not credentials:
        return ""
    payload = json.dumps(credentials, ensure_ascii=False).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def decrypt_credentials(token: str) -> dict[str, str]:
    if not token:
        return {}
    try:
        payload = _fernet().decrypt(token.encode("ascii"))
        data = json.loads(payload.decode("utf-8"))
    except (InvalidToken, ValueError):
        raise TelematicsError(
            "Bağlantı bilgisi çözülemedi; INTEGRATION_SECRET değişmiş olabilir. Bilgileri yeniden girin."
        ) from None
    if not isinstance(data, dict):
        raise TelematicsError("Bağlantı bilgisi bozuk")
    return {str(key): str(value) for key, value in data.items()}
