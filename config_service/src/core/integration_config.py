"""
Integration Configuration System

Manages integrations with different ownership levels:
- Org-level: Shared credentials (OpenAI, Slack app)
- Team-level: Team-specific settings (Grafana URL, default channel)

Config Structure:
{
    "integrations": {
        "openai": {
            "level": "org",
            "locked": true,
            "config_schema": {...},
            "api_key": "sk-..."
        },
        "slack": {
            "level": "org",
            "locked": false,
            "config_schema": {...},
            "team_config_schema": {...},
            "bot_token": "xoxb-...",
            "default_channel": "#incidents"
        },
        "grafana": {
            "level": "team",
            "config_schema": {...},
            "base_url": "https://grafana.team.com",
            "api_key": "glsa_..."
        }
    }
}

Note: Config values are stored at the top level of each integration object,
alongside metadata keys (level, locked, config_schema, team_config_schema).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class IntegrationLevel(str, Enum):
    """Level at which integration is configured."""

    ORG = "org"
    TEAM = "team"


@dataclass
class IntegrationFieldSchema:
    """Schema for an integration field."""

    name: str
    type: str  # string, secret, boolean, integer
    required: bool = False
    default: Any = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    placeholder: Optional[str] = None
    allowed_values: Optional[List[Any]] = None


@dataclass
class IntegrationSchema:
    """Schema for an integration."""

    id: str
    name: str
    description: str
    level: IntegrationLevel
    locked: bool = False
    required: bool = False

    # Fields configured at org level
    org_fields: List[IntegrationFieldSchema] = field(default_factory=list)

    # Fields configured at team level
    team_fields: List[IntegrationFieldSchema] = field(default_factory=list)

    # Documentation
    docs_url: Optional[str] = None
    setup_instructions: Optional[str] = None


# =============================================================================
# Integration Schemas
# =============================================================================

INTEGRATION_SCHEMAS: Dict[str, IntegrationSchema] = {
    "openai": IntegrationSchema(
        id="openai",
        name="OpenAI",
        description="OpenAI API for LLM access",
        level=IntegrationLevel.ORG,
        locked=True,
        required=True,
        org_fields=[
            IntegrationFieldSchema(
                name="api_key",
                type="secret",
                required=True,
                display_name="API Key",
                description="OpenAI API key",
            ),
            IntegrationFieldSchema(
                name="org_id",
                type="string",
                required=False,
                display_name="Organization ID",
                description="OpenAI organization ID (optional)",
            ),
        ],
        team_fields=[],
        docs_url="https://platform.openai.com/docs",
    ),
    "slack": IntegrationSchema(
        id="slack",
        name="Slack",
        description="Slack integration for notifications and triggers",
        level=IntegrationLevel.ORG,
        locked=False,
        required=False,
        org_fields=[
            IntegrationFieldSchema(
                name="bot_token",
                type="secret",
                required=True,
                display_name="Bot Token",
                description="Slack bot token (xoxb-...)",
            ),
            IntegrationFieldSchema(
                name="app_token",
                type="secret",
                required=False,
                display_name="App Token",
                description="Slack app token for socket mode (xapp-...)",
            ),
            IntegrationFieldSchema(
                name="signing_secret",
                type="secret",
                required=False,
                display_name="Signing Secret",
                description="For webhook verification",
            ),
        ],
        team_fields=[
            IntegrationFieldSchema(
                name="default_channel",
                type="string",
                required=False,
                display_name="Default Channel",
                description="Channel for incident notifications",
                placeholder="#incidents",
            ),
            IntegrationFieldSchema(
                name="mention_oncall",
                type="boolean",
                required=False,
                default=True,
                display_name="Mention On-Call",
                description="Whether to mention on-call in notifications",
            ),
            IntegrationFieldSchema(
                name="thread_replies",
                type="boolean",
                required=False,
                default=True,
                display_name="Thread Replies",
                description="Reply in threads instead of new messages",
            ),
        ],
        docs_url="https://api.slack.com/",
        setup_instructions="1. Create a Slack app\n2. Add bot scopes\n3. Install to workspace\n4. Copy bot token",
    ),
    "github": IntegrationSchema(
        id="github",
        name="GitHub",
        description="GitHub integration for code and PR access",
        level=IntegrationLevel.ORG,
        locked=False,
        required=False,
        org_fields=[
            IntegrationFieldSchema(
                name="token",
                type="secret",
                required=True,
                display_name="Access Token",
                description="Personal access token or GitHub App token",
            ),
            IntegrationFieldSchema(
                name="org",
                type="string",
                required=False,
                display_name="Organization",
                description="Default GitHub organization",
            ),
        ],
        team_fields=[
            IntegrationFieldSchema(
                name="default_repo",
                type="string",
                required=False,
                display_name="Default Repository",
                description="Default repo for this team",
                placeholder="owner/repo",
            ),
        ],
    ),
    "gitlab": IntegrationSchema(
        id="gitlab",
        name="GitLab",
        description="GitLab integration for code, MRs, and CI/CD pipelines",
        level=IntegrationLevel.ORG,
        locked=False,
        required=False,
        org_fields=[
            IntegrationFieldSchema(
                name="api_key",
                type="secret",
                required=True,
                display_name="Access Token",
                description="GitLab access token with api scope (personal, project, or group token)",
                placeholder="glpat-...",
            ),
            IntegrationFieldSchema(
                name="domain",
                type="string",
                required=False,
                default="https://gitlab.com",
                display_name="GitLab URL",
                description="GitLab instance URL (leave blank for gitlab.com)",
                placeholder="https://gitlab.yourcompany.com",
            ),
            IntegrationFieldSchema(
                name="verify_ssl",
                type="boolean",
                required=False,
                default=True,
                display_name="Verify SSL",
                description="Verify SSL certificates (disable for self-signed certs)",
            ),
        ],
        team_fields=[
            IntegrationFieldSchema(
                name="default_project",
                type="string",
                required=False,
                display_name="Default Project",
                description="Default project path for this team",
                placeholder="group/project",
            ),
        ],
        docs_url="https://docs.gitlab.com/ee/api/",
        setup_instructions="1. Log into your GitLab instance\n2. For personal: User Settings > Access Tokens\n   For enterprise: group/project Settings > Access Tokens\n3. Create a token with 'api' scope\n4. Enter the token and your GitLab URL",
    ),
    "kubernetes": IntegrationSchema(
        id="kubernetes",
        name="Kubernetes",
        description="Kubernetes cluster access",
        level=IntegrationLevel.ORG,
        locked=False,
        required=False,
        org_fields=[
            IntegrationFieldSchema(
                name="kubeconfig",
                type="secret",
                required=False,
                display_name="Kubeconfig",
                description="Base64-encoded kubeconfig (if not using in-cluster)",
            ),
        ],
        team_fields=[
            IntegrationFieldSchema(
                name="default_namespace",
                type="string",
                required=False,
                default="default",
                display_name="Default Namespace",
            ),
            IntegrationFieldSchema(
                name="allowed_namespaces",
                type="string",
                required=False,
                display_name="Allowed Namespaces",
                description="Comma-separated list of namespaces team can access",
            ),
        ],
    ),
    "grafana": IntegrationSchema(
        id="grafana",
        name="Grafana",
        description="Grafana for dashboards and Prometheus queries",
        level=IntegrationLevel.TEAM,
        locked=False,
        required=False,
        org_fields=[],
        team_fields=[
            IntegrationFieldSchema(
                name="base_url",
                type="string",
                required=True,
                display_name="Grafana URL",
                description="Your Grafana instance URL",
                placeholder="https://grafana.example.com",
            ),
            IntegrationFieldSchema(
                name="api_key",
                type="secret",
                required=True,
                display_name="API Key",
                description="Service account token or API key",
            ),
            IntegrationFieldSchema(
                name="default_datasource",
                type="string",
                required=False,
                default="prometheus",
                display_name="Default Datasource",
            ),
        ],
    ),
    "datadog": IntegrationSchema(
        id="datadog",
        name="Datadog",
        description="Datadog for metrics, logs, and APM",
        level=IntegrationLevel.ORG,
        locked=False,
        required=False,
        org_fields=[
            IntegrationFieldSchema(
                name="api_key",
                type="secret",
                required=True,
                display_name="API Key",
            ),
            IntegrationFieldSchema(
                name="app_key",
                type="secret",
                required=True,
                display_name="Application Key",
            ),
            IntegrationFieldSchema(
                name="site",
                type="string",
                required=False,
                default="datadoghq.com",
                display_name="Datadog Site",
                allowed_values=[
                    "datadoghq.com",
                    "datadoghq.eu",
                    "us3.datadoghq.com",
                    "us5.datadoghq.com",
                ],
            ),
        ],
        team_fields=[
            IntegrationFieldSchema(
                name="service_filter",
                type="string",
                required=False,
                display_name="Service Filter",
                description="Filter services by tag or name pattern",
            ),
        ],
    ),
    "newrelic": IntegrationSchema(
        id="newrelic",
        name="New Relic",
        description="New Relic for APM and infrastructure",
        level=IntegrationLevel.TEAM,
        locked=False,
        required=False,
        org_fields=[],
        team_fields=[
            IntegrationFieldSchema(
                name="api_key",
                type="secret",
                required=True,
                display_name="API Key",
                description="New Relic User API key",
            ),
            IntegrationFieldSchema(
                name="account_id",
                type="string",
                required=True,
                display_name="Account ID",
            ),
            IntegrationFieldSchema(
                name="region",
                type="string",
                required=False,
                default="US",
                allowed_values=["US", "EU"],
            ),
        ],
    ),
    "pagerduty": IntegrationSchema(
        id="pagerduty",
        name="PagerDuty",
        description="PagerDuty for incident management",
        level=IntegrationLevel.ORG,
        locked=False,
        required=False,
        org_fields=[
            IntegrationFieldSchema(
                name="api_key",
                type="secret",
                required=True,
                display_name="API Key",
            ),
        ],
        team_fields=[
            IntegrationFieldSchema(
                name="service_id",
                type="string",
                required=False,
                display_name="Service ID",
                description="PagerDuty service for this team",
            ),
            IntegrationFieldSchema(
                name="escalation_policy_id",
                type="string",
                required=False,
                display_name="Escalation Policy",
            ),
        ],
    ),
    "google_docs": IntegrationSchema(
        id="google_docs",
        name="Google Docs",
        description="Google Docs/Drive for runbooks and documentation",
        level=IntegrationLevel.ORG,
        locked=False,
        required=False,
        org_fields=[
            IntegrationFieldSchema(
                name="service_account_key",
                type="secret",
                required=True,
                display_name="Service Account Key",
                description="JSON key for service account",
            ),
        ],
        team_fields=[
            IntegrationFieldSchema(
                name="runbook_folder_id",
                type="string",
                required=False,
                display_name="Runbook Folder ID",
            ),
            IntegrationFieldSchema(
                name="postmortem_folder_id",
                type="string",
                required=False,
                display_name="Postmortem Folder ID",
            ),
        ],
    ),
    "tavily": IntegrationSchema(
        id="tavily",
        name="Tavily",
        description="Tavily Search API for web search capabilities",
        level=IntegrationLevel.ORG,
        locked=False,
        required=False,
        org_fields=[
            IntegrationFieldSchema(
                name="api_key",
                type="secret",
                required=True,
                display_name="API Key",
                description="Tavily API key",
                placeholder="tvly-...",
            ),
        ],
        team_fields=[],
        docs_url="https://tavily.com/",
        setup_instructions="1. Sign up at https://tavily.com/\n2. Get your API key from the dashboard\n3. Add it to the integration settings",
    ),
    "incident_io": IntegrationSchema(
        id="incident_io",
        name="incident.io",
        description="Incident management and alerting platform",
        level=IntegrationLevel.ORG,
        locked=False,
        required=False,
        org_fields=[
            IntegrationFieldSchema(
                name="api_key",
                type="secret",
                required=True,
                display_name="API Key",
                description="incident.io API key with View data permission",
                placeholder="inc_...",
            ),
        ],
        team_fields=[],
        docs_url="https://api-docs.incident.io/",
        setup_instructions="1. Go to your incident.io dashboard\n2. Click settings > API keys\n3. Create a new key with View data permission\n4. Copy the API key",
    ),
}


def get_integration_schema(integration_id: str) -> Optional[IntegrationSchema]:
    """Get schema for an integration."""
    return INTEGRATION_SCHEMAS.get(integration_id)


def get_all_integration_schemas() -> List[IntegrationSchema]:
    """Get all integration schemas."""
    return list(INTEGRATION_SCHEMAS.values())


# =============================================================================
# Integration Config Resolution
# =============================================================================


@dataclass
class ResolvedIntegration:
    """Resolved integration configuration with merged values."""

    id: str
    name: str
    level: IntegrationLevel
    enabled: bool
    configured: bool  # All required fields present

    # Merged config values
    config: Dict[str, Any]

    # What's missing
    missing_fields: List[str]


def resolve_integration(
    integration_id: str,
    org_config: Dict[str, Any],
    team_config: Optional[Dict[str, Any]] = None,
) -> ResolvedIntegration:
    """
    Resolve an integration's configuration.

    Args:
        integration_id: Integration identifier
        org_config: Organization-level config for this integration
        team_config: Team-level config for this integration

    Returns:
        ResolvedIntegration with merged values
    """
    schema = get_integration_schema(integration_id)
    if not schema:
        return ResolvedIntegration(
            id=integration_id,
            name=integration_id,
            level=IntegrationLevel.ORG,
            enabled=False,
            configured=False,
            config={},
            missing_fields=[],
        )

    # Start with defaults
    config = {}
    missing = []

    # Apply org fields
    for field in schema.org_fields:
        value = org_config.get(field.name)
        if value is not None:
            config[field.name] = value
        elif field.default is not None:
            config[field.name] = field.default
        elif field.required:
            missing.append(field.name)

    # Apply team fields
    team_cfg = team_config or {}
    for field in schema.team_fields:
        value = team_cfg.get(field.name)
        if value is not None:
            config[field.name] = value
        elif field.default is not None:
            config[field.name] = field.default
        elif field.required:
            missing.append(field.name)

    # Check if enabled
    enabled = org_config.get("enabled", True) and team_cfg.get("enabled", True)

    return ResolvedIntegration(
        id=integration_id,
        name=schema.name,
        level=schema.level,
        enabled=enabled,
        configured=len(missing) == 0,
        config=config,
        missing_fields=missing,
    )


def resolve_all_integrations(
    effective_config: Dict[str, Any],
) -> Dict[str, ResolvedIntegration]:
    """
    Resolve all integrations from effective config.

    Args:
        effective_config: The merged effective configuration

    Returns:
        Dict of integration_id → ResolvedIntegration
    """
    integrations_config = effective_config.get("integrations", {})
    result = {}

    for integration_id, schema in INTEGRATION_SCHEMAS.items():
        int_config = integrations_config.get(integration_id, {})
        org_config = int_config.get("config", {})
        team_config = int_config.get("team_config", {})

        result[integration_id] = resolve_integration(
            integration_id,
            org_config,
            team_config,
        )

    return result


def get_missing_required_integrations(
    effective_config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Get list of required integrations that are not fully configured.

    Returns:
        List of {id, name, missing_fields}
    """
    resolved = resolve_all_integrations(effective_config)
    missing = []

    for integration_id, integration in resolved.items():
        schema = get_integration_schema(integration_id)
        if schema and schema.required and not integration.configured:
            missing.append(
                {
                    "id": integration_id,
                    "name": integration.name,
                    "missing_fields": integration.missing_fields,
                }
            )

    return missing


