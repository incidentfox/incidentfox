import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


# =============================================================================
# Permission constants for token scopes
# =============================================================================
class TokenPermission:
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    TOKENS_ISSUE = "tokens:issue"
    TOKENS_REVOKE = "tokens:revoke"
    AGENT_INVOKE = "agent:invoke"
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"

    # Default permissions for new tokens
    DEFAULT_TEAM = [CONFIG_READ, CONFIG_WRITE, AGENT_INVOKE]
    ALL = [
        CONFIG_READ,
        CONFIG_WRITE,
        TOKENS_ISSUE,
        TOKENS_REVOKE,
        AGENT_INVOKE,
        AUDIT_READ,
        AUDIT_EXPORT,
    ]


class NodeType(str, enum.Enum):
    org = "org"
    team = "team"


class OrgNode(Base):
    __tablename__ = "org_nodes"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    parent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    node_type: Mapped[NodeType] = mapped_column(
        Enum(NodeType, name="node_type"), nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "parent_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_org_nodes_parent",
            ondelete="SET NULL",
        ),
        Index("ix_org_nodes_org_parent", "org_id", "parent_id"),
        Index("ix_org_nodes_org_type", "org_id", "node_type"),
    )


class TeamToken(Base):
    __tablename__ = "team_tokens"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_node_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    token_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    issued_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # New fields for enterprise security
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    permissions: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=lambda: TokenPermission.DEFAULT_TEAM,
    )
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "team_node_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_team_tokens_team_node",
            ondelete="CASCADE",
        ),
        Index("ix_team_tokens_org_team", "org_id", "team_node_id"),
        Index("ux_team_tokens_token_id", "token_id", unique=True),
    )

    def is_expired(self) -> bool:
        """Check if token has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at.replace(tzinfo=None)

    def has_permission(self, permission: str) -> bool:
        """Check if token has a specific permission."""
        return permission in (self.permissions or [])


class OrgAdminToken(Base):
    """
    Per-organization admin tokens.

    Each organization has its own admin(s) with tokens scoped to that org only.
    This replaces the global admin token for multi-tenant deployments.
    """

    __tablename__ = "org_admin_tokens"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    issued_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Security fields
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        # No FK - org_nodes has composite PK; app layer validates org existence
        Index("ix_org_admin_tokens_org", "org_id"),
        Index("ux_org_admin_tokens_token_id", "token_id", unique=True),
    )

    def is_expired(self) -> bool:
        """Check if token has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at.replace(tzinfo=None)


class ImpersonationJTI(Base):
    """
    Optional tracking table for IncidentFox-issued team impersonation JWTs.

    Notes:
    - This is NOT required for token validation by default (JWT signature + exp are enough).
    - When enabled, it can be used for auditing and (optionally) to require that a token's `jti`
      was minted by this config_service instance (DB allowlist).
    - This is not a one-time-use token table; impersonation JWTs are bearer tokens and may be reused
      across multiple requests during their TTL.
    """

    __tablename__ = "impersonation_jtis"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team_node_id: Mapped[str] = mapped_column(String(128), nullable=False)

    subject: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "team_node_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_impersonation_jtis_team_node",
            ondelete="CASCADE",
        ),
        Index("ix_impersonation_jtis_org_team", "org_id", "team_node_id"),
        Index("ix_impersonation_jtis_expires_at", "expires_at"),
    )


class KnowledgeEdge(Base):
    """
    Minimal team-scoped “knowledge base” edges.

    MVP:
    - Stored in the same RDS as config_service (so we can auth with existing team tokens)
    - Queried via team-scoped endpoints for lightweight retrieval
    """

    __tablename__ = "knowledge_edges"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_node_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    entity: Mapped[str] = mapped_column(String(256), primary_key=True)
    relationship: Mapped[str] = mapped_column(String(64), primary_key=True)
    target: Mapped[str] = mapped_column(String(256), primary_key=True)

    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "team_node_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_knowledge_edges_team_node",
            ondelete="CASCADE",
        ),
        Index("ix_knowledge_edges_org_team", "org_id", "team_node_id"),
        Index("ix_knowledge_edges_relationship", "relationship"),
    )


