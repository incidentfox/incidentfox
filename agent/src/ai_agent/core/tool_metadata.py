"""
Tool Metadata Registry

Defines explicit metadata for all tools including integration requirements,
enabling validation and better UX.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolCategory(str, Enum):
    """Tool categories for organization."""

    OBSERVABILITY = "observability"
    DATA_WAREHOUSE = "data-warehouse"
    KUBERNETES = "kubernetes"
    AWS = "aws"
    CICD = "cicd"
    SCM = "scm"
    COMMUNICATION = "communication"
    ANALYTICS = "analytics"
    REASONING = "reasoning"
    OTHER = "other"


@dataclass
class IntegrationFieldMapping:
    """
    Maps an integration config field to how it's used by the tool.
    """

    integration: str
    field: str
    description: str
    required: bool = True


@dataclass
class ToolMetadata:
    """
    Metadata for a tool including integration requirements.
    """

    id: str
    name: str
    description: str
    category: ToolCategory

    # Integration requirements
    requires_integration: str | None = None
    integration_fields: list[IntegrationFieldMapping] = field(default_factory=list)

    # Additional metadata
    builtin: bool = True
    mcp_server: str | None = None
    enabled_by_default: bool = False


# =============================================================================
# Tool Registry
# =============================================================================

# Built-in tools with explicit integration requirements
TOOL_REGISTRY: dict[str, ToolMetadata] = {
    # Reasoning tools (no integration required)
    "think": ToolMetadata(
        id="think",
        name="Think",
        description="Internal reasoning and planning",
        category=ToolCategory.REASONING,
        enabled_by_default=True,
    ),
    "llm_call": ToolMetadata(
        id="llm_call",
        name="LLM Call",
        description="Get additional AI perspective",
        category=ToolCategory.REASONING,
        enabled_by_default=True,
    ),
    "web_search": ToolMetadata(
        id="web_search",
        name="Web Search",
        description="Search the web for information",
        category=ToolCategory.REASONING,
        enabled_by_default=True,
    ),
    # Coralogix tools (require coralogix integration)
    "search_coralogix_logs": ToolMetadata(
        id="search_coralogix_logs",
        name="Search Coralogix Logs",
        description="Search application logs in Coralogix",
        category=ToolCategory.OBSERVABILITY,
        requires_integration="coralogix",
        integration_fields=[
            IntegrationFieldMapping(
                integration="coralogix",
                field="api_key",
                description="Used for API authentication",
                required=True,
            ),
            IntegrationFieldMapping(
                integration="coralogix",
                field="region",
                description="Determines API endpoint (e.g., cx498)",
                required=True,
            ),
            IntegrationFieldMapping(
                integration="coralogix",
                field="team_id",
                description="Filters logs to your Coralogix team",
                required=False,
            ),
        ],
    ),
    "get_coralogix_error_logs": ToolMetadata(
        id="get_coralogix_error_logs",
        name="Get Coralogix Error Logs",
        description="Get recent error logs from Coralogix",
        category=ToolCategory.OBSERVABILITY,
        requires_integration="coralogix",
        integration_fields=[
            IntegrationFieldMapping(
                "coralogix", "api_key", "API authentication", required=True
            ),
            IntegrationFieldMapping(
                "coralogix", "region", "API endpoint", required=True
            ),
        ],
    ),
    "query_coralogix_metrics": ToolMetadata(
        id="query_coralogix_metrics",
        name="Query Coralogix Metrics",
        description="Query metrics from Coralogix",
        category=ToolCategory.OBSERVABILITY,
        requires_integration="coralogix",
        integration_fields=[
            IntegrationFieldMapping(
                "coralogix", "api_key", "API authentication", required=True
            ),
            IntegrationFieldMapping(
                "coralogix", "region", "API endpoint", required=True
            ),
        ],
    ),
    "search_coralogix_traces": ToolMetadata(
        id="search_coralogix_traces",
        name="Search Coralogix Traces",
        description="Search distributed traces in Coralogix",
        category=ToolCategory.OBSERVABILITY,
        requires_integration="coralogix",
        integration_fields=[
            IntegrationFieldMapping(
                "coralogix", "api_key", "API authentication", required=True
            ),
            IntegrationFieldMapping(
                "coralogix", "region", "API endpoint", required=True
            ),
        ],
    ),
    # Snowflake tools (require snowflake integration)
    "run_snowflake_query": ToolMetadata(
        id="run_snowflake_query",
        name="Run Snowflake Query",
        description="Execute SQL query in Snowflake data warehouse",
        category=ToolCategory.DATA_WAREHOUSE,
        requires_integration="snowflake",
        integration_fields=[
            IntegrationFieldMapping(
                "snowflake", "account", "Snowflake account identifier", required=True
            ),
            IntegrationFieldMapping(
                "snowflake", "username", "Database username", required=True
            ),
            IntegrationFieldMapping(
                "snowflake", "password", "Database password", required=True
            ),
            IntegrationFieldMapping(
                "snowflake", "warehouse", "Compute warehouse name", required=True
            ),
            IntegrationFieldMapping(
                "snowflake", "database", "Database name", required=False
            ),
            IntegrationFieldMapping(
                "snowflake", "schema", "Schema name", required=False
            ),
        ],
    ),
    "get_snowflake_schema": ToolMetadata(
        id="get_snowflake_schema",
        name="Get Snowflake Schema",
        description="Get database schema information from Snowflake",
        category=ToolCategory.DATA_WAREHOUSE,
        requires_integration="snowflake",
        integration_fields=[
            IntegrationFieldMapping(
                "snowflake", "account", "Snowflake account", required=True
            ),
            IntegrationFieldMapping("snowflake", "username", "Username", required=True),
            IntegrationFieldMapping("snowflake", "password", "Password", required=True),
        ],
    ),
    # Slack tools (require slack integration)
    "slack_send_message": ToolMetadata(
        id="slack_send_message",
        name="Send Slack Message",
        description="Send a message to Slack channel",
        category=ToolCategory.COMMUNICATION,
        requires_integration="slack",
        integration_fields=[
            IntegrationFieldMapping(
                "slack", "bot_token", "Slack bot token for API access", required=True
            ),
            IntegrationFieldMapping(
                "slack",
                "default_channel",
                "Default channel for messages",
                required=False,
            ),
        ],
    ),
    "slack_get_channel_history": ToolMetadata(
        id="slack_get_channel_history",
        name="Get Slack Channel History",
        description="Get recent messages from Slack channel",
        category=ToolCategory.COMMUNICATION,
        requires_integration="slack",
        integration_fields=[
            IntegrationFieldMapping(
                "slack", "bot_token", "Slack bot token", required=True
            ),
        ],
    ),
    # GitHub tools (require github integration)
    "search_github_code": ToolMetadata(
        id="search_github_code",
        name="Search GitHub Code",
        description="Search code in GitHub repositories",
        category=ToolCategory.SCM,
        requires_integration="github",
        integration_fields=[
            IntegrationFieldMapping(
                "github",
                "token",
                "GitHub personal access token or App token",
                required=True,
            ),
            IntegrationFieldMapping(
                "github", "org", "GitHub organization name", required=False
            ),
        ],
    ),
    "read_github_file": ToolMetadata(
        id="read_github_file",
        name="Read GitHub File",
        description="Read a file from GitHub repository",
        category=ToolCategory.SCM,
        requires_integration="github",
        integration_fields=[
            IntegrationFieldMapping("github", "token", "GitHub token", required=True),
        ],
    ),
    "get_file_content": ToolMetadata(
        id="get_file_content",
        name="Get File Content",
        description="Get file content from GitHub",
        category=ToolCategory.SCM,
        requires_integration="github",
        integration_fields=[
            IntegrationFieldMapping("github", "token", "GitHub token", required=True),
        ],
    ),
    "commit_file_changes": ToolMetadata(
        id="commit_file_changes",
        name="Commit File Changes",
        description="Commit changes to GitHub repository",
        category=ToolCategory.SCM,
        requires_integration="github",
        integration_fields=[
            IntegrationFieldMapping(
                "github", "token", "GitHub token with write access", required=True
            ),
        ],
    ),
    # Kubernetes tools (no integration, uses kubeconfig)
    "list_pods": ToolMetadata(
        id="list_pods",
        name="List Kubernetes Pods",
        description="List pods in Kubernetes namespace",
        category=ToolCategory.KUBERNETES,
    ),
    "get_pod_logs": ToolMetadata(
        id="get_pod_logs",
        name="Get Pod Logs",
        description="Get logs from Kubernetes pod",
        category=ToolCategory.KUBERNETES,
    ),
    "describe_pod": ToolMetadata(
        id="describe_pod",
        name="Describe Pod",
        description="Get detailed information about a Kubernetes pod",
        category=ToolCategory.KUBERNETES,
    ),
}


def get_tool_metadata(tool_id: str) -> ToolMetadata | None:
    """Get metadata for a tool by ID."""
    return TOOL_REGISTRY.get(tool_id)


def get_tools_by_integration(integration_id: str) -> list[ToolMetadata]:
    """Get all tools that require a specific integration."""
    return [
        tool
        for tool in TOOL_REGISTRY.values()
        if tool.requires_integration == integration_id
    ]


def get_required_fields_for_tool(tool_id: str) -> list[str]:
    """Get required integration fields for a tool."""
    tool = get_tool_metadata(tool_id)
    if not tool or not tool.integration_fields:
        return []

    return [mapping.field for mapping in tool.integration_fields if mapping.required]


def validate_tool_integration(
    tool_id: str, integrations: dict[str, Any]
) -> tuple[bool, list[str]]:
    """
    Validate that a tool's required integration is configured.

    Args:
        tool_id: Tool identifier
        integrations: Team's integration configuration

    Returns:
        Tuple of (is_valid, missing_fields)
    """
    tool = get_tool_metadata(tool_id)

    # Tool doesn't exist or doesn't require integration
    if not tool or not tool.requires_integration:
        return True, []

    integration = integrations.get(tool.requires_integration, {})

    # Integration values are stored at top-level (not nested in "config")
    # Check required fields directly on the integration object
    missing_fields = []
    for mapping in tool.integration_fields:
        if mapping.required and not integration.get(mapping.field):
            missing_fields.append(mapping.field)

    return len(missing_fields) == 0, missing_fields
