"""
Shared utility for generating config_required responses.

This module provides a standardized way to generate structured responses
when an integration is not configured. The CLI can detect these responses
and offer interactive configuration prompts.

Pattern adopted from kubernetes.py which successfully implements this flow.
"""

import json
from typing import Any

from .logging import get_logger

logger = get_logger(__name__)

# Default documentation URLs for integrations
INTEGRATION_DOCS = {
    "github": "https://docs.incidentfox.ai/integrations/github",
    "aws": "https://docs.incidentfox.ai/integrations/aws",
    "slack": "https://docs.incidentfox.ai/integrations/slack",
    "datadog": "https://docs.incidentfox.ai/integrations/datadog",
    "sentry": "https://docs.incidentfox.ai/integrations/sentry",
    "jira": "https://docs.incidentfox.ai/integrations/jira",
    "grafana": "https://docs.incidentfox.ai/integrations/grafana",
    "pagerduty": "https://docs.incidentfox.ai/integrations/pagerduty",
    "coralogix": "https://docs.incidentfox.ai/integrations/coralogix",
    "snowflake": "https://docs.incidentfox.ai/integrations/snowflake",
    "elasticsearch": "https://docs.incidentfox.ai/integrations/elasticsearch",
    "splunk": "https://docs.incidentfox.ai/integrations/splunk",
    "newrelic": "https://docs.incidentfox.ai/integrations/newrelic",
    "azure": "https://docs.incidentfox.ai/integrations/azure",
    "gcp": "https://docs.incidentfox.ai/integrations/gcp",
    "bigquery": "https://docs.incidentfox.ai/integrations/bigquery",
    "gitlab": "https://docs.incidentfox.ai/integrations/gitlab",
    "confluence": "https://docs.incidentfox.ai/integrations/confluence",
    "notion": "https://docs.incidentfox.ai/integrations/notion",
    "linear": "https://docs.incidentfox.ai/integrations/linear",
    "kubernetes": "https://docs.incidentfox.ai/integrations/kubernetes",
    "tavily": "https://docs.incidentfox.ai/integrations/tavily",
}

# Default help options for common integrations
INTEGRATION_HELP = {
    "github": [
        "Set GITHUB_TOKEN environment variable with a personal access token",
        "Or configure via team settings at /team/settings/integrations/github",
        "Get a token at https://github.com/settings/tokens (needs 'repo' scope)",
    ],
    "aws": [
        "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables",
        "Or configure ~/.aws/credentials with your AWS credentials",
        "Or run on EC2/ECS with an IAM instance role",
    ],
    "slack": [
        "Set SLACK_BOT_TOKEN environment variable",
        "Or configure via team settings at /team/settings/integrations/slack",
        "Create a Slack app at https://api.slack.com/apps",
    ],
    "datadog": [
        "Set DATADOG_API_KEY and DATADOG_APP_KEY environment variables",
        "Or configure via team settings at /team/settings/integrations/datadog",
    ],
    "sentry": [
        "Set SENTRY_AUTH_TOKEN environment variable",
        "Or configure via team settings at /team/settings/integrations/sentry",
    ],
    "jira": [
        "Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN environment variables",
        "Or configure via team settings at /team/settings/integrations/jira",
    ],
    "grafana": [
        "Set GRAFANA_URL and GRAFANA_API_KEY environment variables",
        "Or configure via team settings at /team/settings/integrations/grafana",
    ],
    "pagerduty": [
        "Set PAGERDUTY_API_KEY environment variable",
        "Or configure via team settings at /team/settings/integrations/pagerduty",
    ],
    "coralogix": [
        "Set CORALOGIX_API_KEY and CORALOGIX_DOMAIN environment variables",
        "Or configure via team settings at /team/settings/integrations/coralogix",
    ],
    "snowflake": [
        "Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD environment variables",
        "Or configure via team settings at /team/settings/integrations/snowflake",
    ],
    "elasticsearch": [
        "Set ELASTICSEARCH_URL environment variable",
        "Or configure via team settings at /team/settings/integrations/elasticsearch",
    ],
    "splunk": [
        "Set SPLUNK_URL and SPLUNK_TOKEN environment variables",
        "Or configure via team settings at /team/settings/integrations/splunk",
    ],
    "newrelic": [
        "Set NEWRELIC_API_KEY environment variable",
        "Or configure via team settings at /team/settings/integrations/newrelic",
    ],
    "azure": [
        "Set AZURE_SUBSCRIPTION_ID and configure Azure credentials",
        "Or configure via team settings at /team/settings/integrations/azure",
    ],
    "gcp": [
        "Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON path",
        "Or configure via team settings at /team/settings/integrations/gcp",
    ],
    "bigquery": [
        "Set GOOGLE_APPLICATION_CREDENTIALS to your service account JSON path",
        "Or configure via team settings at /team/settings/integrations/bigquery",
    ],
    "gitlab": [
        "Set GITLAB_TOKEN environment variable",
        "Or configure via team settings at /team/settings/integrations/gitlab",
    ],
    "confluence": [
        "Set CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN environment variables",
        "Or configure via team settings at /team/settings/integrations/confluence",
    ],
    "notion": [
        "Set NOTION_API_KEY environment variable",
        "Or configure via team settings at /team/settings/integrations/notion",
    ],
    "linear": [
        "Set LINEAR_API_KEY environment variable",
        "Or configure via team settings at /team/settings/integrations/linear",
    ],
    "tavily": [
        "Set TAVILY_API_KEY environment variable for web search",
        "Get an API key at https://tavily.com",
    ],
}


