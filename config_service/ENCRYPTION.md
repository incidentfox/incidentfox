# Column-Level Encryption

Config-service implements column-level encryption for sensitive data using Fernet (symmetric encryption).

## What Gets Encrypted

### Automatically Encrypted Columns

The following database columns are transparently encrypted/decrypted:

1. **`integrations.config`** (EncryptedJSONB)
   - Automatically encrypts sensitive keys: `api_key`, `bot_token`, `client_secret`, `password`, `token`, `webhook_url`
   - Other fields remain in plaintext for efficient querying
   - Example: `{"api_key": "fernet:...", "domain": "example.com"}`

2. **`sso_configs.client_secret_encrypted`** (EncryptedText)
   - OAuth/OIDC client secrets

3. **`slack_installations.bot_token`** (EncryptedText)
   - Slack bot OAuth token

4. **`slack_installations.user_token`** (EncryptedText)
   - Slack user OAuth token (if using user-level installation)

5. **`slack_installations.incoming_webhook_url`** (EncryptedText)
   - Webhook URLs contain sensitive tokens in query parameters

## Encryption Method

- **Algorithm**: Fernet (AES-128-CBC with HMAC authentication)
- **Library**: `cryptography.fernet` (Python Cryptographic Authority)
- **Key Size**: 32 bytes (256 bits), base64-encoded to 44 characters
- **Format**: `fernet:ENCRYPTED_DATA` (prefixed for version identification)

## Key Management

### Development

Generate a key and add to `.env`:

```bash
python scripts/generate-encryption-key.py
```

Add to `.env`:
```bash
ENCRYPTION_KEY=<generated-key>
```

### Production

Encryption key is stored in AWS Secrets Manager:

```bash
# View current key
aws secretsmanager get-secret-value \
  --secret-id "incidentfox/prod/config-service" \
  --region us-west-2 \
  --query 'SecretString' | jq -r '. | fromjson | .encryption_key'

# Rotate key (WARNING: requires data migration)
python scripts/generate-encryption-key.py
aws secretsmanager update-secret \
  --secret-id "incidentfox/prod/config-service" \
  --secret-string '{"token_pepper":"...","admin_token":"...","encryption_key":"NEW_KEY"}' \
  --region us-west-2
```

The key is automatically:
- Fetched by `deploy-eks.sh` during deployment
- Mounted as K8s secret `config-service-secrets.encryption-key`
- Loaded by the application as `ENCRYPTION_KEY` environment variable

## Security Considerations

### What This Protects Against

✅ **Database breaches** - Encrypted data is useless without the key
✅ **Database backups** - Backups contain encrypted data
✅ **SQL injection** - Stolen data is encrypted
✅ **Insider threats** - DBAs cannot read sensitive data without the key

### What This Does NOT Protect Against

❌ **Application-level attacks** - If attacker compromises the app, they have the key
❌ **Memory dumps** - Decrypted data exists in memory during processing
❌ **Key compromise** - If ENCRYPTION_KEY is stolen, all data can be decrypted

### Complementary Security Measures

1. **RDS Encryption at Rest** - Protects against physical disk theft
2. **Network Encryption (TLS/SSL)** - Protects data in transit
3. **IAM Permissions** - Restricts who can access Secrets Manager
4. **Audit Logging** - Tracks who accessed what data and when

## Key Rotation

⚠️ **WARNING**: Key rotation requires re-encrypting all existing data.

Process:

1. Generate new encryption key
2. Create migration script that:
   - Decrypts data with old key
   - Re-encrypts with new key
3. Update AWS Secrets Manager with new key
4. Deploy updated application

**Not yet implemented** - Coming soon if needed.

## Testing Encryption

```python
# Test encryption utilities
from src.crypto import encrypt, decrypt, encrypt_dict, decrypt_dict

# Text encryption
encrypted = encrypt("secret-api-key")
assert encrypted.startswith("fernet:")
assert decrypt(encrypted) == "secret-api-key"

# Dict encryption (auto-detects sensitive keys)
config = {"api_key": "sk-123", "domain": "example.com"}
encrypted_config = encrypt_dict(config)
assert encrypted_config["api_key"].startswith("fernet:")
assert encrypted_config["domain"] == "example.com"  # Not encrypted
decrypted_config = decrypt_dict(encrypted_config)
assert decrypted_config == config
```

## Performance Impact

- **Write operations**: ~2-5ms overhead per encrypted field
- **Read operations**: ~2-5ms overhead per encrypted field
- **Batch operations**: Negligible (parallelizable)

Encryption overhead is minimal compared to network/database latency (~10-50ms).

## Compliance

This implementation helps meet:

- **GDPR** - Data protection by design
- **SOC 2** - Data encryption requirements
- **HIPAA** - PHI encryption (if applicable)
- **PCI DSS** - Cardholder data encryption

## Troubleshooting

### "ENCRYPTION_KEY must be set"

Set the environment variable:
```bash
export ENCRYPTION_KEY=$(python scripts/generate-encryption-key.py | tail -1)
```

### "Decryption failed: invalid token"

- Key has changed since data was encrypted
- Data is corrupted
- Check if using correct environment (dev vs prod keys)

### Migration fails with encryption errors

Ensure `ENCRYPTION_KEY` is set before running migrations:
```bash
export ENCRYPTION_KEY=<your-key>
alembic upgrade head
```
