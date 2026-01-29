from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

DEFAULT_IMPERSONATION_JWT_AUDIENCE = "incidentfox-agent-runtime"
LEGACY_IMPERSONATION_JWT_AUDIENCE = "incidentfox-config-service"


def get_impersonation_jwt_secret() -> str:
    secret = (os.getenv("IMPERSONATION_JWT_SECRET") or "").strip()
    if not secret:
        raise RuntimeError("IMPERSONATION_JWT_SECRET is not set")
    return secret


def get_impersonation_jwt_audience() -> str:
    aud = (
        os.getenv("IMPERSONATION_JWT_AUDIENCE") or DEFAULT_IMPERSONATION_JWT_AUDIENCE
    ).strip()
    return aud or DEFAULT_IMPERSONATION_JWT_AUDIENCE


def accept_legacy_impersonation_jwt_audience() -> bool:
    return (
        os.getenv("IMPERSONATION_JWT_ACCEPT_LEGACY_AUDIENCE", "0") or "0"
    ).strip() == "1"


def get_impersonation_ttl_seconds() -> int:
    try:
        return int(os.getenv("IMPERSONATION_TOKEN_TTL_SECONDS", "900"))
    except Exception:
        return 900


def mint_team_impersonation_token(
    *,
    org_id: str,
    team_node_id: str,
    actor_subject: str,
    actor_email: Optional[str],
    ttl_seconds: Optional[int] = None,
) -> tuple[str, int, str]:
    """
    Mint a short-lived JWT that can be used as a team-scoped bearer token.

    This token is intended for server-to-server flows (e.g. orchestrator -> agent -> config_service),
    and should never be stored as a long-lived credential.
    """
    try:
        import jwt  # PyJWT
    except Exception as e:
        raise RuntimeError("Impersonation tokens require PyJWT to be installed") from e

    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else get_impersonation_ttl_seconds()
    exp = now + max(60, int(ttl))  # enforce a minimum TTL to avoid clock-skew footguns
    jti = __import__("uuid").uuid4().hex

    claims: Dict[str, Any] = {
        "iss": "incidentfox-config-service",
        # Dedicated audience to reduce cross-service token reuse.
        # This token is intended to be used by the agent runtime when calling config_service.
        "aud": get_impersonation_jwt_audience(),
        "sub": actor_subject,
        "email": actor_email,
        "org_id": org_id,
        "team_node_id": team_node_id,
        "ifx_kind": "team_impersonation",
        "scope": ["team:read"],
        "iat": now,
        "exp": exp,
        "jti": jti,
    }

    token = jwt.encode(claims, get_impersonation_jwt_secret(), algorithm="HS256")
    return str(token), exp, jti


def verify_team_impersonation_token(token: str) -> Dict[str, Any]:
    """Verify the impersonation JWT and return claims."""
    try:
        import jwt  # PyJWT
    except Exception as e:
        raise RuntimeError("Impersonation tokens require PyJWT to be installed") from e

    audiences = [get_impersonation_jwt_audience()]
    if accept_legacy_impersonation_jwt_audience():
        audiences.append(LEGACY_IMPERSONATION_JWT_AUDIENCE)

    last_err: Optional[Exception] = None
    claims = None
    for aud in audiences:
        try:
            claims = jwt.decode(
                token,
                key=get_impersonation_jwt_secret(),
                algorithms=["HS256"],
                audience=aud,
                issuer="incidentfox-config-service",
                options={
                    "require": [
                        "exp",
                        "iat",
                        "sub",
                        "org_id",
                        "team_node_id",
                        "ifx_kind",
                        "scope",
                        "jti",
                    ]
                },
            )
            break
        except Exception as e:
            last_err = e
            continue
    if claims is None:
        raise ValueError(f"Invalid impersonation token: {last_err}")

    if claims.get("ifx_kind") not in ("team_impersonation", "visitor"):
        raise ValueError("Invalid token kind")
    scope = claims.get("scope") or []
    if isinstance(scope, str):
        scope = [scope]
    if "team:read" not in set(scope or []):
        raise ValueError("Missing required scope 'team:read'")
    return dict(claims)


