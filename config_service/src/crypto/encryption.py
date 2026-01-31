"""
Column-level encryption for sensitive data using Fernet (symmetric encryption).

Encryption key management:
- Development: Generated key stored in .env (ENCRYPTION_KEY)
- Production: Fetched from AWS Secrets Manager or K8s secret (TOKEN_PEPPER can be reused)

Security notes:
- Fernet uses AES-128 in CBC mode with HMAC for authentication
- Keys are base64-encoded 32-byte values
- Each encryption includes a timestamp for key rotation support
"""

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""

    pass


class EncryptionService:
    """
    Handles encryption and decryption of sensitive data using Fernet.

    The encryption key is loaded from the ENCRYPTION_KEY environment variable.
    If not set, falls back to TOKEN_PEPPER for backwards compatibility.
    """

    def __init__(self):
        # Try ENCRYPTION_KEY first, fallback to TOKEN_PEPPER
        key_material = os.getenv("ENCRYPTION_KEY") or os.getenv("TOKEN_PEPPER")
        if not key_material:
            raise EncryptionError(
                "ENCRYPTION_KEY or TOKEN_PEPPER must be set for column encryption"
            )

        # Ensure key is valid Fernet format (32 bytes, base64-encoded)
        try:
            # If key_material is not base64, derive a key from it
            if len(key_material) != 44:  # Fernet keys are 44 chars when base64-encoded
                # Derive a Fernet key from the pepper using SHA256
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=b"incidentfox-config-service",  # Static salt for deterministic key
                    iterations=100000,
                )
                derived_key = base64.urlsafe_b64encode(
                    kdf.derive(key_material.encode())
                )
                self.fernet = Fernet(derived_key)
            else:
                # Assume it's already a valid Fernet key
                self.fernet = Fernet(key_material.encode())
        except Exception as e:
            raise EncryptionError(f"Failed to initialize encryption: {e}")

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string value.

        Args:
            plaintext: The string to encrypt

        Returns:
            Base64-encoded encrypted value with format: "fernet:ENCRYPTED_DATA"
        """
        if not plaintext:
            return ""

        try:
            encrypted_bytes = self.fernet.encrypt(plaintext.encode())
            # Prefix with "fernet:" to distinguish from old base64-encoded values
            return f"fernet:{encrypted_bytes.decode()}"
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt an encrypted string value.

        Args:
            ciphertext: The encrypted string (with or without "fernet:" prefix)

        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ""

        try:
            # Handle old base64-encoded values (backwards compatibility)
            if ciphertext.startswith("enc:"):
                # Old format from base64 encoding - decode directly
                import base64

                return base64.b64decode(ciphertext[4:]).decode()

            # New Fernet-encrypted format
            if ciphertext.startswith("fernet:"):
                ciphertext = ciphertext[7:]  # Strip prefix

            decrypted_bytes = self.fernet.decrypt(ciphertext.encode())
            return decrypted_bytes.decode()
        except InvalidToken:
            raise EncryptionError("Decryption failed: invalid token or corrupted data")
        except Exception as e:
            raise EncryptionError(f"Decryption failed: {e}")

    def encrypt_dict(self, data: dict) -> dict:
        """
        Recursively encrypt sensitive values in a dictionary.

        Encrypts values for keys containing: token, secret, key, password, webhook_url

        Args:
            data: Dictionary that may contain sensitive values

        Returns:
            New dictionary with encrypted sensitive values
        """
        if not isinstance(data, dict):
            return data

        encrypted = {}
        sensitive_keys = {
            "token",
            "secret",
            "key",
            "password",
            "webhook_url",
            "api_key",
            "bot_token",
            "client_secret",
        }

        for key, value in data.items():
            # Check if key contains sensitive terms
            is_sensitive = any(term in key.lower() for term in sensitive_keys)

            if is_sensitive and isinstance(value, str) and value:
                # Don't re-encrypt already encrypted values
                if not value.startswith("fernet:"):
                    encrypted[key] = self.encrypt(value)
                else:
                    encrypted[key] = value
            elif isinstance(value, dict):
                encrypted[key] = self.encrypt_dict(value)
            else:
                encrypted[key] = value

        return encrypted

    def decrypt_dict(self, data: dict) -> dict:
        """
        Recursively decrypt encrypted values in a dictionary.

        Args:
            data: Dictionary that may contain encrypted values

        Returns:
            New dictionary with decrypted values
        """
        if not isinstance(data, dict):
            return data

        decrypted = {}

        for key, value in data.items():
            if isinstance(value, str) and (
                value.startswith("fernet:") or value.startswith("enc:")
            ):
                try:
                    decrypted[key] = self.decrypt(value)
                except EncryptionError:
                    # If decryption fails, keep the original value
                    decrypted[key] = value
            elif isinstance(value, dict):
                decrypted[key] = self.decrypt_dict(value)
            else:
                decrypted[key] = value

        return decrypted

    @classmethod
    def generate_key(cls) -> str:
        """
        Generate a new Fernet encryption key.

        Returns:
            Base64-encoded 32-byte key suitable for ENCRYPTION_KEY env var
        """
        return Fernet.generate_key().decode()


# Singleton instance
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """Get or create the global encryption service instance."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service


# Convenience functions
def encrypt(plaintext: str) -> str:
    """Encrypt a string value."""
    return get_encryption_service().encrypt(plaintext)


def decrypt(ciphertext: str) -> str:
    """Decrypt an encrypted string value."""
    return get_encryption_service().decrypt(ciphertext)


def encrypt_dict(data: dict) -> dict:
    """Encrypt sensitive values in a dictionary."""
    return get_encryption_service().encrypt_dict(data)


def decrypt_dict(data: dict) -> dict:
    """Decrypt encrypted values in a dictionary."""
    return get_encryption_service().decrypt_dict(data)
