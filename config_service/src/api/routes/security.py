"""
Security policies API routes.

Enterprise security features:
- Security policies CRUD
- Token audit logs
- Integration status
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.models import Integration, SecurityPolicy, TokenAudit, TokenPermission
from ...db.session import get_db
from .admin import check_org_access, require_admin

router = APIRouter(prefix="/api/v1/admin/orgs/{org_id}", tags=["security"])


# =============================================================================
# Pydantic Models
# =============================================================================


class SecurityPolicyResponse(BaseModel):
    org_id: str
    token_expiry_days: Optional[int] = None
    token_warn_before_days: Optional[int] = 7
    token_revoke_inactive_days: Optional[int] = None
    locked_settings: List[str] = Field(default_factory=list)
    max_values: Dict[str, Any] = Field(default_factory=dict)
    required_settings: Dict[str, Any] = Field(default_factory=dict)
    allowed_values: Dict[str, Any] = Field(default_factory=dict)
    require_approval_for_prompts: bool = False
    require_approval_for_tools: bool = False
    log_all_changes: bool = True
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True


class SecurityPolicyUpdate(BaseModel):
    token_expiry_days: Optional[int] = None
    token_warn_before_days: Optional[int] = None
    token_revoke_inactive_days: Optional[int] = None
    locked_settings: Optional[List[str]] = None
    max_values: Optional[Dict[str, Any]] = None
    required_settings: Optional[Dict[str, Any]] = None
    allowed_values: Optional[Dict[str, Any]] = None
    require_approval_for_prompts: Optional[bool] = None
    require_approval_for_tools: Optional[bool] = None
    log_all_changes: Optional[bool] = None


class TokenAuditResponse(BaseModel):
    id: int
    org_id: str
    team_node_id: str
    token_id: str
    event_type: str
    event_at: datetime
    actor: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None

    class Config:
        from_attributes = True


class IntegrationResponse(BaseModel):
    org_id: str
    integration_id: str
    status: str
    display_name: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    last_checked_at: Optional[datetime] = None
    error_message: Optional[str] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class IntegrationUpdate(BaseModel):
    status: Optional[str] = None
    display_name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


# =============================================================================
# Security Policies Endpoints
# =============================================================================


@router.get("/security-policies", response_model=SecurityPolicyResponse)
async def get_security_policies(
    org_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Get security policies for an organization."""
    check_org_access(admin, org_id)
    policy = db.query(SecurityPolicy).filter(SecurityPolicy.org_id == org_id).first()

    if not policy:
        # Return default policy
        return SecurityPolicyResponse(
            org_id=org_id,
            token_expiry_days=None,
            token_warn_before_days=7,
            token_revoke_inactive_days=None,
            locked_settings=[],
            max_values={},
            required_settings={},
            allowed_values={},
            require_approval_for_prompts=False,
            require_approval_for_tools=False,
            log_all_changes=True,
        )

    return SecurityPolicyResponse.model_validate(policy)