# =============================================================================
# Visitor Token (for public playground)
# =============================================================================


def get_visitor_token_ttl_seconds() -> int:
    """Get TTL for visitor tokens (default 30 minutes)."""
    try:
        return int(os.getenv("VISITOR_TOKEN_TTL_SECONDS", "1800"))
    except Exception:
        return 1800  # 30 minutes


def create_visitor_token(
    *,
    session_id: str,
    email: str,
    org_id: str,
    team_node_id: str,
    ttl_seconds: Optional[int] = None,
) -> str:
    """
    Create a JWT token for a visitor session.

    This token grants limited access to the playground team:
    - Can read team configuration
    - Can invoke agents
    - Cannot write configuration (routing, destinations, etc.)

    Args:
        session_id: The visitor session ID (used as subject)
        email: Visitor's email address
        org_id: Playground org ID (typically "playground")
        team_node_id: Playground team node ID (typically "visitor-playground")
        ttl_seconds: Optional custom TTL (default: 30 minutes)

    Returns:
        JWT token string
    """
    try:
        import jwt  # PyJWT
    except Exception as e:
        raise RuntimeError("Visitor tokens require PyJWT to be installed") from e

    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else get_visitor_token_ttl_seconds()
    exp = now + max(60, int(ttl))
    jti = __import__("uuid").uuid4().hex

    claims: Dict[str, Any] = {
        "iss": "incidentfox-config-service",
        "aud": get_impersonation_jwt_audience(),
        "sub": f"visitor:{session_id}",
        "email": email,
        "org_id": org_id,
        "team_node_id": team_node_id,
        "ifx_kind": "visitor",
        "visitor_session_id": session_id,
        "scope": ["team:read", "agent:invoke"],  # Limited scope - no write
        "iat": now,
        "exp": exp,
        "jti": jti,
    }

    token = jwt.encode(claims, get_impersonation_jwt_secret(), algorithm="HS256")
    return str(token)


def verify_visitor_token(token: str) -> Dict[str, Any]:
    """
    Verify a visitor JWT and return claims.

    Raises:
        ValueError: If token is invalid or expired
    """
    try:
        import jwt  # PyJWT
    except Exception as e:
        raise RuntimeError("Visitor tokens require PyJWT to be installed") from e

    audiences = [get_impersonation_jwt_audience()]
    if accept_legacy_impersonation_jwt_audience():
        audiences.append(LEGACY_IMPERSONATION_JWT_AUDIENCE)

    last_err: Optional[Exception] = None
    claims = None
    for aud in audiences:
        try:
            claims = jwt.decode(
                token,
                key=get_impersonation_jwt_secret(),
                algorithms=["HS256"],
                audience=aud,
                issuer="incidentfox-config-service",
                options={
                    "require": [
                        "exp",
                        "iat",
                        "sub",
                        "org_id",
                        "team_node_id",
                        "ifx_kind",
                        "scope",
                        "jti",
                    ]
                },
            )
            break
        except Exception as e:
            last_err = e
            continue

    if claims is None:
        raise ValueError(f"Invalid visitor token: {last_err}")

    if claims.get("ifx_kind") != "visitor":
        raise ValueError("Not a visitor token")

    return dict(claims)


def extract_visitor_session_id(token: str) -> Optional[str]:
    """
    Extract the visitor session ID from a token without full verification.

    Used for heartbeat endpoint where we need the session ID before
    full authentication.

    Returns None if not a valid visitor token format.
    """
    try:
        import jwt  # PyJWT

        # Decode without verification to get claims
        unverified = jwt.decode(token, options={"verify_signature": False})
        if unverified.get("ifx_kind") == "visitor":
            return unverified.get("visitor_session_id")
    except Exception:
        pass
    return None
