"""JWT generation for sandbox credential proxy.

This module handles server-side JWT generation. The credential-resolver
service has its own jwt_auth.py for validation (they're separate Docker images).

Sandboxes are untrusted - they could execute malicious code via prompt injection.
JWT ensures credential-resolver only provides credentials to legitimate sandboxes
by cryptographically binding tenant/team context to the sandbox identity.

Flow:
1. Server generates JWT with tenant_id, team_id, sandbox_name when creating sandbox
2. JWT is embedded in per-sandbox Envoy ConfigMap as a static header
3. Envoy adds x-sandbox-jwt header to all ext_authz requests
4. Credential-resolver validates JWT and extracts tenant/team (ignores spoofed headers)

Note: JWT validation is in credential-proxy/src/credential_resolver/jwt_auth.py
"""

import os
from datetime import datetime, timedelta, timezone

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
    """Generate a JWT for a sandbox.

    Args:
        tenant_id: Organization/tenant ID
        team_id: Team node ID
        sandbox_name: Kubernetes sandbox name
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
