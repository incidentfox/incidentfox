"""Tests for column-level encryption."""

import os

import pytest


@pytest.fixture(autouse=True)
def set_encryption_key():
    """Set encryption key for tests."""
    # Use a test-specific key
    os.environ["ENCRYPTION_KEY"] = (
        "test-key-for-encryption-must-be-at-least-32-bytes-long-for-fernet"
    )
    yield
    os.environ.pop("ENCRYPTION_KEY", None)


def test_encrypt_decrypt_text():
    """Test basic text encryption and decryption."""
    from src.crypto import decrypt, encrypt

    plaintext = "super-secret-api-key"
    encrypted = encrypt(plaintext)

    # Verify format
    assert encrypted.startswith("fernet:")
    assert encrypted != plaintext
    assert len(encrypted) > len(plaintext)

    # Verify decryption
    decrypted = decrypt(encrypted)
    assert decrypted == plaintext


def test_encrypt_empty_string():
    """Test encryption of empty strings."""
    from src.crypto import decrypt, encrypt

    assert encrypt("") == ""
    assert decrypt("") == ""


def test_decrypt_backwards_compat():
    """Test backwards compatibility with old base64 format."""
    # Old format: enc:BASE64
    import base64

    from src.crypto import decrypt

    old_encrypted = "enc:" + base64.b64encode(b"secret").decode()
    assert decrypt(old_encrypted) == "secret"


def test_encrypt_dict_sensitive_keys():
    """Test dictionary encryption of sensitive keys."""
    from src.crypto import decrypt_dict, encrypt_dict

    config = {
        "api_key": "sk-123456",
        "bot_token": "xoxb-123456",
        "client_secret": "secret123",
        "password": "pass123",
        "webhook_url": "https://hooks.slack.com/services/T00/B00/secret",
        "domain": "example.com",  # Should NOT be encrypted
        "port": 443,  # Should NOT be encrypted
    }

    encrypted = encrypt_dict(config)

    # Verify sensitive keys are encrypted
    assert encrypted["api_key"].startswith("fernet:")
    assert encrypted["bot_token"].startswith("fernet:")
    assert encrypted["client_secret"].startswith("fernet:")
    assert encrypted["password"].startswith("fernet:")
    assert encrypted["webhook_url"].startswith("fernet:")

    # Verify non-sensitive keys are NOT encrypted
    assert encrypted["domain"] == "example.com"
    assert encrypted["port"] == 443

    # Verify decryption restores original
    decrypted = decrypt_dict(encrypted)
    assert decrypted == config


def test_encrypt_dict_nested():
    """Test encryption of nested dictionaries."""
    from src.crypto import decrypt_dict, encrypt_dict

    config = {
        "oauth": {"client_secret": "secret123", "client_id": "client-id"},
        "api": {"api_key": "key123", "endpoint": "https://api.example.com"},
    }

    encrypted = encrypt_dict(config)

    # Verify nested encryption
    assert encrypted["oauth"]["client_secret"].startswith("fernet:")
    assert encrypted["oauth"]["client_id"] == "client-id"
    assert encrypted["api"]["api_key"].startswith("fernet:")
    assert encrypted["api"]["endpoint"] == "https://api.example.com"

    # Verify decryption
    decrypted = decrypt_dict(encrypted)
    assert decrypted == config


def test_encrypt_dict_already_encrypted():
    """Test that already encrypted values are not re-encrypted."""
    from src.crypto import encrypt, encrypt_dict

    already_encrypted = encrypt("secret")
    config = {"api_key": already_encrypted}

    encrypted = encrypt_dict(config)

    # Should not be double-encrypted
    assert encrypted["api_key"] == already_encrypted


def test_sqlalchemy_encrypted_text():
    """Test EncryptedText SQLAlchemy type."""
    from src.crypto.sqlalchemy_types import EncryptedText

    type_obj = EncryptedText()

    # Test encryption (bind)
    plaintext = "secret-token"
    encrypted = type_obj.process_bind_param(plaintext, None)
    assert encrypted.startswith("fernet:")

    # Test decryption (result)
    decrypted = type_obj.process_result_value(encrypted, None)
    assert decrypted == plaintext

    # Test None handling
    assert type_obj.process_bind_param(None, None) is None
    assert type_obj.process_result_value(None, None) is None

    # Test backwards compat (plaintext)
    assert type_obj.process_result_value("plaintext", None) == "plaintext"


def test_sqlalchemy_encrypted_jsonb():
    """Test EncryptedJSONB SQLAlchemy type."""
    from src.crypto.sqlalchemy_types import EncryptedJSONB

    type_obj = EncryptedJSONB()

    # Test encryption (bind)
    config = {"api_key": "secret", "domain": "example.com"}
    encrypted = type_obj.process_bind_param(config, None)
    assert encrypted["api_key"].startswith("fernet:")
    assert encrypted["domain"] == "example.com"

    # Test decryption (result)
    decrypted = type_obj.process_result_value(encrypted, None)
    assert decrypted == config

    # Test None handling
    assert type_obj.process_bind_param(None, None) is None
    assert type_obj.process_result_value(None, None) is None


def test_encryption_error_handling():
    """Test encryption error handling."""
    from src.crypto import EncryptionError, decrypt

    # Invalid encrypted data should raise EncryptionError
    with pytest.raises(EncryptionError):
        decrypt("fernet:invalid-data-here")


def test_encryption_service_initialization_error():
    """Test EncryptionService initialization without key."""
    os.environ.pop("ENCRYPTION_KEY", None)
    os.environ.pop("TOKEN_PEPPER", None)

    from src.crypto import EncryptionError, EncryptionService

    with pytest.raises(EncryptionError, match="ENCRYPTION_KEY or TOKEN_PEPPER"):
        EncryptionService()


def test_generate_key():
    """Test key generation."""
    from src.crypto import EncryptionService

    key = EncryptionService.generate_key()

    # Should be valid base64-encoded 32-byte key (44 chars)
    assert len(key) == 44
    assert key.endswith("=")  # Base64 padding
