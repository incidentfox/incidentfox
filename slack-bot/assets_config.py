"""
Asset URLs for IncidentFox Slack Bot

All assets are hosted on S3 with public read access.
This eliminates the need for per-workspace file uploads and
distributed caching of Slack file IDs.
"""

# Base URL for all assets
ASSETS_BASE_URL = "https://incidentfox-assets.s3.us-west-2.amazonaws.com/slack"

# Core UI assets
ASSET_URLS = {
    "loading": f"{ASSETS_BASE_URL}/loading.gif",
    "done": f"{ASSETS_BASE_URL}/done.png",
    "logo": f"{ASSETS_BASE_URL}/logo.png",
}

# Integration logos
INTEGRATION_LOGOS = {
    # Observability
    "coralogix": f"{ASSETS_BASE_URL}/integrations/coralogix.png",
    "datadog": f"{ASSETS_BASE_URL}/integrations/datadog.png",
    "cloudwatch": f"{ASSETS_BASE_URL}/integrations/cloudwatch.png",
    "prometheus": f"{ASSETS_BASE_URL}/integrations/prometheus.png",
    "grafana": f"{ASSETS_BASE_URL}/integrations/grafana.png",
    "jaeger": f"{ASSETS_BASE_URL}/integrations/jaeger.png",
    "splunk": f"{ASSETS_BASE_URL}/integrations/splunk.png",
    "elasticsearch": f"{ASSETS_BASE_URL}/integrations/elasticsearch.png",
    "opensearch": f"{ASSETS_BASE_URL}/integrations/opensearch.png",
    "newrelic": f"{ASSETS_BASE_URL}/integrations/new-relic.png",
    "honeycomb": f"{ASSETS_BASE_URL}/integrations/honeycomb.png",
    "dynatrace": f"{ASSETS_BASE_URL}/integrations/dynatrace.png",
    "chronosphere": f"{ASSETS_BASE_URL}/integrations/chronosphere.png",
    "victoriametrics": f"{ASSETS_BASE_URL}/integrations/victoria-metrics.png",
    "kloudfuse": f"{ASSETS_BASE_URL}/integrations/kloudfuse.png",
    "sentry": f"{ASSETS_BASE_URL}/integrations/sentry.png",
    "loki": f"{ASSETS_BASE_URL}/integrations/loki.png",
    # Incident management
    "incident_io": f"{ASSETS_BASE_URL}/integrations/incident_io.png",
    "pagerduty": f"{ASSETS_BASE_URL}/integrations/pagerduty.png",
    "opsgenie": f"{ASSETS_BASE_URL}/integrations/opsgenie.png",
    # Cloud providers
    "aws": f"{ASSETS_BASE_URL}/integrations/aws.png",
    "gcp": f"{ASSETS_BASE_URL}/integrations/gcp.png",
    "azure": f"{ASSETS_BASE_URL}/integrations/azure.png",
    # Source control & collaboration
    "github": f"{ASSETS_BASE_URL}/integrations/github.png",
    "github-app": f"{ASSETS_BASE_URL}/integrations/github.png",
    "gitlab": f"{ASSETS_BASE_URL}/integrations/gitlab.png",
    "jira": f"{ASSETS_BASE_URL}/integrations/jira.png",
    "linear": f"{ASSETS_BASE_URL}/integrations/linear.png",
    "notion": f"{ASSETS_BASE_URL}/integrations/notion.png",
    "confluence": f"{ASSETS_BASE_URL}/integrations/confluence.png",
    "google-docs": f"{ASSETS_BASE_URL}/integrations/gdocs.png",
    "glean": f"{ASSETS_BASE_URL}/integrations/glean.png",
    "servicenow": f"{ASSETS_BASE_URL}/integrations/servicenow.png",
    # Project management
    "clickup": f"{ASSETS_BASE_URL}/integrations/clickup.png",
    # Infrastructure
    "kubernetes": f"{ASSETS_BASE_URL}/integrations/k8s.png",
    "kubernetes_saas": f"{ASSETS_BASE_URL}/integrations/k8s.png",
    "temporal": f"{ASSETS_BASE_URL}/integrations/temporal.png",
    "codepipeline": f"{ASSETS_BASE_URL}/integrations/codepipeline.png",
    # Incident management (additional)
    "blameless": f"{ASSETS_BASE_URL}/integrations/blameless.png",
    "firehydrant": f"{ASSETS_BASE_URL}/integrations/firehydrant.png",
    # Communication
    "msteams": f"{ASSETS_BASE_URL}/integrations/ms_team.png",
    "slack": f"{ASSETS_BASE_URL}/integrations/slack.png",
    # Data
    "snowflake": f"{ASSETS_BASE_URL}/integrations/snowflake.png",
    "bigquery": f"{ASSETS_BASE_URL}/integrations/bigquery.png",
    "postgresql": f"{ASSETS_BASE_URL}/integrations/postgresql.png",
}


def get_asset_url(asset_key: str) -> str:
    """Get URL for a core UI asset."""
    return ASSET_URLS.get(asset_key, "")


def get_integration_logo_url(integration_id: str) -> str:
    """Get logo URL for an integration."""
    return INTEGRATION_LOGOS.get(integration_id, "")
