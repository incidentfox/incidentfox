"""
Hierarchical Configuration API Routes (v2)

Provides REST API for managing node configurations with inheritance.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.config_cache import get_config_cache
from ...core.hierarchical_config import (
    check_locked_fields,
    get_fields_requiring_approval,
    get_full_default_config,
)
from ...core.security import get_token_pepper
from ...db import config_repository as repo
from ...db.models import OrgSettings
from ...db.session import get_db
from ...services.config_service_rds import ConfigServiceRDS
from ..auth import AdminPrincipal, authenticate_team_request, require_admin

logger = structlog.get_logger(__name__)


# =============================================================================
# Authentication Helpers
# =============================================================================


def _check_visitor_write_access(authorization: str) -> None:
    """
    Check if the authorization header contains a visitor token.

    Note: Visitor write access is now ALLOWED for the playground demo.
    Visitors can configure integrations and agents to try out the product.
    """
    # Visitors are now allowed to write for playground demo
    pass


def _resolve_team_identity(
    authorization: str,
    x_org_id: Optional[str],
    x_team_node_id: Optional[str],
    session: Session,
) -> Tuple[str, str]:
    """
    Resolve team identity from either Bearer token or headers.

    Supports two auth methods:
    1. Bearer token (v1 style): Parses token to get org_id and team_node_id
    2. Headers (v2 style): Uses X-Org-Id and X-Team-Node-Id headers

    Returns: (org_id, team_node_id)
    """
    # Method 1: Try Bearer token first (v1 compatibility)
    if authorization and authorization.strip():
        try:
            auth_result = authenticate_team_request(authorization, session=session)
            auth_kind, oidc_principal, raw = auth_result

            if auth_kind == "team_token":
                team_mode = (
                    (os.getenv("TEAM_AUTH_MODE", "token") or "token").strip().lower()
                )
                pepper = get_token_pepper() if team_mode in ("token", "both") else None
                svc = ConfigServiceRDS(pepper=pepper, cache=get_config_cache())
                principal = svc.authenticate(session, raw)
                return principal.org_id, principal.team_node_id
            elif auth_kind == "impersonation" and oidc_principal:
                if oidc_principal.org_id and oidc_principal.team_node_id:
                    return oidc_principal.org_id, oidc_principal.team_node_id
            elif auth_kind == "oidc" and oidc_principal:
                if oidc_principal.org_id and oidc_principal.team_node_id:
                    return oidc_principal.org_id, oidc_principal.team_node_id
            elif auth_kind == "visitor" and oidc_principal:
                if oidc_principal.org_id and oidc_principal.team_node_id:
                    return oidc_principal.org_id, oidc_principal.team_node_id
        except Exception as e:
            logger.debug("bearer_token_auth_failed", error=str(e))

    # Method 2: Use headers (v2 style)
    if x_org_id and x_team_node_id:
        return x_org_id, x_team_node_id

    raise HTTPException(
        status_code=401,
        detail="Authentication required: provide either Bearer token or X-Org-Id/X-Team-Node-Id headers",
    )


def _resolve_identity_with_admin_fallback(
    authorization: str,
    x_org_id: Optional[str],
    x_team_node_id: Optional[str],
    session: Session,
) -> Tuple[str, str]:
    """
    Resolve identity from team token, admin token, or headers.

    Supports three auth methods:
    1. Team Bearer token: Parses token to get org_id and team_node_id
    2. Admin Bearer token: Uses org_id as team_node_id (org root node)
    3. Headers: Uses X-Org-Id and X-Team-Node-Id headers

    When admin token is provided without team_node_id, uses org_id as team_node_id
    (which points to the org root node in the hierarchy where node_id == org_id).

    Returns: (org_id, team_node_id)
    """
    # Try team auth first (includes impersonation JWTs)
    try:
        return _resolve_team_identity(authorization, x_org_id, x_team_node_id, session)
    except HTTPException:
        pass

    # Try admin auth as fallback
    if authorization and authorization.startswith("Bearer "):
        try:
            from src.db.repository import authenticate_org_admin_token

            token = authorization[7:]  # Remove "Bearer " prefix
            pepper = get_token_pepper()
            admin_principal = authenticate_org_admin_token(
                session, bearer=token, pepper=pepper
            )

            # Admin accessing settings - use org root node
            # The org node has node_id == org_id and is the root of the hierarchy
            logger.info(
                "admin_token_using_org_root_node", org_id=admin_principal.org_id
            )
            return admin_principal.org_id, admin_principal.org_id
        except Exception as e:
            logger.debug("admin_token_auth_failed", error=str(e))

    raise HTTPException(
        status_code=401,
        detail="Authentication required: provide either Bearer token or X-Org-Id/X-Team-Node-Id headers",
    )


# =============================================================================
# Request/Response Models
# =============================================================================


class ConfigPatchRequest(BaseModel):
    """Request to update configuration (always performs deep merge)."""

    config: Dict[str, Any] = Field(
        ..., description="Configuration changes to merge into existing config"
    )
    reason: Optional[str] = Field(None, description="Reason for the change")


class ConfigResponse(BaseModel):
    """Configuration response."""

    node_id: str
    node_type: str
    config: Dict[str, Any]
    version: int
    updated_at: Optional[datetime]
    updated_by: Optional[str]


class EffectiveConfigResponse(BaseModel):
    """Effective (merged) configuration response."""

    node_id: str
    effective_config: Dict[str, Any]
    computed_at: Optional[datetime]
    hierarchy: List[str]


class ValidationResponse(BaseModel):
    """Validation result response."""

    node_id: str
    valid: bool
    missing_required: List[Dict[str, Any]]
    errors: List[str]


class FieldDefinitionResponse(BaseModel):
    """Field definition response."""

    path: str
    field_type: str
    required: bool
    default_value: Optional[Any]
    locked_at_level: Optional[str]
    requires_approval: bool
    display_name: Optional[str]
    description: Optional[str]
    category: Optional[str]
    allowed_values: Optional[List[Any]]


class ConfigHistoryResponse(BaseModel):
    """Configuration history entry."""

    version: int
    changed_at: datetime
    changed_by: Optional[str]
    change_reason: Optional[str]
    change_diff: Optional[Dict[str, Any]]


class RequiredFieldsResponse(BaseModel):
    """List of required fields that need to be configured."""

    node_id: str
    missing: List[Dict[str, Any]]
    total_required: int
    configured: int


class EffectiveTreeInfo(BaseModel):
    """Information about a knowledge tree in the effective tree list."""

    tree_name: str
    level: str  # "org", "group", "team"
    node_name: str
    node_id: str
    inherited: bool


class EffectiveTreesResponse(BaseModel):
    """Response containing all effective knowledge trees for a team."""

    trees: List[EffectiveTreeInfo]
    team_node_id: str


# =============================================================================
# Router
# =============================================================================

router = APIRouter(prefix="/api/v1/config", tags=["config"])


# =============================================================================
# Admin Endpoints
# =============================================================================


@router.get("/defaults", response_model=Dict[str, Any])
async def get_default_config(db: Session = Depends(get_db)):
    """Get the system default configuration with integration schemas from DB."""
    return get_full_default_config(db=db)


@router.get("/orgs/{org_id}/nodes/{node_id}/raw", response_model=ConfigResponse)
async def get_raw_config(
    org_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Get raw configuration for a node (overrides only, not merged).

    This shows only what's explicitly configured at this level.
    """
    config = repo.get_node_configuration(db, org_id, node_id)

    if not config:
        raise HTTPException(status_code=404, detail="Node configuration not found")

    return ConfigResponse(
        node_id=config.node_id,
        node_type=config.node_type,
        config=config.config_json,
        version=config.version,
        updated_at=config.updated_at,
        updated_by=config.updated_by,
    )


