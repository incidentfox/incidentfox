"""Team-level API routes for knowledge, pending changes, and agent runs."""

import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.config_cache import get_config_cache
from ...core.security import get_token_pepper
from ...db.models import (
    AgentRun,
    KnowledgeDocument,
    OrgNode,
    PendingConfigChange,
    TeamOutputConfig,
)
from ...db.session import get_db
from ...services.config_service_rds import ConfigServiceRDS
from ..auth import TeamPrincipal, authenticate_team_request, require_team_auth

logger = structlog.get_logger(__name__)


router = APIRouter(prefix="/api/v1/team", tags=["team"])


# =============================================================================
# Authentication Helpers
# =============================================================================


def _resolve_team_or_admin_identity(
    authorization: str,
    session: Session,
) -> Tuple[str, str]:
    """
    Resolve identity from team or admin Bearer token.

    Supports two auth methods:
    1. Team Bearer token: Parses token to get org_id and team_node_id
    2. Admin Bearer token: Uses org_id as team_node_id (org root node)

    When admin token is provided, uses org_id as team_node_id
    (which points to the org root node in the hierarchy where node_id == org_id).

    Returns: (org_id, team_node_id)
    """
    if not authorization or not authorization.strip():
        raise HTTPException(status_code=401, detail="Authorization header required")

    # Try team auth first
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
        elif auth_kind == "oidc" and oidc_principal:
            if oidc_principal.org_id and oidc_principal.team_node_id:
                return oidc_principal.org_id, oidc_principal.team_node_id
    except Exception as e:
        logger.debug("team_token_auth_failed", error=str(e))

    # Try admin auth as fallback
    if authorization.startswith("Bearer "):
        try:
            from ...db.repository import authenticate_org_admin_token

            token = authorization[7:]  # Remove "Bearer " prefix
            pepper = get_token_pepper()
            admin_principal = authenticate_org_admin_token(
                session, bearer=token, pepper=pepper
            )

            # Admin accessing team endpoint - use org root node
            # The org node has node_id == org_id and is the root of the hierarchy
            logger.info(
                "admin_token_using_org_root_node_for_team_endpoint",
                org_id=admin_principal.org_id,
            )
            return admin_principal.org_id, admin_principal.org_id
        except Exception as e:
            logger.debug("admin_token_auth_failed", error=str(e))

    raise HTTPException(
        status_code=401, detail="Invalid or missing authentication token"
    )


# =============================================================================
# Knowledge Documents
# =============================================================================


class KnowledgeDocumentResponse(BaseModel):
    id: str
    title: Optional[str]
    type: str  # document, url, manual, learned
    source: Optional[str]
    summary: Optional[str]
    content: Optional[str]
    createdAt: str
    createdBy: str
    status: str
    confidence: Optional[int] = None

    class Config:
        from_attributes = True


class KnowledgeDocumentCreate(BaseModel):
    title: str
    content: str
    type: str = "manual"
    source: Optional[str] = None


class ProposedKBChangeResponse(BaseModel):
    id: str
    changeType: str
    document: Dict[str, Any]
    reason: str
    learnedFrom: Optional[str] = None
    proposedAt: str
    status: str


@router.get("/knowledge/documents", response_model=List[KnowledgeDocumentResponse])
async def list_knowledge_documents(
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """List all knowledge documents for the team."""
    docs = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.org_id == team.org_id,
            KnowledgeDocument.team_node_id == team.team_node_id,
        )
        .order_by(KnowledgeDocument.updated_at.desc())
        .all()
    )

    return [
        KnowledgeDocumentResponse(
            id=doc.doc_id,
            title=doc.title,
            type=doc.source_type or "document",
            source=doc.source_id,
            summary=(
                doc.content[:200] + "..." if len(doc.content) > 200 else doc.content
            ),
            content=doc.content,
            createdAt=doc.updated_at.isoformat(),
            createdBy=doc.source_id or "system",
            status="active",
        )
        for doc in docs
    ]


@router.post("/knowledge/documents", response_model=KnowledgeDocumentResponse)
async def create_knowledge_document(
    body: KnowledgeDocumentCreate,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Create a new knowledge document."""
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"

    doc = KnowledgeDocument(
        org_id=team.org_id,
        team_node_id=team.team_node_id,
        doc_id=doc_id,
        title=body.title,
        content=body.content,
        source_type=body.type,
        source_id=body.source,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return KnowledgeDocumentResponse(
        id=doc.doc_id,
        title=doc.title,
        type=doc.source_type or "manual",
        source=doc.source_id,
        summary=doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
        content=doc.content,
        createdAt=doc.updated_at.isoformat(),
        createdBy=team.subject or "user",
        status="active",
    )


@router.delete("/knowledge/documents/{doc_id}")
async def delete_knowledge_document(
    doc_id: str,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Delete a knowledge document."""
    doc = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.org_id == team.org_id,
            KnowledgeDocument.team_node_id == team.team_node_id,
            KnowledgeDocument.doc_id == doc_id,
        )
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    db.commit()

    return {"status": "deleted"}