class KnowledgeDocument(Base):
    """
    Team-scoped knowledge documents/chunks for RAG-style retrieval.

    Storage MVP:
    - Plain text content (chunk) stored in Postgres
    - Simple substring search via API (no embeddings yet)
    """

    __tablename__ = "knowledge_documents"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_node_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(256), primary_key=True)

    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    source_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "team_node_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_knowledge_documents_team_node",
            ondelete="CASCADE",
        ),
        Index("ix_knowledge_documents_org_team", "org_id", "team_node_id"),
        Index("ix_knowledge_documents_source", "source_type", "source_id"),
    )


class PendingKnowledgeTeaching(Base):
    """
    Pending knowledge teachings from agents awaiting review.

    When an agent learns something during an investigation, it can "teach"
    the knowledge base. Depending on confidence and team settings, teachings
    may be auto-approved or queued for human review.

    Lifecycle:
    1. Agent calls teach_knowledge_base() tool
    2. Teaching is created with status="pending" (or "auto_approved" if high confidence)
    3. Human reviews and approves/rejects
    4. On approval, knowledge is added to the RAPTOR tree
    """

    __tablename__ = "pending_knowledge_teachings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    team_node_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # The knowledge being taught
    content: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="procedural"
    )  # procedural, factual, temporal, relational

    # Metadata about the teaching
    source: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="agent_learning"
    )
    confidence: Mapped[float] = mapped_column(
        nullable=False, server_default="0.7"
    )
    related_services: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Context from the investigation
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    agent_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    task_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    incident_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Similarity analysis (did we find similar existing knowledge?)
    similar_node_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    similarity_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    is_potential_contradiction: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )
    contradiction_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lifecycle
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    proposed_by: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )  # agent or user who initiated

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )  # pending, auto_approved, approved, rejected, merged

    # Review
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Result after approval
    created_node_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    merged_with_node_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "team_node_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_pending_knowledge_teachings_team_node",
            ondelete="CASCADE",
        ),
        Index("ix_pending_knowledge_teachings_org_team", "org_id", "team_node_id"),
        Index("ix_pending_knowledge_teachings_status", "status"),
        Index("ix_pending_knowledge_teachings_proposed_at", "proposed_at"),
    )


# =============================================================================
# Enterprise Security Models
# =============================================================================


class SecurityPolicy(Base):
    """
    Org-level security policies and guardrails.

    These settings apply org-wide and cannot be overridden by teams.
    """

    __tablename__ = "security_policies"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Token lifecycle policies
    token_expiry_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # null = never
    token_warn_before_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=7
    )
    token_revoke_inactive_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # null = don't auto-revoke

    # Configuration guardrails
    locked_settings: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    max_values: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    required_settings: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    allowed_values: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )

    # Change policies
    require_approval_for_prompts: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    require_approval_for_tools: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    log_all_changes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Metadata
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class TokenAudit(Base):
    """
    Audit log for token-related security events.

    Event types: issued, revoked, expired, used, permission_denied
    """

    __tablename__ = "token_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team_node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    token_id: Mapped[str] = mapped_column(String(128), nullable=False)

    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    actor: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("ix_token_audit_org_team", "org_id", "team_node_id"),
        Index("ix_token_audit_token_id", "token_id"),
        Index("ix_token_audit_event_at", "event_at"),
        Index("ix_token_audit_event_type", "event_type"),
    )


class Integration(Base):
    """
    Track connected external services and their status.
    """

    __tablename__ = "integrations"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    integration_id: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )  # slack, openai, k8s, datadog

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_configured"
    )
    display_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    config: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )

    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class PendingConfigChange(Base):
    """
    Pending configuration changes awaiting admin approval.

    Used when security policies require approval for:
    - Custom prompt changes (require_approval_for_prompts)
    - Tool enablement changes (require_approval_for_tools)
    """

    __tablename__ = "pending_config_changes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # What's changing
    change_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "prompt", "tools", "config"
    change_path: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    proposed_value: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    previous_value: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Request metadata
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Approval status
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending, approved, rejected
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "node_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_pending_config_changes_node",
            ondelete="CASCADE",
        ),
        Index("ix_pending_config_changes_org_id", "org_id"),
        Index("ix_pending_config_changes_status", "status"),
        Index("ix_pending_config_changes_requested_at", "requested_at"),
    )


