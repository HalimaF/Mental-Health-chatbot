"""Field-level encryption for sensitive columns.

Everything a user discloses to this app -- what they typed, what the assistant
said back, the crisis assessment attached to it -- is encrypted before it
reaches the database. A stolen dump or a leaked backup yields ciphertext, not
somebody's disclosures about wanting to die.

The key lives in ``ENCRYPTION_KEY`` and never in source control. Losing it
means losing the plaintext forever; there is intentionally no recovery path.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text, TypeDecorator

logger = logging.getLogger(__name__)

# Marks a value as produced by this module, so we can distinguish real
# ciphertext from plaintext written by an older schema version and migrate
# it lazily instead of raising.
_PREFIX = "enc:v1:"


class EncryptionNotConfigured(RuntimeError):
    pass


class Encryptor:
    """Wraps Fernet (AES-128-CBC + HMAC-SHA256) with a stable envelope."""

    def __init__(self, key: str | bytes | None):
        self._fernet: Fernet | None = None
        if key:
            self._fernet = Fernet(self._coerce_key(key))

    @staticmethod
    def _coerce_key(key: str | bytes) -> bytes:
        """Accept either a real Fernet key or arbitrary secret material.

        A proper 32-byte urlsafe-base64 key is used as-is. Anything else is
        stretched through SHA-256 so that a developer who pastes a random
        string into ENCRYPTION_KEY still gets a valid, deterministic key
        rather than a stack trace on boot.
        """
        raw = key.encode() if isinstance(key, str) else key
        try:
            if len(base64.urlsafe_b64decode(raw)) == 32:
                return raw
        except (ValueError, TypeError, base64.binascii.Error):  # type: ignore[attr-defined]
            pass
        digest = hashlib.sha256(raw).digest()
        return base64.urlsafe_b64encode(digest)

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if self._fernet is None:
            raise EncryptionNotConfigured(
                "ENCRYPTION_KEY is not set; refusing to store sensitive data in plaintext."
            )
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return _PREFIX + token

    def decrypt(self, stored: str) -> str:
        if not stored.startswith(_PREFIX):
            # Written before encryption was introduced. Return it as-is so old
            # rows stay readable; they get re-encrypted next time they're written.
            return stored
        if self._fernet is None:
            raise EncryptionNotConfigured(
                "ENCRYPTION_KEY is not set; cannot decrypt stored data."
            )
        token = stored[len(_PREFIX) :].encode("ascii")
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken:
            # Wrong or rotated key. Never crash a page render over one bad row.
            logger.error("Failed to decrypt a stored value: key mismatch or corruption.")
            return "[unable to decrypt this message]"


# Bound during create_app(); module-level so the SQLAlchemy type can reach it.
_encryptor = Encryptor(None)


def init_encryption(key: str | bytes | None) -> Encryptor:
    global _encryptor
    _encryptor = Encryptor(key)
    return _encryptor


def get_encryptor() -> Encryptor:
    return _encryptor


class EncryptedText(TypeDecorator):
    """A Text column that is transparently encrypted on the way in and
    decrypted on the way out. Models use it exactly like a normal string."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _encryptor.encrypt(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _encryptor.decrypt(value)