@router.post("/knowledge/upload", response_model=KnowledgeDocumentResponse)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Upload a document to the knowledge base."""
    content = await file.read()
    text_content = content.decode("utf-8", errors="ignore")

    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    title = file.filename.rsplit(".", 1)[0] if file.filename else "Untitled"

    doc = KnowledgeDocument(
        org_id=team.org_id,
        team_node_id=team.team_node_id,
        doc_id=doc_id,
        title=title,
        content=text_content,
        source_type="document",
        source_id=file.filename,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return KnowledgeDocumentResponse(
        id=doc.doc_id,
        title=doc.title,
        type="document",
        source=file.filename,
        summary=text_content[:200] + "..." if len(text_content) > 200 else text_content,
        content=text_content,
        createdAt=doc.updated_at.isoformat(),
        createdBy=team.subject or "user",
        status="active",
    )


@router.get(
    "/knowledge/proposed-changes", response_model=List[ProposedKBChangeResponse]
)
async def list_proposed_kb_changes(
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """List AI-proposed changes to the knowledge base."""
    changes = (
        db.query(PendingConfigChange)
        .filter(
            PendingConfigChange.org_id == team.org_id,
            PendingConfigChange.node_id == team.team_node_id,
            PendingConfigChange.change_type == "knowledge",
            PendingConfigChange.status == "pending",
        )
        .order_by(PendingConfigChange.requested_at.desc())
        .all()
    )

    return [
        ProposedKBChangeResponse(
            id=str(change.id),
            changeType="add",
            document={
                "title": proposed.get("title", "Untitled"),
                "type": "learned",
                "summary": proposed.get("summary", ""),
            },
            reason=change.reason or "Learned from incident",
            learnedFrom=proposed.get("learned_from"),
            proposedAt=change.requested_at.isoformat(),
            status=change.status,
        )
        for change in changes
        for proposed in [change.proposed_value or {}]
    ]


@router.post("/knowledge/proposed-changes/{change_id}/approve")
async def approve_kb_change(
    change_id: str,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Approve a proposed knowledge change and add it to the knowledge base."""
    change = (
        db.query(PendingConfigChange)
        .filter(
            PendingConfigChange.id == change_id,
            PendingConfigChange.org_id == team.org_id,
            PendingConfigChange.node_id == team.team_node_id,
        )
        .first()
    )

    if not change:
        raise HTTPException(status_code=404, detail="Change not found")

    proposed = change.proposed_value or {}

    # Create the knowledge document
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    doc = KnowledgeDocument(
        org_id=team.org_id,
        team_node_id=team.team_node_id,
        doc_id=doc_id,
        title=proposed.get("title", "Learned Knowledge"),
        content=proposed.get("summary", ""),
        source_type="learned",
        source_id=proposed.get("learned_from"),
    )
    db.add(doc)

    # Mark change as approved
    change.status = "approved"
    change.reviewed_at = datetime.utcnow()
    change.reviewed_by = team.subject or "user"

    db.commit()

    return {"status": "approved", "doc_id": doc_id}


