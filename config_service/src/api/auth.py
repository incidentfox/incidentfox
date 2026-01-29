from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException

from src.core.metrics import ADMIN_ACTIONS_TOTAL, AUTH_FAILURES_TOTAL


def _split_bearer(authorization: str) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return authorization.split(" ", 1)[1].strip()


def _count_dots(token: str) -> int:
    return token.count(".")


@dataclass(frozen=True)
class OIDCPrincipal:
    subject: str
    email: Optional[str]
    org_id: Optional[str]
    team_node_id: Optional[str]
    claims: Dict[str, Any]


def authenticate_team_request(
    authorization: str = Header(default=""), *, session: Any = None
) -> tuple[str, Optional[OIDCPrincipal], str]:
    """Return (auth_kind, oidc_principal, raw_token_string).

    auth_kind: "team_token" | "oidc" | "impersonation" | "visitor"
    """
    mode = os.getenv("TEAM_AUTH_MODE", "token")  # token|oidc|both
    token = _split_bearer(authorization)

    dots = _count_dots(token)
    if dots == 1 and mode in ("token", "both"):
        return "team_token", None, token

    # 2 dots may be:
    # - OIDC JWT (RS256)
    # - IncidentFox-issued team impersonation JWT (HS256)
    # - IncidentFox-issued visitor JWT (HS256)
    if dots == 2:
        # Check for visitor token first
        secret = (os.getenv("IMPERSONATION_JWT_SECRET") or "").strip()
        if secret:
            try:
                from src.core.impersonation import verify_visitor_token

                claims = verify_visitor_token(token)
                principal = OIDCPrincipal(
                    subject=str(claims.get("sub", "")),
                    email=claims.get("email"),
                    org_id=str(claims.get("org_id") or ""),
                    team_node_id=str(claims.get("team_node_id") or ""),
                    claims=claims,
                )
                return "visitor", principal, token
            except ValueError:
                # Not a visitor token, continue to other methods
                pass
            except Exception:
                pass

        # Prefer impersonation if configured; it is explicitly issued by config_service.
        if secret:
            try:
                from src.core.impersonation import verify_team_impersonation_token

                claims = verify_team_impersonation_token(token)
                # Optional DB-backed allowlist: require that this token's `jti` was recorded at mint-time.
                if (
                    os.getenv("IMPERSONATION_JTI_DB_REQUIRE", "0") or "0"
                ).strip() == "1":
                    if session is None:
                        raise HTTPException(
                            status_code=503, detail="Database is not configured"
                        )
                    jti = str(claims.get("jti") or "").strip()
                    if not jti:
                        raise HTTPException(status_code=401, detail="Invalid token")
                    from src.db.repository import impersonation_jti_exists

                    if not impersonation_jti_exists(session, jti=jti):
                        raise HTTPException(status_code=401, detail="Invalid token")
                principal = OIDCPrincipal(
                    subject=str(claims.get("sub", "")),
                    email=claims.get("email"),
                    org_id=str(claims.get("org_id") or ""),
                    team_node_id=str(claims.get("team_node_id") or ""),
                    claims=claims,
                )
                return "impersonation", principal, token
            except HTTPException:
                raise
            except Exception:
                # fallthrough to OIDC if enabled
                pass

    if dots == 2 and mode in ("oidc", "both"):
        from src.core.oidc import load_oidc_config, verify_oidc_jwt

        cfg = load_oidc_config()
        if not cfg:
            AUTH_FAILURES_TOTAL.labels("oidc_disabled").inc()
            raise HTTPException(status_code=401, detail="OIDC is not configured")
        try:
            claims = verify_oidc_jwt(token, cfg=cfg)
        except Exception:
            AUTH_FAILURES_TOTAL.labels("oidc_invalid").inc()
            raise HTTPException(status_code=401, detail="Invalid token")

        sub = str(claims.get(cfg.subject_claim, ""))
        if not sub:
            AUTH_FAILURES_TOTAL.labels("oidc_missing_sub").inc()
            raise HTTPException(status_code=401, detail="Invalid token")

        org_id = claims.get(cfg.org_id_claim)
        team_node_id = claims.get(cfg.team_node_id_claim)
        principal = OIDCPrincipal(
            subject=sub,
            email=claims.get(cfg.email_claim),
            org_id=str(org_id) if org_id is not None else None,
            team_node_id=str(team_node_id) if team_node_id is not None else None,
            claims=claims,
        )
        return "oidc", principal, token

    AUTH_FAILURES_TOTAL.labels("unsupported_token").inc()
    raise HTTPException(status_code=401, detail="Invalid token")


