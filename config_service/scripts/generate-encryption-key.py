#!/usr/bin/env python3
"""
Generate a Fernet encryption key for column-level encryption.

Usage:
    python scripts/generate-encryption-key.py

This generates a base64-encoded 32-byte key suitable for the ENCRYPTION_KEY environment variable.
"""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    key = Fernet.generate_key().decode()
    print("Generated encryption key (keep this secret!):")
    print()
    print(key)
    print()
    print("Add this to your .env file:")
    print(f"ENCRYPTION_KEY={key}")
    print()
    print("Or add to AWS Secrets Manager:")
    print(
        f'aws secretsmanager create-secret --name incidentfox/prod/config-service --secret-string \'{{"encryption_key":"{key}"}}\''
    )