@router.post("/knowledge/proposed-changes/{change_id}/reject")
async def reject_kb_change(
    change_id: str,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Reject a proposed knowledge change."""
    change = (
        db.query(PendingConfigChange)
        .filter(
            PendingConfigChange.id == change_id,
            PendingConfigChange.org_id == team.org_id,
            PendingConfigChange.node_id == team.team_node_id,
        )
        .first()
    )

    if not change:
        raise HTTPException(status_code=404, detail="Change not found")

    change.status = "rejected"
    change.reviewed_at = datetime.utcnow()
    change.reviewed_by = team.subject or "user"

    db.commit()

    return {"status": "rejected"}


# =============================================================================
# Pending Changes (Prompts, MCPs, etc.)
# =============================================================================


class EvidenceItem(BaseModel):
    """Supporting evidence for AI-generated proposals."""

    source_type: str  # 'slack_thread', 'confluence_doc', 'agent_trace', etc.
    source_id: str
    quote: str
    link_hint: Optional[str] = None  # channel name, doc title, or context
    link: Optional[str] = None  # full URL if available


class PendingChangeResponse(BaseModel):
    id: str
    changeType: str
    status: str
    title: str
    description: str
    proposedBy: str
    proposedAt: str
    source: str
    confidence: Optional[float] = None  # 0.0-1.0, from AI pipeline
    evidence: Optional[List[EvidenceItem]] = None  # supporting evidence
    diff: Optional[Dict[str, Any]] = None
    reviewedBy: Optional[str] = None
    reviewedAt: Optional[str] = None
    reviewComment: Optional[str] = None


@router.get("/pending-changes", response_model=List[PendingChangeResponse])
async def list_pending_changes(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """List all pending configuration changes for the team."""
    changes = (
        db.query(PendingConfigChange)
        .filter(
            PendingConfigChange.org_id == team.org_id,
            PendingConfigChange.node_id == team.team_node_id,
        )
        .order_by(PendingConfigChange.requested_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    result = []
    for change in changes:
        proposed = change.proposed_value
        if isinstance(proposed, str):
            import json

            try:
                proposed = json.loads(proposed)
            except (json.JSONDecodeError, ValueError, TypeError):
                proposed = {}
        proposed = proposed or {}

        # Extract confidence and evidence from proposed_value (AI pipeline fields)
        confidence = None
        evidence = None
        source = "manual"

        if isinstance(proposed, dict):
            confidence = proposed.get("confidence")
            raw_evidence = proposed.get("evidence", [])
            if raw_evidence and isinstance(raw_evidence, list):
                evidence = [
                    EvidenceItem(
                        source_type=ev.get("source_type", "unknown"),
                        source_id=ev.get("source_id", ""),
                        quote=ev.get("quote", ""),
                        link_hint=ev.get("link_hint"),
                        link=ev.get("link"),
                    )
                    for ev in raw_evidence
                    if isinstance(ev, dict)
                ]
            # Check source from proposed_value first, then from requested_by
            if proposed.get("source") == "ai_pipeline":
                source = "ai_pipeline"
            elif "ai_pipeline" in (change.requested_by or "").lower():
                source = "ai_pipeline"

        result.append(
            PendingChangeResponse(
                id=str(change.id),
                changeType=change.change_type,
                status=change.status,
                title=(
                    proposed.get("title", f"Change to {change.change_type}")
                    if isinstance(proposed, dict)
                    else f"Change to {change.change_type}"
                ),
                description=change.reason
                or (
                    proposed.get("recommendation", proposed.get("description", ""))
                    if isinstance(proposed, dict)
                    else ""
                ),
                proposedBy=change.requested_by or "AI Pipeline",
                proposedAt=change.requested_at.isoformat(),
                source=source,
                confidence=confidence,
                evidence=evidence,
                diff={
                    "before": change.previous_value,
                    "after": change.proposed_value,
                },
                reviewedBy=change.reviewed_by,
                reviewedAt=(
                    change.reviewed_at.isoformat() if change.reviewed_at else None
                ),
                reviewComment=change.review_comment,
            )
        )
    return result


@router.post("/pending-changes/{change_id}/approve")
async def approve_pending_change(
    change_id: str,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Approve a pending configuration change."""
    change = (
        db.query(PendingConfigChange)
        .filter(
            PendingConfigChange.id == change_id,
            PendingConfigChange.org_id == team.org_id,
            PendingConfigChange.node_id == team.team_node_id,
            PendingConfigChange.status == "pending",
        )
        .first()
    )

    if not change:
        raise HTTPException(
            status_code=404, detail="Change not found or already reviewed"
        )

    proposed = change.proposed_value or {}

    # Apply the change based on type
    if change.change_type == "mcp":
        # Update team's MCP config (new dict-based schema)
        node = (
            db.query(OrgNode)
            .filter(
                OrgNode.org_id == team.org_id,
                OrgNode.node_id == team.team_node_id,
            )
            .first()
        )
        if node and node.config_overrides:
            # New schema: mcp_servers is a dict keyed by MCP ID
            mcp_servers = node.config_overrides.get("mcp_servers", {})
            if not isinstance(mcp_servers, dict):
                mcp_servers = {}

            # Extract MCP ID from proposed config
            mcp_id = proposed.get("id") or proposed.get("name", "").lower().replace(
                " ", "-"
            )
            if not mcp_id:
                raise HTTPException(
                    status_code=400, detail="MCP must have an 'id' or 'name' field"
                )

            # Remove 'id' from proposed (it's now the key)
            mcp_config = {k: v for k, v in proposed.items() if k != "id"}

            # Add to dict
            mcp_servers[mcp_id] = mcp_config
            node.config_overrides = {
                **node.config_overrides,
                "mcp_servers": mcp_servers,
            }

    elif change.change_type == "prompt":
        # Update team's prompt config
        node = (
            db.query(OrgNode)
            .filter(
                OrgNode.org_id == team.org_id,
                OrgNode.node_id == team.team_node_id,
            )
            .first()
        )
        if node:
            prompts = (node.config_overrides or {}).get("agent_prompts", {})
            prompts.update(proposed)
            node.config_overrides = {
                **(node.config_overrides or {}),
                "agent_prompts": prompts,
            }

    change.status = "approved"
    change.reviewed_at = datetime.utcnow()
    change.reviewed_by = team.subject or "user"

    db.commit()

    return {"status": "approved"}


@router.post("/pending-changes/{change_id}/reject")
async def reject_pending_change(
    change_id: str,
    comment: Optional[str] = None,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Reject a pending configuration change."""
    change = (
        db.query(PendingConfigChange)
        .filter(
            PendingConfigChange.id == change_id,
            PendingConfigChange.org_id == team.org_id,
            PendingConfigChange.node_id == team.team_node_id,
            PendingConfigChange.status == "pending",
        )
        .first()
    )

    if not change:
        raise HTTPException(
            status_code=404, detail="Change not found or already reviewed"
        )

    change.status = "rejected"
    change.reviewed_at = datetime.utcnow()
    change.reviewed_by = team.subject or "user"
    change.review_comment = comment

    db.commit()

    return {"status": "rejected"}


# =============================================================================
# Agent Runs
# =============================================================================


class AgentRunResponse(BaseModel):
    id: str
    correlationId: str
    agentName: str
    triggerSource: str
    triggerActor: Optional[str] = None
    triggerMessage: Optional[str] = None
    status: str
    startedAt: str
    completedAt: Optional[str] = None
    durationSeconds: Optional[int] = None
    toolCallsCount: Optional[int] = None
    outputSummary: Optional[str] = None
    errorMessage: Optional[str] = None
    confidence: Optional[int] = None


@router.get("/agent-runs", response_model=List[AgentRunResponse])
async def list_agent_runs(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """List agent runs for the team."""
    runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.org_id == team.org_id,
            AgentRun.team_node_id == team.team_node_id,
        )
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    result = []
    for run in runs:
        duration = None
        if run.completed_at and run.started_at:
            duration = int((run.completed_at - run.started_at).total_seconds())

        result.append(
            AgentRunResponse(
                id=str(run.id),
                correlationId=run.correlation_id or "",
                agentName=run.agent_name or "unknown",
                triggerSource=run.trigger_source or "api",
                triggerActor=run.trigger_actor,
                triggerMessage=run.trigger_message,
                status=run.status,
                startedAt=run.started_at.isoformat(),
                completedAt=run.completed_at.isoformat() if run.completed_at else None,
                durationSeconds=duration,
                toolCallsCount=run.tool_calls_count,
                outputSummary=run.output_summary,
                errorMessage=run.error_message,
                confidence=run.confidence,
            )
        )

    return result


@router.get("/agent-runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: str,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Get details of a specific agent run."""
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == int(run_id),
            AgentRun.org_id == team.org_id,
            AgentRun.team_node_id == team.team_node_id,
        )
        .first()
    )

    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    duration = None
    if run.completed_at and run.started_at:
        duration = int((run.completed_at - run.started_at).total_seconds())

    return AgentRunResponse(
        id=str(run.id),
        correlationId=run.correlation_id or "",
        agentName=run.agent_name or "unknown",
        triggerSource=run.trigger_source or "api",
        triggerActor=run.trigger_actor,
        triggerMessage=run.trigger_message,
        status=run.status,
        startedAt=run.started_at.isoformat(),
        completedAt=run.completed_at.isoformat() if run.completed_at else None,
        durationSeconds=duration,
        toolCallsCount=run.tool_calls_count,
        outputSummary=run.output_summary,
        errorMessage=run.error_message,
        confidence=run.confidence,
    )