class AgentRun(Base):
    """
    Track all agent runs for audit and analytics.

    Each run records:
    - How it was triggered (Slack, API, Web UI)
    - Which agent ran and for how long
    - The result, tool calls, and any errors
    """

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team_node_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Trigger info
    trigger_source: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # slack, api, web_ui
    trigger_actor: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    trigger_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Execution
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # running, completed, failed, timeout

    # Results
    tool_calls_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_json: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # Store as float for precision

    # Extra metadata
    extra_metadata: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    __table_args__ = (
        Index("ix_agent_runs_org_id", "org_id"),
        Index("ix_agent_runs_team_node_id", "org_id", "team_node_id"),
        Index("ix_agent_runs_correlation_id", "correlation_id"),
        Index("ix_agent_runs_started_at", "started_at"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_trigger_source", "trigger_source"),
    )


class AgentToolCall(Base):
    """
    Individual tool calls within an agent run.

    Provides detailed execution traces for:
    - Understanding which tools agents use and how
    - Identifying patterns in tool usage
    - Debugging failed tool calls
    - Training AI pipeline to recommend tools
    """

    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Agent info (for sub-agent tracking)
    agent_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    parent_agent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Tool info
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_input: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    tool_output: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Truncated output

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="success"
    )  # success, error
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Ordering
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_agent_tool_calls_run_id", "run_id"),
        Index("ix_agent_tool_calls_tool_name", "tool_name"),
        Index("ix_agent_tool_calls_started_at", "started_at"),
    )


class ConversationMapping(Base):
    """
    Map external session identifiers to OpenAI conversation IDs.

    This enables conversation resumption for Slack threads, GitHub PRs, etc.
    by storing the mapping between our identifier and OpenAI's conversation_id.

    Example:
    - session_id: "slack_C0A8JDPU3SR_1768599264_192439" (our identifier)
    - openai_conversation_id: "conv_xxx..." (OpenAI's identifier)
    """

    __tablename__ = "conversation_mappings"

    session_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    openai_conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # Context
    org_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    team_node_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    session_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # slack, github, api

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_conversation_mappings_openai_id", "openai_conversation_id"),
        Index("ix_conversation_mappings_org_team", "org_id", "team_node_id"),
        Index("ix_conversation_mappings_type", "session_type"),
    )


# =============================================================================
# Organization Settings (per-org)
# =============================================================================


class OrgSettings(Base):
    """Per-organization settings (telemetry, feature flags, etc)."""

    __tablename__ = "org_settings"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Telemetry opt-in/out
    telemetry_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


# =============================================================================
# Team Output Configuration
# =============================================================================


class TeamOutputConfig(Base):
    """
    Team-level output destination preferences for agent results.

    Controls where agent outputs are delivered (Slack, GitHub, PagerDuty, etc.)
    and trigger-specific routing rules.
    """

    __tablename__ = "team_output_configs"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_node_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    # Default destinations (JSON array)
    # Example: [{"type": "slack", "channel_id": "C123456", "channel_name": "#incidents"}]
    default_destinations: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True, default=list
    )

    # Trigger-specific overrides (JSON object)
    # Example: {"slack": "reply_in_thread", "github": "comment_on_pr", "api": "use_default"}
    trigger_overrides: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True, default=dict
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "team_node_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_team_output_configs_team_node",
            ondelete="CASCADE",
        ),
        Index("ix_team_output_configs_org_team", "org_id", "team_node_id"),
    )


# =============================================================================
# SSO Configuration (per-org)
# =============================================================================


class SSOConfig(Base):
    """Per-organization SSO configuration."""

    __tablename__ = "sso_configs"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Provider type: google, azure, okta, oidc (generic)
    provider_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="oidc"
    )
    provider_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # OIDC Configuration
    issuer: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    client_secret_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scopes: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, default="openid email profile"
    )

    # Azure AD specific
    tenant_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Claim mappings
    email_claim: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, default="email"
    )
    name_claim: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, default="name"
    )
    groups_claim: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, default="groups"
    )
    admin_group: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Domain restrictions (comma-separated)
    allowed_domains: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


# =============================================================================
# Template System Models
# =============================================================================


