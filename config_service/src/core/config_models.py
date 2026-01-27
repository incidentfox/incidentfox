"""Configuration models for org/group/team nodes.

Focus is on team-facing fields with arbitrary-depth inheritance across lineage.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TokensVaultPaths(BaseModel):
    openai_token: Optional[str] = None
    slack_bot: Optional[str] = None
    glean: Optional[str] = None


class AgentToggles(BaseModel):
    prompt: str = ""
    enabled: Optional[bool] = None
    disable_default_tools: List[str] = Field(default_factory=list)
    enable_extra_tools: List[str] = Field(default_factory=list)


class AgentsConfig(BaseModel):
    investigation_agent: Optional[AgentToggles] = None
    code_fix_agent: Optional[AgentToggles] = None


class KnowledgeSources(BaseModel):
    grafana: List[str] = Field(default_factory=list)
    google: List[str] = Field(default_factory=list)
    confluence: List[str] = Field(default_factory=list)


class AlertsConfig(BaseModel):
    disabled: List[str] = Field(default_factory=list)


class AIPipelineConfig(BaseModel):
    """Configuration for AI Learning Pipeline.

    Controls whether the AI pipeline is enabled for a team and the schedule
    for pipeline runs that process incident data and build knowledge base.

    Example:
        {
            "enabled": true,
            "schedule": "0 2 * * *"
        }
    """

    enabled: bool = Field(default=False, description="Enable AI pipeline")
    schedule: str = Field(
        default="0 2 * * *",
        description="Cron schedule for pipeline runs (default: 2 AM daily)",
    )


class DependencyDiscoverySourcesConfig(BaseModel):
    """Toggle which discovery sources to use."""

    new_relic: bool = Field(
        default=True, description="Use New Relic distributed tracing"
    )
    cloudwatch: bool = Field(default=False, description="Use AWS X-Ray traces")
    prometheus: bool = Field(
        default=False, description="Use Prometheus service mesh metrics"
    )
    datadog: bool = Field(default=False, description="Use Datadog APM traces")


class DependencyDiscoveryConfig(BaseModel):
    """Configuration for service dependency discovery.

    Controls whether dependency discovery is enabled for a team,
    the schedule for discovery jobs, and which sources to query.

    Example:
        {
            "enabled": true,
            "schedule": "0 */2 * * *",
            "sources": {
                "new_relic": true,
                "datadog": true
            },
            "time_range_hours": 24,
            "min_confidence": 0.7
        }
    """

    enabled: bool = Field(default=False, description="Enable dependency discovery")
    schedule: str = Field(
        default="0 */2 * * *",
        description="Cron schedule for discovery (default: every 2 hours)",
    )
    sources: DependencyDiscoverySourcesConfig = Field(
        default_factory=DependencyDiscoverySourcesConfig,
        description="Which discovery sources to use",
    )
    time_range_hours: int = Field(
        default=24,
        description="How far back to look for dependencies (hours)",
    )
    min_call_count: int = Field(
        default=5,
        description="Minimum calls to consider a valid dependency",
    )
    min_confidence: float = Field(
        default=0.5,
        description="Minimum confidence threshold (0.0 to 1.0)",
    )


class CorrelationConfig(BaseModel):
    """Configuration for alert correlation.

    Controls whether alert correlation is enabled for a team.
    When enabled, incoming alerts are correlated using temporal,
    topology, and semantic analysis to identify related incidents.

    Example:
        {
            "enabled": true,
            "temporal_window_seconds": 300,
            "semantic_threshold": 0.75
        }
    """

    enabled: bool = Field(
        default=False,
        description="Enable alert correlation (feature flag)",
    )
    temporal_window_seconds: int = Field(
        default=300,
        description="Time window in seconds for temporal correlation",
    )
    semantic_threshold: float = Field(
        default=0.75,
        description="Similarity threshold for semantic correlation (0.0 to 1.0)",
    )


# =============================================================================
# Knowledge Base / Self-Learning System Config
# =============================================================================


class KnowledgeIngestionSourceConfig(BaseModel):
    """Configuration for individual ingestion sources.

    Each source type can be enabled/disabled and has source-specific settings.
    These inherit from parent configs (org → team) with override capability.
    """

    # Web sources (Confluence, Google Docs, etc.)
    confluence_enabled: bool = Field(default=False, description="Ingest from Confluence")
    confluence_spaces: List[str] = Field(
        default_factory=list,
        description="Confluence space keys to ingest (empty = all accessible)",
    )
    google_docs_enabled: bool = Field(default=False, description="Ingest from Google Docs")
    google_docs_folders: List[str] = Field(
        default_factory=list,
        description="Google Drive folder IDs to ingest",
    )

    # Grafana dashboards and alerts
    grafana_enabled: bool = Field(default=False, description="Ingest Grafana dashboards")
    grafana_folders: List[str] = Field(
        default_factory=list,
        description="Grafana folder UIDs to ingest (empty = all)",
    )

    # GitHub/GitLab repos
    github_enabled: bool = Field(default=False, description="Ingest from GitHub repos")
    github_repos: List[str] = Field(
        default_factory=list,
        description="GitHub repos to ingest (format: owner/repo)",
    )
    github_paths: List[str] = Field(
        default_factory=lambda: ["docs/", "runbooks/", "*.md"],
        description="Glob patterns for files to ingest",
    )

    # Incident history (from incident management tools)
    incidents_enabled: bool = Field(
        default=True,
        description="Ingest past incidents and postmortems",
    )
    incidents_lookback_days: int = Field(
        default=90,
        description="How many days of incident history to ingest",
    )

    # Slack channels (for tribal knowledge)
    slack_enabled: bool = Field(default=False, description="Ingest from Slack channels")
    slack_channels: List[str] = Field(
        default_factory=list,
        description="Slack channel IDs to ingest",
    )


class KnowledgeIngestionConfig(BaseModel):
    """Configuration for knowledge base ingestion.

    Controls scheduled ingestion of documentation, runbooks, and other
    knowledge sources into the team's knowledge base (RAPTOR trees).

    Inherits from parent config with merge semantics:
    - enabled: child overrides parent
    - schedule: child overrides parent
    - sources: deep merge (child sources override parent sources)

    Example:
        {
            "enabled": true,
            "schedule": "0 3 * * *",
            "sources": {
                "confluence_enabled": true,
                "confluence_spaces": ["ENG", "OPS"],
                "incidents_enabled": true
            }
        }
    """

    enabled: bool = Field(
        default=False,
        description="Enable scheduled knowledge ingestion",
    )
    schedule: str = Field(
        default="0 3 * * *",
        description="Cron schedule for ingestion (default: 3 AM daily)",
    )
    sources: KnowledgeIngestionSourceConfig = Field(
        default_factory=KnowledgeIngestionSourceConfig,
        description="Which sources to ingest from",
    )
    chunk_size: int = Field(
        default=512,
        description="Target chunk size for text splitting (tokens)",
    )
    chunk_overlap: int = Field(
        default=50,
        description="Overlap between chunks (tokens)",
    )
    max_documents_per_run: int = Field(
        default=1000,
        description="Maximum documents to process per ingestion run",
    )


class KnowledgeMaintenanceConfig(BaseModel):
    """Configuration for knowledge base maintenance.

    Controls automated maintenance tasks like:
    - Knowledge decay (reducing importance of stale information)
    - Tree rebalancing (optimizing retrieval performance)
    - Gap detection (finding missing knowledge)
    - Contradiction detection (finding conflicting information)

    Example:
        {
            "enabled": true,
            "schedule": "0 4 * * 0",
            "decay_enabled": true,
            "decay_half_life_days": 180
        }
    """

    enabled: bool = Field(
        default=False,
        description="Enable scheduled maintenance",
    )
    schedule: str = Field(
        default="0 4 * * 0",
        description="Cron schedule for maintenance (default: 4 AM Sundays)",
    )
    decay_enabled: bool = Field(
        default=True,
        description="Enable knowledge decay (reduce stale knowledge importance)",
    )
    decay_half_life_days: int = Field(
        default=180,
        description="Half-life for knowledge decay in days",
    )
    rebalance_enabled: bool = Field(
        default=True,
        description="Enable tree rebalancing for optimal retrieval",
    )
    gap_detection_enabled: bool = Field(
        default=True,
        description="Enable detection of knowledge gaps",
    )
    contradiction_detection_enabled: bool = Field(
        default=True,
        description="Enable detection of contradicting knowledge",
    )


class KnowledgeTeachingConfig(BaseModel):
    """Configuration for agent-taught knowledge.

    Controls how knowledge taught by agents during investigations
    is handled - auto-approval vs human review.

    Example:
        {
            "auto_approve_threshold": 0.8,
            "require_review_for_contradictions": true
        }
    """

    enabled: bool = Field(
        default=True,
        description="Allow agents to teach the knowledge base",
    )
    auto_approve_threshold: float = Field(
        default=0.8,
        description="Auto-approve teachings with confidence >= this (0.0 to 1.0)",
    )
    require_review_for_contradictions: bool = Field(
        default=True,
        description="Always require human review for potential contradictions",
    )
    require_review_for_procedural: bool = Field(
        default=False,
        description="Require human review for procedural (runbook-like) knowledge",
    )
    max_pending_per_day: int = Field(
        default=50,
        description="Maximum pending teachings per day (prevents spam)",
    )


class SelfLearningConfig(BaseModel):
    """Unified configuration for the Self-Learning System.

    The Self-Learning System includes:
    - Knowledge Ingestion: Scheduled pulling from documentation sources
    - Knowledge Maintenance: Tree health, decay, rebalancing
    - Knowledge Teaching: Agent-learned knowledge processing
    - AI Pipeline: Gap analysis and improvement proposals

    Example:
        {
            "enabled": true,
            "ingestion": {"enabled": true, "schedule": "0 3 * * *"},
            "maintenance": {"enabled": true, "schedule": "0 4 * * 0"},
            "teaching": {"enabled": true, "auto_approve_threshold": 0.8}
        }
    """

    enabled: bool = Field(
        default=False,
        description="Master switch for the entire self-learning system",
    )
    ingestion: KnowledgeIngestionConfig = Field(
        default_factory=KnowledgeIngestionConfig,
        description="Knowledge ingestion configuration",
    )
    maintenance: KnowledgeMaintenanceConfig = Field(
        default_factory=KnowledgeMaintenanceConfig,
        description="Knowledge maintenance configuration",
    )
    teaching: KnowledgeTeachingConfig = Field(
        default_factory=KnowledgeTeachingConfig,
        description="Agent teaching configuration",
    )


class TeamLevelConfig(BaseModel):
    team_name: Optional[str] = None
    tokens_vault_path: Optional[TokensVaultPaths] = None
    mcp_servers: List[str] = Field(default_factory=list)
    a2a_agents: List[str] = Field(default_factory=list)
    slack_group_to_ping: Optional[str] = None
    knowledge_source: Optional[KnowledgeSources] = None
    knowledge_tree: Optional[str] = None
    agents: Optional[AgentsConfig] = None
    alerts: Optional[AlertsConfig] = None
    ai_pipeline: Optional[AIPipelineConfig] = None
    dependency_discovery: Optional[DependencyDiscoveryConfig] = None
    correlation: Optional[CorrelationConfig] = None
    # Self-Learning System (knowledge ingestion, maintenance, teaching)
    self_learning: Optional[SelfLearningConfig] = None

    model_config = ConfigDict(extra="allow")


IMMUTABLE_KEYS: List[str] = ["team_name"]


def validate_immutable_fields(
    original: TeamLevelConfig, update: TeamLevelConfig
) -> None:
    """Raise ValueError if an immutable field is present/changed in update.

    For team-scoped writes we currently enforce immutables strictly: clients must not
    set these fields at all (even if original is None).
    """
    for key in IMMUTABLE_KEYS:
        update_value = getattr(update, key, None)
        if update_value is not None:
            raise ValueError(f"Field '{key}' is immutable and cannot be set/changed")