@router.put("/security-policies", response_model=SecurityPolicyResponse)
async def update_security_policies(
    org_id: str,
    body: SecurityPolicyUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Update security policies for an organization."""
    check_org_access(admin, org_id)
    policy = db.query(SecurityPolicy).filter(SecurityPolicy.org_id == org_id).first()

    if not policy:
        # Create new policy
        policy = SecurityPolicy(
            org_id=org_id,
            updated_at=datetime.utcnow(),
            updated_by=admin.subject if hasattr(admin, "subject") else "admin",
        )
        db.add(policy)

    # Update fields
    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(policy, key, value)

    policy.updated_at = datetime.utcnow()
    policy.updated_by = admin.subject if hasattr(admin, "subject") else "admin"

    db.commit()
    db.refresh(policy)

    return SecurityPolicyResponse.model_validate(policy)


# =============================================================================
# Token Audit Endpoints
# =============================================================================


@router.get("/token-audit", response_model=List[TokenAuditResponse])
async def get_token_audit(
    org_id: str,
    team_node_id: Optional[str] = Query(None),
    token_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Get token audit logs with optional filtering."""
    check_org_access(admin, org_id)
    query = db.query(TokenAudit).filter(TokenAudit.org_id == org_id)

    if team_node_id:
        query = query.filter(TokenAudit.team_node_id == team_node_id)
    if token_id:
        query = query.filter(TokenAudit.token_id == token_id)
    if event_type:
        query = query.filter(TokenAudit.event_type == event_type)

    query = query.order_by(TokenAudit.event_at.desc())
    query = query.offset(offset).limit(limit)

    return [TokenAuditResponse.model_validate(a) for a in query.all()]


# =============================================================================
# Integration Endpoints
# =============================================================================


@router.get("/integrations", response_model=List[IntegrationResponse])
async def list_integrations(
    org_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """List all integrations for an organization."""
    check_org_access(admin, org_id)
    integrations = db.query(Integration).filter(Integration.org_id == org_id).all()

    # If no integrations exist, return default list
    if not integrations:
        default_integrations = [
            {
                "integration_id": "slack",
                "display_name": "Slack",
                "status": "not_configured",
            },
            {
                "integration_id": "openai",
                "display_name": "OpenAI",
                "status": "not_configured",
            },
            {
                "integration_id": "kubernetes",
                "display_name": "Kubernetes",
                "status": "not_configured",
            },
            {
                "integration_id": "datadog",
                "display_name": "Datadog",
                "status": "not_configured",
            },
            {
                "integration_id": "github",
                "display_name": "GitHub",
                "status": "not_configured",
            },
        ]
        return [
            IntegrationResponse(
                org_id=org_id,
                integration_id=i["integration_id"],
                display_name=i["display_name"],
                status=i["status"],
                config={},
                updated_at=datetime.utcnow(),
            )
            for i in default_integrations
        ]

    return [IntegrationResponse.model_validate(i) for i in integrations]


@router.get("/integrations/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    org_id: str,
    integration_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Get a specific integration."""
    check_org_access(admin, org_id)
    integration = (
        db.query(Integration)
        .filter(
            Integration.org_id == org_id,
            Integration.integration_id == integration_id,
        )
        .first()
    )

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    return IntegrationResponse.model_validate(integration)


@router.put("/integrations/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    org_id: str,
    integration_id: str,
    body: IntegrationUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Update an integration."""
    check_org_access(admin, org_id)
    integration = (
        db.query(Integration)
        .filter(
            Integration.org_id == org_id,
            Integration.integration_id == integration_id,
        )
        .first()
    )

    if not integration:
        # Create new
        integration = Integration(
            org_id=org_id,
            integration_id=integration_id,
            status="not_configured",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(integration)

    # Update fields
    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(integration, key, value)

    integration.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(integration)

    return IntegrationResponse.model_validate(integration)


class IntegrationTestRequest(BaseModel):
    config: Dict[str, Any] = Field(default_factory=dict)


class IntegrationTestResponse(BaseModel):
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None


@router.post(
    "/integrations/{integration_id}/test", response_model=IntegrationTestResponse
)
async def test_integration(
    org_id: str,
    integration_id: str,
    body: IntegrationTestRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Test an integration connection."""
    check_org_access(admin, org_id)
    import httpx

    config = body.config

    try:
        if integration_id == "slack":
            # Test Slack API
            bot_token = config.get("bot_token", "")
            if not bot_token:
                return IntegrationTestResponse(
                    success=False, message="Bot token is required"
                )

            async with httpx.AsyncClient() as client:
                res = await client.get(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    timeout=10,
                )
                data = res.json()
                if data.get("ok"):
                    return IntegrationTestResponse(
                        success=True,
                        message=f"Connected to workspace: {data.get('team', 'Unknown')}",
                        details={"team": data.get("team"), "user": data.get("user")},
                    )
                else:
                    return IntegrationTestResponse(
                        success=False,
                        message=f"Slack error: {data.get('error', 'Unknown error')}",
                    )

        elif integration_id == "openai":
            # Test OpenAI API
            api_key = config.get("api_key", "")
            if not api_key:
                return IntegrationTestResponse(
                    success=False, message="API key is required"
                )

            async with httpx.AsyncClient() as client:
                res = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10,
                )
                if res.status_code == 200:
                    data = res.json()
                    model_count = len(data.get("data", []))
                    return IntegrationTestResponse(
                        success=True,
                        message=f"Connected! {model_count} models available",
                        details={"models_count": model_count},
                    )
                elif res.status_code == 401:
                    return IntegrationTestResponse(
                        success=False, message="Invalid API key"
                    )
                else:
                    return IntegrationTestResponse(
                        success=False, message=f"API error: {res.status_code}"
                    )

        elif integration_id == "github":
            # Test GitHub API
            token = config.get("token", "")
            if not token:
                return IntegrationTestResponse(
                    success=False, message="Personal access token is required"
                )

            async with httpx.AsyncClient() as client:
                res = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                    timeout=10,
                )
                if res.status_code == 200:
                    data = res.json()
                    return IntegrationTestResponse(
                        success=True,
                        message=f"Connected as: {data.get('login', 'Unknown')}",
                        details={"login": data.get("login"), "name": data.get("name")},
                    )
                elif res.status_code == 401:
                    return IntegrationTestResponse(
                        success=False, message="Invalid token"
                    )
                else:
                    return IntegrationTestResponse(
                        success=False, message=f"API error: {res.status_code}"
                    )

        elif integration_id == "datadog":
            # Test Datadog API
            api_key = config.get("api_key", "")
            app_key = config.get("app_key", "")
            site = config.get("site", "datadoghq.com")

            if not api_key or not app_key:
                return IntegrationTestResponse(
                    success=False, message="API key and App key are required"
                )

            async with httpx.AsyncClient() as client:
                res = await client.get(
                    f"https://api.{site}/api/v1/validate",
                    headers={
                        "DD-API-KEY": api_key,
                        "DD-APPLICATION-KEY": app_key,
                    },
                    timeout=10,
                )
                if res.status_code == 200:
                    return IntegrationTestResponse(
                        success=True,
                        message="Datadog connection verified",
                    )
                elif res.status_code == 403:
                    return IntegrationTestResponse(
                        success=False, message="Invalid API or App key"
                    )
                else:
                    return IntegrationTestResponse(
                        success=False, message=f"API error: {res.status_code}"
                    )

        elif integration_id == "kubernetes":
            # For Kubernetes, we just validate the config format
            cluster_name = config.get("cluster_name", "")
            if not cluster_name:
                return IntegrationTestResponse(
                    success=False, message="Cluster name is required"
                )

            # In production, this would use the kubeconfig or in-cluster config
            # For now, we'll just validate the config structure
            return IntegrationTestResponse(
                success=True,
                message=f"Configuration valid for cluster: {cluster_name}",
                details={
                    "cluster_name": cluster_name,
                    "note": "In-cluster authentication used at runtime",
                },
            )

        else:
            return IntegrationTestResponse(
                success=False,
                message=f"Unknown integration: {integration_id}",
            )

    except httpx.TimeoutException:
        return IntegrationTestResponse(success=False, message="Connection timed out")
    except httpx.RequestError as e:
        return IntegrationTestResponse(
            success=False, message=f"Connection error: {str(e)}"
        )
    except Exception as e:
        return IntegrationTestResponse(success=False, message=f"Error: {str(e)}")


# =============================================================================
# Token Permissions Helper
# =============================================================================


@router.get("/token-permissions", response_model=Dict[str, Any])
async def get_available_permissions(
    org_id: str,
    admin: dict = Depends(require_admin),
):
    """Get list of available token permissions."""
    check_org_access(admin, org_id)
    return {
        "permissions": [
            {
                "id": TokenPermission.CONFIG_READ,
                "name": "Config Read",
                "description": "View team configuration",
            },
            {
                "id": TokenPermission.CONFIG_WRITE,
                "name": "Config Write",
                "description": "Modify team configuration",
            },
            {
                "id": TokenPermission.TOKENS_ISSUE,
                "name": "Issue Tokens",
                "description": "Issue new team tokens",
            },
            {
                "id": TokenPermission.TOKENS_REVOKE,
                "name": "Revoke Tokens",
                "description": "Revoke team tokens",
            },
            {
                "id": TokenPermission.AGENT_INVOKE,
                "name": "Invoke Agent",
                "description": "Run agent investigations",
            },
            {
                "id": TokenPermission.AUDIT_READ,
                "name": "Audit Read",
                "description": "View audit logs",
            },
            {
                "id": TokenPermission.AUDIT_EXPORT,
                "name": "Audit Export",
                "description": "Export audit logs",
            },
        ],
        "default_team_permissions": TokenPermission.DEFAULT_TEAM,
        "all_permissions": TokenPermission.ALL,
    }


# =============================================================================
# Token Lifecycle Management
# =============================================================================


class TokenLifecycleResponse(BaseModel):
    org_id: str
    tokens_expiring_soon: List[Dict[str, Any]]
    tokens_revoked: List[str]
    warnings_sent: int


@router.post("/token-lifecycle/run", response_model=TokenLifecycleResponse)
async def run_token_lifecycle(
    org_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Run token lifecycle checks (expiry warnings, auto-revocation).

    This endpoint should be called periodically by a scheduler/cron job.
    It will:
    1. Find tokens expiring soon and record warning audit events
    2. Auto-revoke tokens that have been inactive too long
    """
    check_org_access(admin, org_id)
    from ...db import repository

    result = repository.process_token_lifecycle(db, org_id=org_id)
    db.commit()

    return TokenLifecycleResponse(
        org_id=org_id,
        tokens_expiring_soon=result.tokens_expiring_soon,
        tokens_revoked=result.tokens_revoked,
        warnings_sent=result.warnings_sent,
    )


# =============================================================================
# Approval Workflow Endpoints
# =============================================================================


class PendingChangeResponse(BaseModel):
    id: str
    org_id: str
    node_id: str
    change_type: str
    change_path: Optional[str] = None
    proposed_value: Optional[Any] = None
    previous_value: Optional[Any] = None
    requested_by: str
    requested_at: datetime
    reason: Optional[str] = None
    status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None

    class Config:
        from_attributes = True


class PendingChangeListResponse(BaseModel):
    items: List[PendingChangeResponse]
    total: int


class ReviewChangeRequest(BaseModel):
    action: str  # "approve" or "reject"
    comment: Optional[str] = None


@router.get("/pending-changes", response_model=PendingChangeListResponse)
async def list_pending_changes(
    org_id: str,
    node_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """List pending config changes awaiting approval."""
    check_org_access(admin, org_id)
    from ...db import repository

    changes = repository.list_pending_changes(
        db,
        org_id=org_id,
        node_id=node_id,
        status=status,
        change_type=change_type,
        limit=limit,
        offset=offset,
    )

    # Count total pending for this org
    total_stmt = db.query(repository.PendingConfigChange).filter(
        repository.PendingConfigChange.org_id == org_id
    )
    if status:
        total_stmt = total_stmt.filter(repository.PendingConfigChange.status == status)
    total = total_stmt.count()

    return PendingChangeListResponse(
        items=[PendingChangeResponse.model_validate(c) for c in changes],
        total=total,
    )


@router.get("/pending-changes/{change_id}", response_model=PendingChangeResponse)
async def get_pending_change(
    org_id: str,
    change_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Get a single pending change."""
    check_org_access(admin, org_id)
    from ...db import repository

    change = repository.get_pending_change(db, change_id=change_id)
    if not change or change.org_id != org_id:
        raise HTTPException(status_code=404, detail="Pending change not found")

    return PendingChangeResponse.model_validate(change)


@router.post(
    "/pending-changes/{change_id}/review", response_model=PendingChangeResponse
)
async def review_pending_change(
    org_id: str,
    change_id: str,
    body: ReviewChangeRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Approve or reject a pending change."""
    check_org_access(admin, org_id)
    from ...db import repository
    from ...services.email_service import (
        send_change_approved_notification,
        send_change_rejected_notification,
    )

    change = repository.get_pending_change(db, change_id=change_id)
    if not change or change.org_id != org_id:
        raise HTTPException(status_code=404, detail="Pending change not found")

    reviewer = admin.subject if hasattr(admin, "subject") else "admin"

    try:
        if body.action == "approve":
            result = repository.approve_pending_change(
                db,
                change_id=change_id,
                reviewed_by=reviewer,
                review_comment=body.comment,
                apply_change=True,
            )
            # Send approval notification email
            if change.requested_by and "@" in (change.requested_by or ""):
                send_change_approved_notification(
                    to_email=change.requested_by,
                    change_type=change.change_type,
                    team_name=change.node_id,
                    approved_by=reviewer,
                    comment=body.comment,
                )
        elif body.action == "reject":
            result = repository.reject_pending_change(
                db,
                change_id=change_id,
                reviewed_by=reviewer,
                review_comment=body.comment,
            )
            # Send rejection notification email
            if change.requested_by and "@" in (change.requested_by or ""):
                send_change_rejected_notification(
                    to_email=change.requested_by,
                    change_type=change.change_type,
                    team_name=change.node_id,
                    rejected_by=reviewer,
                    comment=body.comment,
                )
        else:
            raise HTTPException(
                status_code=400, detail="Invalid action. Use 'approve' or 'reject'."
            )

        db.commit()
        return PendingChangeResponse.model_validate(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# SSO Configuration
# =============================================================================


class SSOConfigResponse(BaseModel):
    org_id: str
    enabled: bool = False
    provider_type: str = "oidc"
    provider_name: Optional[str] = None
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    # Note: client_secret is never returned, only a masked indicator
    has_client_secret: bool = False
    scopes: Optional[str] = "openid email profile"
    tenant_id: Optional[str] = None
    email_claim: Optional[str] = "email"
    name_claim: Optional[str] = "name"
    groups_claim: Optional[str] = "groups"
    admin_group: Optional[str] = None
    allowed_domains: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True


class SSOConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    provider_type: Optional[str] = None
    provider_name: Optional[str] = None
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None  # Plain text, will be encrypted
    scopes: Optional[str] = None
    tenant_id: Optional[str] = None
    email_claim: Optional[str] = None
    name_claim: Optional[str] = None
    groups_claim: Optional[str] = None
    admin_group: Optional[str] = None
    allowed_domains: Optional[str] = None


class SSOTestRequest(BaseModel):
    # For testing, we use the current config or provided overrides
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class SSOTestResponse(BaseModel):
    success: bool
    message: str
    metadata: Optional[Dict[str, Any]] = None


def _encrypt_secret(secret: str) -> str:
    """Encrypt client secrets using Fernet (AES-128-CBC with HMAC)."""
    from src.crypto import encrypt

    return encrypt(secret)


def _decrypt_secret(encrypted: str) -> str:
    """Decrypt a client secret."""
    from src.crypto import decrypt

    return decrypt(encrypted)


@router.get("/sso-config", response_model=SSOConfigResponse)
async def get_sso_config(
    org_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Get SSO configuration for an organization."""
    check_org_access(admin, org_id)
    from ...db.models import SSOConfig

    config = db.query(SSOConfig).filter(SSOConfig.org_id == org_id).first()

    if not config:
        return SSOConfigResponse(org_id=org_id, enabled=False)

    return SSOConfigResponse(
        org_id=config.org_id,
        enabled=config.enabled,
        provider_type=config.provider_type,
        provider_name=config.provider_name,
        issuer=config.issuer,
        client_id=config.client_id,
        has_client_secret=bool(config.client_secret_encrypted),
        scopes=config.scopes,
        tenant_id=config.tenant_id,
        email_claim=config.email_claim,
        name_claim=config.name_claim,
        groups_claim=config.groups_claim,
        admin_group=config.admin_group,
        allowed_domains=config.allowed_domains,
        updated_at=config.updated_at,
        updated_by=config.updated_by,
    )


@router.put("/sso-config", response_model=SSOConfigResponse)
async def update_sso_config(
    org_id: str,
    body: SSOConfigUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Update SSO configuration for an organization."""
    check_org_access(admin, org_id)
    from ...db.models import SSOConfig

    config = db.query(SSOConfig).filter(SSOConfig.org_id == org_id).first()

    if not config:
        config = SSOConfig(org_id=org_id)
        db.add(config)

    # Update fields
    update_data = body.model_dump(exclude_unset=True)

    # Handle client_secret specially (encrypt it)
    if "client_secret" in update_data:
        secret = update_data.pop("client_secret")
        if secret:
            config.client_secret_encrypted = _encrypt_secret(secret)

    for key, value in update_data.items():
        setattr(config, key, value)

    config.updated_at = datetime.utcnow()
    config.updated_by = admin.subject if hasattr(admin, "subject") else "admin"

    db.commit()
    db.refresh(config)

    return SSOConfigResponse(
        org_id=config.org_id,
        enabled=config.enabled,
        provider_type=config.provider_type,
        provider_name=config.provider_name,
        issuer=config.issuer,
        client_id=config.client_id,
        has_client_secret=bool(config.client_secret_encrypted),
        scopes=config.scopes,
        tenant_id=config.tenant_id,
        email_claim=config.email_claim,
        name_claim=config.name_claim,
        groups_claim=config.groups_claim,
        admin_group=config.admin_group,
        allowed_domains=config.allowed_domains,
        updated_at=config.updated_at,
        updated_by=config.updated_by,
    )


@router.post("/sso-config/test", response_model=SSOTestResponse)
async def test_sso_config(
    org_id: str,
    body: SSOTestRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Test SSO configuration by fetching OIDC discovery document."""
    check_org_access(admin, org_id)
    import httpx

    from ...db.models import SSOConfig

    # Get current config
    config = db.query(SSOConfig).filter(SSOConfig.org_id == org_id).first()

    # Use provided values or fall back to stored config
    issuer = body.issuer or (config.issuer if config else None)
    client_id = body.client_id or (config.client_id if config else None)

    if not issuer:
        return SSOTestResponse(success=False, message="Issuer URL is required")

    try:
        # Fetch OIDC discovery document
        discovery_url = issuer.rstrip("/") + "/.well-known/openid-configuration"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(discovery_url)

            if resp.status_code == 200:
                data = resp.json()
                return SSOTestResponse(
                    success=True,
                    message=f"Successfully connected to {data.get('issuer', issuer)}",
                    metadata={
                        "issuer": data.get("issuer"),
                        "authorization_endpoint": data.get("authorization_endpoint"),
                        "token_endpoint": data.get("token_endpoint"),
                        "userinfo_endpoint": data.get("userinfo_endpoint"),
                        "scopes_supported": data.get("scopes_supported", [])[:5],
                    },
                )
            else:
                return SSOTestResponse(
                    success=False,
                    message=f"Failed to fetch OIDC discovery: HTTP {resp.status_code}",
                )

    except httpx.TimeoutException:
        return SSOTestResponse(success=False, message="Connection timed out")
    except httpx.RequestError as e:
        return SSOTestResponse(success=False, message=f"Connection error: {str(e)}")
    except Exception as e:
        return SSOTestResponse(success=False, message=f"Error: {str(e)}")


# Public endpoint for SSO discovery (no auth required)
# This is called by the Web UI to get SSO config for login page


@router.get("/sso-config/public", response_model=Dict[str, Any])
async def get_public_sso_config(
    org_id: str,
    db: Session = Depends(get_db),
):
    """Get public SSO configuration for login page. No auth required."""
    from ...db.models import SSOConfig

    config = (
        db.query(SSOConfig)
        .filter(SSOConfig.org_id == org_id, SSOConfig.enabled == True)
        .first()
    )

    if not config:
        return {"enabled": False}

    return {
        "enabled": True,
        "provider_type": config.provider_type,
        "provider_name": config.provider_name or config.provider_type.title(),
        "issuer": config.issuer,
        "client_id": config.client_id,
        "scopes": config.scopes,
        "tenant_id": config.tenant_id,
        "allowed_domains": (
            config.allowed_domains.split(",") if config.allowed_domains else None
        ),
    }
