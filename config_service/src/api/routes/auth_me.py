from __future__ import annotations

import os
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import authenticate_admin_request, authenticate_team_request
from src.core.config_cache import get_config_cache
from src.core.security import get_token_pepper
from src.db.session import db_session
from src.services.config_service_rds import ConfigServiceRDS

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class AuthMeResponse(BaseModel):
    role: Literal["admin", "team"]
    auth_kind: Literal["admin_token", "team_token", "oidc", "impersonation", "visitor"]
    org_id: Optional[str] = None
    team_node_id: Optional[str] = None
    subject: Optional[str] = None
    email: Optional[str] = None
    can_write: bool = False
    permissions: List[str] = Field(default_factory=list)
    visitor_session_id: Optional[str] = None  # Set for visitor auth


def _extract_token(authorization: str, x_admin_token: str) -> str:
    """Return raw token string from Authorization Bearer or X-Admin-Token."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if x_admin_token:
        return x_admin_token.strip()
    return ""


def get_db() -> Session:
    # IMPORTANT: /auth/me is used for admin-token-only callers too.
    # In those cases we should not require DB env vars to be configured.
    has_db = bool(os.getenv("DATABASE_URL") or os.getenv("DB_HOST"))
    if not has_db:
        # type: ignore[return-value]
        yield None
        return
    with db_session() as s:
        yield s


def get_service() -> ConfigServiceRDS:
    # TOKEN_PEPPER is only required for opaque team-token auth; OIDC-only mode should not require it.
    team_mode = (os.getenv("TEAM_AUTH_MODE", "token") or "token").strip().lower()
    pepper = None
    if team_mode in ("token", "both"):
        # Avoid failing /auth/me for admin-token callers when TOKEN_PEPPER isn't configured.
        try:
            pepper = get_token_pepper()
        except Exception:
            pepper = None
    return ConfigServiceRDS(pepper=pepper, cache=get_config_cache())


def auth_me_impl(
    session: Session | None = Depends(get_db),
    svc: ConfigServiceRDS = Depends(get_service),
    authorization: str = Header(default=""),
    # Explicitly accept standard header: X-Admin-Token.
    # (We avoid relying on underscore/header-name conversion.)
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    raw = _extract_token(authorization, x_admin_token)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    dots = raw.count(".")

    # 0 dots => admin shared token (or non-JWT garbage)
    if dots == 0:
        principal = authenticate_admin_request(
            authorization=f"Bearer {raw}", x_admin_token=""
        )
        from src.core.admin_rbac import resolve_admin_permissions

        return AuthMeResponse(
            role="admin",
            auth_kind=principal.auth_kind,  # admin_token | oidc
            subject=principal.subject,
            email=principal.email,
            can_write=True,
            permissions=resolve_admin_permissions(
                auth_kind=principal.auth_kind, oidc_claims=principal.claims
            ),
        )

    # 1 dot => opaque token (could be team token or org admin token)
    if dots == 1:
        if session is None:
            raise HTTPException(status_code=503, detail="Database is not configured")

        # First, try org admin token authentication
        try:
            from src.core.security import get_token_pepper
            from src.db.repository import authenticate_org_admin_token

            pepper = get_token_pepper()
            org_admin_principal = authenticate_org_admin_token(
                session, bearer=raw, pepper=pepper, update_last_used=True
            )
            from src.core.admin_rbac import resolve_admin_permissions

            return AuthMeResponse(
                role="admin",
                auth_kind="admin_token",
                org_id=org_admin_principal.org_id,
                can_write=True,
                permissions=resolve_admin_permissions(
                    auth_kind="admin_token", oidc_claims={}
                ),
            )
        except (ValueError, Exception):
            pass  # Not an org admin token, try team token

        # Keep behavior consistent with team endpoints: respect TEAM_AUTH_MODE.
        team_mode = (os.getenv("TEAM_AUTH_MODE", "token") or "token").strip().lower()
        if team_mode not in ("token", "both"):
            raise HTTPException(status_code=401, detail="Invalid token")
        try:
            principal = svc.authenticate(session, raw)
        except RuntimeError as e:
            # e.g. TOKEN_PEPPER missing
            raise HTTPException(status_code=503, detail=str(e))
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid token")
        return AuthMeResponse(
            role="team",
            auth_kind="team_token",
            org_id=principal.org_id,
            team_node_id=principal.team_node_id,
            can_write=True,
            permissions=["team:read", "team:write"],
        )

    # 2 dots => JWT; could be admin OIDC or team OIDC (depending on claims + env modes).
    if dots == 2:
        # Prefer classifying as admin if it passes admin OIDC auth (admin group check).
        try:
            admin_principal = authenticate_admin_request(
                authorization=f"Bearer {raw}", x_admin_token=""
            )
            from src.core.admin_rbac import resolve_admin_permissions

            return AuthMeResponse(
                role="admin",
                auth_kind=admin_principal.auth_kind,
                subject=admin_principal.subject,
                email=admin_principal.email,
                can_write=True,
                permissions=resolve_admin_permissions(
                    auth_kind=admin_principal.auth_kind,
                    oidc_claims=admin_principal.claims,
                ),
            )
        except HTTPException:
            pass

        auth_kind, oidc_principal, _ = authenticate_team_request(
            authorization=f"Bearer {raw}", session=session
        )
        assert oidc_principal is not None
        if not oidc_principal.org_id or not oidc_principal.team_node_id:
            raise HTTPException(
                status_code=403, detail="OIDC token missing org/team scope"
            )

        # Handle visitor tokens (public playground users)
        if auth_kind == "visitor":
            return AuthMeResponse(
                role="team",
                auth_kind="visitor",
                org_id=oidc_principal.org_id,
                team_node_id=oidc_principal.team_node_id,
                subject=oidc_principal.subject,
                email=oidc_principal.email,
                can_write=False,  # Visitors cannot write configuration
                permissions=["team:read", "agent:invoke"],  # Limited permissions
                visitor_session_id=oidc_principal.claims.get("visitor_session_id"),
            )

        can_write = (auth_kind == "oidc") and (
            os.getenv("TEAM_OIDC_WRITE_ENABLED", "0") == "1"
        )
        perms = ["team:read"] + (["team:write"] if can_write else [])
        return AuthMeResponse(
            role="team",
            auth_kind=auth_kind,  # oidc | impersonation
            org_id=oidc_principal.org_id,
            team_node_id=oidc_principal.team_node_id,
            subject=oidc_principal.subject,
            email=oidc_principal.email,
            can_write=can_write,
            permissions=perms,
        )

    raise HTTPException(status_code=401, detail="Invalid token")


@router.get("/me", response_model=AuthMeResponse)
def auth_me(
    session: Session = Depends(get_db),
    svc: ConfigServiceRDS = Depends(get_service),
    authorization: str = Header(default=""),
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
):
    return auth_me_impl(
        session=session,
        svc=svc,
        authorization=authorization,
        x_admin_token=x_admin_token,
    )
