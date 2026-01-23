from __future__ import annotations

import csv
import io
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import AdminPrincipal, authenticate_admin_request
from src.core.audit_log import audit_logger
from src.core.config_cache import get_config_cache
from src.core.metrics import ADMIN_ACTIONS_TOTAL
from src.core.security import get_token_pepper
from src.db.config_repository import (
    get_effective_config,
    get_node_configuration,
    get_node_configurations,
    invalidate_config_cache,
    rollback_to_version,
    update_node_configuration,
)
from src.db.models import KnowledgeDocument, KnowledgeEdge, NodeType, Template
from src.db.repository import (
    create_org_node,
    create_pending_change,
    get_lineage_nodes,
    get_org_node,
    issue_team_token,
    list_node_config_audit,
    list_org_config_audit,
    list_org_nodes,
    list_team_tokens,
    requires_approval,
    revoke_team_token_scoped,
    update_org_node,
)
from src.db.session import db_session
from src.services.email_service import send_pending_approval_notification

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Default template to apply when creating new organizations
DEFAULT_TEMPLATE_SLUG = "slack-incident-triage"


def require_admin(
    principal: AdminPrincipal = Depends(authenticate_admin_request),
) -> AdminPrincipal:
    return principal


def check_org_access(principal: AdminPrincipal, org_id: str) -> None:
    """
    Verify that the principal has access to the specified org.

    - Super-admin (org_id=None) can access all orgs
    - Org admin can only access their own org

    Raises HTTPException 403 if access denied.
    """
    if principal.org_id is not None and principal.org_id != org_id:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: you can only access org '{principal.org_id}'",
        )


def get_db() -> Session:
    with db_session() as s:
        yield s


def apply_default_template_to_org(session: Session, org_id: str, node_id: str) -> bool:
    """
    Apply the default template (slack-incident-triage) to a newly created org.

    This ensures new orgs have a working agent configuration out of the box.
    Users can later choose different templates or customize their config.

    Returns True if template was applied, False if template not found.
    """
    from src.api.routes.templates import apply_template_with_agent_replacement
    from src.db.config_models import NodeConfiguration

    # Find the default template
    template = (
        session.query(Template)
        .filter(
            Template.slug == DEFAULT_TEMPLATE_SLUG,
            Template.is_published == True,
        )
        .first()
    )

    if not template:
        # Template not found - this can happen if templates haven't been seeded yet
        # Log a warning but don't fail org creation
        audit_logger().warning(
            "default_template_not_found",
            template_slug=DEFAULT_TEMPLATE_SLUG,
            org_id=org_id,
        )
        return False

    # Get the NodeConfiguration that was just created
    node_config = (
        session.query(NodeConfiguration)
        .filter(
            NodeConfiguration.org_id == org_id,
            NodeConfiguration.node_id == node_id,
        )
        .first()
    )

    if not node_config:
        # This shouldn't happen since create_org_node creates the config
        audit_logger().warning(
            "node_config_not_found_for_template",
            org_id=org_id,
            node_id=node_id,
        )
        return False

    # Apply the template with agent replacement logic
    merged_config = apply_template_with_agent_replacement(
        node_config.config_json or {}, template.template_json
    )
    node_config.config_json = merged_config
    node_config.updated_by = "system"

    # Update template usage count
    template.usage_count = (template.usage_count or 0) + 1

    audit_logger().info(
        "default_template_applied",
        audit=True,
        org_id=org_id,
        node_id=node_id,
        template_slug=DEFAULT_TEMPLATE_SLUG,
        template_name=template.name,
    )

    return True


class CreateNodeRequest(BaseModel):
    node_id: str = Field(min_length=1, max_length=128)
    parent_id: Optional[str] = Field(default=None, max_length=128)
    node_type: NodeType
    name: Optional[str] = Field(default=None, max_length=256)


class UpdateNodeRequest(BaseModel):
    parent_id: Optional[str] = Field(default=None, max_length=128)
    name: Optional[str] = Field(default=None, max_length=256)


class PatchConfigRequest(BaseModel):
    patch: Dict[str, Any] = Field(default_factory=dict)


class RollbackConfigRequest(BaseModel):
    version: int = Field(ge=1)


class IssueTokenResponse(BaseModel):
    token: str
    issued_at: datetime


class IssueImpersonationTokenResponse(BaseModel):
    token: str
    expires_at: datetime


class TokenRow(BaseModel):
    token_id: str
    issued_at: datetime
    revoked_at: Optional[datetime] = None
    issued_by: Optional[str] = None


class KnowledgeEdgeIn(BaseModel):
    entity: str = Field(min_length=1, max_length=256)
    relationship: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=256)
    source: Optional[str] = None


class KnowledgeEdgeRow(KnowledgeEdgeIn):
    created_at: datetime


class KnowledgeDocIn(BaseModel):
    doc_id: str = Field(min_length=1, max_length=256)
    title: Optional[str] = Field(default=None, max_length=512)
    content: str = Field(min_length=1, max_length=50_000)
    source_type: Optional[str] = Field(default=None, max_length=64)
    source_id: Optional[str] = Field(default=None, max_length=256)


class KnowledgeDocRow(KnowledgeDocIn):
    updated_at: datetime


class NodeRow(BaseModel):
    org_id: str
    node_id: str
    parent_id: Optional[str] = None
    node_type: str
    name: Optional[str] = None


class AuditRow(BaseModel):
    org_id: str
    node_id: str
    version: int
    changed_at: datetime
    changed_by: Optional[str] = None
    diff: Dict[str, Any]
    full_config: Dict[str, Any]


class OrgAuditRow(BaseModel):
    org_id: str
    node_id: str
    version: int
    changed_at: datetime
    changed_by: Optional[str] = None
    diff: Dict[str, Any]
    full_config: Optional[Dict[str, Any]] = None


