"""
Column-level encryption for sensitive data using Fernet (symmetric encryption).

Encryption key management:
- Development: Generated key stored in .env (ENCRYPTION_KEY)
- Production: Fetched from AWS Secrets Manager or K8s secret

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

    The encryption key MUST be loaded from the ENCRYPTION_KEY environment variable.
    The deployment script (deploy-eks.sh) automatically ensures this is set.
    """

    def __init__(self):
        key_material = os.getenv("ENCRYPTION_KEY")
        if not key_material:
            raise EncryptionError(
                "ENCRYPTION_KEY must be set for column encryption. "
                "Generate one with: python scripts/generate-encryption-key.py"
            )

        # Validate key is in proper Fernet format (44 chars, base64-encoded)
        if len(key_material) != 44:
            raise EncryptionError(
                f"ENCRYPTION_KEY must be 44 characters (base64-encoded 32-byte key), "
                f"got {len(key_material)} characters. "
                f"Generate a valid key with: python scripts/generate-encryption-key.py"
            )

        try:
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
            # Prefix with "fernet:" for version identification
            return f"fernet:{encrypted_bytes.decode()}"
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt an encrypted string value.

        Args:
            ciphertext: The encrypted string (must have "fernet:" prefix)

        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ""

        try:
            # Fernet-encrypted format (strip prefix if present)
            if ciphertext.startswith("fernet:"):
                ciphertext = ciphertext[7:]

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
            if isinstance(value, str) and value.startswith("fernet:"):
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