# =============================================================================
# Tools Catalog
# =============================================================================


class ToolsCatalogResponse(BaseModel):
    """Response model for tools catalog."""

    tools: List[Dict[str, Any]]
    count: int

    class Config:
        from_attributes = True


@router.get("/tools/catalog", response_model=ToolsCatalogResponse)
async def get_tools_catalog(
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Get complete tools catalog for the team.

    Returns all available tools (built-in + MCP) that can be configured for agents.
    This is configuration data only - no health checks are performed.

    Response includes:
    - Built-in tools (always available)
    - MCP tools (from team's MCP configuration)

    Each tool includes:
    - id: Tool identifier
    - name: Human-readable name
    - description: Tool description
    - category: Tool category (kubernetes, aws, github, etc.)
    - source: "built-in" or "mcp"
    - mcp_server: MCP server ID (only for MCP tools)
    """
    from ...core.tools_catalog import get_tools_catalog
    from ...db.config_repository import get_effective_config

    # Get team's effective configuration
    effective_config = get_effective_config(
        session=db,
        org_id=team.org_id,
        node_id=team.team_node_id,
    )

    # Extract MCP configurations (new flat structure)
    team_mcps = []

    # Get MCP servers from new dict-based structure
    # New schema: mcp_servers is a dict keyed by MCP ID
    mcp_servers_dict = effective_config.get("mcp_servers", {})

    # Convert dict to list for catalog (only enabled MCPs)
    for mcp_id, mcp_config in mcp_servers_dict.items():
        if not isinstance(mcp_config, dict):
            continue

        # Only include enabled MCPs
        if not mcp_config.get("enabled", True):
            continue

        # Add ID to config for catalog
        mcp_with_id = {"id": mcp_id, **mcp_config}

        mcp_type = mcp_config.get("type", "mcp_server")
        # Only include MCP servers (not integrations)
        if mcp_type in ["mcp_server", "tool"]:
            team_mcps.append(mcp_with_id)

    # Get catalog
    catalog = get_tools_catalog(team_mcps)

    return ToolsCatalogResponse(
        tools=catalog["tools"],
        count=catalog["count"],
    )


# =============================================================================
# Output Configuration (Delivery & Notifications)
# =============================================================================


class OutputDestination(BaseModel):
    """Single output destination configuration."""

    type: str  # slack, github, pagerduty, incidentio
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    repo: Optional[str] = None
    config: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class OutputConfigResponse(BaseModel):
    """Response model for team output configuration."""

    default_destinations: List[OutputDestination] = []
    trigger_overrides: Dict[str, str] = {}
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True


class OutputConfigUpdate(BaseModel):
    """Request model for updating output configuration."""

    default_destinations: Optional[List[OutputDestination]] = None
    trigger_overrides: Optional[Dict[str, str]] = None


@router.get("/output-config", response_model=OutputConfigResponse)
async def get_output_config(
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
):
    """
    Get the team's output configuration for agent results.

    Controls where agent outputs are delivered (Slack, GitHub, etc.)
    and trigger-specific routing rules.
    Supports both team and admin tokens (admin uses org root node).
    """
    org_id, team_node_id = _resolve_team_or_admin_identity(authorization, db)

    config = (
        db.query(TeamOutputConfig)
        .filter(
            TeamOutputConfig.org_id == org_id,
            TeamOutputConfig.team_node_id == team_node_id,
        )
        .first()
    )

    if not config:
        # Return defaults if no config exists
        return OutputConfigResponse(
            default_destinations=[],
            trigger_overrides={},
        )

    # Convert raw JSON to typed models
    destinations = []
    if config.default_destinations:
        for dest in config.default_destinations:
            destinations.append(OutputDestination(**dest))

    return OutputConfigResponse(
        default_destinations=destinations,
        trigger_overrides=config.trigger_overrides or {},
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
        updated_by=config.updated_by,
    )


@router.put("/output-config", response_model=OutputConfigResponse)
async def update_output_config(
    body: OutputConfigUpdate,
    db: Session = Depends(get_db),
    authorization: str = Header(default=""),
):
    """
    Update the team's output configuration.

    Allows teams to configure:
    - Default destinations for agent results
    - Trigger-specific routing rules (e.g., Slack -> reply in thread)
    Supports both team and admin tokens (admin uses org root node).
    """
    org_id, team_node_id = _resolve_team_or_admin_identity(authorization, db)

    config = (
        db.query(TeamOutputConfig)
        .filter(
            TeamOutputConfig.org_id == org_id,
            TeamOutputConfig.team_node_id == team_node_id,
        )
        .first()
    )

    if not config:
        # Create new config
        config = TeamOutputConfig(
            org_id=org_id,
            team_node_id=team_node_id,
            default_destinations=[],
            trigger_overrides={},
        )
        db.add(config)

    # Update fields
    if body.default_destinations is not None:
        config.default_destinations = [
            dest.model_dump() for dest in body.default_destinations
        ]

    if body.trigger_overrides is not None:
        config.trigger_overrides = body.trigger_overrides

    config.updated_by = "admin"  # Could be team or admin user
    config.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(config)

    # Convert back to response model
    destinations = []
    if config.default_destinations:
        for dest in config.default_destinations:
            destinations.append(OutputDestination(**dest))

    return OutputConfigResponse(
        default_destinations=destinations,
        trigger_overrides=config.trigger_overrides or {},
        updated_at=config.updated_at.isoformat(),
        updated_by=config.updated_by,
    )


# =============================================================================
# Dashboard Stats & Analytics
# =============================================================================

from datetime import timedelta

from sqlalchemy import case, func


class TeamStatsResponse(BaseModel):
    """Response model for team dashboard statistics."""

    totalRuns: int
    successRate: float
    avgMttdSeconds: Optional[float]  # Average Mean Time To Detect (run duration)
    runsThisWeek: int
    runsPrevWeek: int
    trend: str  # up, down, stable

    class Config:
        from_attributes = True


class AgentPerformanceItem(BaseModel):
    """Performance metrics for a single agent."""

    agent_id: str
    agent_name: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    avg_duration_seconds: Optional[float]
    last_run_at: Optional[str]

    class Config:
        from_attributes = True


class AgentPerformanceResponse(BaseModel):
    """Response model for agent performance."""

    agents: List[AgentPerformanceItem]

    class Config:
        from_attributes = True


class ActivityItemResponse(BaseModel):
    """Single activity item for the feed."""

    id: str
    type: str  # run, config, knowledge, template
    description: str
    timestamp: str
    status: str  # success, failed, pending, info


class ActivityFeedResponse(BaseModel):
    """Response model for activity feed."""

    activities: List[ActivityItemResponse]

    class Config:
        from_attributes = True


class PendingItemsResponse(BaseModel):
    """Response model for pending items count."""

    configChanges: int
    knowledgeChanges: int

    class Config:
        from_attributes = True


class IntegrationHealthItem(BaseModel):
    """Health status for a single integration."""

    name: str
    status: str  # connected, error, not_configured


class IntegrationHealthResponse(BaseModel):
    """Response model for integration health."""

    integrations: List[IntegrationHealthItem]

    class Config:
        from_attributes = True


@router.get("/stats", response_model=TeamStatsResponse)
async def get_team_stats(
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Get team dashboard statistics.

    Returns:
    - Total runs (all time)
    - Success rate
    - Average MTTD (run duration in seconds)
    - Weekly trend
    """
    import structlog

    logger = structlog.get_logger()

    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    # Debug logging
    logger.info(
        "get_team_stats called",
        org_id=team.org_id,
        team_node_id=team.team_node_id,
        auth_kind=team.auth_kind,
    )

    # Check total runs without filters
    total_runs_no_filter = (
        db.query(func.count(AgentRun.id))
        .filter(
            AgentRun.org_id == team.org_id,
        )
        .scalar()
        or 0
    )

    logger.info("total_runs_no_filter (org only)", count=total_runs_no_filter)

    # Total runs (all time, with team_node_id filter)
    total_runs = (
        db.query(func.count(AgentRun.id))
        .filter(
            AgentRun.org_id == team.org_id,
            AgentRun.team_node_id == team.team_node_id,
        )
        .scalar()
        or 0
    )

    logger.info("total_runs (with team_node_id)", count=total_runs)

    # Success rate (all time)
    successful_runs = (
        db.query(func.count(AgentRun.id))
        .filter(
            AgentRun.org_id == team.org_id,
            AgentRun.team_node_id == team.team_node_id,
            AgentRun.status == "completed",
        )
        .scalar()
        or 0
    )

    success_rate = round(
        (successful_runs / total_runs * 100) if total_runs > 0 else 0, 1
    )

    # Calculate average MTTD (run duration) for completed runs in last 30 days
    thirty_days_ago = now - timedelta(days=30)
    completed_runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.org_id == team.org_id,
            AgentRun.team_node_id == team.team_node_id,
            AgentRun.started_at >= thirty_days_ago,
            AgentRun.status == "completed",
            AgentRun.completed_at.isnot(None),
        )
        .all()
    )

    avg_mttd_seconds = None
    if completed_runs:
        durations = [
            (run.completed_at - run.started_at).total_seconds()
            for run in completed_runs
            if run.completed_at and run.started_at
        ]
        if durations:
            avg_mttd_seconds = round(sum(durations) / len(durations), 1)

    # Runs this week
    runs_this_week = (
        db.query(func.count(AgentRun.id))
        .filter(
            AgentRun.org_id == team.org_id,
            AgentRun.team_node_id == team.team_node_id,
            AgentRun.started_at >= seven_days_ago,
        )
        .scalar()
        or 0
    )

    # Runs previous week
    runs_prev_week = (
        db.query(func.count(AgentRun.id))
        .filter(
            AgentRun.org_id == team.org_id,
            AgentRun.team_node_id == team.team_node_id,
            AgentRun.started_at >= fourteen_days_ago,
            AgentRun.started_at < seven_days_ago,
        )
        .scalar()
        or 0
    )

    # Determine trend
    if runs_this_week > runs_prev_week * 1.1:
        trend = "up"
    elif runs_this_week < runs_prev_week * 0.9:
        trend = "down"
    else:
        trend = "stable"

    return TeamStatsResponse(
        totalRuns=total_runs,
        successRate=success_rate,
        avgMttdSeconds=avg_mttd_seconds,
        runsThisWeek=runs_this_week,
        runsPrevWeek=runs_prev_week,
        trend=trend,
    )