@router.post("/orgs/{org_id}/nodes")
def admin_create_node(
    org_id: str,
    body: CreateNodeRequest,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    check_org_access(principal, org_id)
    try:
        node = create_org_node(
            session,
            org_id=org_id,
            node_id=body.node_id,
            parent_id=body.parent_id,
            node_type=body.node_type,
            name=body.name,
        )

        # Auto-apply default template for org nodes
        # This gives new orgs a working agent config out of the box
        template_applied = False
        if body.node_type == NodeType.org:
            template_applied = apply_default_template_to_org(
                session, org_id, body.node_id
            )

        ADMIN_ACTIONS_TOTAL.labels("create_node", "ok").inc()
        cache = get_config_cache()
        if cache is not None:
            cache.bump_org_epoch(org_id)
        audit_logger().info(
            "admin_create_node",
            audit=True,
            org_id=org_id,
            node_id=body.node_id,
            auth_kind=principal.auth_kind,
            actor=principal.email or principal.subject,
            template_applied=template_applied,
        )
        return {
            "org_id": node.org_id,
            "node_id": node.node_id,
            "parent_id": node.parent_id,
            "node_type": node.node_type.value,
            "name": node.name,
            "template_applied": template_applied,
        }
    except ValueError as e:
        ADMIN_ACTIONS_TOTAL.labels("create_node", "error").inc()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orgs/{org_id}/nodes", response_model=List[NodeRow])
def admin_list_nodes(
    org_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    check_org_access(principal, org_id)
    nodes = list_org_nodes(session, org_id=org_id)
    ADMIN_ACTIONS_TOTAL.labels("list_nodes", "ok").inc()
    audit_logger().info(
        "admin_list_nodes",
        audit=True,
        org_id=org_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return [
        NodeRow(
            org_id=n.org_id,
            node_id=n.node_id,
            parent_id=n.parent_id,
            node_type=n.node_type.value,
            name=n.name,
        )
        for n in nodes
    ]


@router.get("/orgs/{org_id}/nodes/{node_id}", response_model=NodeRow)
def admin_get_node(
    org_id: str,
    node_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    check_org_access(principal, org_id)
    try:
        n = get_org_node(session, org_id=org_id, node_id=node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    ADMIN_ACTIONS_TOTAL.labels("get_node", "ok").inc()
    audit_logger().info(
        "admin_get_node",
        audit=True,
        org_id=org_id,
        node_id=node_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return NodeRow(
        org_id=n.org_id,
        node_id=n.node_id,
        parent_id=n.parent_id,
        node_type=n.node_type.value,
        name=n.name,
    )


@router.get("/orgs/{org_id}/nodes/{node_id}/config")
def admin_get_node_config(
    org_id: str,
    node_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    node_config = get_node_configuration(session, org_id=org_id, node_id=node_id)
    cfg = node_config.config_json if node_config else {}
    ADMIN_ACTIONS_TOTAL.labels("get_node_config", "ok").inc()
    audit_logger().info(
        "admin_get_node_config",
        audit=True,
        org_id=org_id,
        node_id=node_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return {"config": cfg}


@router.get("/orgs/{org_id}/nodes/{node_id}/raw")
def admin_get_node_raw_config(
    org_id: str,
    node_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Return lineage + per-node configs for any node (root/group/team).

    Same response shape as GET /api/v1/config/me/raw, but admin-scoped.
    """
    try:
        lineage_nodes = get_lineage_nodes(session, org_id=org_id, node_id=node_id)
        node_ids = [n.node_id for n in lineage_nodes]
        configs = get_node_configurations(session, org_id=org_id, node_ids=node_ids)
        lineage = [
            {
                "node_id": n.node_id,
                "node_type": n.node_type.value,
                "name": n.name,
                "parent_id": n.parent_id,
            }
            for n in lineage_nodes
        ]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    ADMIN_ACTIONS_TOTAL.labels("get_node_raw", "ok").inc()
    audit_logger().info(
        "admin_get_node_raw",
        audit=True,
        org_id=org_id,
        node_id=node_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return {"lineage": lineage, "configs": configs}


@router.get("/orgs/{org_id}/nodes/{node_id}/effective")
def admin_get_node_effective_config(
    org_id: str,
    node_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Return effective merged config for any node (root/group/team).

    Same response shape as GET /api/v1/config/me/effective, but admin-scoped.
    """
    try:
        eff = get_effective_config(session, org_id=org_id, node_id=node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    ADMIN_ACTIONS_TOTAL.labels("get_node_effective", "ok").inc()
    audit_logger().info(
        "admin_get_node_effective",
        audit=True,
        org_id=org_id,
        node_id=node_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return eff


@router.get("/orgs/{org_id}/nodes/{node_id}/audit", response_model=List[AuditRow])
def admin_get_node_audit(
    org_id: str,
    node_id: str,
    limit: int = 50,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    rows = list_node_config_audit(session, org_id=org_id, node_id=node_id, limit=limit)
    ADMIN_ACTIONS_TOTAL.labels("get_node_audit", "ok").inc()
    audit_logger().info(
        "admin_get_node_audit",
        audit=True,
        org_id=org_id,
        node_id=node_id,
        limit=limit,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return [
        AuditRow(
            org_id=r.org_id,
            node_id=r.node_id,
            version=int(r.version),
            changed_at=r.changed_at,
            changed_by=r.changed_by,
            diff=r.change_diff or {},
            full_config=r.new_config or {},
        )
        for r in rows
    ]


@router.get("/orgs/{org_id}/audit", response_model=List[OrgAuditRow])
def admin_get_org_audit(
    org_id: str,
    node_id: Optional[str] = None,
    changed_by: Optional[str] = None,
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = 200,
    include_full: bool = False,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    rows = list_org_config_audit(
        session,
        org_id=org_id,
        node_id=node_id,
        changed_by=changed_by,
        since=since,
        until=until,
        limit=limit,
    )
    ADMIN_ACTIONS_TOTAL.labels("get_org_audit", "ok").inc()
    audit_logger().info(
        "admin_get_org_audit",
        audit=True,
        org_id=org_id,
        node_id=node_id,
        changed_by=changed_by,
        since=since.isoformat() if since else None,
        until=until.isoformat() if until else None,
        limit=limit,
        include_full=include_full,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return [
        OrgAuditRow(
            org_id=r.org_id,
            node_id=r.node_id,
            version=int(r.version),
            changed_at=r.changed_at,
            changed_by=r.changed_by,
            diff=r.change_diff or {},
            full_config=(r.new_config or {}) if include_full else None,
        )
        for r in rows
    ]


@router.get("/orgs/{org_id}/audit/export")
def admin_export_org_audit(
    org_id: str,
    format: str = "csv",
    node_id: Optional[str] = None,
    changed_by: Optional[str] = None,
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = 500,
    include_full: bool = False,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    fmt = (format or "csv").strip().lower()
    if fmt not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="format must be one of: csv, json")

    rows = list_org_config_audit(
        session,
        org_id=org_id,
        node_id=node_id,
        changed_by=changed_by,
        since=since,
        until=until,
        limit=limit,
    )

    ADMIN_ACTIONS_TOTAL.labels("export_org_audit", "ok").inc()
    audit_logger().info(
        "admin_export_org_audit",
        audit=True,
        org_id=org_id,
        format=fmt,
        node_id=node_id,
        changed_by=changed_by,
        since=since.isoformat() if since else None,
        until=until.isoformat() if until else None,
        limit=limit,
        include_full=include_full,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )

    if fmt == "json":
        payload = [
            OrgAuditRow(
                org_id=r.org_id,
                node_id=r.node_id,
                version=int(r.version),
                changed_at=r.changed_at,
                changed_by=r.changed_by,
                diff=r.change_diff or {},
                full_config=(r.new_config or {}) if include_full else None,
            ).model_dump()
            for r in rows
        ]
        return payload

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "org_id",
            "node_id",
            "version",
            "changed_at",
            "changed_by",
            "change_diff",
            "new_config",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r.org_id,
                r.node_id,
                int(r.version),
                r.changed_at.isoformat(),
                r.changed_by or "",
                (r.change_diff or {}),
                (r.new_config or {}) if include_full else {},
            ]
        )
    filename = f"{org_id}-audit.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/orgs/{org_id}/nodes/{node_id}")
def admin_update_node(
    org_id: str,
    node_id: str,
    body: UpdateNodeRequest,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    try:
        node = update_org_node(
            session,
            org_id=org_id,
            node_id=node_id,
            parent_id=body.parent_id,
            name=body.name,
        )
        ADMIN_ACTIONS_TOTAL.labels("update_node", "ok").inc()
        cache = get_config_cache()
        if cache is not None:
            cache.bump_org_epoch(org_id)
        audit_logger().info(
            "admin_update_node",
            audit=True,
            org_id=org_id,
            node_id=node_id,
            auth_kind=principal.auth_kind,
            actor=principal.email or principal.subject,
        )
        return {
            "org_id": node.org_id,
            "node_id": node.node_id,
            "parent_id": node.parent_id,
            "node_type": node.node_type.value,
            "name": node.name,
        }
    except ValueError as e:
        ADMIN_ACTIONS_TOTAL.labels("update_node", "error").inc()
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/orgs/{org_id}/nodes/{node_id}/config")
def admin_patch_node_config(
    org_id: str,
    node_id: str,
    body: PatchConfigRequest,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    x_admin_actor: str = Header(default="admin", convert_underscores=False),
    x_bypass_approval: str = Header(default="", convert_underscores=False),
):
    try:
        # Check if this change requires approval
        bypass = x_bypass_approval.lower() == "true"

        if not bypass:
            # Check for prompt changes requiring approval
            if "custom_prompt" in body.patch or "system_prompt" in body.patch:
                if requires_approval(session, org_id=org_id, change_type="prompt"):
                    # Get current value
                    node_config = get_node_configuration(
                        session, org_id=org_id, node_id=node_id
                    )
                    current_config = node_config.config_json if node_config else {}
                    change_path = (
                        "custom_prompt"
                        if "custom_prompt" in body.patch
                        else "system_prompt"
                    )

                    pending = create_pending_change(
                        session,
                        org_id=org_id,
                        node_id=node_id,
                        change_type="prompt",
                        change_path=change_path,
                        proposed_value=body.patch.get(change_path),
                        previous_value=current_config.get(change_path),
                        requested_by=x_admin_actor,
                    )
                    session.commit()

                    # Send email notification to admins
                    dashboard_url = (
                        os.getenv("WEB_UI_URL", "http://localhost:3000")
                        + "/admin/pending-changes"
                    )
                    admin_email = os.getenv("ADMIN_NOTIFICATION_EMAIL")
                    if admin_email:
                        send_pending_approval_notification(
                            to_emails=[admin_email],
                            change_type="Prompt",
                            team_name=node_id,
                            requested_by=x_admin_actor,
                            change_summary=f"Change to {change_path}",
                            dashboard_url=dashboard_url,
                        )

                    return {
                        "status": "pending_approval",
                        "message": "Prompt changes require approval",
                        "pending_change_id": pending.id,
                    }

            # Check for tool changes requiring approval
            if "enabled_tools" in body.patch:
                if requires_approval(session, org_id=org_id, change_type="tools"):
                    node_config = get_node_configuration(
                        session, org_id=org_id, node_id=node_id
                    )
                    current_config = node_config.config_json if node_config else {}

                    pending = create_pending_change(
                        session,
                        org_id=org_id,
                        node_id=node_id,
                        change_type="tools",
                        change_path="enabled_tools",
                        proposed_value=body.patch.get("enabled_tools"),
                        previous_value=current_config.get("enabled_tools"),
                        requested_by=x_admin_actor,
                    )
                    session.commit()

                    # Send email notification to admins
                    dashboard_url = (
                        os.getenv("WEB_UI_URL", "http://localhost:3000")
                        + "/admin/pending-changes"
                    )
                    admin_email = os.getenv("ADMIN_NOTIFICATION_EMAIL")
                    if admin_email:
                        send_pending_approval_notification(
                            to_emails=[admin_email],
                            change_type="Tool Enablement",
                            team_name=node_id,
                            requested_by=x_admin_actor,
                            change_summary="Changes to enabled tools",
                            dashboard_url=dashboard_url,
                        )

                    return {
                        "status": "pending_approval",
                        "message": "Tool enablement changes require approval",
                        "pending_change_id": pending.id,
                    }

        # Apply the change directly
        updated_config, diff = update_node_configuration(
            session,
            org_id=org_id,
            node_id=node_id,
            config_patch=body.patch,
            updated_by=x_admin_actor,
            skip_validation=True,  # Admin can bypass validation
        )
        merged = updated_config.config_json
        session.commit()

        # Invalidate cached effective configs for this node and all descendants
        invalidate_config_cache(session, org_id, node_id, cascade=True)
        session.commit()

        ADMIN_ACTIONS_TOTAL.labels("patch_node_config", "ok").inc()
        cache = get_config_cache()
        if cache is not None:
            cache.bump_org_epoch(org_id)
        audit_logger().info(
            "admin_patch_node_config",
            audit=True,
            org_id=org_id,
            node_id=node_id,
            updated_by=x_admin_actor,
            auth_kind=principal.auth_kind,
            actor=principal.email or principal.subject,
        )
        return {"config": merged}
    except ValueError as e:
        ADMIN_ACTIONS_TOTAL.labels("patch_node_config", "error").inc()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/orgs/{org_id}/nodes/{node_id}/config/rollback")
def admin_rollback_node_config(
    org_id: str,
    node_id: str,
    body: RollbackConfigRequest,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    x_admin_actor: str = Header(default="admin", convert_underscores=False),
):
    try:
        updated_config, diff = rollback_to_version(
            session,
            org_id=org_id,
            node_id=node_id,
            version=body.version,
            rolled_back_by=x_admin_actor,
        )
        cfg = updated_config.config_json
        session.commit()

        # Invalidate cached effective configs for this node and all descendants
        invalidate_config_cache(session, org_id, node_id, cascade=True)
        session.commit()

        ADMIN_ACTIONS_TOTAL.labels("rollback_node_config", "ok").inc()
        cache = get_config_cache()
        if cache is not None:
            cache.bump_org_epoch(org_id)
        audit_logger().info(
            "admin_rollback_node_config",
            audit=True,
            org_id=org_id,
            node_id=node_id,
            rollback_version=body.version,
            updated_by=x_admin_actor,
            auth_kind=principal.auth_kind,
            actor=principal.email or principal.subject,
        )
        return {"config": cfg}
    except ValueError as e:
        ADMIN_ACTIONS_TOTAL.labels("rollback_node_config", "error").inc()
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/orgs/{org_id}/teams/{team_node_id}/tokens", response_model=IssueTokenResponse
)
def admin_issue_team_token(
    org_id: str,
    team_node_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    x_admin_actor: str = Header(default="admin", convert_underscores=False),
):
    pepper = get_token_pepper()
    token = issue_team_token(
        session,
        org_id=org_id,
        team_node_id=team_node_id,
        issued_by=x_admin_actor,
        pepper=pepper,
    )
    ADMIN_ACTIONS_TOTAL.labels("issue_team_token", "ok").inc()
    audit_logger().info(
        "admin_issue_team_token",
        audit=True,
        org_id=org_id,
        team_node_id=team_node_id,
        issued_by=x_admin_actor,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return IssueTokenResponse(token=token, issued_at=datetime.utcnow())


@router.post(
    "/orgs/{org_id}/teams/{team_node_id}/impersonation-token",
    response_model=IssueImpersonationTokenResponse,
)
def admin_issue_team_impersonation_token(
    org_id: str,
    team_node_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    x_admin_actor: str = Header(default="admin", convert_underscores=False),
    session: Session = Depends(get_db),
):
    """
    Mint a short-lived team-scoped JWT for server-to-server calls.

    This avoids long-lived team token sprawl when orchestrator needs to call team-scoped endpoints.
    """
    from src.core.impersonation import mint_team_impersonation_token
    from src.db.repository import record_impersonation_jti

    token, exp, jti = mint_team_impersonation_token(
        org_id=org_id,
        team_node_id=team_node_id,
        actor_subject=principal.subject,
        actor_email=principal.email,
        ttl_seconds=None,
    )

    # Optional DB-backed audit log (and optional allowlist enforcement on verify).
    if (os.getenv("IMPERSONATION_JTI_DB_LOGGING", "0") or "0").strip() == "1":
        try:
            record_impersonation_jti(
                session,
                jti=jti,
                org_id=org_id,
                team_node_id=team_node_id,
                subject=principal.subject,
                email=principal.email,
                issued_at=datetime.utcnow(),
                expires_at=datetime.utcfromtimestamp(exp),
            )
        except Exception:
            # Never fail token minting for audit-log issues.
            audit_logger().warning(
                "impersonation_jti_record_failed",
                audit=True,
                org_id=org_id,
                team_node_id=team_node_id,
                jti=jti,
            )

    ADMIN_ACTIONS_TOTAL.labels("issue_team_impersonation_token", "ok").inc()
    audit_logger().info(
        "admin_issue_team_impersonation_token",
        audit=True,
        org_id=org_id,
        team_node_id=team_node_id,
        issued_by=x_admin_actor,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
        jti=jti,
        expires_at=datetime.utcfromtimestamp(exp).isoformat(),
    )
    return IssueImpersonationTokenResponse(
        token=token, expires_at=datetime.utcfromtimestamp(exp)
    )


@router.post("/orgs/{org_id}/teams/{team_node_id}/tokens/{token_id}/revoke")
def admin_revoke_team_token(
    org_id: str,
    team_node_id: str,
    token_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    x_admin_actor: str = Header(default="admin", convert_underscores=False),
):
    revoke_team_token_scoped(
        session, org_id=org_id, team_node_id=team_node_id, token_id=token_id
    )
    ADMIN_ACTIONS_TOTAL.labels("revoke_team_token", "ok").inc()
    audit_logger().info(
        "admin_revoke_team_token",
        audit=True,
        org_id=org_id,
        team_node_id=team_node_id,
        token_id=token_id,
        revoked_by=x_admin_actor,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return {"status": "ok"}


@router.get("/orgs/{org_id}/teams/{team_node_id}/tokens", response_model=List[TokenRow])
def admin_list_team_tokens(
    org_id: str,
    team_node_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    rows = list_team_tokens(session, org_id=org_id, team_node_id=team_node_id)
    ADMIN_ACTIONS_TOTAL.labels("list_team_tokens", "ok").inc()
    audit_logger().info(
        "admin_list_team_tokens",
        audit=True,
        org_id=org_id,
        team_node_id=team_node_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return [
        TokenRow(
            token_id=r.token_id,
            issued_at=r.issued_at,
            revoked_at=r.revoked_at,
            issued_by=r.issued_by,
        )
        for r in rows
    ]


# =============================================================================
# Org-Wide Token Management (All teams)
# =============================================================================


@router.get("/orgs/{org_id}/tokens")
def admin_list_org_tokens(
    org_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """List all tokens across all teams in the organization."""
    from src.db.repository import get_org_node, list_org_tokens

    # Verify org exists (org root node has node_id == org_id)
    try:
        org_node = get_org_node(session, org_id=org_id, node_id=org_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Organization not found")

    tokens = list_org_tokens(session, org_id=org_id)
    ADMIN_ACTIONS_TOTAL.labels("list_org_tokens", "ok").inc()
    audit_logger().info(
        "admin_list_org_tokens",
        audit=True,
        org_id=org_id,
        token_count=len(tokens),
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )

    # Return extended token information
    return {
        "tokens": [
            {
                "token_id": t.token_id,
                "team_node_id": t.team_node_id,
                "issued_at": t.issued_at.isoformat() if t.issued_at else None,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
                "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
                "issued_by": t.issued_by,
                "label": t.label,
                "permissions": t.permissions,
                "status": (
                    "revoked"
                    if t.revoked_at
                    else ("expired" if t.is_expired() else "active")
                ),
            }
            for t in tokens
        ],
        "total": len(tokens),
    }


@router.get("/orgs/{org_id}/tokens/{token_id}")
def admin_get_token_details(
    org_id: str,
    token_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Get detailed information about a specific token."""
    from src.db.repository import get_token_by_id

    token = get_token_by_id(session, token_id=token_id)

    if not token or token.org_id != org_id:
        raise HTTPException(status_code=404, detail="Token not found")

    ADMIN_ACTIONS_TOTAL.labels("get_token_details", "ok").inc()
    audit_logger().info(
        "admin_get_token_details",
        audit=True,
        org_id=org_id,
        token_id=token_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )

    return {
        "token_id": token.token_id,
        "team_node_id": token.team_node_id,
        "issued_at": token.issued_at.isoformat() if token.issued_at else None,
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "revoked_at": token.revoked_at.isoformat() if token.revoked_at else None,
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
        "issued_by": token.issued_by,
        "label": token.label,
        "permissions": token.permissions,
        "status": (
            "revoked"
            if token.revoked_at
            else ("expired" if token.is_expired() else "active")
        ),
    }


@router.post("/orgs/{org_id}/tokens/{token_id}/extend")
def admin_extend_token(
    org_id: str,
    token_id: str,
    body: dict,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    x_admin_actor: str = Header(default="admin", convert_underscores=False),
):
    """Extend token expiration by specified number of days."""
    from src.db.repository import extend_token_expiration, get_token_by_id

    # Verify token belongs to org
    token = get_token_by_id(session, token_id=token_id)
    if not token or token.org_id != org_id:
        raise HTTPException(status_code=404, detail="Token not found")

    days = body.get("days", 90)
    if not isinstance(days, int) or days <= 0:
        raise HTTPException(status_code=400, detail="Days must be a positive integer")

    updated_token = extend_token_expiration(
        session,
        token_id=token_id,
        days=days,
        extended_by=x_admin_actor,
    )

    if not updated_token:
        raise HTTPException(
            status_code=400, detail="Token cannot be extended (revoked or not found)"
        )

    session.commit()

    ADMIN_ACTIONS_TOTAL.labels("extend_token", "ok").inc()
    audit_logger().info(
        "admin_extend_token",
        audit=True,
        org_id=org_id,
        token_id=token_id,
        days=days,
        extended_by=x_admin_actor,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )

    return {
        "status": "ok",
        "token_id": token_id,
        "expires_at": (
            updated_token.expires_at.isoformat() if updated_token.expires_at else None
        ),
    }


@router.post("/orgs/{org_id}/tokens/bulk-revoke")
def admin_bulk_revoke_tokens(
    org_id: str,
    body: dict,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    x_admin_actor: str = Header(default="admin", convert_underscores=False),
):
    """Bulk revoke multiple tokens."""
    from src.db.repository import bulk_revoke_tokens, get_token_by_id

    token_ids = body.get("token_ids", [])
    if not isinstance(token_ids, list) or not token_ids:
        raise HTTPException(
            status_code=400, detail="token_ids must be a non-empty list"
        )

    # Verify all tokens belong to the org
    for token_id in token_ids:
        token = get_token_by_id(session, token_id=token_id)
        if token and token.org_id != org_id:
            raise HTTPException(
                status_code=403,
                detail=f"Token {token_id} does not belong to organization",
            )

    count = bulk_revoke_tokens(
        session,
        token_ids=token_ids,
        revoked_by=x_admin_actor,
    )

    session.commit()

    ADMIN_ACTIONS_TOTAL.labels("bulk_revoke_tokens", "ok").inc()
    audit_logger().info(
        "admin_bulk_revoke_tokens",
        audit=True,
        org_id=org_id,
        token_count=count,
        revoked_by=x_admin_actor,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )

    return {
        "status": "ok",
        "revoked_count": count,
        "total_requested": len(token_ids),
    }


# =============================================================================
# Admin Dashboard APIs
# =============================================================================


@router.get("/orgs/{org_id}/stats")
def admin_get_org_stats(
    org_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Get organization statistics for the dashboard."""
    from datetime import timedelta

    from sqlalchemy import and_, func

    from src.db.models import AgentRun
    from src.db.repository import list_org_nodes

    # Get all nodes (teams)
    nodes = list_org_nodes(session, org_id=org_id)
    team_nodes = [n for n in nodes if n.node_type == "team"]
    total_teams = len(team_nodes)

    # Get active teams (teams with agent runs in last 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    active_teams_count = (
        session.query(func.count(func.distinct(AgentRun.team_node_id)))
        .filter(and_(AgentRun.org_id == org_id, AgentRun.started_at >= seven_days_ago))
        .scalar()
        or 0
    )

    # Get agent runs count (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    total_runs = (
        session.query(func.count(AgentRun.id))
        .filter(and_(AgentRun.org_id == org_id, AgentRun.started_at >= thirty_days_ago))
        .scalar()
        or 0
    )

    # Calculate success rate
    successful_runs = (
        session.query(func.count(AgentRun.id))
        .filter(
            and_(
                AgentRun.org_id == org_id,
                AgentRun.started_at >= thirty_days_ago,
                AgentRun.status == "completed",
            )
        )
        .scalar()
        or 0
    )

    success_rate = (
        round((successful_runs / total_runs * 100), 1) if total_runs > 0 else 0.0
    )

    # Calculate org-wide MTTD percentiles (last 30 days)
    org_completed_runs = (
        session.query(AgentRun)
        .filter(
            and_(
                AgentRun.org_id == org_id,
                AgentRun.started_at >= thirty_days_ago,
                AgentRun.status == "completed",
                AgentRun.completed_at.isnot(None),
            )
        )
        .all()
    )

    org_duration_percentiles = None
    org_avg_duration_seconds = None
    if org_completed_runs:
        org_durations = [
            (run.completed_at - run.started_at).total_seconds()
            for run in org_completed_runs
            if run.completed_at and run.started_at
        ]
        if org_durations:
            org_avg_duration_seconds = round(sum(org_durations) / len(org_durations), 1)
            sorted_durations = sorted(org_durations)
            count = len(sorted_durations)
            org_duration_percentiles = {
                "p50": round(sorted_durations[int(count * 0.5)] if count > 0 else 0, 1),
                "p95": round(
                    (
                        sorted_durations[int(count * 0.95)]
                        if count > 1
                        else sorted_durations[0]
                    ),
                    1,
                ),
                "p99": round(
                    (
                        sorted_durations[int(count * 0.99)]
                        if count > 1
                        else sorted_durations[0]
                    ),
                    1,
                ),
            }

    # Get per-team statistics
    team_stats = []
    for team_node in team_nodes:
        team_id = team_node.node_id

        # Count runs for this team (last 30 days)
        team_total_runs = (
            session.query(func.count(AgentRun.id))
            .filter(
                and_(
                    AgentRun.team_node_id == team_id,
                    AgentRun.started_at >= thirty_days_ago,
                )
            )
            .scalar()
            or 0
        )

        # Count successful runs for this team
        team_successful_runs = (
            session.query(func.count(AgentRun.id))
            .filter(
                and_(
                    AgentRun.team_node_id == team_id,
                    AgentRun.started_at >= thirty_days_ago,
                    AgentRun.status == "completed",
                )
            )
            .scalar()
            or 0
        )

        # Count failed runs for this team
        team_failed_runs = (
            session.query(func.count(AgentRun.id))
            .filter(
                and_(
                    AgentRun.team_node_id == team_id,
                    AgentRun.started_at >= thirty_days_ago,
                    AgentRun.status == "failed",
                )
            )
            .scalar()
            or 0
        )

        # Get last run timestamp
        last_run = (
            session.query(AgentRun.started_at)
            .filter(AgentRun.team_node_id == team_id)
            .order_by(AgentRun.started_at.desc())
            .first()
        )

        team_success_rate = (
            round((team_successful_runs / team_total_runs * 100), 1)
            if team_total_runs > 0
            else 0.0
        )

        # Calculate average run duration (for completed runs in last 30 days)
        completed_runs = (
            session.query(AgentRun)
            .filter(
                and_(
                    AgentRun.team_node_id == team_id,
                    AgentRun.started_at >= thirty_days_ago,
                    AgentRun.status == "completed",
                    AgentRun.completed_at.isnot(None),
                )
            )
            .all()
        )

        avg_duration_seconds = None
        duration_percentiles = None
        if completed_runs:
            durations = [
                (run.completed_at - run.started_at).total_seconds()
                for run in completed_runs
                if run.completed_at and run.started_at
            ]
            if durations:
                avg_duration_seconds = int(sum(durations) / len(durations))
                # Calculate percentiles for MTTD
                sorted_durations = sorted(durations)
                count = len(sorted_durations)
                duration_percentiles = {
                    "p50": round(
                        sorted_durations[int(count * 0.5)] if count > 0 else 0, 1
                    ),
                    "p95": round(
                        (
                            sorted_durations[int(count * 0.95)]
                            if count > 1
                            else sorted_durations[0]
                        ),
                        1,
                    ),
                    "p99": round(
                        (
                            sorted_durations[int(count * 0.99)]
                            if count > 1
                            else sorted_durations[0]
                        ),
                        1,
                    ),
                }

        # Find most used agent (last 30 days)
        most_used_agent = (
            session.query(AgentRun.agent_name, func.count(AgentRun.id).label("count"))
            .filter(
                and_(
                    AgentRun.team_node_id == team_id,
                    AgentRun.started_at >= thirty_days_ago,
                )
            )
            .group_by(AgentRun.agent_name)
            .order_by(func.count(AgentRun.id).desc())
            .first()
        )

        # Calculate trend (runs this week vs previous week)
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        two_weeks_ago = datetime.utcnow() - timedelta(days=14)

        runs_this_week = (
            session.query(func.count(AgentRun.id))
            .filter(
                and_(
                    AgentRun.team_node_id == team_id,
                    AgentRun.started_at >= one_week_ago,
                )
            )
            .scalar()
            or 0
        )

        runs_prev_week = (
            session.query(func.count(AgentRun.id))
            .filter(
                and_(
                    AgentRun.team_node_id == team_id,
                    AgentRun.started_at >= two_weeks_ago,
                    AgentRun.started_at < one_week_ago,
                )
            )
            .scalar()
            or 0
        )

        # Determine trend: "up", "down", "stable"
        trend = "stable"
        if runs_prev_week > 0:
            change_pct = ((runs_this_week - runs_prev_week) / runs_prev_week) * 100
            if change_pct > 10:
                trend = "up"
            elif change_pct < -10:
                trend = "down"
        elif runs_this_week > 0:
            trend = "up"

        team_stats.append(
            {
                "team_node_id": team_id,
                "team_name": team_node.name or team_id,
                "total_runs": team_total_runs,
                "successful_runs": team_successful_runs,
                "failed_runs": team_failed_runs,
                "success_rate": team_success_rate,
                "last_run_at": last_run[0].isoformat() if last_run else None,
                "avg_duration_seconds": avg_duration_seconds,
                "duration_percentiles": duration_percentiles,
                "most_used_agent": most_used_agent[0] if most_used_agent else None,
                "trend": trend,
                "runs_this_week": runs_this_week,
                "runs_prev_week": runs_prev_week,
            }
        )

    # Sort teams by total runs descending
    team_stats.sort(key=lambda t: t["total_runs"], reverse=True)

    ADMIN_ACTIONS_TOTAL.labels("get_org_stats", "ok").inc()

    return {
        "totalTeams": total_teams,
        "activeTeams": active_teams_count,
        "totalRuns": total_runs,
        "successRate": success_rate,
        "avgDurationSeconds": org_avg_duration_seconds,
        "durationPercentiles": org_duration_percentiles,
        "teams": team_stats,
    }


@router.get("/orgs/{org_id}/activity")
def admin_get_org_activity(
    org_id: str,
    limit: int = Query(10, ge=1, le=100),
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Get recent activity feed for the dashboard."""
    from sqlalchemy import desc

    from src.db.config_models import ConfigChangeHistory
    from src.db.models import AgentRun, TokenAudit

    activities = []

    # Get recent agent runs
    runs = (
        session.query(AgentRun)
        .filter(AgentRun.org_id == org_id)
        .order_by(desc(AgentRun.started_at))
        .limit(limit)
        .all()
    )

    for run in runs:
        status_map = {"completed": "success", "failed": "failed", "running": "pending"}
        activities.append(
            {
                "id": run.id,
                "type": "run",
                "description": f"Investigation {run.status}: {run.trigger_message or 'No description'}",
                "timestamp": run.started_at.isoformat() if run.started_at else None,
                "status": status_map.get(run.status, "info"),
                "teamName": run.team_node_id,
            }
        )

    # Get recent config changes
    config_audits = (
        session.query(ConfigChangeHistory)
        .filter(ConfigChangeHistory.org_id == org_id)
        .order_by(desc(ConfigChangeHistory.changed_at))
        .limit(limit // 2)
        .all()
    )

    for audit in config_audits:
        activities.append(
            {
                "id": f"config-{audit.org_id}-{audit.node_id}-{audit.version}",
                "type": "config",
                "description": f"Config updated for {audit.node_id}",
                "timestamp": audit.changed_at.isoformat() if audit.changed_at else None,
                "status": "info",
                "teamName": audit.node_id if audit.node_id != org_id else None,
            }
        )

    # Get recent token events
    token_events = (
        session.query(TokenAudit)
        .filter(TokenAudit.org_id == org_id)
        .order_by(desc(TokenAudit.event_at))
        .limit(limit // 2)
        .all()
    )

    for event in token_events:
        if event.event_type == "issued":
            activities.append(
                {
                    "id": f"token-{event.id}",
                    "type": "token",
                    "description": f"New token issued for {event.team_node_id}",
                    "timestamp": event.event_at.isoformat() if event.event_at else None,
                    "status": "info",
                    "teamName": event.team_node_id,
                }
            )

    # Sort by timestamp and limit
    activities.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    activities = activities[:limit]

    ADMIN_ACTIONS_TOTAL.labels("get_org_activity", "ok").inc()

    return {
        "activities": activities,
        "total": len(activities),
    }


@router.get("/orgs/{org_id}/pending")
def admin_get_pending_items(
    org_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Get counts of pending items that need attention."""
    from datetime import timedelta

    from sqlalchemy import and_, func

    # Pending remediations (agent runs awaiting approval)
    from src.db.models import AgentRun, PendingConfigChange, TeamToken

    pending_remediations = (
        session.query(func.count(AgentRun.id))
        .filter(and_(AgentRun.org_id == org_id, AgentRun.status == "awaiting_approval"))
        .scalar()
        or 0
    )

    # Pending config changes
    pending_config = (
        session.query(func.count(PendingConfigChange.id))
        .filter(
            and_(
                PendingConfigChange.org_id == org_id,
                PendingConfigChange.status == "pending",
            )
        )
        .scalar()
        or 0
    )

    # Expiring tokens (expires within 7 days)
    seven_days_from_now = datetime.utcnow() + timedelta(days=7)
    expiring_tokens = (
        session.query(func.count(TeamToken.token_id))
        .filter(
            and_(
                TeamToken.org_id == org_id,
                TeamToken.revoked_at.is_(None),
                TeamToken.expires_at.isnot(None),
                TeamToken.expires_at <= seven_days_from_now,
                TeamToken.expires_at > datetime.utcnow(),
            )
        )
        .scalar()
        or 0
    )

    ADMIN_ACTIONS_TOTAL.labels("get_pending_items", "ok").inc()

    return {
        "remediations": pending_remediations,
        "configChanges": pending_config,
        "expiringTokens": expiring_tokens,
    }


@router.get("/orgs/{org_id}/health")
def admin_get_system_health(
    org_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """Get system health status for services and integrations."""
    from src.db.models import Integration

    # Get all integrations for the org
    integrations = session.query(Integration).filter(Integration.org_id == org_id).all()

    integration_status = []
    for integration in integrations:
        status_map = {
            "connected": "connected",
            "error": "error",
            "disconnected": "not_configured",
        }
        integration_status.append(
            {
                "name": integration.integration_type,
                "status": status_map.get(integration.status, "not_configured"),
                "icon": integration.integration_type,
            }
        )

    # System services health (hardcoded for now - could be enhanced with actual health checks)
    services = [
        {
            "name": "Agent Service",
            "status": "healthy",
            "lastCheck": datetime.utcnow().isoformat(),
        },
        {
            "name": "Config Service",
            "status": "healthy",
            "lastCheck": datetime.utcnow().isoformat(),
        },
        {
            "name": "Orchestrator",
            "status": "healthy",
            "lastCheck": datetime.utcnow().isoformat(),
        },
        {
            "name": "Web UI",
            "status": "healthy",
            "lastCheck": datetime.utcnow().isoformat(),
        },
    ]

    ADMIN_ACTIONS_TOTAL.labels("get_system_health", "ok").inc()

    return {
        "services": services,
        "integrations": integration_status,
    }


# =============================================================================
# Org Admin Token Management
# =============================================================================


@router.post("/orgs/{org_id}/admin-tokens", response_model=IssueTokenResponse)
def admin_issue_org_admin_token(
    org_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    x_admin_actor: str = Header(default="admin", convert_underscores=False),
):
    """Issue a new org admin token.

    Only super-admins (global admin token) can issue org admin tokens.
    Org admins cannot issue new admin tokens for their own org.
    """
    # Only super-admin can issue org admin tokens
    if principal.org_id is not None:
        raise HTTPException(
            status_code=403, detail="Only super-admin can issue org admin tokens"
        )

    from src.db.repository import issue_org_admin_token

    pepper = get_token_pepper()
    token = issue_org_admin_token(
        session,
        org_id=org_id,
        issued_by=x_admin_actor,
        pepper=pepper,
    )
    ADMIN_ACTIONS_TOTAL.labels("issue_org_admin_token", "ok").inc()
    audit_logger().info(
        "admin_issue_org_admin_token",
        audit=True,
        org_id=org_id,
        issued_by=x_admin_actor,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return IssueTokenResponse(token=token, issued_at=datetime.utcnow())


@router.post("/orgs/{org_id}/admin-tokens/{token_id}/revoke")
def admin_revoke_org_admin_token(
    org_id: str,
    token_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    x_admin_actor: str = Header(default="admin", convert_underscores=False),
):
    """Revoke an org admin token.

    Can be done by super-admin or by another org admin of the same org.
    """
    # Super-admin can revoke any, org admin can only revoke their own org's tokens
    if principal.org_id is not None and principal.org_id != org_id:
        raise HTTPException(
            status_code=403, detail="Cannot revoke tokens for other organizations"
        )

    from src.db.repository import revoke_org_admin_token

    revoke_org_admin_token(
        session, org_id=org_id, token_id=token_id, revoked_by=x_admin_actor
    )
    ADMIN_ACTIONS_TOTAL.labels("revoke_org_admin_token", "ok").inc()
    audit_logger().info(
        "admin_revoke_org_admin_token",
        audit=True,
        org_id=org_id,
        token_id=token_id,
        revoked_by=x_admin_actor,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return {"status": "ok"}


@router.get("/orgs/{org_id}/admin-tokens", response_model=List[TokenRow])
def admin_list_org_admin_tokens(
    org_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    """List all admin tokens for an organization.

    Can be viewed by super-admin or org admin of the same org.
    """
    # Super-admin can list any, org admin can only list their own org's tokens
    if principal.org_id is not None and principal.org_id != org_id:
        raise HTTPException(
            status_code=403, detail="Cannot view tokens for other organizations"
        )

    from src.db.repository import list_org_admin_tokens

    rows = list_org_admin_tokens(session, org_id=org_id)
    ADMIN_ACTIONS_TOTAL.labels("list_org_admin_tokens", "ok").inc()
    audit_logger().info(
        "admin_list_org_admin_tokens",
        audit=True,
        org_id=org_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
    )
    return [
        TokenRow(
            token_id=r.token_id,
            issued_at=r.issued_at,
            revoked_at=r.revoked_at,
            issued_by=r.issued_by,
        )
        for r in rows
    ]


@router.get(
    "/orgs/{org_id}/teams/{team_node_id}/knowledge/edges",
    response_model=List[KnowledgeEdgeRow],
)
def admin_list_knowledge_edges(
    org_id: str,
    team_node_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    limit: int = 200,
):
    rows = (
        session.query(KnowledgeEdge)
        .filter(
            KnowledgeEdge.org_id == org_id, KnowledgeEdge.team_node_id == team_node_id
        )
        .order_by(KnowledgeEdge.created_at.desc())
        .limit(limit)
        .all()
    )
    ADMIN_ACTIONS_TOTAL.labels("list_knowledge_edges", "ok").inc()
    audit_logger().info(
        "admin_list_knowledge_edges",
        audit=True,
        org_id=org_id,
        team_node_id=team_node_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
        count=len(rows),
    )
    return [
        KnowledgeEdgeRow(
            entity=r.entity,
            relationship=r.relationship,
            target=r.target,
            source=r.source,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/orgs/{org_id}/teams/{team_node_id}/knowledge/edges", response_model=dict)
def admin_upsert_knowledge_edges(
    org_id: str,
    team_node_id: str,
    edges: List[KnowledgeEdgeIn],
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    upserted = 0
    for e in edges or []:
        entity = (e.entity or "").strip()
        rel = (e.relationship or "").strip()
        target = (e.target or "").strip()
        if not entity or not rel or not target:
            continue

        row = (
            session.query(KnowledgeEdge)
            .filter(
                KnowledgeEdge.org_id == org_id,
                KnowledgeEdge.team_node_id == team_node_id,
                KnowledgeEdge.entity == entity,
                KnowledgeEdge.relationship == rel,
                KnowledgeEdge.target == target,
            )
            .one_or_none()
        )
        if row is None:
            session.add(
                KnowledgeEdge(
                    org_id=org_id,
                    team_node_id=team_node_id,
                    entity=entity,
                    relationship=rel,
                    target=target,
                    source=e.source,
                )
            )
        else:
            row.source = e.source
        upserted += 1

    ADMIN_ACTIONS_TOTAL.labels("upsert_knowledge_edges", "ok").inc()
    audit_logger().info(
        "admin_upsert_knowledge_edges",
        audit=True,
        org_id=org_id,
        team_node_id=team_node_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
        count=upserted,
    )
    return {"status": "ok", "upserted": upserted}


@router.get(
    "/orgs/{org_id}/teams/{team_node_id}/knowledge/docs",
    response_model=List[KnowledgeDocRow],
)
def admin_list_knowledge_docs(
    org_id: str,
    team_node_id: str,
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
    limit: int = 200,
):
    rows = (
        session.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.org_id == org_id,
            KnowledgeDocument.team_node_id == team_node_id,
        )
        .order_by(KnowledgeDocument.updated_at.desc())
        .limit(limit)
        .all()
    )
    ADMIN_ACTIONS_TOTAL.labels("list_knowledge_docs", "ok").inc()
    audit_logger().info(
        "admin_list_knowledge_docs",
        audit=True,
        org_id=org_id,
        team_node_id=team_node_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
        count=len(rows),
    )
    return [
        KnowledgeDocRow(
            doc_id=r.doc_id,
            title=r.title,
            content=r.content,
            source_type=r.source_type,
            source_id=r.source_id,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/orgs/{org_id}/teams/{team_node_id}/knowledge/docs", response_model=dict)
def admin_upsert_knowledge_docs(
    org_id: str,
    team_node_id: str,
    docs: List[KnowledgeDocIn],
    principal: AdminPrincipal = Depends(require_admin),
    session: Session = Depends(get_db),
):
    upserted = 0
    for d in docs or []:
        doc_id = (d.doc_id or "").strip()
        if not doc_id:
            continue
        row = (
            session.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.org_id == org_id,
                KnowledgeDocument.team_node_id == team_node_id,
                KnowledgeDocument.doc_id == doc_id,
            )
            .one_or_none()
        )
        if row is None:
            session.add(
                KnowledgeDocument(
                    org_id=org_id,
                    team_node_id=team_node_id,
                    doc_id=doc_id,
                    title=d.title,
                    content=d.content,
                    source_type=d.source_type,
                    source_id=d.source_id,
                )
            )
        else:
            row.title = d.title
            row.content = d.content
            row.source_type = d.source_type
            row.source_id = d.source_id
        upserted += 1

    ADMIN_ACTIONS_TOTAL.labels("upsert_knowledge_docs", "ok").inc()
    audit_logger().info(
        "admin_upsert_knowledge_docs",
        audit=True,
        org_id=org_id,
        team_node_id=team_node_id,
        auth_kind=principal.auth_kind,
        actor=principal.email or principal.subject,
        count=upserted,
    )
    return {"status": "ok", "upserted": upserted}