@router.get(
    "/orgs/{org_id}/nodes/{node_id}/effective", response_model=EffectiveConfigResponse
)
async def get_effective_config(
    org_id: str,
    node_id: str,
    force_refresh: bool = Query(
        False, description="Force recomputation of cached config"
    ),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Get effective (merged) configuration for a node.

    This is the actual configuration that will be used at runtime,
    computed by merging the hierarchy: defaults → org → team → sub-team.
    """
    try:
        effective = repo.compute_and_cache_effective_config(
            db, org_id, node_id, force=force_refresh
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    hierarchy = repo.get_node_hierarchy(db, org_id, node_id)
    config = repo.get_node_configuration(db, org_id, node_id)

    return EffectiveConfigResponse(
        node_id=node_id,
        effective_config=effective,
        computed_at=config.effective_config_computed_at if config else None,
        hierarchy=hierarchy,
    )


@router.patch("/orgs/{org_id}/nodes/{node_id}", response_model=ConfigResponse)
async def update_config(
    org_id: str,
    node_id: str,
    body: ConfigPatchRequest,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Update configuration for a node.

    By default, deep merges the patch with existing config.
    Set merge=false to replace entirely.
    """
    # Get or create node configuration
    config = repo.get_node_configuration(db, org_id, node_id)
    if not config:
        # Auto-create config if it doesn't exist (same as team endpoint behavior)
        # Infer node type from OrgNode table
        from ..db.models import OrgNode

        node = (
            db.query(OrgNode)
            .filter(
                OrgNode.org_id == org_id,
                OrgNode.node_id == node_id,
            )
            .first()
        )
        if not node:
            raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

        config = repo.get_or_create_node_configuration(
            db, org_id, node_id, node.node_type
        )

    # Check locked fields
    db_fields = repo.get_field_definitions(db)
    field_defs = repo.convert_db_to_field_definitions(db_fields)

    locked_errors = check_locked_fields(
        body.config,
        config.config_json,
        field_defs,
        config.node_type,
    )

    if locked_errors:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Cannot modify locked fields",
                "errors": locked_errors,
            },
        )

    # Check if approval is required
    approval_fields = get_fields_requiring_approval(
        body.config,
        config.config_json,
        field_defs,
    )

    # TODO: If approval required, create pending change instead
    # For now, allow direct changes

    try:
        updated_config, diff = repo.update_node_configuration(
            db,
            org_id,
            node_id,
            body.config,
            updated_by=admin.subject if hasattr(admin, "subject") else "admin",
            change_reason=body.reason,
        )

        # Invalidate cache for this node and descendants
        repo.invalidate_config_cache(db, org_id, node_id, cascade=True)

        db.commit()

        return ConfigResponse(
            node_id=updated_config.node_id,
            node_type=updated_config.node_type,
            config=updated_config.config_json,
            version=updated_config.version,
            updated_at=updated_config.updated_at,
            updated_by=updated_config.updated_by,
        )

    except ValueError as e:
        # Dependency validation errors or other validation failures
        db.rollback()
        error_msg = str(e)
        if "Dependency validation failed" in error_msg:
            raise HTTPException(
                status_code=400,
                detail={"error": "dependency_validation_failed", "message": error_msg},
            )
        else:
            raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/orgs/{org_id}/nodes/{node_id}/validate", response_model=ValidationResponse
)
async def validate_config(
    org_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """
    Validate a node's configuration.

    Checks for missing required fields and validation errors.
    """
    try:
        result = repo.validate_node_config(db, org_id, node_id)
        db.commit()

        return ValidationResponse(
            node_id=node_id,
            valid=result["valid"],
            missing_required=result["missing_required"],
            errors=result["errors"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/orgs/{org_id}/nodes/{node_id}/history", response_model=List[ConfigHistoryResponse]
)
async def get_config_history(
    org_id: str,
    node_id: str,
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """Get configuration change history for a node."""
    history = repo.get_config_history(db, org_id, node_id, limit)

    return [
        ConfigHistoryResponse(
            version=h.version,
            changed_at=h.changed_at,
            changed_by=h.changed_by,
            change_reason=h.change_reason,
            change_diff=h.change_diff,
        )
        for h in history
    ]


@router.post(
    "/orgs/{org_id}/nodes/{node_id}/rollback/{version}", response_model=ConfigResponse
)
async def rollback_config(
    org_id: str,
    node_id: str,
    version: int,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """Rollback configuration to a specific version."""
    try:
        config, diff = repo.rollback_to_version(
            db,
            org_id,
            node_id,
            version,
            rolled_back_by=admin.subject if hasattr(admin, "subject") else "admin",
        )

        repo.invalidate_config_cache(db, org_id, node_id, cascade=True)
        db.commit()

        return ConfigResponse(
            node_id=config.node_id,
            node_type=config.node_type,
            config=config.config_json,
            version=config.version,
            updated_at=config.updated_at,
            updated_by=config.updated_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orgs/{org_id}/validation-status", response_model=List[Dict[str, Any]])
async def get_org_validation_status(
    org_id: str,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """Get validation status for all nodes in an organization."""
    return repo.get_nodes_with_missing_config(db, org_id)


# =============================================================================
# Field Definitions Endpoints
# =============================================================================


@router.get("/field-definitions", response_model=List[FieldDefinitionResponse])
async def get_field_definitions(
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db),
):
    """
    Get configuration field definitions.

    These define what configuration fields exist, their types,
    whether they're required, etc.
    """
    fields = repo.get_field_definitions(db, category)

    return [
        FieldDefinitionResponse(
            path=f.path,
            field_type=f.field_type,
            required=f.required,
            default_value=f.default_value,
            locked_at_level=f.locked_at_level,
            requires_approval=f.requires_approval,
            display_name=f.display_name,
            description=f.description,
            category=f.category,
            allowed_values=f.allowed_values,
        )
        for f in fields
    ]


@router.get("/schema")
async def get_config_schema():
    """
    Get the full configuration schema.

    Returns a JSON schema describing all available configuration options.
    """
    # This could be generated from field definitions
    # For now, return a simplified version
    return {
        "type": "object",
        "properties": {
            "agents": {
                "type": "object",
                "description": "Agent configurations",
            },
            "tools": {
                "type": "object",
                "description": "Tool configurations",
            },
            "mcps": {
                "type": "object",
                "description": "MCP server configurations",
            },
            "integrations": {
                "type": "object",
                "description": "Integration configurations",
            },
            "runtime": {
                "type": "object",
                "description": "Runtime settings",
            },
        },
    }


# =============================================================================
# Team-Facing Endpoints
# =============================================================================


@router.get("/me", response_model=EffectiveConfigResponse)
@router.get("/me/effective", response_model=EffectiveConfigResponse)
async def get_my_config(
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
    x_org_id: Optional[str] = Header(default=None),
    x_team_node_id: Optional[str] = Header(default=None),
):
    """
    Get effective configuration for the current team.

    This is the merged configuration that will be used for agent runs.

    Auth: Supports both Bearer token (v1 style) and X-Org-Id/X-Team-Node-Id headers (v2 style).

    Note: /me/effective is an alias for backwards compatibility.
    """
    org_id, team_node_id = _resolve_team_identity(
        authorization, x_org_id, x_team_node_id, db
    )

    effective = repo.get_effective_config(db, org_id, team_node_id)
    hierarchy = repo.get_node_hierarchy(db, org_id, team_node_id)
    config = repo.get_node_configuration(db, org_id, team_node_id)

    return EffectiveConfigResponse(
        node_id=team_node_id,
        effective_config=effective,
        computed_at=config.effective_config_computed_at if config else None,
        hierarchy=hierarchy,
    )


@router.get("/me/required-fields", response_model=RequiredFieldsResponse)
async def get_my_required_fields(
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
    x_org_id: Optional[str] = Header(default=None),
    x_team_node_id: Optional[str] = Header(default=None),
):
    """
    Get list of required fields that need to be configured.

    Teams should use this to know what configuration they need to provide.

    Auth: Supports both Bearer token (v1 style) and X-Org-Id/X-Team-Node-Id headers (v2 style).
    """
    org_id, team_node_id = _resolve_team_identity(
        authorization, x_org_id, x_team_node_id, db
    )

    result = repo.validate_node_config(db, org_id, team_node_id)
    db.commit()

    # Count total required fields
    all_fields = repo.get_field_definitions(db)
    total_required = sum(1 for f in all_fields if f.required)

    return RequiredFieldsResponse(
        node_id=team_node_id,
        missing=result["missing_required"],
        total_required=total_required,
        configured=total_required - len(result["missing_required"]),
    )


@router.get("/me/raw")
async def get_my_raw_config(
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
    x_org_id: Optional[str] = Header(default=None),
    x_team_node_id: Optional[str] = Header(default=None),
):
    """
    Get raw configuration hierarchy for the current team.

    Returns lineage and per-node configs for debugging/understanding inheritance.

    Auth: Supports both Bearer token (v1 style) and X-Org-Id/X-Team-Node-Id headers (v2 style).
    """
    org_id, team_node_id = _resolve_team_identity(
        authorization, x_org_id, x_team_node_id, db
    )

    hierarchy = repo.get_node_hierarchy(db, org_id, team_node_id)
    configs = {}

    for node_id in hierarchy:
        config = repo.get_node_configuration(db, org_id, node_id)
        if config:
            configs[node_id] = config.config_json

    return {
        "lineage": hierarchy,
        "configs": configs,
    }


@router.get("/me/effective-trees", response_model=EffectiveTreesResponse)
async def get_my_effective_trees(
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
    x_org_id: Optional[str] = Header(default=None),
    x_team_node_id: Optional[str] = Header(default=None),
):
    """
    Get all knowledge trees effective for the current team.

    Walks the org hierarchy and collects knowledge_tree configs from each level.
    Trees are listed from most specific (team) to most general (org).

    Auth: Supports both Bearer token (v1 style) and X-Org-Id/X-Team-Node-Id headers (v2 style).
    """
    from ...db.models import OrgNode

    org_id, team_node_id = _resolve_team_identity(
        authorization, x_org_id, x_team_node_id, db
    )

    # Get hierarchy (from org root to team)
    hierarchy_ids = repo.get_node_hierarchy(db, org_id, team_node_id)

    trees = []
    for node_id in hierarchy_ids:
        # Get node info
        node = (
            db.query(OrgNode)
            .filter(OrgNode.org_id == org_id, OrgNode.node_id == node_id)
            .first()
        )
        if not node:
            continue

        # Get config for this node
        config = repo.get_node_configuration(db, org_id, node_id)
        if not config:
            continue

        # Check if this node has a knowledge_tree configured
        knowledge_tree = config.config_json.get("knowledge_tree")
        if knowledge_tree:
            trees.append(
                EffectiveTreeInfo(
                    tree_name=knowledge_tree,
                    level=(
                        node.node_type.value
                        if hasattr(node.node_type, "value")
                        else str(node.node_type)
                    ),
                    node_name=node.name or node_id,
                    node_id=node_id,
                    inherited=node_id != team_node_id,
                )
            )

    # Reverse so most specific (team) comes first
    trees.reverse()

    return EffectiveTreesResponse(trees=trees, team_node_id=team_node_id)


@router.get("/me/org-settings")
async def get_my_org_settings(
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
    x_org_id: Optional[str] = Header(default=None),
    x_team_node_id: Optional[str] = Header(default=None),
):
    """
    Get organization settings for the current team's organization.

    Returns settings like telemetry opt-in/out.
    Supports both team and admin tokens (admin uses org root node).
    """
    org_id, team_node_id = _resolve_identity_with_admin_fallback(
        authorization, x_org_id, x_team_node_id, db
    )

    settings = db.query(OrgSettings).filter(OrgSettings.org_id == org_id).first()

    if not settings:
        # Return defaults for new orgs
        return {
            "telemetry_enabled": True,
            "created_at": None,
            "updated_at": None,
            "updated_by": None,
        }

    return {
        "telemetry_enabled": settings.telemetry_enabled,
        "created_at": settings.created_at.isoformat() if settings.created_at else None,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
        "updated_by": settings.updated_by,
    }


@router.put("/me/org-settings")
async def update_my_org_settings(
    body: dict,
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
    x_org_id: Optional[str] = Header(default=None),
    x_team_node_id: Optional[str] = Header(default=None),
):
    """
    Update organization settings for the current team's organization.

    Supports both team and admin tokens (admin uses org root node).
    Only org admins should be able to call this (TODO: add permission check).
    """
    org_id, team_node_id = _resolve_identity_with_admin_fallback(
        authorization, x_org_id, x_team_node_id, db
    )

    settings = db.query(OrgSettings).filter(OrgSettings.org_id == org_id).first()

    if not settings:
        # Create new settings
        settings = OrgSettings(
            org_id=org_id,
            telemetry_enabled=body.get("telemetry_enabled", True),
        )
        db.add(settings)
    else:
        # Update existing
        if "telemetry_enabled" in body:
            settings.telemetry_enabled = body["telemetry_enabled"]
        settings.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(settings)

    return {
        "telemetry_enabled": settings.telemetry_enabled,
        "created_at": settings.created_at.isoformat() if settings.created_at else None,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
        "updated_by": settings.updated_by,
    }


def validate_agent_disable(
    agent_id: str,
    current_effective_config: Dict[str, Any],
    new_config_patch: Dict[str, Any],
) -> Optional[str]:
    """
    Validate that disabling an agent won't break the system.

    Returns error message if validation fails, None if valid.
    """
    agents = current_effective_config.get("agents", {})
    if agent_id not in agents:
        return None  # Agent doesn't exist, nothing to validate

    agent = agents[agent_id]
    is_being_disabled = False

    # Check if this agent is being disabled
    if "agents" in new_config_patch and agent_id in new_config_patch["agents"]:
        agent_patch = new_config_patch["agents"][agent_id]
        if "enabled" in agent_patch and agent_patch["enabled"] is False:
            is_being_disabled = True

    if not is_being_disabled:
        return None  # Not being disabled, no validation needed

    # Rule 1: Check if this agent is used as a sub-agent by any other ENABLED agent
    dependent_agents = []
    for other_id, other_agent in agents.items():
        if other_id == agent_id:
            continue

        # Check if this other agent is enabled (consider patches)
        other_enabled = other_agent.get("enabled", True)
        if "agents" in new_config_patch and other_id in new_config_patch["agents"]:
            other_patch = new_config_patch["agents"][other_id]
            if "enabled" in other_patch:
                other_enabled = other_patch["enabled"]

        if not other_enabled:
            continue  # Other agent is disabled, ignore it

        # Check if other agent uses this agent as sub-agent
        sub_agents = other_agent.get("sub_agents", {})
        if isinstance(sub_agents, dict) and sub_agents.get(agent_id) is True:
            dependent_agents.append(other_agent.get("name", other_id))

    if dependent_agents:
        return (
            f"Cannot disable '{agent.get('name', agent_id)}' because it is used as a sub-agent by: "
            f"{', '.join(dependent_agents)}. Please remove it from those agents first."
        )

    # Rule 2: Check if this is the last entrance agent (orchestrator)
    # An entrance agent is one that has sub_agents but is not used by anyone
    agent_sub_agents = agent.get("sub_agents", {})
    has_sub_agents = isinstance(agent_sub_agents, dict) and any(
        v is True for v in agent_sub_agents.values()
    )

    if has_sub_agents:
        # Check if any other ENABLED agent is an entrance agent
        other_entrance_agents = []
        for other_id, other_agent in agents.items():
            if other_id == agent_id:
                continue

            # Check if this other agent is enabled
            other_enabled = other_agent.get("enabled", True)
            if "agents" in new_config_patch and other_id in new_config_patch["agents"]:
                other_patch = new_config_patch["agents"][other_id]
                if "enabled" in other_patch:
                    other_enabled = other_patch["enabled"]

            if not other_enabled:
                continue

            # Check if it's an entrance agent (has sub-agents, not used by others)
            other_sub_agents = other_agent.get("sub_agents", {})
            other_has_subs = isinstance(other_sub_agents, dict) and any(
                v is True for v in other_sub_agents.values()
            )

            if not other_has_subs:
                continue  # Not an orchestrator

            # Check if used by anyone
            is_used = False
            for check_id, check_agent in agents.items():
                if check_id == other_id:
                    continue
                check_subs = check_agent.get("sub_agents", {})
                if isinstance(check_subs, dict) and check_subs.get(other_id) is True:
                    is_used = True
                    break

            if not is_used:
                other_entrance_agents.append(other_id)

        if not other_entrance_agents:
            return (
                f"Cannot disable '{agent.get('name', agent_id)}' because it is the last entrance agent. "
                f"The system needs at least one entrance agent (orchestrator) to function."
            )

    return None


@router.patch("/me", response_model=ConfigResponse)
async def update_my_config(
    body: ConfigPatchRequest,
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
    x_org_id: Optional[str] = Header(default=None),
    x_team_node_id: Optional[str] = Header(default=None),
):
    """
    Update configuration for the current team.

    Teams can only modify non-locked fields.

    Auth: Supports both Bearer token (v1 style) and X-Org-Id/X-Team-Node-Id headers (v2 style).
    """
    # Visitors cannot modify configuration
    _check_visitor_write_access(authorization)

    org_id, team_node_id = _resolve_team_identity(
        authorization, x_org_id, x_team_node_id, db
    )

    config = repo.get_node_configuration(db, org_id, team_node_id)

    if not config:
        # Create team config if it doesn't exist
        config = repo.get_or_create_node_configuration(db, org_id, team_node_id, "team")

    # Check locked fields
    db_fields = repo.get_field_definitions(db)
    field_defs = repo.convert_db_to_field_definitions(db_fields)

    locked_errors = check_locked_fields(
        body.config,
        config.config_json,
        field_defs,
        "team",
    )

    if locked_errors:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Cannot modify locked fields",
                "errors": locked_errors,
            },
        )

    # Validate agent enable/disable operations
    if "agents" in body.config:
        from ...db.config_repository import compute_effective_config

        effective_config = compute_effective_config(db, org_id, team_node_id)

        # Check each agent being modified
        agent_errors = []
        for agent_id, agent_patch in body.config["agents"].items():
            error_msg = validate_agent_disable(agent_id, effective_config, body.config)
            if error_msg:
                agent_errors.append(error_msg)

        if agent_errors:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Agent configuration validation failed",
                    "errors": agent_errors,
                },
            )

    try:
        # DEBUG: Log what we're receiving
        logger.info(
            f"🔍 DEBUG - PATCH /api/v1/config/me - org_id={org_id}, team_node_id={team_node_id}"
        )
        logger.info(f"🔍 DEBUG - body.config keys: {list(body.config.keys())}")
        if "mcp_servers" in body.config:
            logger.info(
                f"🔍 DEBUG - mcp_servers in patch: {body.config['mcp_servers']}"
            )
            for mcp_id, mcp_patch in body.config["mcp_servers"].items():
                logger.info(f"🔍 DEBUG - MCP {mcp_id} patch: {mcp_patch}")
                if "enabled_tools" in mcp_patch:
                    logger.info(
                        f"🔍 DEBUG - enabled_tools: {mcp_patch['enabled_tools']} (type: {type(mcp_patch['enabled_tools'])})"
                    )

        updated_config, diff = repo.update_node_configuration(
            db,
            org_id,
            team_node_id,
            body.config,
            updated_by="team",
            change_reason=body.reason,
        )

        # DEBUG: Log what was actually saved
        if "mcp_servers" in updated_config.config_json:
            logger.info("🔍 DEBUG - After merge, saved mcp_servers:")
            for mcp_id, mcp_config in updated_config.config_json["mcp_servers"].items():
                logger.info(
                    f"🔍 DEBUG - MCP {mcp_id} saved enabled_tools: {mcp_config.get('enabled_tools', ['*'])}"
                )

        repo.invalidate_config_cache(db, org_id, team_node_id, cascade=False)
        db.commit()

        return ConfigResponse(
            node_id=updated_config.node_id,
            node_type=updated_config.node_type,
            config=updated_config.config_json,
            version=updated_config.version,
            updated_at=updated_config.updated_at,
            updated_by=updated_config.updated_by,
        )

    except ValueError as e:
        # Dependency validation errors or other validation failures
        db.rollback()
        error_msg = str(e)
        logger.error(
            f"Config update validation failed for org_id={org_id}, team_node_id={team_node_id}: {error_msg}",
            exc_info=True,
        )
        if "Dependency validation failed" in error_msg:
            raise HTTPException(
                status_code=400,
                detail={"error": "dependency_validation_failed", "message": error_msg},
            )
        else:
            raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        db.rollback()
        logger.error(
            f"Config update failed for org_id={org_id}, team_node_id={team_node_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))
