"""SSO Authentication endpoints for OAuth/OIDC login."""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.models import SSOConfig, TeamToken
from ...db.session import get_db

router = APIRouter(prefix="/api/v1/auth/sso", tags=["sso"])


class TokenExchangeRequest(BaseModel):
    org_id: str
    code: str
    redirect_uri: str


class TokenExchangeResponse(BaseModel):
    session_token: str
    email: str
    name: Optional[str] = None
    role: str  # admin or team
    org_id: str


def _decrypt_secret(encrypted: str) -> str:
    """Decrypt a client secret."""
    if encrypted.startswith("enc:"):
        return base64.b64decode(encrypted[4:]).decode()
    return encrypted


def _generate_token_id() -> str:
    """Generate a unique token ID."""
    return f"sso_{secrets.token_urlsafe(8)}"


def _generate_token_secret() -> str:
    """Generate a secure token secret."""
    return secrets.token_urlsafe(32)


def _hash_secret(secret: str) -> str:
    """Hash a token secret for storage."""
    return hashlib.sha256(secret.encode()).hexdigest()


@router.post("/exchange", response_model=TokenExchangeResponse)
async def exchange_auth_code(
    body: TokenExchangeRequest,
    db: Session = Depends(get_db),
):
    """
    Exchange an OAuth authorization code for a session token.

    This endpoint:
    1. Gets the org's SSO config
    2. Exchanges the code for OAuth tokens
    3. Validates the ID token / fetches user info
    4. Creates or updates a token for the user
    5. Returns a session token
    """
    # Get SSO config
    config = (
        db.query(SSOConfig)
        .filter(SSOConfig.org_id == body.org_id, SSOConfig.enabled == True)
        .first()
    )

    if not config:
        raise HTTPException(
            status_code=400, detail="SSO not configured for this organization"
        )

    if not config.client_id or not config.client_secret_encrypted:
        raise HTTPException(status_code=400, detail="SSO configuration incomplete")

    client_secret = _decrypt_secret(config.client_secret_encrypted)

    # Build token endpoint URL
    if config.provider_type == "google":
        token_url = "https://oauth2.googleapis.com/token"
        userinfo_url = "https://openidconnect.googleapis.com/v1/userinfo"
    elif config.provider_type == "azure":
        tenant = config.tenant_id or "common"
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        userinfo_url = "https://graph.microsoft.com/oidc/userinfo"
    else:
        issuer = config.issuer.rstrip("/") if config.issuer else ""
        token_url = f"{issuer}/token"
        userinfo_url = f"{issuer}/userinfo"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Exchange code for tokens
            token_resp = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": body.code,
                    "redirect_uri": body.redirect_uri,
                    "client_id": config.client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if token_resp.status_code != 200:
                error_detail = token_resp.text
                raise HTTPException(
                    status_code=400, detail=f"Token exchange failed: {error_detail}"
                )

            tokens = token_resp.json()
            access_token = tokens.get("access_token")
            tokens.get("id_token")

            if not access_token:
                raise HTTPException(status_code=400, detail="No access token received")

            # Get user info
            userinfo_resp = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if userinfo_resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to get user info: {userinfo_resp.text}",
                )

            userinfo = userinfo_resp.json()

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"OAuth request failed: {str(e)}")

    # Extract user details
    email_claim = config.email_claim or "email"
    name_claim = config.name_claim or "name"
    groups_claim = config.groups_claim or "groups"

    email = userinfo.get(email_claim)
    name = userinfo.get(name_claim)
    groups = userinfo.get(groups_claim, [])

    if not email:
        raise HTTPException(status_code=400, detail="No email in user info")

    # Check allowed domains
    if config.allowed_domains:
        allowed = [d.strip().lower() for d in config.allowed_domains.split(",")]
        email_domain = email.split("@")[-1].lower()
        if email_domain not in allowed:
            raise HTTPException(
                status_code=403, detail=f"Email domain '{email_domain}' not allowed"
            )

    # Determine role
    role = "team"  # default
    if config.admin_group:
        if isinstance(groups, list) and config.admin_group in groups:
            role = "admin"

    # Create or find session token for this user
    # Look for existing SSO token for this email
    existing_token = (
        db.query(TeamToken)
        .filter(
            TeamToken.org_id == body.org_id,
            TeamToken.label == f"sso:{email}",
            TeamToken.revoked_at.is_(None),
        )
        .first()
    )

    token_secret = _generate_token_secret()

    # For SSO tokens, we use a special team_node_id
    sso_team_node = "sso-users"  # Could be configurable per org

    if existing_token:
        # Update existing token
        existing_token.token_hash = _hash_secret(token_secret)
        existing_token.last_used_at = datetime.utcnow()
        existing_token.expires_at = datetime.utcnow() + timedelta(days=7)
        token_id = existing_token.token_id
    else:
        # Create new token
        token_id = _generate_token_id()
        new_token = TeamToken(
            org_id=body.org_id,
            team_node_id=sso_team_node,
            token_id=token_id,
            token_hash=_hash_secret(token_secret),
            label=f"sso:{email}",
            permissions=(
                ["config:read", "config:write", "agent:invoke"]
                if role == "team"
                else [
                    "config:read",
                    "config:write",
                    "tokens:issue",
                    "tokens:revoke",
                    "agent:invoke",
                    "audit:read",
                    "audit:export",
                ]
            ),
            expires_at=datetime.utcnow() + timedelta(days=7),
            issued_by=f"sso:{email}",
        )
        db.add(new_token)

    db.commit()

    # Return session token (token_id.secret format)
    session_token = f"{token_id}.{token_secret}"

    return TokenExchangeResponse(
        session_token=session_token,
        email=email,
        name=name,
        role=role,
        org_id=body.org_id,
    )