def make_config_required_response(
    integration: str,
    tool: str,
    missing_config: list[str] | None = None,
    help_options: list[str] | None = None,
    docs_url: str | None = None,
    message: str | None = None,
) -> str:
    """
    Create a structured config_required response for CLI detection.

    This response format is recognized by the CLI and triggers an interactive
    configuration flow where the user is prompted to configure the integration.

    Args:
        integration: Integration identifier (e.g., "github", "aws", "slack")
        tool: Tool name that requires the integration
        missing_config: List of specific missing configuration items
        help_options: List of help text options for the user
        docs_url: Documentation URL for the integration
        message: Custom message (defaults to generic message)

    Returns:
        JSON string with config_required response that CLI can detect

    Example:
        >>> make_config_required_response(
        ...     integration="github",
        ...     tool="list_pull_requests",
        ...     missing_config=["GITHUB_TOKEN"],
        ... )
        '{"config_required": true, "integration": "github", ...}'
    """
    if missing_config is None:
        missing_config = []

    if help_options is None:
        help_options = INTEGRATION_HELP.get(integration, [
            f"Configure via team settings at /team/settings/integrations/{integration}",
        ])

    if docs_url is None:
        docs_url = INTEGRATION_DOCS.get(
            integration,
            f"https://docs.incidentfox.ai/integrations/{integration}",
        )

    if message is None:
        message = f"{integration.title()} integration is not configured. Please provide the required configuration."

    response = {
        "config_required": True,
        "integration": integration,
        "tool": tool,
        "message": message,
        "missing_config": missing_config,
        "help": {
            "description": f"To enable {integration.title()} integration, you need to:",
            "options": help_options,
            "docs_url": docs_url,
        },
    }

    logger.info(
        "config_required_response",
        integration=integration,
        tool=tool,
        missing_config=missing_config,
    )

    return json.dumps(response)


def handle_integration_not_configured(
    error: Exception,
    tool: str,
    integration: str | None = None,
) -> str:
    """
    Convert an IntegrationNotConfiguredError to a config_required response.

    This is a convenience function to use in except blocks when catching
    IntegrationNotConfiguredError exceptions.

    Args:
        error: The caught exception (typically IntegrationNotConfiguredError)
        tool: Tool name that caught the error
        integration: Integration ID (if not available from error)

    Returns:
        JSON string with config_required response

    Example:
        try:
            config = _get_github_config()
        except IntegrationNotConfiguredError as e:
            return handle_integration_not_configured(e, "list_pull_requests")
    """
    # Extract integration info from error if available
    error_integration = getattr(error, "integration_id", None)
    error_missing = getattr(error, "missing_fields", None)

    final_integration = integration or error_integration or "unknown"
    missing_config = error_missing or []

    return make_config_required_response(
        integration=final_integration,
        tool=tool,
        missing_config=missing_config,
    )
