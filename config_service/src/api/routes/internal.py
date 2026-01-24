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

from src.db import repository
from src.db.config_models import NodeConfiguration
from src.db.models import OrgNode
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