class Template(Base):
    """
    Use case templates that can be applied to teams.

    Templates are pre-configured multi-agent systems optimized for specific use cases.
    Teams can browse the template marketplace and apply templates to their config.
    """

    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Metadata
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detailed_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    use_case_category: Mapped[str] = mapped_column(String(50), nullable=False)

    # Template Content
    template_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )

    # Visual Assets
    icon_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    example_scenarios: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    demo_video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Template Type
    is_system_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    org_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Visibility & Versioning
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")

    # Requirements
    required_mcps: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    required_tools: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    minimum_agent_version: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Analytics
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_rating: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_templates_category", "use_case_category"),
        Index("ix_templates_published", "is_published", "is_system_template"),
        Index("ix_templates_org", "org_id"),
    )


class TemplateApplication(Base):
    """
    Tracks which teams have applied which templates.

    Each team can have one active template at a time.
    Tracks customizations made after template application.
    """

    __tablename__ = "template_applications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # References
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team_node_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # Application Details
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    applied_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    template_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # Customization Tracking
    has_customizations: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    customization_summary: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            name="fk_template_applications_template",
            ondelete="CASCADE",
        ),
        Index("ix_template_applications_template", "template_id"),
        Index("ix_template_applications_team", "team_node_id"),
        Index("ix_template_applications_active", "is_active"),
    )


class TemplateAnalytics(Base):
    """
    Usage analytics and feedback for templates.

    Tracks how teams use templates, success rates, and user feedback.
    """

    __tablename__ = "template_analytics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team_node_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # Metrics
    first_agent_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_agent_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_agent_success_rate: Mapped[Optional[float]] = mapped_column(
        Integer, nullable=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Feedback
    user_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            name="fk_template_analytics_template",
            ondelete="CASCADE",
        ),
        Index("ix_template_analytics_template", "template_id"),
        Index("ix_template_analytics_team", "team_node_id"),
    )


# =============================================================================
# Agent Session Persistence (File-Sync Approach)
# =============================================================================


class AgentSession(Base):
    """
    Agent session persistence for container restart resilience.

    Stores SDK session files (.jsonl) in database to survive pod restarts.
    Based on approach from: https://github.com/anthropics/claude-agent-sdk-typescript/issues/97
    """

    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Session identification
    investigation_id: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False
    )
    sdk_session_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Session file content (entire .jsonl file)
    session_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Stats for monitoring
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_cost_usd: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 6), nullable=True
    )

    # Additional session metadata
    session_metadata: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    __table_args__ = (
        Index("idx_agent_sessions_investigation_id", "investigation_id"),
        Index("idx_agent_sessions_sdk_session_id", "sdk_session_id"),
        Index("idx_agent_sessions_status", "status"),
        Index("idx_agent_sessions_updated_at", "updated_at"),
    )


# =============================================================================
# Remediation Approval Workflow
# =============================================================================


class PendingRemediation(Base):
    """Pending remediation actions awaiting approval."""

    __tablename__ = "pending_remediations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    team_node_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Action details
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(256), nullable=False)
    parameters: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Context
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    urgency: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="medium"
    )
    rollback_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Agent context
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    agent_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    investigation_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Lifecycle
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    proposed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )

    # Review
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Execution
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_result: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    execution_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Rollback tracking
    rolled_back: Mapped[bool] = mapped_column(Boolean, default=False)
    rollback_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rollback_result: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )


# =============================================================================
# Meeting Data (from Circleback webhooks)
# =============================================================================


class MeetingData(Base):
    """
    Store meeting transcription data received from webhook providers.

    This data is used by agents to get context from incident-related meetings.
    Currently supports data from Circleback webhooks (push model).
    """

    __tablename__ = "meeting_data"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_node_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(256), primary_key=True)

    # Meeting metadata
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # circleback, fireflies, etc
    name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    meeting_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    meeting_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Participants
    attendees: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Content
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )  # [{speaker, text, timestamp}]
    action_items: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )  # [{title, assignee, status}]
    summary: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )  # {overview, key_points, decisions}

    # Full raw payload for debugging
    raw_payload: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "team_node_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_meeting_data_team_node",
            ondelete="CASCADE",
        ),
        Index("ix_meeting_data_org_team", "org_id", "team_node_id"),
        Index("ix_meeting_data_provider", "provider"),
        Index("ix_meeting_data_meeting_time", "meeting_time"),
        Index("ix_meeting_data_created_at", "created_at"),
    )
