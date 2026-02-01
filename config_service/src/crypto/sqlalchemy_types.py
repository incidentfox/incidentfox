"""
Custom SQLAlchemy types for encrypted columns.

Usage:
    from src.crypto import EncryptedText, EncryptedJSONB

    class MyModel(Base):
        api_key: Mapped[str] = mapped_column(EncryptedText, nullable=False)
        config: Mapped[dict] = mapped_column(EncryptedJSONB, nullable=False)
"""

from typing import Any, Optional

from sqlalchemy import Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

from .encryption import decrypt, decrypt_dict, encrypt, encrypt_dict


class EncryptedText(TypeDecorator):
    """
    SQLAlchemy type for encrypted text columns.

    Transparently encrypts data before storing and decrypts when retrieving.

    Example:
        bot_token: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        """Encrypt value before storing in database."""
        if value is None:
            return None
        # Don't re-encrypt already encrypted values
        if isinstance(value, str) and value.startswith("fernet:"):
            return value
        return encrypt(value)

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        """Decrypt value when retrieving from database."""
        if value is None:
            return None
        # Handle both encrypted and plaintext (for migration compatibility)
        if isinstance(value, str) and (
            value.startswith("fernet:") or value.startswith("enc:")
        ):
            return decrypt(value)
        return value  # Return as-is if not encrypted (backwards compatibility)


class EncryptedJSONB(TypeDecorator):
    """
    SQLAlchemy type for encrypted JSONB columns.

    Recursively encrypts sensitive fields (containing: token, secret, key, password)
    in the JSON structure before storing, and decrypts when retrieving.

    Example:
        config: Mapped[dict] = mapped_column(EncryptedJSONB, nullable=False)
    """

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value: Optional[dict], dialect) -> Optional[dict]:
        """Encrypt sensitive fields before storing in database."""
        if value is None:
            return None
        return encrypt_dict(value)

    def process_result_value(self, value: Optional[dict], dialect) -> Optional[dict]:
        """Decrypt sensitive fields when retrieving from database."""
        if value is None:
            return None
        return decrypt_dict(value)