@dataclass(frozen=True)
class AdminPrincipal:
    auth_kind: str  # "admin_token" | "org_admin_token" | "oidc"
    subject: str
    email: Optional[str]
    claims: Dict[str, Any]
    org_id: Optional[str] = None  # Set for org-scoped admins


def authenticate_admin_request(
    authorization: str = Header(default=""),
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    x_internal_service: str = Header(default="", alias="X-Internal-Service"),
) -> AdminPrincipal:
    """Authenticate an admin request.

    Checks in order:
    0. Internal service header (for agent service to record runs)
    1. Global super-admin token (ADMIN_TOKEN env var) - can access all orgs
    2. Org admin token (from RDS) - scoped to specific org
    3. OIDC JWT
    """
    mode = os.getenv("ADMIN_AUTH_MODE", "token")  # token|oidc|both

    # 0) Internal service header for agent service
    internal_secret = os.getenv("INTERNAL_SERVICE_SECRET", "")
    if x_internal_service and (
        x_internal_service == "agent"
        or (
            internal_secret
            and secrets.compare_digest(x_internal_service, internal_secret)
        )
    ):
        return AdminPrincipal(
            auth_kind="internal_service",
            subject=f"service:{x_internal_service}",
            email=None,
            claims={},
            org_id=None,
        )

    # Gather candidate token string
    raw = ""
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
    elif x_admin_token:
        raw = x_admin_token.strip()

    if not raw:
        ADMIN_ACTIONS_TOTAL.labels("auth", "denied").inc()
        raise HTTPException(status_code=401, detail="Missing admin token")

    # 1) Global super-admin token (break-glass / internal ops)
    configured = os.getenv("ADMIN_TOKEN")
    if (
        configured
        and mode in ("token", "both")
        and secrets.compare_digest(raw, configured)
    ):
        return AdminPrincipal(
            auth_kind="admin_token",
            subject="super_admin",
            email=None,
            claims={},
            org_id=None,
        )

    # 2) Org admin token from RDS (per-org admins)
    if mode in ("token", "both") and _count_dots(raw) == 1:
        pepper = os.getenv("TOKEN_PEPPER", "")
        if pepper:
            from src.db.repository import authenticate_org_admin_token
            from src.db.session import get_db

            db = next(get_db())
            try:
                principal = authenticate_org_admin_token(
                    db,
                    bearer=raw,
                    pepper=pepper,
                    update_last_used=True,
                )
                return AdminPrincipal(
                    auth_kind="org_admin_token",
                    subject=f"org_admin:{principal.org_id}",
                    email=None,
                    claims={},
                    org_id=principal.org_id,
                )
            except ValueError:
                # Not a valid org admin token, continue to other methods
                pass
            finally:
                db.close()

    # 3) OIDC JWT
    if mode in ("oidc", "both") and _count_dots(raw) == 2:
        from src.core.oidc import load_oidc_config, verify_oidc_jwt

        cfg = load_oidc_config()
        if not cfg:
            ADMIN_ACTIONS_TOTAL.labels("auth", "denied").inc()
            raise HTTPException(status_code=503, detail="OIDC is not configured")
        try:
            claims = verify_oidc_jwt(raw, cfg=cfg)
        except Exception:
            ADMIN_ACTIONS_TOTAL.labels("auth", "denied").inc()
            raise HTTPException(status_code=401, detail="Invalid admin token")

        groups = claims.get(cfg.groups_claim, [])
        if isinstance(groups, str):
            groups = [groups]
        if cfg.admin_group and cfg.admin_group not in set(groups or []):
            ADMIN_ACTIONS_TOTAL.labels("auth", "denied").inc()
            raise HTTPException(status_code=403, detail="Not an admin")

        sub = str(claims.get(cfg.subject_claim, ""))
        if not sub:
            ADMIN_ACTIONS_TOTAL.labels("auth", "denied").inc()
            raise HTTPException(status_code=401, detail="Invalid admin token")

        # OIDC admins may have org_id in claims
        org_id = claims.get("org_id")
        return AdminPrincipal(
            auth_kind="oidc",
            subject=sub,
            email=claims.get(cfg.email_claim),
            claims=claims,
            org_id=str(org_id) if org_id else None,
        )

    ADMIN_ACTIONS_TOTAL.labels("auth", "denied").inc()
    raise HTTPException(status_code=401, detail="Invalid admin token")


