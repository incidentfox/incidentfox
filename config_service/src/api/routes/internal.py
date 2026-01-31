"""
Internal API routes for service-to-service communication.
These endpoints are not exposed externally and use internal auth.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import json
import uuid as uuid_lib

from src.db import repository
from src.db.config_models import NodeConfiguration
from src.db.models import OrgNode, SlackInstallation
from src.db.session import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


# Priority order for routing identifiers (highest priority first)
ROUTING_PRIORITY = [
    "incidentio_team_ids",
    "pagerduty_service_ids",
    "slack_channel_ids",
    "github_repos",
    "coralogix_team_names",
    "incidentio_alert_source_ids",
    "services",
]


def require_internal_service(
    x_internal_service: str = Header(default="", alias="X-Internal-Service"),
) -> str:
    """Validate internal service header."""
    if not x_internal_service:
        raise HTTPException(status_code=401, detail="Missing internal service header")
    # Accept any internal service header for now - can add verification later
    return x_internal_service


class AgentRunCreateRequest(BaseModel):
    run_id: str
    org_id: str
    team_node_id: str
    correlation_id: str
    agent_name: str
    trigger_source: str = "api"
    trigger_actor: Optional[str] = None
    trigger_message: Optional[str] = None
    trigger_channel_id: Optional[str] = None
    metadata: Optional[dict] = None


class AgentRunCompleteRequest(BaseModel):
    status: str  # completed, failed, timeout
    duration_seconds: float
    output_summary: Optional[str] = None
    error_message: Optional[str] = None
    tool_calls_count: int = 0
    confidence: Optional[float] = None


class AgentRunResponse(BaseModel):
    id: str
    org_id: str
    team_node_id: str
    correlation_id: str
    agent_name: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    tool_calls_count: Optional[int] = None
    output_summary: Optional[str] = None
    error_message: Optional[str] = None


@router.post("/agent-runs", response_model=AgentRunResponse)
def create_agent_run(
    request: AgentRunCreateRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """Create a new agent run record (called by agent service at run start)."""
    run = repository.create_agent_run(
        session,
        run_id=request.run_id,
        org_id=request.org_id,
        team_node_id=request.team_node_id,
        correlation_id=request.correlation_id,
        trigger_source=request.trigger_source,
        trigger_actor=request.trigger_actor,
        trigger_message=request.trigger_message,
        trigger_channel_id=request.trigger_channel_id,
        agent_name=request.agent_name,
        metadata=request.metadata,
    )
    session.commit()

    return AgentRunResponse(
        id=run.id,
        org_id=run.org_id,
        team_node_id=run.team_node_id,
        correlation_id=run.correlation_id,
        agent_name=run.agent_name,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_seconds=run.duration_seconds,
        tool_calls_count=run.tool_calls_count,
        output_summary=run.output_summary,
        error_message=run.error_message,
    )


@router.patch("/agent-runs/{run_id}", response_model=AgentRunResponse)
def complete_agent_run(
    run_id: str,
    request: AgentRunCompleteRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """Mark an agent run as complete (called by agent service when run finishes)."""
    run = repository.complete_agent_run(
        session,
        run_id=run_id,
        status=request.status,
        tool_calls_count=request.tool_calls_count,
        output_summary=request.output_summary,
        error_message=request.error_message,
        confidence=request.confidence,
    )

    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    session.commit()

    return AgentRunResponse(
        id=run.id,
        org_id=run.org_id,
        team_node_id=run.team_node_id,
        correlation_id=run.correlation_id,
        agent_name=run.agent_name,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        duration_seconds=run.duration_seconds,
        tool_calls_count=run.tool_calls_count,
        output_summary=run.output_summary,
        error_message=run.error_message,
    )


class AgentRunListResponse(BaseModel):
    """Response for listing agent runs."""

    runs: List[AgentRunResponse]
    total: int
    has_more: bool


@router.get("/agent-runs/list", response_model=AgentRunListResponse)
def list_agent_runs_internal(
    team_node_id: Optional[str] = None,
    org_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    status: Optional[str] = None,
    agent_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    List agent runs for a team (internal endpoint for AI pipeline).

    Used by the AI pipeline to ingest agent execution data for self-analysis.
    """
    # Parse timestamps
    since = None
    until = None
    if start_time:
        try:
            since = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_time format")
    if end_time:
        try:
            until = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_time format")

    # Need at least org_id or team_node_id
    if not org_id and not team_node_id:
        # Try to get org_id from team_node_id lookup
        if team_node_id:
            node = (
                session.query(OrgNode).filter(OrgNode.node_id == team_node_id).first()
            )
            if node:
                org_id = node.org_id

    if not org_id:
        raise HTTPException(
            status_code=400, detail="Either org_id or team_node_id is required"
        )

    runs = repository.list_agent_runs(
        session,
        org_id=org_id,
        team_node_id=team_node_id,
        status=status,
        agent_name=agent_name,
        since=since,
        until=until,
        limit=limit + 1,  # Fetch one extra to check has_more
        offset=offset,
    )

    has_more = len(runs) > limit
    if has_more:
        runs = runs[:limit]

    return AgentRunListResponse(
        runs=[
            AgentRunResponse(
                id=run.id,
                org_id=run.org_id,
                team_node_id=run.team_node_id,
                correlation_id=run.correlation_id,
                agent_name=run.agent_name,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                duration_seconds=run.duration_seconds,
                tool_calls_count=run.tool_calls_count,
                output_summary=run.output_summary,
                error_message=run.error_message,
            )
            for run in runs
        ],
        total=len(runs),
        has_more=has_more,
    )


# ==================== Stale Run Cleanup ====================


class StaleRunsCleanupRequest(BaseModel):
    """Request to mark stale runs as timeout."""

    max_age_seconds: int = 600  # Default: 10 minutes (2x typical 5min timeout)


class StaleRunsCleanupResponse(BaseModel):
    """Response from stale runs cleanup."""

    marked_count: int
    max_age_seconds: int
    message: str


class StaleRunsCountResponse(BaseModel):
    """Response with count of stale runs."""

    stale_count: int
    max_age_seconds: int


