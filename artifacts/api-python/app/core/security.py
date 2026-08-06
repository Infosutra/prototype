"""Secret encryption using Fernet (AES-128-CBC + HMAC).

Fresh DB is expected; we do not need wire-compatibility with the old Node AES-GCM format.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class SecretError(Exception):
    pass


def _fernet() -> Fernet:
    raw = get_settings().encryption_key
    if not raw:
        raise SecretError(
            "SECRET_KEY (or KOBO_CREDENTIALS_ENCRYPTION_KEY) is not configured",
        )
    # Derive a stable 32-byte url-safe key from whatever the operator provides.
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretError(
            "Stored secret could not be decrypted (encryption key changed). "
            "Re-enter the credential in Settings and save again.",
        ) from exc
