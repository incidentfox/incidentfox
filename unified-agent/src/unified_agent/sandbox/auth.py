"""
JWT Authentication for Sandbox Credential Proxy.

This module handles JWT generation and validation for sandbox identity.
The credential-resolver service validates these JWTs to ensure only
legitimate sandboxes can request credentials for their designated tenant/team.

Security Model:
- Sandboxes are untrusted (could execute malicious code via prompt injection)
- JWT cryptographically binds tenant/team context to sandbox identity
- Credential-resolver ignores spoofed headers, only trusts JWT claims

Flow:
1. Server generates JWT with tenant_id, team_id, sandbox_name when creating sandbox
2. JWT is embedded in per-sandbox Envoy ConfigMap as a static header
3. Envoy adds x-sandbox-jwt header to all ext_authz requests
4. Credential-resolver validates JWT and extracts tenant/team context
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

# Shared secret between server and credential-resolver
# In production, load from K8s Secret (same secret in both deployments)
JWT_SECRET = os.getenv("JWT_SECRET", "incidentfox-sandbox-jwt-secret-change-in-prod")

# JWT settings (must match credential-resolver/jwt_auth.py)
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "incidentfox-server"
JWT_AUDIENCE = "credential-resolver"


def generate_sandbox_jwt(
    tenant_id: str,
    team_id: str,
    sandbox_name: str,
    thread_id: str,
    ttl_hours: int = 24,
) -> str:
    """
    Generate a JWT for a sandbox.

    Args:
        tenant_id: Organization/tenant ID (e.g., "slack-T12345")
        team_id: Team node ID for config lookup
        sandbox_name: Kubernetes sandbox name (e.g., "investigation-thread123")
        thread_id: Investigation thread ID
        ttl_hours: Token validity period (default: 24h)

    Returns:
        Signed JWT string
    """
    now = datetime.now(timezone.utc)
    payload = {
        # Standard claims
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
        # Custom claims
        "tenant_id": tenant_id,
        "team_id": team_id,
        "sandbox_name": sandbox_name,
        "thread_id": thread_id,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_sandbox_jwt(token: str) -> Optional[dict]:
    """
    Verify and decode a sandbox JWT.

    Args:
        token: JWT string to verify

    Returns:
        Decoded payload dict if valid, None if invalid/expired
    """
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_jwt_claims(token: str) -> Optional[dict]:
    """
    Extract claims from JWT without verification (for debugging).

    Args:
        token: JWT string

    Returns:
        Decoded payload (unverified) or None if malformed
    """
    try:
        # Decode without verification to inspect claims
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None