@router.post("/agent-runs/cleanup-stale", response_model=StaleRunsCleanupResponse)
def cleanup_stale_agent_runs(
    request: StaleRunsCleanupRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Mark stale agent runs as 'timeout'.

    This is a cleanup endpoint to handle runs that were orphaned due to:
    - Process crash/OOM kill
    - Network partition during completion recording
    - Pod termination without graceful shutdown

    Intended to be called by a periodic cronjob.
    """
    logger.info(
        "cleanup_stale_runs_requested",
        max_age_seconds=request.max_age_seconds,
        service=service,
    )

    marked_count = repository.mark_stale_runs_as_timeout(
        session,
        max_age_seconds=request.max_age_seconds,
    )
    session.commit()

    logger.info(
        "cleanup_stale_runs_completed",
        marked_count=marked_count,
        max_age_seconds=request.max_age_seconds,
    )

    return StaleRunsCleanupResponse(
        marked_count=marked_count,
        max_age_seconds=request.max_age_seconds,
        message=f"Marked {marked_count} stale runs as timeout",
    )


@router.get("/agent-runs/stale-count", response_model=StaleRunsCountResponse)
def get_stale_runs_count(
    max_age_seconds: int = 600,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Get count of stale agent runs (for monitoring/alerting).

    Returns the number of runs stuck in 'running' status for longer
    than max_age_seconds. Useful for Prometheus metrics or alerts.
    """
    count = repository.get_stale_runs_count(
        session,
        max_age_seconds=max_age_seconds,
    )

    return StaleRunsCountResponse(
        stale_count=count,
        max_age_seconds=max_age_seconds,
    )


# ==================== Agent Tool Calls ====================


class ToolCallItem(BaseModel):
    """A single tool call in a batch."""

    id: str
    tool_name: str
    agent_name: Optional[str] = None
    parent_agent: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[str] = None
    started_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    status: str = "success"
    error_message: Optional[str] = None
    sequence_number: int = 0


class ToolCallsBatchRequest(BaseModel):
    """Request to record multiple tool calls for a run."""

    run_id: str
    tool_calls: List[ToolCallItem]


class ToolCallResponse(BaseModel):
    """Response for a single tool call."""

    id: str
    run_id: str
    tool_name: str
    agent_name: Optional[str] = None
    parent_agent: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[str] = None
    started_at: datetime
    duration_ms: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    sequence_number: int


class ToolCallsListResponse(BaseModel):
    """Response for listing tool calls."""

    tool_calls: List[ToolCallResponse]
    total: int


@router.post("/agent-runs/{run_id}/tool-calls", response_model=ToolCallsListResponse)
def record_tool_calls(
    run_id: str,
    request: ToolCallsBatchRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Record tool calls for an agent run (called by agent service after run completes).

    This endpoint allows the agent to submit detailed tool execution traces
    including inputs, outputs, and timing information.
    """
    if request.run_id != run_id:
        raise HTTPException(
            status_code=400, detail="run_id in path must match request body"
        )

    # Convert to dict format for bulk insert
    tool_calls_data = [
        {
            "id": tc.id,
            "tool_name": tc.tool_name,
            "agent_name": tc.agent_name,
            "parent_agent": tc.parent_agent,
            "tool_input": tc.tool_input,
            "tool_output": tc.tool_output,
            "started_at": tc.started_at,
            "duration_ms": tc.duration_ms,
            "status": tc.status,
            "error_message": tc.error_message,
            "sequence_number": tc.sequence_number,
        }
        for tc in request.tool_calls
    ]

    count = repository.bulk_create_tool_calls(
        session,
        run_id=run_id,
        tool_calls=tool_calls_data,
    )
    session.commit()

    # Fetch the created records to return
    tool_calls = repository.get_tool_calls_for_run(session, run_id=run_id)

    return ToolCallsListResponse(
        tool_calls=[
            ToolCallResponse(
                id=tc.id,
                run_id=tc.run_id,
                tool_name=tc.tool_name,
                agent_name=tc.agent_name,
                parent_agent=tc.parent_agent,
                tool_input=tc.tool_input,
                tool_output=tc.tool_output,
                started_at=tc.started_at,
                duration_ms=tc.duration_ms,
                status=tc.status,
                error_message=tc.error_message,
                sequence_number=tc.sequence_number,
            )
            for tc in tool_calls
        ],
        total=count,
    )


@router.get("/agent-runs/{run_id}/tool-calls", response_model=ToolCallsListResponse)
def get_tool_calls(
    run_id: str,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Get all tool calls for an agent run.

    Used by the AI pipeline to analyze detailed agent execution traces.
    """
    tool_calls = repository.get_tool_calls_for_run(session, run_id=run_id)

    return ToolCallsListResponse(
        tool_calls=[
            ToolCallResponse(
                id=tc.id,
                run_id=tc.run_id,
                tool_name=tc.tool_name,
                tool_input=tc.tool_input,
                tool_output=tc.tool_output,
                started_at=tc.started_at,
                duration_ms=tc.duration_ms,
                status=tc.status,
                error_message=tc.error_message,
                sequence_number=tc.sequence_number,
            )
            for tc in tool_calls
        ],
        total=len(tool_calls),
    )


class ToolCallsQueryRequest(BaseModel):
    """Request to query tool calls across multiple runs."""

    run_ids: Optional[List[str]] = None
    tool_name: Optional[str] = None
    status: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    limit: int = 1000
    offset: int = 0


@router.post("/tool-calls/query", response_model=ToolCallsListResponse)
def query_tool_calls(
    request: ToolCallsQueryRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Query tool calls across multiple runs.

    Used by the AI pipeline for aggregate analysis of tool usage patterns.
    """
    # Parse timestamps
    since = None
    until = None
    if request.start_time:
        try:
            since = datetime.fromisoformat(request.start_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_time format")
    if request.end_time:
        try:
            until = datetime.fromisoformat(request.end_time.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_time format")

    tool_calls = repository.list_tool_calls(
        session,
        run_ids=request.run_ids,
        tool_name=request.tool_name,
        status=request.status,
        since=since,
        until=until,
        limit=request.limit,
        offset=request.offset,
    )

    return ToolCallsListResponse(
        tool_calls=[
            ToolCallResponse(
                id=tc.id,
                run_id=tc.run_id,
                tool_name=tc.tool_name,
                tool_input=tc.tool_input,
                tool_output=tc.tool_output,
                started_at=tc.started_at,
                duration_ms=tc.duration_ms,
                status=tc.status,
                error_message=tc.error_message,
                sequence_number=tc.sequence_number,
            )
            for tc in tool_calls
        ],
        total=len(tool_calls),
    )


# ==================== Pending Changes (AI Pipeline Proposals) ====================


class PendingChangeCreateRequest(BaseModel):
    """Request to create a pending change from AI pipeline."""

    id: str
    org_id: str
    node_id: str
    change_type: str  # "prompt", "tools", "knowledge"
    change_path: Optional[str] = None
    proposed_value: Optional[Dict[str, Any]] = None
    previous_value: Optional[Dict[str, Any]] = None
    requested_by: str = "ai_pipeline"
    reason: Optional[str] = None
    status: str = "pending"


class PendingChangeResponse(BaseModel):
    """Response for pending change operations."""

    id: str
    org_id: str
    node_id: str
    change_type: str
    status: str
    requested_by: str
    requested_at: datetime


@router.post("/pending-changes", response_model=PendingChangeResponse)
def create_pending_change_internal(
    request: PendingChangeCreateRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Create a pending change record (for AI pipeline proposals).

    Used by the AI pipeline to submit human-readable proposals for review.
    """
    from src.db.models import PendingConfigChange

    # Check if change with this ID already exists
    existing = (
        session.query(PendingConfigChange)
        .filter(PendingConfigChange.id == request.id)
        .first()
    )
    if existing:
        # Return existing instead of error (idempotent)
        return PendingChangeResponse(
            id=existing.id,
            org_id=existing.org_id,
            node_id=existing.node_id,
            change_type=existing.change_type,
            status=existing.status,
            requested_by=existing.requested_by,
            requested_at=existing.requested_at,
        )

    # Create new pending change
    change = PendingConfigChange(
        id=request.id,
        org_id=request.org_id,
        node_id=request.node_id,
        change_type=request.change_type,
        change_path=request.change_path,
        proposed_value=request.proposed_value,
        previous_value=request.previous_value,
        requested_by=request.requested_by,
        reason=request.reason,
        status=request.status,
    )
    session.add(change)
    session.commit()

    logger.info(
        "created_pending_change",
        id=change.id,
        change_type=change.change_type,
        requested_by=change.requested_by,
    )

    return PendingChangeResponse(
        id=change.id,
        org_id=change.org_id,
        node_id=change.node_id,
        change_type=change.change_type,
        status=change.status,
        requested_by=change.requested_by,
        requested_at=change.requested_at,
    )


# ==================== Routing Lookup ====================


class RoutingLookupRequest(BaseModel):
    """Request to look up which team owns given identifiers."""

    org_id: Optional[str] = None  # Optional - scope to specific org
    identifiers: Dict[str, str]  # identifier_type -> value


class RoutingLookupResponse(BaseModel):
    """Response with routing lookup result."""

    found: bool
    org_id: Optional[str] = None
    team_node_id: Optional[str] = None
    team_token: Optional[str] = None  # For fetching full config
    matched_by: Optional[str] = None  # Which identifier matched
    matched_value: Optional[str] = None
    tried: List[str] = []  # Which identifiers were tried


def _normalize_identifier(identifier_type: str, value: str) -> str:
    """Normalize identifier value for comparison."""
    value = value.strip()
    # Lowercase for text-based identifiers
    if identifier_type in ("coralogix_team_names", "github_repos", "services"):
        value = value.lower()
    return value


def _check_routing_match(
    routing_config: Dict[str, Any],
    identifier_type: str,
    value: str,
) -> bool:
    """Check if a routing config matches the given identifier."""
    if not routing_config:
        return False

    # Map request identifier names to config field names
    # Request uses singular, config uses plural list
    field_map = {
        "incidentio_team_id": "incidentio_team_ids",
        "pagerduty_service_id": "pagerduty_service_ids",
        "slack_channel_id": "slack_channel_ids",
        "github_repo": "github_repos",
        "coralogix_team_name": "coralogix_team_names",
        "incidentio_alert_source_id": "incidentio_alert_source_ids",
        "service": "services",
    }

    config_field = field_map.get(identifier_type)
    if not config_field:
        return False

    config_values = routing_config.get(config_field, [])
    if not config_values:
        return False

    normalized_value = _normalize_identifier(identifier_type, value)
    for cv in config_values:
        if _normalize_identifier(identifier_type, cv) == normalized_value:
            return True

    return False


@router.post("/routing/lookup", response_model=RoutingLookupResponse)
def lookup_routing(
    request: RoutingLookupRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Look up which team owns the given identifiers.

    Tries identifiers in priority order and returns the first match.
    Used by the agent service to route incoming webhooks to the correct team.
    """
    tried = []

    # Priority order for checking (maps request field name to internal field name)
    check_order = [
        "incidentio_team_id",
        "pagerduty_service_id",
        "slack_channel_id",
        "github_repo",
        "coralogix_team_name",
        "incidentio_alert_source_id",
        "service",
    ]

    # Get all team nodes (teams have configs, we need to check routing in each)
    # If org_id is specified, filter by org
    if request.org_id:
        team_nodes = (
            session.query(OrgNode)
            .filter(
                OrgNode.org_id == request.org_id,
                OrgNode.node_type == "team",
            )
            .all()
        )
    else:
        team_nodes = (
            session.query(OrgNode)
            .filter(
                OrgNode.node_type == "team",
            )
            .all()
        )

    logger.info(
        "routing_lookup_start",
        org_id=request.org_id,
        identifiers=list(request.identifiers.keys()),
        team_count=len(team_nodes),
    )

    # Try each identifier type in priority order
    for identifier_type in check_order:
        value = request.identifiers.get(identifier_type)
        if not value:
            continue

        tried.append(identifier_type)

        # Search all team configs
        for team_node in team_nodes:
            # Get team's config
            config_row = (
                session.query(NodeConfiguration)
                .filter(
                    NodeConfiguration.org_id == team_node.org_id,
                    NodeConfiguration.node_id == team_node.node_id,
                )
                .first()
            )

            if not config_row or not config_row.config_json:
                continue

            routing = config_row.config_json.get("routing", {})

            if _check_routing_match(routing, identifier_type, value):
                logger.info(
                    "routing_lookup_match",
                    org_id=team_node.org_id,
                    team_node_id=team_node.node_id,
                    matched_by=identifier_type,
                    matched_value=value,
                )

                # For now we don't return actual token - caller should use org/team IDs
                return RoutingLookupResponse(
                    found=True,
                    org_id=team_node.org_id,
                    team_node_id=team_node.node_id,
                    matched_by=identifier_type,
                    matched_value=value,
                    tried=tried,
                )

    logger.info("routing_lookup_no_match", tried=tried)
    return RoutingLookupResponse(found=False, tried=tried)


# ==================== Conversation Mapping ====================


class ConversationMappingRequest(BaseModel):
    """Request to create/get a conversation mapping."""

    session_id: str
    openai_conversation_id: Optional[str] = None  # Required for create
    session_type: str = "slack"  # slack, github, api
    org_id: Optional[str] = None
    team_node_id: Optional[str] = None


class ConversationMappingResponse(BaseModel):
    """Response with conversation mapping."""

    found: bool
    session_id: str
    openai_conversation_id: Optional[str] = None
    session_type: Optional[str] = None
    created: bool = False


@router.get("/conversations/{session_id}", response_model=ConversationMappingResponse)
def get_conversation_mapping(
    session_id: str,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """Get OpenAI conversation_id for a session."""
    mapping = repository.get_conversation_mapping(session, session_id=session_id)

    if mapping:
        # Update last_used timestamp
        repository.update_conversation_mapping_last_used(session, session_id=session_id)
        session.commit()

        return ConversationMappingResponse(
            found=True,
            session_id=mapping.session_id,
            openai_conversation_id=mapping.openai_conversation_id,
            session_type=mapping.session_type,
        )

    return ConversationMappingResponse(
        found=False,
        session_id=session_id,
    )


@router.post("/conversations", response_model=ConversationMappingResponse)
def create_conversation_mapping(
    request: ConversationMappingRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """Create or update a conversation mapping (upsert to handle race conditions)."""
    if not request.openai_conversation_id:
        raise HTTPException(
            status_code=400, detail="openai_conversation_id is required"
        )

    # Use upsert to handle concurrent requests safely
    mapping, created = repository.upsert_conversation_mapping(
        session,
        session_id=request.session_id,
        openai_conversation_id=request.openai_conversation_id,
        session_type=request.session_type,
        org_id=request.org_id,
        team_node_id=request.team_node_id,
    )
    session.commit()

    if created:
        logger.info(
            "conversation_mapping_created",
            session_id=request.session_id,
            openai_conversation_id=request.openai_conversation_id,
            session_type=request.session_type,
        )
    else:
        logger.info(
            "conversation_mapping_updated",
            session_id=request.session_id,
            openai_conversation_id=request.openai_conversation_id,
        )

    return ConversationMappingResponse(
        found=True,
        session_id=mapping.session_id,
        openai_conversation_id=mapping.openai_conversation_id,
        session_type=mapping.session_type,
        created=created,
    )


@router.delete("/conversations/{session_id}")
def delete_conversation_mapping(
    session_id: str,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """Delete a conversation mapping."""
    deleted = repository.delete_conversation_mapping(session, session_id=session_id)
    session.commit()

    if deleted:
        return {"deleted": True, "session_id": session_id}

    raise HTTPException(status_code=404, detail="Conversation mapping not found")


# ==================== Meeting Data Storage ====================


class MeetingDataRequest(BaseModel):
    """Request to store meeting data from webhook."""

    org_id: str
    team_node_id: str
    meeting_id: str
    provider: str = "circleback"
    name: Optional[str] = None
    meetingUrl: Optional[str] = None
    duration: Optional[int] = None
    createdAt: Optional[str] = None
    attendees: Optional[List[dict]] = None
    notes: Optional[str] = None
    transcript: Optional[List[dict]] = None
    action_items: Optional[List[dict]] = None
    insights: Optional[List[dict]] = None


class MeetingDataResponse(BaseModel):
    """Response with stored meeting data."""

    meeting_id: str
    org_id: str
    team_node_id: str
    provider: str
    created: bool = False


class MeetingSearchResponse(BaseModel):
    """Response with meeting search results."""

    meetings: List[dict]
    total: int


@router.post("/meetings", response_model=MeetingDataResponse)
def store_meeting_data(
    request: MeetingDataRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Store meeting data from a webhook provider.

    This endpoint receives meeting transcripts and metadata from webhook providers
    like Circleback and stores them for later querying by agents.
    """
    from datetime import datetime as dt

    from src.db.models import MeetingData

    logger.info(
        "store_meeting_data",
        org_id=request.org_id,
        team_node_id=request.team_node_id,
        meeting_id=request.meeting_id,
        provider=request.provider,
    )

    # Check if meeting already exists
    existing = (
        session.query(MeetingData)
        .filter(
            MeetingData.org_id == request.org_id,
            MeetingData.team_node_id == request.team_node_id,
            MeetingData.meeting_id == request.meeting_id,
        )
        .first()
    )

    if existing:
        # Update existing meeting data
        existing.name = request.name
        existing.meeting_url = request.meetingUrl
        existing.duration_seconds = request.duration
        existing.attendees = request.attendees
        existing.notes = request.notes
        existing.transcript = request.transcript
        existing.action_items = request.action_items
        existing.raw_payload = {
            "insights": request.insights,
            "createdAt": request.createdAt,
        }
        existing.updated_at = dt.utcnow()
        session.commit()

        return MeetingDataResponse(
            meeting_id=request.meeting_id,
            org_id=request.org_id,
            team_node_id=request.team_node_id,
            provider=request.provider,
            created=False,
        )

    # Parse meeting time from createdAt
    meeting_time = None
    if request.createdAt:
        try:
            meeting_time = dt.fromisoformat(request.createdAt.replace("Z", "+00:00"))
        except ValueError:
            pass

    # Create new meeting data
    meeting = MeetingData(
        org_id=request.org_id,
        team_node_id=request.team_node_id,
        meeting_id=request.meeting_id,
        provider=request.provider,
        name=request.name,
        meeting_url=request.meetingUrl,
        duration_seconds=request.duration,
        meeting_time=meeting_time,
        attendees=request.attendees,
        notes=request.notes,
        transcript=request.transcript,
        action_items=request.action_items,
        raw_payload={
            "insights": request.insights,
            "createdAt": request.createdAt,
        },
    )

    session.add(meeting)
    session.commit()

    logger.info(
        "meeting_data_stored",
        org_id=request.org_id,
        team_node_id=request.team_node_id,
        meeting_id=request.meeting_id,
    )

    return MeetingDataResponse(
        meeting_id=request.meeting_id,
        org_id=request.org_id,
        team_node_id=request.team_node_id,
        provider=request.provider,
        created=True,
    )


@router.get("/meetings/{meeting_id}", response_model=dict)
def get_meeting_data(
    meeting_id: str,
    org_id: str,
    team_node_id: str,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """Get meeting data by ID."""
    from src.db.models import MeetingData

    meeting = (
        session.query(MeetingData)
        .filter(
            MeetingData.org_id == org_id,
            MeetingData.team_node_id == team_node_id,
            MeetingData.meeting_id == meeting_id,
        )
        .first()
    )

    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    return {
        "id": meeting.meeting_id,
        "name": meeting.name,
        "provider": meeting.provider,
        "meeting_url": meeting.meeting_url,
        "duration": meeting.duration_seconds,
        "meeting_time": (
            meeting.meeting_time.isoformat() if meeting.meeting_time else None
        ),
        "attendees": meeting.attendees or [],
        "notes": meeting.notes,
        "transcript": meeting.transcript or [],
        "action_items": meeting.action_items or [],
        "created_at": meeting.created_at.isoformat() if meeting.created_at else None,
    }


@router.get("/meetings", response_model=MeetingSearchResponse)
def search_meetings(
    org_id: str,
    team_node_id: str,
    q: Optional[str] = None,
    hours_back: int = 24,
    limit: int = 20,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Search meetings for a team.

    Args:
        org_id: Organization ID
        team_node_id: Team node ID
        q: Optional search query (searches name and notes)
        hours_back: How many hours back to search
        limit: Maximum results to return
    """
    from datetime import timedelta

    from sqlalchemy import or_

    from src.db.models import MeetingData

    # Base query
    query = session.query(MeetingData).filter(
        MeetingData.org_id == org_id,
        MeetingData.team_node_id == team_node_id,
    )

    # Time filter
    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
    query = query.filter(MeetingData.created_at >= cutoff)

    # Search filter
    if q:
        search_pattern = f"%{q}%"
        query = query.filter(
            or_(
                MeetingData.name.ilike(search_pattern),
                MeetingData.notes.ilike(search_pattern),
            )
        )

    # Order by meeting time, most recent first
    query = query.order_by(MeetingData.created_at.desc())

    # Limit
    query = query.limit(limit)

    meetings = query.all()

    return MeetingSearchResponse(
        meetings=[
            {
                "id": m.meeting_id,
                "name": m.name,
                "provider": m.provider,
                "duration": m.duration_seconds,
                "meeting_time": m.meeting_time.isoformat() if m.meeting_time else None,
                "attendees": [
                    a.get("email") for a in (m.attendees or []) if a.get("email")
                ],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in meetings
        ],
        total=len(meetings),
    )


# ==================== Feedback Recording ====================


class FeedbackRequest(BaseModel):
    """Request to record user feedback."""

    run_id: str
    correlation_id: Optional[str] = None
    feedback: str  # "positive" or "negative"
    user_id: Optional[str] = None
    source: str = "unknown"  # slack, github, web


class FeedbackResponse(BaseModel):
    """Response with created feedback."""

    id: str
    run_id: str
    feedback_type: str
    source: str
    created_at: datetime


@router.post("/feedback", response_model=FeedbackResponse)
def record_feedback(
    request: FeedbackRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Record user feedback on an agent run.

    Called by orchestrator when users click feedback buttons in Slack
    or react to GitHub comments.
    """
    import uuid

    from src.core.metrics import FEEDBACK_TOTAL

    logger.info(
        "record_feedback",
        run_id=request.run_id,
        feedback=request.feedback,
        source=request.source,
        user_id=request.user_id,
    )

    feedback_id = uuid.uuid4().hex

    feedback = repository.create_agent_feedback(
        session,
        feedback_id=feedback_id,
        run_id=request.run_id,
        feedback_type=request.feedback,
        source=request.source,
        user_id=request.user_id,
        correlation_id=request.correlation_id,
    )
    session.commit()

    # Increment Prometheus counter
    FEEDBACK_TOTAL.labels(
        feedback_type=request.feedback,
        source=request.source,
    ).inc()

    return FeedbackResponse(
        id=feedback.id,
        run_id=feedback.run_id,
        feedback_type=feedback.feedback_type,
        source=feedback.source,
        created_at=feedback.created_at,
    )


class FeedbackStatsResponse(BaseModel):
    """Aggregated feedback statistics."""

    total: int
    positive: int
    negative: int
    positive_rate: float
    by_source: Dict[str, Dict[str, int]]


@router.get("/feedback/stats", response_model=FeedbackStatsResponse)
def get_feedback_statistics(
    org_id: Optional[str] = None,
    team_node_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Get aggregated feedback statistics.

    Returns counts and rates for positive/negative feedback by source.
    """
    since_dt = None
    until_dt = None

    if since:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    if until:
        until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))

    stats = repository.get_feedback_stats(
        session,
        org_id=org_id,
        team_node_id=team_node_id,
        since=since_dt,
        until=until_dt,
    )

    positive_rate = 0.0
    if stats["total"] > 0:
        positive_rate = stats["positive"] / stats["total"]

    return FeedbackStatsResponse(
        total=stats["total"],
        positive=stats["positive"],
        negative=stats["negative"],
        positive_rate=positive_rate,
        by_source=stats["by_source"],
    )


# ==================== Knowledge Tree Management ====================


class ActiveTreeInfo(BaseModel):
    """Information about an active knowledge tree."""

    tree_name: str
    org_id: str
    team_count: int  # Number of teams using this tree
    teams: List[str]  # Team node IDs using this tree


class ActiveTreesResponse(BaseModel):
    """Response with all active knowledge trees."""

    trees: List[ActiveTreeInfo]
    total_trees: int
    total_teams_with_trees: int


@router.get("/active-trees", response_model=ActiveTreesResponse)
def get_active_trees(
    org_id: Optional[str] = None,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Get all unique knowledge trees configured across teams.

    This endpoint is used by:
    - Init containers to know which trees to preload
    - Monitoring dashboards to track tree usage
    - Cache warmup jobs

    Args:
        org_id: Optional org filter (omit to get all orgs)

    Returns:
        List of unique tree names with usage stats
    """
    # Build query for all team configurations
    query = session.query(NodeConfiguration)

    if org_id:
        query = query.filter(NodeConfiguration.org_id == org_id)

    configs = query.all()

    # Extract knowledge_tree from each config and group by tree name
    tree_teams: Dict[str, List[tuple]] = (
        {}
    )  # tree_name -> [(org_id, team_node_id), ...]

    for config in configs:
        if not config.config_json:
            continue

        knowledge_tree = config.config_json.get("knowledge_tree")
        if knowledge_tree:
            if knowledge_tree not in tree_teams:
                tree_teams[knowledge_tree] = []
            tree_teams[knowledge_tree].append((config.org_id, config.node_id))

    # Build response
    trees = []
    for tree_name, team_list in sorted(tree_teams.items()):
        trees.append(
            ActiveTreeInfo(
                tree_name=tree_name,
                org_id=team_list[0][0] if team_list else "",
                team_count=len(team_list),
                teams=[t[1] for t in team_list],
            )
        )

    logger.info(
        "active_trees_query",
        org_id=org_id,
        total_trees=len(trees),
        total_teams=sum(t.team_count for t in trees),
    )

    return ActiveTreesResponse(
        trees=trees,
        total_trees=len(trees),
        total_teams_with_trees=sum(t.team_count for t in trees),
    )


# ==================== Recall.ai Bot Management ====================


class RecallBotCreateRequest(BaseModel):
    """Request to create a recall bot record."""

    id: str
    org_id: str
    team_node_id: str
    recall_bot_id: str
    meeting_url: str
    incident_id: Optional[str] = None
    bot_name: Optional[str] = None
    slack_channel_id: Optional[str] = None
    slack_thread_ts: Optional[str] = None


class RecallBotResponse(BaseModel):
    """Response with recall bot info."""

    id: str
    org_id: str
    team_node_id: str
    recall_bot_id: str
    meeting_url: str
    incident_id: Optional[str] = None
    status: str
    slack_channel_id: Optional[str] = None
    slack_thread_ts: Optional[str] = None
    slack_summary_ts: Optional[str] = None
    transcript_segments_count: int = 0
    created_at: datetime


@router.post("/recall-bots", response_model=RecallBotResponse)
def create_recall_bot(
    request: RecallBotCreateRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Create a recall bot record.

    Called by orchestrator when a meeting bot is created via Recall.ai.
    """
    from sqlalchemy import text

    logger.info(
        "create_recall_bot",
        id=request.id,
        org_id=request.org_id,
        recall_bot_id=request.recall_bot_id,
        meeting_url=request.meeting_url,
        slack_channel_id=request.slack_channel_id,
    )

    session.execute(
        text("""
            INSERT INTO recall_bots (
                id, org_id, team_node_id, recall_bot_id, meeting_url,
                incident_id, bot_name, status, slack_channel_id, slack_thread_ts
            ) VALUES (
                :id, :org_id, :team_node_id, :recall_bot_id, :meeting_url,
                :incident_id, :bot_name, 'requested', :slack_channel_id, :slack_thread_ts
            )
        """),
        {
            "id": request.id,
            "org_id": request.org_id,
            "team_node_id": request.team_node_id,
            "recall_bot_id": request.recall_bot_id,
            "meeting_url": request.meeting_url,
            "incident_id": request.incident_id,
            "bot_name": request.bot_name,
            "slack_channel_id": request.slack_channel_id,
            "slack_thread_ts": request.slack_thread_ts,
        },
    )
    session.commit()

    return RecallBotResponse(
        id=request.id,
        org_id=request.org_id,
        team_node_id=request.team_node_id,
        recall_bot_id=request.recall_bot_id,
        meeting_url=request.meeting_url,
        incident_id=request.incident_id,
        status="requested",
        slack_channel_id=request.slack_channel_id,
        slack_thread_ts=request.slack_thread_ts,
        slack_summary_ts=None,
        transcript_segments_count=0,
        created_at=datetime.utcnow(),
    )


@router.get("/recall-bots/{recall_bot_id}", response_model=RecallBotResponse)
def get_recall_bot(
    recall_bot_id: str,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Get a recall bot by its Recall.ai bot ID.
    """
    from sqlalchemy import text

    result = session.execute(
        text("""
            SELECT id, org_id, team_node_id, recall_bot_id, meeting_url,
                   incident_id, status, slack_channel_id, slack_thread_ts,
                   slack_summary_ts, transcript_segments_count, created_at
            FROM recall_bots
            WHERE recall_bot_id = :recall_bot_id
        """),
        {"recall_bot_id": recall_bot_id},
    ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Recall bot not found")

    return RecallBotResponse(
        id=result.id,
        org_id=result.org_id,
        team_node_id=result.team_node_id,
        recall_bot_id=result.recall_bot_id,
        meeting_url=result.meeting_url,
        incident_id=result.incident_id,
        status=result.status,
        slack_channel_id=result.slack_channel_id,
        slack_thread_ts=result.slack_thread_ts,
        slack_summary_ts=result.slack_summary_ts,
        transcript_segments_count=result.transcript_segments_count,
        created_at=result.created_at,
    )


class RecallBotStatusUpdateRequest(BaseModel):
    """Request to update recall bot status."""

    status: str
    status_message: Optional[str] = None


@router.patch("/recall-bots/{recall_bot_id}/status")
def update_recall_bot_status(
    recall_bot_id: str,
    request: RecallBotStatusUpdateRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Update a recall bot's status.

    Called by orchestrator when receiving status change webhooks from Recall.ai.
    """
    from sqlalchemy import text

    logger.info(
        "update_recall_bot_status",
        recall_bot_id=recall_bot_id,
        status=request.status,
    )

    # Map Recall.ai status codes to our status values
    # Recall statuses: created, joining, in_call_not_recording, in_call_recording, call_ended
    status_mapping = {
        "created": "requested",
        "joining": "joining",
        "in_call_not_recording": "in_call",
        "in_call_recording": "recording",
        "call_ended": "done",
    }
    mapped_status = status_mapping.get(request.status, request.status)

    # Update timestamp based on status
    timestamp_field = ""
    if mapped_status == "joining":
        timestamp_field = ", joined_at = NOW()"
    elif mapped_status == "done":
        timestamp_field = ", left_at = NOW()"

    session.execute(
        text(f"""
            UPDATE recall_bots
            SET status = :status,
                status_message = :status_message,
                updated_at = NOW()
                {timestamp_field}
            WHERE recall_bot_id = :recall_bot_id
        """),
        {
            "recall_bot_id": recall_bot_id,
            "status": mapped_status,
            "status_message": request.status_message,
        },
    )
    session.commit()

    return {"ok": True, "status": mapped_status}


class RecallTranscriptSegmentRequest(BaseModel):
    """Request to store a transcript segment."""

    segment_id: str
    recall_bot_id: str
    org_id: str
    incident_id: Optional[str] = None
    speaker: Optional[str] = None
    text: str
    timestamp_ms: Optional[int] = None
    is_partial: bool = False
    raw_event: Optional[dict] = None


@router.post("/recall-bots/{recall_bot_id}/transcript-segments")
def store_recall_transcript_segment(
    recall_bot_id: str,
    request: RecallTranscriptSegmentRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Store a transcript segment from Recall.ai.

    Called by orchestrator when receiving transcript webhooks from Recall.ai.
    """
    from sqlalchemy import text

    session.execute(
        text("""
            INSERT INTO recall_transcript_segments (
                id, recall_bot_id, org_id, incident_id, speaker, text,
                timestamp_ms, is_partial, raw_event
            ) VALUES (
                :id, :recall_bot_id, :org_id, :incident_id, :speaker, :text,
                :timestamp_ms, :is_partial, CAST(:raw_event AS jsonb)
            )
        """),
        {
            "id": request.segment_id,
            "recall_bot_id": request.recall_bot_id,
            "org_id": request.org_id,
            "incident_id": request.incident_id,
            "speaker": request.speaker,
            "text": request.text,
            "timestamp_ms": request.timestamp_ms,
            "is_partial": request.is_partial,
            "raw_event": json.dumps(request.raw_event) if request.raw_event else None,
        },
    )
    session.commit()

    return {"ok": True, "segment_id": request.segment_id}


@router.post("/recall-bots/{recall_bot_id}/increment-transcript-count")
def increment_recall_bot_transcript_count(
    recall_bot_id: str,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Increment the transcript segment count and update last_transcript_at.
    """
    from sqlalchemy import text

    session.execute(
        text("""
            UPDATE recall_bots
            SET transcript_segments_count = transcript_segments_count + 1,
                last_transcript_at = NOW(),
                updated_at = NOW()
            WHERE recall_bot_id = :recall_bot_id
        """),
        {"recall_bot_id": recall_bot_id},
    )
    session.commit()

    return {"ok": True}


class RecallBotSlackSummaryUpdateRequest(BaseModel):
    """Request to update the Slack summary message timestamp."""

    slack_summary_ts: str


@router.patch("/recall-bots/{recall_bot_id}/slack-summary")
def update_recall_bot_slack_summary(
    recall_bot_id: str,
    request: RecallBotSlackSummaryUpdateRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Update the Slack summary message timestamp for a recall bot.

    Called after posting/updating the transcript summary to Slack.
    """
    from sqlalchemy import text

    session.execute(
        text("""
            UPDATE recall_bots
            SET slack_summary_ts = :slack_summary_ts,
                last_summary_at = NOW(),
                updated_at = NOW()
            WHERE recall_bot_id = :recall_bot_id
        """),
        {
            "recall_bot_id": recall_bot_id,
            "slack_summary_ts": request.slack_summary_ts,
        },
    )
    session.commit()

    return {"ok": True}


class RecallTranscriptSegmentsResponse(BaseModel):
    """Response with transcript segments."""

    segments: List[dict]
    total: int


@router.get(
    "/recall-bots/{recall_bot_id}/transcript-segments",
    response_model=RecallTranscriptSegmentsResponse,
)
def get_recall_transcript_segments(
    recall_bot_id: str,
    since_id: Optional[str] = None,
    limit: int = 100,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Get transcript segments for a recall bot.

    Args:
        recall_bot_id: The Recall.ai bot ID
        since_id: Only return segments created after this ID
        limit: Maximum number of segments to return
    """
    from sqlalchemy import text

    if since_id:
        result = session.execute(
            text("""
                SELECT id, speaker, text, timestamp_ms, is_partial, created_at
                FROM recall_transcript_segments
                WHERE recall_bot_id = :recall_bot_id
                  AND id > :since_id
                  AND is_partial = false
                ORDER BY timestamp_ms ASC, created_at ASC
                LIMIT :limit
            """),
            {"recall_bot_id": recall_bot_id, "since_id": since_id, "limit": limit},
        ).fetchall()
    else:
        result = session.execute(
            text("""
                SELECT id, speaker, text, timestamp_ms, is_partial, created_at
                FROM recall_transcript_segments
                WHERE recall_bot_id = :recall_bot_id
                  AND is_partial = false
                ORDER BY timestamp_ms ASC, created_at ASC
                LIMIT :limit
            """),
            {"recall_bot_id": recall_bot_id, "limit": limit},
        ).fetchall()

    segments = [
        {
            "id": row.id,
            "speaker": row.speaker,
            "text": row.text,
            "timestamp_ms": row.timestamp_ms,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in result
    ]

    return RecallTranscriptSegmentsResponse(
        segments=segments,
        total=len(segments),
    )


# ==================== Slack Installation Storage ====================


class SlackInstallationRequest(BaseModel):
    """Request to save a Slack installation."""

    enterprise_id: Optional[str] = None
    team_id: str
    user_id: Optional[str] = None
    app_id: Optional[str] = None
    bot_token: str
    bot_id: Optional[str] = None
    bot_user_id: Optional[str] = None
    bot_scopes: Optional[List[str]] = None
    user_token: Optional[str] = None
    user_scopes: Optional[List[str]] = None
    incoming_webhook_url: Optional[str] = None
    incoming_webhook_channel: Optional[str] = None
    incoming_webhook_channel_id: Optional[str] = None
    incoming_webhook_configuration_url: Optional[str] = None
    is_enterprise_install: bool = False
    token_type: Optional[str] = None


class SlackInstallationResponse(BaseModel):
    """Response with Slack installation data."""

    id: str
    enterprise_id: Optional[str] = None
    team_id: str
    user_id: Optional[str] = None
    app_id: Optional[str] = None
    bot_token: str
    bot_id: Optional[str] = None
    bot_user_id: Optional[str] = None
    bot_scopes: Optional[List[str]] = None
    user_token: Optional[str] = None
    user_scopes: Optional[List[str]] = None
    incoming_webhook_url: Optional[str] = None
    incoming_webhook_channel: Optional[str] = None
    incoming_webhook_channel_id: Optional[str] = None
    incoming_webhook_configuration_url: Optional[str] = None
    is_enterprise_install: bool = False
    token_type: Optional[str] = None
    installed_at: datetime


def _installation_to_response(installation: SlackInstallation) -> SlackInstallationResponse:
    """Convert a SlackInstallation model to response."""
    return SlackInstallationResponse(
        id=installation.id,
        enterprise_id=installation.enterprise_id,
        team_id=installation.team_id,
        user_id=installation.user_id,
        app_id=installation.app_id,
        bot_token=installation.bot_token,
        bot_id=installation.bot_id,
        bot_user_id=installation.bot_user_id,
        bot_scopes=installation.bot_scopes.split(",") if installation.bot_scopes else None,
        user_token=installation.user_token,
        user_scopes=installation.user_scopes.split(",") if installation.user_scopes else None,
        incoming_webhook_url=installation.incoming_webhook_url,
        incoming_webhook_channel=installation.incoming_webhook_channel,
        incoming_webhook_channel_id=installation.incoming_webhook_channel_id,
        incoming_webhook_configuration_url=installation.incoming_webhook_configuration_url,
        is_enterprise_install=installation.is_enterprise_install,
        token_type=installation.token_type,
        installed_at=installation.installed_at,
    )


@router.post("/slack/installations", response_model=SlackInstallationResponse)
def save_slack_installation(
    request: SlackInstallationRequest,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Save a Slack OAuth installation.

    This is an upsert operation - if an installation with the same
    (enterprise_id, team_id, user_id) exists, it will be updated.
    """
    logger.info(
        "save_slack_installation",
        enterprise_id=request.enterprise_id,
        team_id=request.team_id,
        user_id=request.user_id,
    )

    # Look for existing installation
    query = session.query(SlackInstallation).filter(
        SlackInstallation.team_id == request.team_id,
    )
    if request.enterprise_id:
        query = query.filter(SlackInstallation.enterprise_id == request.enterprise_id)
    else:
        query = query.filter(SlackInstallation.enterprise_id.is_(None))

    if request.user_id:
        query = query.filter(SlackInstallation.user_id == request.user_id)
    else:
        query = query.filter(SlackInstallation.user_id.is_(None))

    existing = query.first()

    if existing:
        # Update existing installation
        existing.app_id = request.app_id
        existing.bot_token = request.bot_token
        existing.bot_id = request.bot_id
        existing.bot_user_id = request.bot_user_id
        existing.bot_scopes = ",".join(request.bot_scopes) if request.bot_scopes else None
        existing.user_token = request.user_token
        existing.user_scopes = ",".join(request.user_scopes) if request.user_scopes else None
        existing.incoming_webhook_url = request.incoming_webhook_url
        existing.incoming_webhook_channel = request.incoming_webhook_channel
        existing.incoming_webhook_channel_id = request.incoming_webhook_channel_id
        existing.incoming_webhook_configuration_url = request.incoming_webhook_configuration_url
        existing.is_enterprise_install = request.is_enterprise_install
        existing.token_type = request.token_type
        existing.raw_data = request.model_dump()
        session.commit()

        logger.info("slack_installation_updated", id=existing.id)
        return _installation_to_response(existing)

    # Create new installation
    installation = SlackInstallation(
        id=str(uuid_lib.uuid4()),
        enterprise_id=request.enterprise_id,
        team_id=request.team_id,
        user_id=request.user_id,
        app_id=request.app_id,
        bot_token=request.bot_token,
        bot_id=request.bot_id,
        bot_user_id=request.bot_user_id,
        bot_scopes=",".join(request.bot_scopes) if request.bot_scopes else None,
        user_token=request.user_token,
        user_scopes=",".join(request.user_scopes) if request.user_scopes else None,
        incoming_webhook_url=request.incoming_webhook_url,
        incoming_webhook_channel=request.incoming_webhook_channel,
        incoming_webhook_channel_id=request.incoming_webhook_channel_id,
        incoming_webhook_configuration_url=request.incoming_webhook_configuration_url,
        is_enterprise_install=request.is_enterprise_install,
        token_type=request.token_type,
        raw_data=request.model_dump(),
    )

    session.add(installation)
    session.commit()

    logger.info("slack_installation_created", id=installation.id)
    return _installation_to_response(installation)


@router.get("/slack/installations/find", response_model=Optional[SlackInstallationResponse])
def find_slack_installation(
    team_id: str,
    enterprise_id: Optional[str] = None,
    user_id: Optional[str] = None,
    is_enterprise_install: bool = False,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Find a Slack installation by team_id, enterprise_id, and user_id.

    Returns None (null) if not found.
    """
    query = session.query(SlackInstallation).filter(
        SlackInstallation.team_id == team_id,
    )

    if enterprise_id:
        query = query.filter(SlackInstallation.enterprise_id == enterprise_id)
    else:
        query = query.filter(SlackInstallation.enterprise_id.is_(None))

    if user_id:
        query = query.filter(SlackInstallation.user_id == user_id)
    else:
        query = query.filter(SlackInstallation.user_id.is_(None))

    installation = query.first()

    if not installation:
        return None

    return _installation_to_response(installation)


@router.delete("/slack/installations")
def delete_slack_installation(
    team_id: str,
    enterprise_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session: Session = Depends(get_db),
    service: str = Depends(require_internal_service),
):
    """
    Delete a Slack installation.
    """
    logger.info(
        "delete_slack_installation",
        enterprise_id=enterprise_id,
        team_id=team_id,
        user_id=user_id,
    )

    query = session.query(SlackInstallation).filter(
        SlackInstallation.team_id == team_id,
    )

    if enterprise_id:
        query = query.filter(SlackInstallation.enterprise_id == enterprise_id)
    else:
        query = query.filter(SlackInstallation.enterprise_id.is_(None))

    if user_id:
        query = query.filter(SlackInstallation.user_id == user_id)
    else:
        query = query.filter(SlackInstallation.user_id.is_(None))

    deleted_count = query.delete()
    session.commit()

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Installation not found")

    return {"deleted": True, "count": deleted_count}