@router.get("/agent-performance", response_model=AgentPerformanceResponse)
async def get_agent_performance(
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Get performance metrics for each agent.

    Returns per-agent (all time):
    - Total runs
    - Success/failure counts
    - Success rate
    - Average duration
    - Last run timestamp
    """
    # Query agent performance (all time)
    results = (
        db.query(
            AgentRun.agent_name,
            func.count(AgentRun.id).label("total_runs"),
            func.sum(case((AgentRun.status == "completed", 1), else_=0)).label(
                "successful_runs"
            ),
            func.sum(case((AgentRun.status == "failed", 1), else_=0)).label(
                "failed_runs"
            ),
            func.avg(
                case(
                    (
                        AgentRun.completed_at.isnot(None),
                        func.extract(
                            "epoch", AgentRun.completed_at - AgentRun.started_at
                        ),
                    ),
                    else_=None,
                )
            ).label("avg_duration"),
            func.max(AgentRun.started_at).label("last_run_at"),
        )
        .filter(
            AgentRun.org_id == team.org_id,
            AgentRun.team_node_id == team.team_node_id,
        )
        .group_by(AgentRun.agent_name)
        .all()
    )

    agents = []
    for result in results:
        total = result.total_runs or 0
        successful = result.successful_runs or 0
        failed = result.failed_runs or 0
        success_rate = round((successful / total * 100) if total > 0 else 0, 1)

        agents.append(
            AgentPerformanceItem(
                agent_id=result.agent_name or "unknown",
                agent_name=result.agent_name or "Unknown Agent",
                total_runs=total,
                successful_runs=successful,
                failed_runs=failed,
                success_rate=success_rate,
                avg_duration_seconds=(
                    round(result.avg_duration) if result.avg_duration else None
                ),
                last_run_at=(
                    result.last_run_at.isoformat() if result.last_run_at else None
                ),
            )
        )

    return AgentPerformanceResponse(agents=agents)


@router.get("/activity", response_model=ActivityFeedResponse)
async def get_team_activity(
    limit: int = 10,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Get recent team activity feed.

    Combines:
    - Agent runs
    - Configuration changes
    - Knowledge base updates

    Sorted by timestamp (most recent first).
    """
    activities = []

    # Recent agent runs
    recent_runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.org_id == team.org_id,
            AgentRun.team_node_id == team.team_node_id,
        )
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
        .all()
    )

    for run in recent_runs:
        status = (
            "success"
            if run.status == "completed"
            else "failed" if run.status == "failed" else "pending"
        )
        activities.append(
            ActivityItemResponse(
                id=f"run_{run.id}",
                type="run",
                description=f"Agent '{run.agent_name}' run {run.status}",
                timestamp=run.started_at.isoformat(),
                status=status,
            )
        )

    # Recent config changes
    recent_changes = (
        db.query(PendingConfigChange)
        .filter(
            PendingConfigChange.org_id == team.org_id,
            PendingConfigChange.node_id == team.team_node_id,
        )
        .order_by(PendingConfigChange.requested_at.desc())
        .limit(5)
        .all()
    )

    for change in recent_changes:
        status = (
            "success"
            if change.status == "approved"
            else "failed" if change.status == "rejected" else "pending"
        )
        activities.append(
            ActivityItemResponse(
                id=f"change_{change.id}",
                type="config",
                description=f"Config change ({change.change_type}) {change.status}",
                timestamp=change.requested_at.isoformat(),
                status=status,
            )
        )

    # Recent knowledge updates
    recent_docs = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.org_id == team.org_id,
            KnowledgeDocument.team_node_id == team.team_node_id,
        )
        .order_by(KnowledgeDocument.updated_at.desc())
        .limit(5)
        .all()
    )

    for doc in recent_docs:
        activities.append(
            ActivityItemResponse(
                id=f"doc_{doc.id}",
                type="knowledge",
                description=f"Knowledge document '{doc.title}' added",
                timestamp=doc.updated_at.isoformat(),
                status="info",
            )
        )

    # Sort all activities by timestamp
    activities.sort(key=lambda x: x.timestamp, reverse=True)

    return ActivityFeedResponse(activities=activities[:limit])