def require_admin(
    principal: AdminPrincipal = Depends(authenticate_admin_request),
) -> AdminPrincipal:
    """FastAPI dependency for requiring admin authentication."""
    return principal


@dataclass(frozen=True)
class TeamPrincipal:
    """Principal for team-level authentication."""

    auth_kind: str  # "team_token" | "oidc" | "impersonation" | "visitor"
    org_id: str
    team_node_id: str
    subject: Optional[str] = None
    email: Optional[str] = None
    token: Optional[str] = None
    visitor_session_id: Optional[str] = None  # Set for visitor auth

    def is_visitor(self) -> bool:
        """Check if this is a visitor (public playground user)."""
        return self.auth_kind == "visitor"

    def can_write(self) -> bool:
        """Check if this principal can write configuration."""
        # Visitors cannot write - they have read-only access
        return self.auth_kind != "visitor"


def require_team_auth(
    authorization: str = Header(default=""),
) -> TeamPrincipal:
    """
    Authenticate a team request and return a TeamPrincipal.

    This is a FastAPI dependency that validates team tokens and extracts
    org_id and team_node_id for use in team-level API routes.
    """
    from src.db.repository import Principal, authenticate_bearer_token
    from src.db.session import get_db

    mode = os.getenv("TEAM_AUTH_MODE", "token")
    token = _split_bearer(authorization)

    dots = _count_dots(token)

    # Team token format: token_id.secret
    if dots == 1 and mode in ("token", "both"):
        pepper = os.getenv("TOKEN_PEPPER", "")
        if not pepper:
            AUTH_FAILURES_TOTAL.labels("token_pepper_missing").inc()
            raise HTTPException(
                status_code=500, detail="Token authentication not configured"
            )

        db = next(get_db())
        try:
            principal: Principal = authenticate_bearer_token(
                db,
                bearer=token,
                pepper=pepper,
                update_last_used=True,
            )

            return TeamPrincipal(
                auth_kind="team_token",
                org_id=principal.org_id,
                team_node_id=principal.team_node_id,
                token=token,
            )
        except ValueError as e:
            AUTH_FAILURES_TOTAL.labels("team_token_invalid").inc()
            raise HTTPException(status_code=401, detail=str(e))
        finally:
            db.close()

    # OIDC, impersonation, or visitor JWT
    if dots == 2:
        auth_kind, principal, _ = authenticate_team_request(authorization)
        if principal:
            # Extract visitor session ID if this is a visitor token
            visitor_session_id = None
            if auth_kind == "visitor":
                visitor_session_id = principal.claims.get("visitor_session_id")

            return TeamPrincipal(
                auth_kind=auth_kind,
                org_id=principal.org_id or "",
                team_node_id=principal.team_node_id or "",
                subject=principal.subject,
                email=principal.email,
                token=token,
                visitor_session_id=visitor_session_id,
            )

    AUTH_FAILURES_TOTAL.labels("team_auth_failed").inc()
    raise HTTPException(status_code=401, detail="Invalid token")