def get_integration_config_for_tool(
    tool_name: str,
    effective_config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get integration configuration for a specific tool.

    Maps tool names to their integration configs.
    """
    tool_to_integration = {
        "grafana_query_prometheus": "grafana",
        "grafana_list_dashboards": "grafana",
        "grafana_get_dashboard": "grafana",
        "query_datadog_metrics": "datadog",
        "search_datadog_logs": "datadog",
        "query_newrelic_nrql": "newrelic",
        "get_apm_summary": "newrelic",
        "search_github_code": "github",
        "read_github_file": "github",
        "gitlab_list_projects": "gitlab",
        "gitlab_get_project": "gitlab",
        "gitlab_search_projects": "gitlab",
        "gitlab_get_pipelines": "gitlab",
        "gitlab_get_pipeline_jobs": "gitlab",
        "gitlab_get_merge_requests": "gitlab",
        "gitlab_get_mr": "gitlab",
        "gitlab_get_mr_changes": "gitlab",
        "gitlab_add_mr_comment": "gitlab",
        "gitlab_list_commits": "gitlab",
        "gitlab_get_commit": "gitlab",
        "gitlab_list_branches": "gitlab",
        "gitlab_list_tags": "gitlab",
        "gitlab_list_issues": "gitlab",
        "gitlab_get_issue": "gitlab",
        "gitlab_create_issue": "gitlab",
        "search_slack_messages": "slack",
        "web_search": "tavily",
        "incidentio_list_incidents": "incident_io",
        "incidentio_get_incident": "incident_io",
        "incidentio_get_incident_updates": "incident_io",
        "incidentio_list_incidents_by_date_range": "incident_io",
        "incidentio_list_severities": "incident_io",
        "incidentio_list_incident_types": "incident_io",
        "incidentio_get_alert_analytics": "incident_io",
        "incidentio_calculate_mttr": "incident_io",
    }

    integration_id = tool_to_integration.get(tool_name)
    if not integration_id:
        return {}

    resolved = resolve_all_integrations(effective_config)
    integration = resolved.get(integration_id)

    if integration and integration.configured:
        return integration.config

    return {}
