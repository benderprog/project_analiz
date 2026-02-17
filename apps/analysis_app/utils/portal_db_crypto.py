import base64
import hashlib
import os

from django.conf import settings


def _derive_key() -> bytes:
    key_from_env = os.getenv("PORTAL_DB_FERNET_KEY", "").strip()
    if key_from_env:
        return key_from_env.encode("utf-8")
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("cryptography package is required for portal DB password encryption") from exc
    return Fernet(_derive_key())


def encrypt_password(plain: str) -> str:
    if not plain:
        return ""
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_password(token: str) -> str:
    if not token:
        return ""
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