@router.get("/pending", response_model=PendingItemsResponse)
async def get_pending_items(
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Get counts of pending items requiring review.

    Returns:
    - Config changes awaiting approval
    - Knowledge changes (proposed by AI)
    """
    # Pending config changes
    config_changes = (
        db.query(func.count(PendingConfigChange.id))
        .filter(
            PendingConfigChange.org_id == team.org_id,
            PendingConfigChange.node_id == team.team_node_id,
            PendingConfigChange.status == "pending",
            PendingConfigChange.change_type != "knowledge",
        )
        .scalar()
        or 0
    )

    # Pending knowledge changes
    knowledge_changes = (
        db.query(func.count(PendingConfigChange.id))
        .filter(
            PendingConfigChange.org_id == team.org_id,
            PendingConfigChange.node_id == team.team_node_id,
            PendingConfigChange.status == "pending",
            PendingConfigChange.change_type == "knowledge",
        )
        .scalar()
        or 0
    )

    return PendingItemsResponse(
        configChanges=config_changes,
        knowledgeChanges=knowledge_changes,
    )


@router.get("/integrations/health", response_model=IntegrationHealthResponse)
async def get_integrations_health(
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Get health status of team integrations.

    Returns list of configured integrations with their connection status based on
    whether all required fields (per schema) have values.
    """
    from ...db.config_models import IntegrationSchema
    from ...db.config_repository import get_effective_config

    # Get team's effective configuration
    effective_config = get_effective_config(
        session=db,
        org_id=team.org_id,
        node_id=team.team_node_id,
    )

    # Get all integration schemas to know which fields are required
    schemas = db.query(IntegrationSchema).all()
    schema_map = {schema.id: schema for schema in schemas}

    # Extract integration configurations
    integrations_data = effective_config.get("integrations", {})

    integrations = []
    for integration_id, integration_config in integrations_data.items():
        if not isinstance(integration_config, dict):
            continue

        # Get the schema for this integration
        schema = schema_map.get(integration_id)
        if not schema:
            # Unknown integration, skip
            continue

        # Check if all required fields have non-empty values
        all_required_fields_filled = True
        for field in schema.fields:
            if field.get("required", False):
                field_name = field.get("name")
                value = integration_config.get(field_name)
                if not value or str(value).strip() == "":
                    all_required_fields_filled = False
                    break

        status = "connected" if all_required_fields_filled else "not_configured"

        integrations.append(
            IntegrationHealthItem(
                name=integration_id,
                status=status,
            )
        )

    return IntegrationHealthResponse(integrations=integrations)


# =============================================================================
# MCP Server Management
# =============================================================================


class MCPToolInfo(BaseModel):
    """Information about a single MCP tool."""

    name: str
    display_name: str
    description: str
    category: str
    input_schema: Optional[Dict[str, Any]] = None


class MCPServerInfo(BaseModel):
    """Information about an MCP server."""

    name: str
    protocol_version: str
    connection_type: str


class MCPPreviewRequest(BaseModel):
    """Request to preview an MCP server."""

    name: str
    description: Optional[str] = None
    command: str
    args: List[str]
    env_vars: Dict[str, str] = {}


class MCPPreviewResponse(BaseModel):
    """Response from MCP server preview."""

    success: bool
    server_info: Optional[MCPServerInfo] = None
    tool_count: int = 0
    tools: List[MCPToolInfo] = []
    error: Optional[str] = None
    error_details: Optional[str] = None
    warnings: List[str] = []


def _categorize_tool(tool_name: str) -> str:
    """
    Categorize a tool based on its name.

    This helps organize tools in the UI by grouping related tools together.
    """
    tool_lower = tool_name.lower()

    # Cluster management
    if any(x in tool_lower for x in ["cluster", "stack", "deploy"]):
        return "Cluster Management"

    # Kubernetes resources
    if any(
        x in tool_lower for x in ["k8s", "kubernetes", "resource", "yaml", "manifest"]
    ):
        return "Kubernetes Resources"

    # Troubleshooting
    if any(x in tool_lower for x in ["log", "event", "debug", "troubleshoot"]):
        return "Troubleshooting"

    # File operations
    if any(x in tool_lower for x in ["file", "read", "write", "directory", "list"]):
        return "File Operations"

    # Database
    if any(x in tool_lower for x in ["query", "sql", "database", "table"]):
        return "Database"

    # Git/GitHub
    if any(
        x in tool_lower
        for x in ["git", "github", "repo", "commit", "branch", "pr", "pull"]
    ):
        return "Version Control"

    # Communication
    if any(x in tool_lower for x in ["slack", "message", "channel", "post"]):
        return "Communication"

    # Documentation
    if any(x in tool_lower for x in ["doc", "search", "help"]):
        return "Documentation"

    return "General"


def _get_helpful_error_message(error: Exception) -> str:
    """
    Generate a helpful error message for common MCP connection failures.
    """
    error_str = str(error).lower()

    if "command not found" in error_str or "no such file" in error_str:
        return "Command not found. Make sure Node.js/npx is installed and in PATH."

    if "connection" in error_str or "timeout" in error_str:
        return "Connection failed. Check network connectivity and server availability."

    if "permission" in error_str or "access denied" in error_str:
        return "Permission denied. Check file permissions and credentials."

    if "env" in error_str or "variable" in error_str:
        return "Environment variable issue. Check that all required variables are set."

    return "Check command, arguments, and environment variables."


def _check_for_warnings(
    config: Dict[str, Any], tools: List[Dict[str, Any]]
) -> List[str]:
    """
    Check for potential issues with the MCP configuration.
    """
    warnings = []

    # Check if no tools discovered
    if len(tools) == 0:
        warnings.append("No tools discovered from this MCP server.")

    # Check for missing environment variables
    env_vars = config.get("env", {})
    for key, value in env_vars.items():
        if "${" in str(value) and "}" in str(value):
            warnings.append(
                f"Environment variable {key} contains unresolved placeholder: {value}"
            )

    # Check for potentially dangerous tools
    dangerous_keywords = ["delete", "remove", "destroy", "kill", "terminate"]
    dangerous_tools = [
        tool["name"]
        for tool in tools
        if any(keyword in tool["name"].lower() for keyword in dangerous_keywords)
    ]
    if dangerous_tools:
        warnings.append(
            f"This MCP includes potentially destructive tools: {', '.join(dangerous_tools[:3])}"
        )

    return warnings


@router.post("/mcp-servers/preview", response_model=MCPPreviewResponse)
async def preview_mcp_server(
    body: MCPPreviewRequest,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Preview an MCP server before adding it.

    This endpoint:
    1. Validates the MCP configuration
    2. Temporarily connects to the MCP server
    3. Discovers available tools
    4. Returns tool list to the user

    This gives users immediate feedback about what tools they'll get
    before committing to adding the MCP server.

    NOTE: This does NOT save the MCP to the database.
    That happens when user adds the MCP via the config update endpoint.
    """
    import structlog

    logger = structlog.get_logger()

    logger.info(
        "mcp_preview_requested",
        team_id=team.team_node_id,
        org_id=team.org_id,
        user=team.subject,
        mcp_name=body.name,
        command=body.command,
    )

    # Use standalone MCP preview (no agent dependencies)
    from src.mcp_preview import preview_mcp_server

    # Connect and discover tools
    result = await preview_mcp_server(
        command=body.command, args=body.args, env_vars=body.env_vars, timeout=15
    )

    if not result["success"]:
        return MCPPreviewResponse(
            success=False,
            error=result.get("error", "Unknown error"),
            error_details=result.get("error_details", ""),
        )

    # Categorize and format tools
    tools = []
    for tool_data in result["tools"]:
        tools.append(
            MCPToolInfo(
                name=tool_data["name"],
                display_name=tool_data["display_name"],
                description=tool_data["description"][:200],  # Limit length
                category=_categorize_tool(tool_data["name"]),
                input_schema=tool_data.get("input_schema"),
            )
        )

    # Check for warnings
    mcp_config = {"command": body.command, "args": body.args, "env": body.env_vars}
    warnings = _check_for_warnings(mcp_config, [t.dict() for t in tools])

    return MCPPreviewResponse(
        success=True,
        server_info=MCPServerInfo(
            name=body.name, protocol_version="2025-03-26", connection_type="stdio"
        ),
        tool_count=len(tools),
        tools=tools,
        warnings=warnings,
    )
