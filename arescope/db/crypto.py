"""PII encryption at rest (ARCHITECTURE.md §4.4 — sensitive from day one).

Notable PII (identifier values, finding artifacts) is stored Fernet-encrypted.
The key comes from ARESCOPE_ENCRYPTION_KEY. A SQLAlchemy TypeDecorator does the
transparent encrypt-on-write / decrypt-on-read so models stay clean.
"""

from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy import String, TypeDecorator

from arescope.config import get_settings


def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise RuntimeError(
            "ARESCOPE_ENCRYPTION_KEY is not set. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


class EncryptedString(TypeDecorator):
    """Transparently Fernet-encrypts a text column at rest."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _fernet().decrypt(value.encode()).decode()
