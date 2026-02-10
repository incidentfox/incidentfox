"""
Onboarding Flow for IncidentFox Slack Bot

Handles:
1. Workspace provisioning when OAuth completes
2. Integration setup wizard
3. Free trial management
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from assets_config import get_integration_logo_url

logger = logging.getLogger(__name__)

# =============================================================================
# INTEGRATION DEFINITIONS
# =============================================================================
# Categories for filtering
CATEGORIES = {
    "all": {"name": "All", "emoji": ":star2:"},
    "observability": {"name": "Logs & Metrics", "emoji": ":bar_chart:"},
    "incident": {"name": "Incidents", "emoji": ":fire_engine:"},
    "cloud": {"name": "Cloud", "emoji": ":cloud:"},
    "scm": {"name": "Dev Tools", "emoji": ":hammer_and_wrench:"},
    "infra": {"name": "Infra", "emoji": ":wrench:"},
}

# All supported integrations
# status: "active" = can configure now, "coming_soon" = show but not configurable
INTEGRATIONS: List[Dict[str, Any]] = [
    # ACTIVE INTEGRATIONS
    {
        "id": "coralogix",
        "name": "Coralogix",
        "category": "observability",
        "status": "active",
        "icon": ":coralogix:",  # Custom emoji or fallback
        "icon_fallback": ":chart_with_upwards_trend:",
        "description": "Query logs, metrics, and traces from Coralogix.",
        # Video block metadata
        "video": {
            "title": "How to Connect Coralogix to IncidentFox",
            "title_url": "https://vimeo.com/1161578699?share=copy&fl=sv&fe=ci",
            "video_url": "https://player.vimeo.com/video/1161578699?autoplay=1",
            "thumbnail_url": "https://vumbnail.com/1161578699.jpg",
            "alt_text": "Coralogix setup tutorial",
            "description": "Step-by-step guide to connecting your Coralogix account",
        },
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your Coralogix dashboard\n"
            "2. Go to *Settings* (left navbar) > *API Keys*\n"
            "3. Click *+ Team Key*, select *DataQuerying* role preset, then *Create*\n"
            "4. Copy the API key and your domain below"
        ),
        "docs_url": "https://docs.incidentfox.ai/data-sources/coralogix",
        "context_prompt_placeholder": "e.g., 'Our logs use application=myapp for filtering. Production has env=prod tag. Error logs are in severity=error.'",
        "fields": [
            {
                "id": "api_key",
                "name": "API Key",
                "type": "secret",
                "required": True,
                "placeholder": "cxtp_...",
                "hint": "Your Coralogix API key with query permissions",
            },
            {
                "id": "domain",
                "name": "Dashboard URL or Domain",
                "type": "string",
                "required": True,
                "placeholder": "https://myteam.app.cx498.coralogix.com OR app.cx498.coralogix.com",
                "hint": "Paste your Coralogix dashboard URL or just the domain from your browser",
            },
        ],
    },
    {
        "id": "incident_io",
        "name": "incident.io",
        "category": "incident",
        "status": "active",
        "icon": ":incident_io:",
        "icon_fallback": ":rotating_light:",
        "description": "Sync incidents, pull context, and update status.",
        "video": {
            "title": "How to Connect incident.io to IncidentFox",
            "title_url": "https://vimeo.com/1161602255",
            "video_url": "https://player.vimeo.com/video/1161602255?autoplay=1",
            "thumbnail_url": "https://vumbnail.com/1161602255.jpg",
            "alt_text": "incident.io setup tutorial",
            "description": "Step-by-step guide to connecting your incident.io account",
        },
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Go to your incident.io home dashboard\n"
            "2. Click the settings gear icon at the bottom of the left navbar (next to your name)\n"
            "3. Scroll down to the *Extend* section and click *API keys*\n"
            "4. Click *Add New* (top right)\n"
            "5. Click *View data...* (the first permission option)\n"
            "6. Name your API key appropriately, scroll down, and click *Create*\n"
            "7. Copy the API key and paste it below"
        ),
        "docs_url": "https://api-docs.incident.io/",
        "context_prompt_placeholder": "e.g., 'SEV1 incidents require immediate response. Use #incident-response channel. Our SLO is 99.9% uptime.'",
        "fields": [
            {
                "id": "api_key",
                "name": "API Key",
                "type": "secret",
                "required": True,
                "placeholder": "inc_...",
                "hint": "Your incident.io API key",
            },
        ],
    },
    {
        "id": "confluence",
        "name": "Confluence",
        "category": "scm",
        "status": "active",
        "icon": ":confluence:",
        "icon_fallback": ":notebook:",
        "description": "Search runbooks, documentation, and knowledge base articles.",
        "video": {
            "title": "How to Connect Confluence to IncidentFox",
            "title_url": "https://vimeo.com/1161614962?share=copy&fl=sv&fe=ci",
            "video_url": "https://player.vimeo.com/video/1161614962?autoplay=1",
            "thumbnail_url": "https://vumbnail.com/1161614962.jpg",
            "alt_text": "Confluence setup tutorial",
            "description": "Step-by-step guide to connecting your Confluence account",
        },
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into <https://id.atlassian.com/manage-profile/security/api-tokens|Atlassian API Tokens>\n"
            "2. Click *Create API token with scopes*\n"
            '3. Enter a name (e.g., "IncidentFox") and set an expiration date\n'
            "4. Select *Confluence* as the app\n"
            "5. In the scope search box, paste: `search:confluence` and select it\n"
            "6. Repeat for these scopes: `read:content:confluence`, `read:content-details:confluence`, `read:space:confluence`, `read:attachment:confluence`\n"
            "7. Click *Create token*, then *Copy* the token\n"
            "8. Paste the API token and your details below"
        ),
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/intro/",
        "context_prompt_placeholder": "e.g., 'Runbooks are in the SRE space. Production docs use the PROD label. Our incident response guide is at /wiki/spaces/SRE/pages/123456.'",
        "fields": [
            {
                "id": "api_key",
                "name": "API Token",
                "type": "secret",
                "required": True,
                "placeholder": "ATATT3x...",
                "hint": "Your Atlassian API token with Confluence scopes",
            },
            {
                "id": "email",
                "name": "Atlassian Email",
                "type": "string",
                "required": True,
                "placeholder": "you@company.com",
                "hint": "The email address associated with your Atlassian account",
            },
            {
                "id": "domain",
                "name": "Confluence URL",
                "type": "string",
                "required": True,
                "placeholder": "https://your-team.atlassian.net",
                "hint": "Your Confluence URL (copy from your browser address bar on any Confluence page)",
            },
        ],
    },
    {
        "id": "grafana",
        "name": "Grafana",
        "category": "observability",
        "status": "active",
        "icon": ":grafana:",
        "icon_fallback": ":bar_chart:",
        "description": "Query dashboards, annotations, and Prometheus metrics.",
        "video": {
            "title": "How to Connect Grafana to IncidentFox",
            "title_url": "https://vimeo.com/1161627016?share=copy&fl=sv&fe=ci",
            "video_url": "https://player.vimeo.com/video/1161627016?autoplay=1",
            "thumbnail_url": "https://vumbnail.com/1161627016.jpg",
            "alt_text": "Grafana setup tutorial",
            "description": "Step-by-step guide to connecting your Grafana account",
        },
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your Grafana instance\n"
            "2. Go to *Administration* (gear icon) > *Service accounts*\n"
            "3. Click *Add service account*, give it a name (e.g., 'IncidentFox')\n"
            "4. Set the role to *Viewer* (or *Editor* if you need annotation access)\n"
            "5. Click *Add service account token*, then *Generate token*\n"
            "6. Copy the token and paste it below along with your Grafana URL"
        ),
        "docs_url": "https://grafana.com/docs/grafana/latest/developers/http_api/",
        "context_prompt_placeholder": "e.g., 'Our main dashboards are in the SRE folder. We use Prometheus for metrics. Key dashboards: api-latency, error-rates, k8s-overview.'",
        "fields": [
            {
                "id": "api_key",
                "name": "API Token",
                "type": "secret",
                "required": True,
                "placeholder": "glsa_...",
                "hint": "Your Grafana service account token",
            },
            {
                "id": "domain",
                "name": "Grafana URL",
                "type": "string",
                "required": True,
                "placeholder": "https://your-org.grafana.net or https://grafana.yourcompany.com",
                "hint": "Paste any Grafana dashboard URL or just the base URL",
            },
        ],
    },
    {
        "id": "elasticsearch",
        "name": "Elasticsearch",
        "category": "observability",
        "status": "active",
        "icon": ":elasticsearch:",
        "icon_fallback": ":mag:",
        "description": "Query logs and search data from Elasticsearch or OpenSearch.",
        "video": {
            "title": "How to Connect Elasticsearch to IncidentFox",
            "title_url": "https://vimeo.com/1161634866?share=copy&fl=sv&fe=ci",
            "video_url": "https://player.vimeo.com/video/1161634866?autoplay=1",
            "thumbnail_url": "https://vumbnail.com/1161634866.jpg",
            "alt_text": "Elasticsearch setup tutorial",
            "description": "Step-by-step guide to connecting your Elasticsearch cluster",
        },
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Get your Elasticsearch cluster URL (e.g., https://my-cluster.es.us-east-1.aws.found.io:9243)\n"
            "2. Create an API key or use Basic auth credentials:\n"
            "   • *Elastic Cloud*: Go to *Management* > *Security* > *API keys* > *Create API key*\n"
            "   • *Self-hosted*: Use your existing username/password or create an API key\n"
            "3. Paste your cluster URL and credentials below"
        ),
        "docs_url": "https://www.elastic.co/guide/en/elasticsearch/reference/current/rest-apis.html",
        "context_prompt_placeholder": "e.g., 'Our logs are in the logs-* index. Use kubernetes.namespace for filtering. Error logs have level=error. Timestamps are in @timestamp field.'",
        "fields": [
            {
                "id": "domain",
                "name": "Elasticsearch URL",
                "type": "string",
                "required": True,
                "placeholder": "https://my-cluster.es.us-east-1.aws.found.io:9243",
                "hint": "Your Elasticsearch cluster URL (include port if needed)",
            },
            {
                "id": "username",
                "name": "Username",
                "type": "string",
                "required": False,
                "placeholder": "elastic",
                "hint": "Username for Basic auth (leave blank if using API key only)",
            },
            {
                "id": "api_key",
                "name": "Password or API Key",
                "type": "secret",
                "required": False,
                "placeholder": "password or API key",
                "hint": "Password for Basic auth, or encoded API key (id:key format)",
            },
            {
                "id": "index_pattern",
                "name": "Default Index Pattern",
                "type": "string",
                "required": False,
                "placeholder": "logs-*",
                "hint": "Default index pattern for log queries (optional)",
            },
        ],
    },
    {
        "id": "datadog",
        "name": "Datadog",
        "category": "observability",
        "status": "active",
        "icon": ":datadog:",
        "icon_fallback": ":dog:",
        "description": "Query logs, metrics, and APM traces from Datadog.",
        "video": {
            "title": "How to Connect Datadog to IncidentFox",
            "title_url": "https://vimeo.com/1161632406?share=copy&fl=sv&fe=ci",
            "video_url": "https://player.vimeo.com/video/1161632406?autoplay=1",
            "thumbnail_url": "https://vumbnail.com/1161632406.jpg",
            "alt_text": "Datadog setup tutorial",
            "description": "Step-by-step guide to connecting your Datadog account",
        },
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your Datadog account\n"
            "2. Go to *Organization Settings* > *API Keys*\n"
            "3. Click *+ New Key*, name it 'IncidentFox', and copy the key\n"
            "4. Go to *Application Keys* tab, click *+ New Key*\n"
            "5. *Important:* Restrict the Application Key to these scopes only:\n"
            "   • `logs_read_data` - Read log data\n"
            "   • `logs_read_index_data` - Read log indexes\n"
            "   • `timeseries_query` - Query metrics\n"
            "   • `metrics_read` - View metrics\n"
            "6. Copy the Application Key\n"
            "7. Paste your keys and Datadog URL below (copy any URL from your Datadog browser tab)"
        ),
        "docs_url": "https://docs.datadoghq.com/api/latest/",
        "context_prompt_placeholder": "e.g., 'Our services use service:api-gateway tag. Production env uses env:prod. Error logs are status:error.'",
        "fields": [
            {
                "id": "api_key",
                "name": "API Key",
                "type": "secret",
                "required": True,
                "placeholder": "your-api-key",
                "hint": "Datadog API key from Organization Settings",
            },
            {
                "id": "app_key",
                "name": "Application Key",
                "type": "secret",
                "required": True,
                "placeholder": "your-app-key",
                "hint": "Datadog Application key with read scopes (required for querying logs and metrics)",
            },
            {
                "id": "domain",
                "name": "Datadog URL",
                "type": "string",
                "required": True,
                "placeholder": "https://us5.datadoghq.com or https://app.datadoghq.eu",
                "hint": "Paste any Datadog URL from your browser (we'll extract the site automatically)",
            },
        ],
    },
    {
        "id": "prometheus",
        "name": "Prometheus",
        "category": "observability",
        "status": "active",
        "icon": ":prometheus:",
        "icon_fallback": ":fire:",
        "description": "Query metrics and alerts from Prometheus.",
        "video": {
            "title": "How to Connect Prometheus to IncidentFox",
            "title_url": "https://vimeo.com/1161637712?share=copy&fl=sv&fe=ci",
            "video_url": "https://player.vimeo.com/video/1161637712?autoplay=1",
            "thumbnail_url": "https://vumbnail.com/1161637712.jpg",
            "alt_text": "Prometheus setup tutorial",
            "description": "Step-by-step guide to connecting your Prometheus server",
        },
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Get your Prometheus server URL\n"
            "2. If authentication is required, include credentials in the URL or provide a bearer token\n"
            "3. Paste your Prometheus URL below"
        ),
        "docs_url": "https://prometheus.io/docs/prometheus/latest/querying/api/",
        "context_prompt_placeholder": "e.g., 'Key metrics: http_requests_total, container_cpu_usage_seconds_total. Use namespace label for filtering. Alerts are in prometheus-alerts.'",
        "fields": [
            {
                "id": "domain",
                "name": "Prometheus URL",
                "type": "string",
                "required": True,
                "placeholder": "https://prometheus.example.com or http://localhost:9090",
                "hint": "Your Prometheus server URL",
            },
            {
                "id": "api_key",
                "name": "Bearer Token",
                "type": "secret",
                "required": False,
                "placeholder": "Optional bearer token",
                "hint": "Bearer token for authentication (if required)",
            },
        ],
    },
    {
        "id": "jaeger",
        "name": "Jaeger",
        "category": "observability",
        "status": "active",
        "icon": ":jaeger:",
        "icon_fallback": ":mag:",
        "description": "Search distributed traces and analyze latency.",
        "video": {
            "title": "How to Connect Jaeger to IncidentFox",
            "title_url": "https://vimeo.com/1161635936?share=copy&fl=sv&fe=ci",
            "video_url": "https://player.vimeo.com/video/1161635936?autoplay=1",
            "thumbnail_url": "https://vumbnail.com/1161635936.jpg",
            "alt_text": "Jaeger setup tutorial",
            "description": "Step-by-step guide to connecting your Jaeger instance",
        },
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Get your Jaeger Query UI URL (usually port 16686)\n"
            "2. Paste the URL below"
        ),
        "docs_url": "https://www.jaegertracing.io/docs/apis/",
        "context_prompt_placeholder": "e.g., 'Main services: api-gateway, user-service, order-service. Traces are tagged with env=production.'",
        "fields": [
            {
                "id": "domain",
                "name": "Jaeger URL",
                "type": "string",
                "required": True,
                "placeholder": "https://jaeger.example.com or http://localhost:16686",
                "hint": "Your Jaeger Query UI URL",
            },
        ],
    },
    {
        "id": "kubernetes",
        "name": "Kubernetes (Direct)",
        "category": "infra",
        "status": "active",
        "icon": ":kubernetes:",
        "icon_fallback": ":wheel_of_dharma:",
        "description": "Direct API access - requires exposing your K8s API.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Get your Kubernetes API server URL (e.g., from `kubectl cluster-info`)\n"
            "2. Create a service account with read permissions:\n"
            "   `kubectl create serviceaccount incidentfox -n default`\n"
            "3. Get the service account token:\n"
            "   `kubectl create token incidentfox -n default`\n"
            "4. Paste the API server URL and token below"
        ),
        "docs_url": "https://kubernetes.io/docs/reference/kubernetes-api/",
        "context_prompt_placeholder": "e.g., 'Production namespace is prod. Critical deployments: api, worker, web. Use app label for service identification.'",
        "fields": [
            {
                "id": "domain",
                "name": "Kubernetes API URL",
                "type": "string",
                "required": True,
                "placeholder": "https://kubernetes.example.com:6443",
                "hint": "Your Kubernetes API server URL",
            },
            {
                "id": "api_key",
                "name": "Service Account Token",
                "type": "secret",
                "required": True,
                "placeholder": "eyJhbGciOiJSUzI1NiIs...",
                "hint": "Service account token with read permissions",
            },
            {
                "id": "namespace",
                "name": "Default Namespace",
                "type": "string",
                "required": False,
                "placeholder": "default",
                "hint": "Default namespace for queries (optional)",
            },
        ],
    },
    {
        "id": "kubernetes_saas",
        "name": "Kubernetes (Agent)",
        "category": "infra",
        "status": "active",
        "icon": ":kubernetes:",
        "icon_fallback": ":wheel_of_dharma:",
        "description": "Deploy a lightweight agent in your cluster - no firewall changes needed.",
        "featured": True,
        "custom_flow": "k8s_saas",  # Special handling - not standard field-based config
        "setup_instructions": (
            "*How it works:*\n"
            "1. Register your cluster to get an API key\n"
            "2. Deploy our agent using Helm\n"
            "3. Agent connects outbound to IncidentFox - no inbound firewall rules needed!\n\n"
            "The agent runs in your cluster and proxies K8s API calls securely."
        ),
        "docs_url": "https://docs.incidentfox.ai/integrations/kubernetes-agent",
    },
    {
        "id": "github",
        "name": "GitHub",
        "category": "scm",
        "status": "active",
        "icon": ":github:",
        "icon_fallback": ":octocat:",
        "description": "Search code, PRs, commits, and deployments.",
        "auth_type": "github_app",  # Uses GitHub App OAuth flow
        "github_app_url": "https://github.com/apps/incidentfox/installations/new",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Click the button below to install the IncidentFox GitHub App\n"
            "2. Select your GitHub organization or personal account\n"
            "3. Choose which repositories to grant access to\n"
            "4. After installation, return here and enter your GitHub org/username below"
        ),
        "docs_url": "https://docs.github.com/en/apps",
        "context_prompt_placeholder": "e.g., 'Main repos: org/api, org/frontend. Production branch is main. Deployments are tracked via GitHub Actions.'",
        "fields": [
            {
                "id": "github_org",
                "name": "GitHub Organization/Username",
                "type": "string",
                "required": True,
                "placeholder": "acme-corp",
                "hint": "The GitHub org or username you installed the app on",
            },
        ],
    },
    {
        "id": "gitlab",
        "name": "GitLab",
        "category": "scm",
        "status": "active",
        "icon": ":gitlab:",
        "icon_fallback": ":fox_face:",
        "description": "Search code, merge requests, pipelines, and deployments.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your GitLab instance\n"
            "2. Create an access token with `api` scope:\n"
            "   • *Personal token:* User Settings > Access Tokens\n"
            "   • *Group token (recommended for enterprise):* Group > Settings > Access Tokens\n"
            "   • *Project token:* Project > Settings > Access Tokens\n"
            "3. Name it 'IncidentFox', set an expiration date\n"
            "4. Click *Create* and copy the token\n"
            "5. Paste the token and your GitLab URL below"
        ),
        "docs_url": "https://docs.gitlab.com/ee/api/rest/",
        "context_prompt_placeholder": "e.g., 'Main repos: group/api, group/frontend. Production branch is main. CI/CD pipelines are in .gitlab-ci.yml.'",
        "fields": [
            {
                "id": "api_key",
                "name": "Access Token",
                "type": "secret",
                "required": True,
                "placeholder": "glpat-...",
                "hint": "Personal, group, or project access token with api scope",
            },
            {
                "id": "domain",
                "name": "GitLab URL (Optional)",
                "type": "string",
                "required": False,
                "placeholder": "https://gitlab.com (default) or https://gitlab.yourcompany.com",
                "hint": "Leave blank for gitlab.com. Set this for self-hosted GitLab",
            },
            {
                "id": "verify_ssl",
                "name": "Verify SSL Certificates",
                "type": "boolean",
                "required": False,
                "hint": "Uncheck for self-hosted GitLab with self-signed certificates",
                "default": True,
            },
        ],
    },
    # COMING SOON INTEGRATIONS
    {
        "id": "cloudwatch",
        "name": "CloudWatch",
        "category": "observability",
        "status": "active",
        "icon": ":cloudwatch:",
        "icon_fallback": ":cloud:",
        "description": "Query AWS CloudWatch logs and metrics.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your AWS console\n"
            "2. Go to *IAM* > *Users* > select or create a user\n"
            "3. Attach the *CloudWatchReadOnlyAccess* policy\n"
            "4. Go to *Security credentials* tab > *Create access key*\n"
            "5. Copy the Access Key ID and Secret Access Key below"
        ),
        "docs_url": "https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/",
        "context_prompt_placeholder": "e.g., 'Our Lambda logs are in /aws/lambda/api-handler. Production is in us-east-1. Error logs contain level=ERROR.'",
        "fields": [
            {
                "id": "aws_access_key_id",
                "name": "AWS Access Key ID",
                "type": "secret",
                "required": True,
                "placeholder": "AKIA...",
                "hint": "IAM access key with CloudWatch read permissions",
            },
            {
                "id": "aws_secret_access_key",
                "name": "AWS Secret Access Key",
                "type": "secret",
                "required": True,
                "placeholder": "your-secret-key",
                "hint": "IAM secret access key",
            },
            {
                "id": "region",
                "name": "AWS Region",
                "type": "string",
                "required": False,
                "placeholder": "us-east-1",
                "hint": "Default AWS region (leave blank for us-east-1)",
            },
        ],
    },
    {
        "id": "pagerduty",
        "name": "PagerDuty",
        "category": "incident",
        "status": "active",
        "icon": ":pagerduty:",
        "icon_fallback": ":bell:",
        "description": "Acknowledge alerts and pull incident context.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your PagerDuty account\n"
            "2. Go to *Integrations* > *API Access Keys*\n"
            "3. Click *Create New API Key*\n"
            "4. Enter a description (e.g., 'IncidentFox') and select *Read-only* access\n"
            "5. Click *Create Key* and copy the API key below"
        ),
        "docs_url": "https://developer.pagerduty.com/api-reference/",
        "context_prompt_placeholder": "e.g., 'Our critical services are api-gateway and payment-service. SEV1 incidents require immediate response. Escalation policy is Backend On-Call.'",
        "fields": [
            {
                "id": "api_key",
                "name": "API Key",
                "type": "secret",
                "required": True,
                "placeholder": "u+your-api-key",
                "hint": "PagerDuty REST API key (read-only recommended)",
            },
        ],
    },
    {
        "id": "opsgenie",
        "name": "Opsgenie",
        "category": "incident",
        "status": "coming_soon",
        "icon": ":opsgenie:",
        "icon_fallback": ":bell:",
        "description": "Manage alerts and on-call schedules.",
    },
    {
        "id": "aws",
        "name": "AWS",
        "category": "cloud",
        "status": "coming_soon",
        "icon": ":aws:",
        "icon_fallback": ":cloud:",
        "description": "Query EC2, ECS, Lambda, and other AWS services.",
    },
    {
        "id": "splunk",
        "name": "Splunk",
        "category": "observability",
        "status": "active",
        "icon": ":splunk:",
        "icon_fallback": ":mag:",
        "description": "Query logs and metrics from Splunk.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your Splunk instance\n"
            "2. Go to *Settings* > *Tokens* (under Data Inputs)\n"
            "3. Click *New Token*, give it a name (e.g., 'IncidentFox')\n"
            "4. Set allowed indexes as needed\n"
            "5. Copy the token and your Splunk URL below"
        ),
        "docs_url": "https://docs.splunk.com/Documentation/Splunk/latest/RESTREF/RESTprolog",
        "context_prompt_placeholder": "e.g., 'Our logs are in the main index. Use sourcetype=access_combined for web logs. Error events have level=ERROR.'",
        "fields": [
            {
                "id": "domain",
                "name": "Splunk URL",
                "type": "string",
                "required": True,
                "placeholder": "https://mysplunk.example.com:8089 or https://input-prd-p-xxxxx.cloud.splunk.com:8089",
                "hint": "Your Splunk REST API URL (usually port 8089)",
            },
            {
                "id": "api_key",
                "name": "Auth Token",
                "type": "secret",
                "required": True,
                "placeholder": "your-splunk-token",
                "hint": "Splunk authentication token (Bearer or HEC token)",
            },
        ],
    },
    {
        "id": "opensearch",
        "name": "OpenSearch",
        "category": "observability",
        "status": "active",
        "icon": ":opensearch:",
        "icon_fallback": ":mag:",
        "description": "Query logs and search data from OpenSearch.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your AWS console or OpenSearch dashboard\n"
            "2. Navigate to your OpenSearch domain\n"
            "3. Copy the domain endpoint URL\n"
            "4. Create or use an existing master user with read access\n"
            "5. Enter the endpoint and credentials below"
        ),
        "docs_url": "https://docs.aws.amazon.com/opensearch-service/latest/developerguide/",
        "context_prompt_placeholder": "e.g., 'Our application logs are in the app-logs-* index pattern. Error logs have level field set to ERROR. Timestamps are in @timestamp.'",
        "fields": [
            {
                "id": "domain",
                "name": "OpenSearch Endpoint URL",
                "type": "string",
                "required": True,
                "placeholder": "https://search-my-domain-abc123.us-east-1.es.amazonaws.com",
                "hint": "Your OpenSearch domain endpoint URL",
            },
            {
                "id": "username",
                "name": "Username",
                "type": "string",
                "required": False,
                "placeholder": "admin",
                "hint": "Master user name (if using fine-grained access control)",
            },
            {
                "id": "password",
                "name": "Password",
                "type": "secret",
                "required": False,
                "placeholder": "your-password",
                "hint": "Master user password",
            },
        ],
    },
    {
        "id": "newrelic",
        "name": "New Relic",
        "category": "observability",
        "status": "active",
        "icon": ":newrelic:",
        "icon_fallback": ":chart:",
        "description": "Query APM, logs, and infrastructure metrics.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your New Relic account\n"
            "2. Click your name (bottom-left) > *API Keys*\n"
            "3. Click *Create a key*, select *User* key type\n"
            "4. Give it a name (e.g., 'IncidentFox') and click *Create*\n"
            "5. Copy the API key and your Account ID (found in *Administration* > *Access management*)"
        ),
        "docs_url": "https://docs.newrelic.com/docs/apis/intro-apis/new-relic-api-keys/",
        "context_prompt_placeholder": "e.g., 'Our main app is called api-gateway in New Relic. Production transactions use appName=api-gateway-prod. Key metrics are response time and error rate.'",
        "fields": [
            {
                "id": "api_key",
                "name": "User API Key",
                "type": "secret",
                "required": True,
                "placeholder": "NRAK-...",
                "hint": "New Relic User API key (starts with NRAK-)",
            },
            {
                "id": "account_id",
                "name": "Account ID",
                "type": "string",
                "required": True,
                "placeholder": "1234567",
                "hint": "Your New Relic account ID (found under Administration > Access management)",
            },
        ],
    },
    {
        "id": "honeycomb",
        "name": "Honeycomb",
        "category": "observability",
        "status": "active",
        "icon": ":honeycomb:",
        "icon_fallback": ":honeybee:",
        "description": "Query high-cardinality observability data, traces, and SLOs.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your Honeycomb account\n"
            "2. Go to *Team Settings* (gear icon) > *API Keys*\n"
            "3. Click *Create API Key*\n"
            "4. Name it 'IncidentFox' and select these permissions:\n"
            "   • *Query Data* - Run queries on datasets\n"
            "   • *Manage Queries and Columns* - View columns and query specs\n"
            "5. Click *Create* and copy the API key\n"
            "6. Paste the API key below"
        ),
        "docs_url": "https://docs.honeycomb.io/api/",
        "context_prompt_placeholder": "e.g., 'Our main dataset is production. Key fields: service.name, duration_ms, http.status_code. SLO target is 99.9%.'",
        "fields": [
            {
                "id": "api_key",
                "name": "API Key",
                "type": "secret",
                "required": True,
                "placeholder": "your-honeycomb-api-key",
                "hint": "Honeycomb API key with Query Data permissions",
            },
            {
                "id": "domain",
                "name": "API Endpoint (Optional)",
                "type": "string",
                "required": False,
                "placeholder": "https://api.honeycomb.io (default) or https://api.eu1.honeycomb.io",
                "hint": "Leave blank for US region. Use api.eu1.honeycomb.io for EU",
            },
        ],
    },
    {
        "id": "clickup",
        "name": "ClickUp",
        "category": "project_management",
        "status": "active",
        "icon": ":clickup:",
        "icon_fallback": ":clipboard:",
        "description": "Query and manage tasks for incident tracking and project management.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your ClickUp account\n"
            "2. Go to *Settings* (gear icon) > *Apps*\n"
            "3. Click *Generate* under API Token section\n"
            "4. Copy the Personal API Token\n"
            "5. Optionally, copy your Team/Workspace ID from Settings > Teams\n"
            "6. Paste the API token below"
        ),
        "docs_url": "https://clickup.com/api",
        "context_prompt_placeholder": 'e.g., \'Our incident tasks are in the "SRE" space. Use the "Incidents" list. Severity is tracked in a custom field.\'',
        "fields": [
            {
                "id": "api_key",
                "name": "API Token",
                "type": "secret",
                "required": True,
                "placeholder": "pk_12345678_ABCDEFGHIJKLMNOP",
                "hint": "ClickUp Personal API Token",
            },
            {
                "id": "team_id",
                "name": "Team/Workspace ID (Optional)",
                "type": "string",
                "required": False,
                "placeholder": "12345678",
                "hint": "Leave blank to auto-detect. Find in Settings > Teams",
            },
        ],
    },
    {
        "id": "loki",
        "name": "Loki",
        "category": "observability",
        "status": "active",
        "icon": ":loki:",
        "icon_fallback": ":bar_chart:",
        "description": "Query and search logs from Grafana Loki.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Get your Loki endpoint URL (e.g., from Grafana Cloud or your self-hosted instance)\n"
            "2. If authentication is required, get a bearer token or basic auth credentials\n"
            "   • *Grafana Cloud*: Go to *My Account* > *Grafana Cloud* > *Loki Details* > copy the URL and generate an API key\n"
            "3. Paste your Loki URL and credentials below"
        ),
        "docs_url": "https://grafana.com/docs/loki/latest/reference/loki-http-api/",
        "context_prompt_placeholder": "e.g., 'Our logs use app=myservice label. Production logs have env=prod. Error logs are level=error.'",
        "fields": [
            {
                "id": "domain",
                "name": "Loki URL",
                "type": "string",
                "required": True,
                "placeholder": "https://logs-prod-us-central1.grafana.net or http://loki:3100",
                "hint": "Your Loki endpoint URL",
            },
            {
                "id": "api_key",
                "name": "Bearer Token or API Key",
                "type": "secret",
                "required": False,
                "placeholder": "Optional bearer token or API key",
                "hint": "Required for Grafana Cloud. Leave blank for unauthenticated Loki",
            },
        ],
    },
    {
        "id": "dynatrace",
        "name": "Dynatrace",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":dynatrace:",
        "icon_fallback": ":chart:",
        "description": "Query application performance and infrastructure.",
    },
    {
        "id": "chronosphere",
        "name": "Chronosphere",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":chronosphere:",
        "icon_fallback": ":clock:",
        "description": "Query cloud-native observability data.",
    },
    {
        "id": "victoriametrics",
        "name": "VictoriaMetrics",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":victoriametrics:",
        "icon_fallback": ":chart:",
        "description": "Query time-series metrics.",
    },
    {
        "id": "kloudfuse",
        "name": "Kloudfuse",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":kloudfuse:",
        "icon_fallback": ":cloud:",
        "description": "Unified observability platform.",
    },
    {
        "id": "sentry",
        "name": "Sentry",
        "category": "observability",
        "status": "active",
        "icon": ":sentry:",
        "icon_fallback": ":bug:",
        "description": "Query application errors and performance issues.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your Sentry account\n"
            "2. Go to *Settings* > *Auth Tokens* (under Account)\n"
            "3. Click *Create New Token*\n"
            "4. Select these scopes: `project:read`, `issue:read`, `event:read`\n"
            "5. Click *Create Token* and copy it\n"
            "6. Enter the token, your organization slug, and optionally a default project below"
        ),
        "docs_url": "https://docs.sentry.io/api/",
        "context_prompt_placeholder": "e.g., 'Our main project is api-backend. Critical errors are tagged with level=fatal. We use the production environment.'",
        "fields": [
            {
                "id": "api_key",
                "name": "Auth Token",
                "type": "secret",
                "required": True,
                "placeholder": "sntrys_...",
                "hint": "Sentry auth token with project:read, issue:read, and event:read scopes",
            },
            {
                "id": "organization",
                "name": "Organization Slug",
                "type": "string",
                "required": True,
                "placeholder": "my-org",
                "hint": "Your Sentry organization slug (from the URL: sentry.io/organizations/<slug>/)",
            },
            {
                "id": "project",
                "name": "Default Project (Optional)",
                "type": "string",
                "required": False,
                "placeholder": "my-project",
                "hint": "Default project slug to query (optional)",
            },
            {
                "id": "domain",
                "name": "Sentry URL (Optional)",
                "type": "string",
                "required": False,
                "placeholder": "https://sentry.io (default) or https://sentry.yourcompany.com",
                "hint": "Leave blank for sentry.io. Set this for self-hosted Sentry",
            },
        ],
    },
    {
        "id": "gcp",
        "name": "Google Cloud",
        "category": "cloud",
        "status": "coming_soon",
        "icon": ":gcp:",
        "icon_fallback": ":cloud:",
        "description": "Query GCP services and resources.",
    },
    {
        "id": "azure",
        "name": "Azure",
        "category": "cloud",
        "status": "coming_soon",
        "icon": ":azure:",
        "icon_fallback": ":cloud:",
        "description": "Query Azure services and resources.",
    },
    {
        "id": "jira",
        "name": "Jira",
        "category": "scm",
        "status": "active",
        "icon": ":jira:",
        "icon_fallback": ":ticket:",
        "description": "Create, search, and manage Jira issues and epics.",
        "setup_instructions": (
            "*Setup Instructions:*\n"
            "1. Log into your Atlassian account\n"
            "2. Go to *https://id.atlassian.com/manage-profile/security/api-tokens*\n"
            "3. Click *Create API token*, label it 'IncidentFox'\n"
            "4. Copy the token, your Jira URL, and email below"
        ),
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/",
        "context_prompt_placeholder": "e.g., 'Our incident project key is OPS. Bug tickets use type=Bug. Post-mortems are labeled with post-mortem tag.'",
        "fields": [
            {
                "id": "domain",
                "name": "Jira URL",
                "type": "string",
                "required": True,
                "placeholder": "https://your-company.atlassian.net",
                "hint": "Your Jira Cloud instance URL",
            },
            {
                "id": "email",
                "name": "Email",
                "type": "string",
                "required": True,
                "placeholder": "you@company.com",
                "hint": "Email associated with your Atlassian account",
            },
            {
                "id": "api_key",
                "name": "API Token",
                "type": "secret",
                "required": True,
                "placeholder": "your-api-token",
                "hint": "Atlassian API token from id.atlassian.com",
            },
        ],
    },
    {
        "id": "linear",
        "name": "Linear",
        "category": "scm",
        "status": "coming_soon",
        "icon": ":linear:",
        "icon_fallback": ":ticket:",
        "description": "Query issues and project status.",
    },
    {
        "id": "notion",
        "name": "Notion",
        "category": "scm",
        "status": "coming_soon",
        "icon": ":notion:",
        "icon_fallback": ":notebook:",
        "description": "Search documentation and runbooks.",
    },
    {
        "id": "glean",
        "name": "Glean",
        "category": "scm",
        "status": "coming_soon",
        "icon": ":glean:",
        "icon_fallback": ":mag:",
        "description": "Search across workplace knowledge.",
    },
    {
        "id": "servicenow",
        "name": "ServiceNow",
        "category": "incident",
        "status": "coming_soon",
        "icon": ":servicenow:",
        "icon_fallback": ":ticket:",
        "description": "Query incidents and change requests.",
    },
    {
        "id": "temporal",
        "name": "Temporal",
        "category": "infra",
        "status": "coming_soon",
        "icon": ":temporal:",
        "icon_fallback": ":gear:",
        "description": "Query workflow executions and state.",
    },
    {
        "id": "snowflake",
        "name": "Snowflake",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":snowflake:",
        "icon_fallback": ":snowflake:",
        "description": "Query data warehouse and analytics.",
    },
]


def get_integration_by_id(integration_id: str) -> Optional[Dict[str, Any]]:
    """Get integration definition by ID."""
    for integration in INTEGRATIONS:
        if integration["id"] == integration_id:
            return integration
    return None


def get_integrations_by_category(category: str) -> List[Dict[str, Any]]:
    """Get integrations filtered by category."""
    if category == "all":
        return INTEGRATIONS
    return [i for i in INTEGRATIONS if i.get("category") == category]


def build_api_key_modal(
    team_id: str,
    trial_info: Optional[Dict] = None,
    error_message: str = None,
) -> Dict[str, Any]:
    """
    Build the API key setup modal.

    Args:
        team_id: Slack team/workspace ID
        trial_info: Trial status if on free trial
        error_message: Error to display (e.g., invalid API key)

    Returns:
        Slack modal view object
    """
    blocks = []

    # Header section (removed misleading trial messaging)
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":key: *Set up your Anthropic API key*\n\n"
                    "IncidentFox uses Claude to investigate incidents. "
                    "Enter your Anthropic API key below to get started."
                ),
            },
        }
    )
    blocks.append({"type": "divider"})

    # Error message if any
    if error_message:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *Error:* {error_message}",
                },
            }
        )

    # API Key input
    blocks.append(
        {
            "type": "input",
            "block_id": "api_key_block",
            "element": {
                "type": "plain_text_input",
                "action_id": "api_key_input",
                "placeholder": {"type": "plain_text", "text": "sk-ant-api..."},
            },
            "label": {"type": "plain_text", "text": "Anthropic API Key"},
            "hint": {
                "type": "plain_text",
                "text": "Get your API key from console.anthropic.com",
            },
        }
    )

    # Optional API endpoint (for enterprise ML gateways)
    blocks.append(
        {
            "type": "input",
            "block_id": "api_endpoint_block",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "api_endpoint_input",
                "placeholder": {
                    "type": "plain_text",
                    "text": "https://api.anthropic.com (default)",
                },
            },
            "label": {"type": "plain_text", "text": "API Endpoint (Optional)"},
            "hint": {
                "type": "plain_text",
                "text": "Leave blank to use the default Anthropic API. Set this if your company uses an internal ML gateway.",
            },
        }
    )

    # Help text
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        ":lock: Your API key is encrypted and stored securely. "
                        "<https://console.anthropic.com/settings/keys|Get an API key>"
                    ),
                }
            ],
        }
    )

    return {
        "type": "modal",
        "callback_id": "api_key_submission",
        "private_metadata": team_id,  # Store team_id for submission handler
        "title": {"type": "plain_text", "text": "IncidentFox Setup"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def build_setup_required_message(
    trial_info: Optional[Dict] = None,
    show_upgrade: bool = False,
) -> list:
    """
    Build a message prompting user to set up their API key.

    Returns Block Kit blocks for the message.
    """
    blocks = []

    # Determine message based on trial status
    if trial_info and trial_info.get("expired"):
        # Trial expired - users need to upgrade
        header_text = ":warning: *Your free trial has ended*"
        body_text = (
            "To continue using IncidentFox, please upgrade to a paid subscription."
        )
    elif trial_info and trial_info.get("days_remaining", 0) <= 3:
        # Trial expiring soon - prompt to upgrade
        days = trial_info.get("days_remaining", 0)
        header_text = f":hourglass: *Your free trial expires in {days} days*"
        body_text = "To continue using IncidentFox after the trial, you'll need to upgrade to a paid subscription."
    elif not trial_info:
        # No trial, needs setup
        header_text = ":wave: *Welcome to IncidentFox!*"
        body_text = (
            "To get started, you'll need to set up your Anthropic API key.\n\n"
            "IncidentFox uses Claude to help investigate incidents, "
            "analyze logs, and suggest remediations.\n\n"
            "Click the button below to complete setup."
        )
    else:
        # On active trial - shouldn't hit this case but handle it
        return []

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": header_text}})

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body_text}})

    # Build action buttons based on trial status
    action_elements = []

    # For expired/expiring trial, show upgrade button as primary action
    if trial_info and (
        trial_info.get("expired") or trial_info.get("days_remaining", 0) <= 3
    ):
        action_elements.append(
            {
                "type": "button",
                "action_id": "open_upgrade_page",
                "text": {
                    "type": "plain_text",
                    "text": ":credit_card: Upgrade to Continue",
                    "emoji": True,
                },
                "style": "primary",
                "url": "https://calendly.com/d/cxd2-4hb-qgp/30-minute-demo-call-w-incidentfox",
            }
        )
        action_elements.append(
            {
                "type": "button",
                "action_id": "dismiss_setup_message",
                "text": {"type": "plain_text", "text": "Later"},
            }
        )
    else:
        # For non-trial users, show API key setup as primary action
        action_elements.append(
            {
                "type": "button",
                "action_id": "open_api_key_modal",
                "text": {
                    "type": "plain_text",
                    "text": ":key: Set Up API Key",
                    "emoji": True,
                },
                "style": "primary",
            }
        )
        action_elements.append(
            {
                "type": "button",
                "action_id": "dismiss_setup_message",
                "text": {"type": "plain_text", "text": "Later"},
            }
        )

    blocks.append({"type": "actions", "elements": action_elements})

    # Help text based on trial status
    if trial_info and (
        trial_info.get("expired") or trial_info.get("days_remaining", 0) <= 3
    ):
        help_text = ":bulb: Questions about pricing? Email us at support@incidentfox.ai"
    else:
        help_text = ":bulb: Need help? Visit <https://docs.incidentfox.ai|our docs> or contact support."

    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": help_text}]}
    )

    return blocks


def build_setup_complete_message() -> list:
    """Build a message confirming API key was saved successfully."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":white_check_mark: *Setup complete!*\n\n"
                    "Your API key has been saved. You can now mention me in any channel "
                    "to start investigating incidents.\n\n"
                    "Try it out: `@IncidentFox help me investigate this error`"
                ),
            },
        }
    ]


def build_upgrade_required_message(trial_info: Optional[Dict] = None) -> list:
    """
    Build a message prompting user to upgrade their subscription.

    This is shown when trial has expired and they have an API key but no subscription.
    They need to pay for a subscription to continue using the service.
    """
    blocks = []

    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":warning: *Subscription required*"},
        }
    )

    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Your free trial has ended. We noticed you've already set up your "
                    "API key - great!\n\n"
                    "To continue using IncidentFox, please upgrade to a paid subscription. "
                    "Your API key will be used once the subscription is active."
                ),
            },
        }
    )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "open_upgrade_page",
                    "text": {
                        "type": "plain_text",
                        "text": ":credit_card: Upgrade",
                        "emoji": True,
                    },
                    "style": "primary",
                    "url": "https://calendly.com/d/cxd2-4hb-qgp/30-minute-demo-call-w-incidentfox",
                },
            ],
        }
    )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        ":bulb: Plans start at $X/month. "
                        "Questions? Email us at support@incidentfox.ai"
                    ),
                }
            ],
        }
    )

    return blocks


def validate_api_key(api_key: str) -> tuple[bool, str]:
    """
    Validate an Anthropic API key format.

    Returns (is_valid, error_message).
    """
    if not api_key:
        return False, "API key is required"

    api_key = api_key.strip()

    if len(api_key) < 20:
        return False, "API key is too short"

    # Anthropic keys typically start with sk-ant-
    if not (api_key.startswith("sk-ant-") or api_key.startswith("sk-")):
        return False, "Invalid API key format. Anthropic keys start with sk-ant-"

    return True, ""


def extract_coralogix_domain(input_str: str) -> tuple[bool, str, str]:
    """
    Extract Coralogix domain from URL or domain string.

    Args:
        input_str: URL (e.g., https://myteam.app.cx498.coralogix.com/#/settings/api-keys)
                   or domain (e.g., app.cx498.coralogix.com)

    Returns:
        (is_valid, domain, error_message)
    """
    import re
    from urllib.parse import urlparse

    if not input_str:
        return False, "", "Domain or URL is required"

    input_str = input_str.strip()

    # If it looks like a URL, parse it
    if input_str.startswith(("http://", "https://")):
        try:
            parsed = urlparse(input_str)
            hostname = parsed.hostname or parsed.netloc.split(":")[0]
        except Exception:
            return False, "", "Invalid URL format"
    else:
        # Treat as domain directly
        hostname = input_str

    # Validate it's a Coralogix domain
    # Valid patterns: *.coralogix.com, *.app.coralogix.us, *.app.coralogix.in,
    #                 *.app.coralogixsg.com, *.app.cx498.coralogix.com,
    #                 *.app.eu2.coralogix.com, *.app.ap3.coralogix.com
    valid_patterns = [
        r"\.?coralogix\.com$",
        r"\.?app\.coralogix\.us$",
        r"\.?app\.coralogix\.in$",
        r"\.?app\.coralogixsg\.com$",
        r"\.?app\.cx498\.coralogix\.com$",
        r"\.?app\.eu2\.coralogix\.com$",
        r"\.?app\.ap3\.coralogix\.com$",
    ]

    is_valid = any(re.search(pattern, hostname) for pattern in valid_patterns)

    if not is_valid:
        return (
            False,
            "",
            f"Invalid Coralogix domain: {hostname}. Please use a domain like app.cx498.coralogix.com or coralogix.com",
        )

    return True, hostname, ""


def extract_grafana_url(input_str: str) -> tuple[bool, str, str]:
    """
    Extract Grafana base URL from URL or domain string.

    Args:
        input_str: URL (e.g., https://myorg.grafana.net/d/abc123/my-dashboard)
                   or domain (e.g., myorg.grafana.net or grafana.mycompany.com)

    Returns:
        (is_valid, base_url, error_message)
    """
    from urllib.parse import urlparse

    if not input_str:
        return False, "", "Grafana URL is required"

    input_str = input_str.strip()

    # If it doesn't start with http, add https://
    if not input_str.startswith(("http://", "https://")):
        input_str = f"https://{input_str}"

    try:
        parsed = urlparse(input_str)
        hostname = parsed.hostname or parsed.netloc.split(":")[0]
        port = parsed.port

        if not hostname:
            return False, "", "Could not parse Grafana URL"

        # Build base URL (scheme + host + optional port)
        scheme = parsed.scheme or "https"
        if port and port not in (80, 443):
            base_url = f"{scheme}://{hostname}:{port}"
        else:
            base_url = f"{scheme}://{hostname}"

        return True, base_url, ""

    except Exception:
        return False, "", "Invalid URL format"


def extract_elasticsearch_url(input_str: str) -> tuple[bool, str, str]:
    """
    Extract Elasticsearch base URL from URL string.

    Args:
        input_str: URL (e.g., https://my-cluster.es.us-east-1.aws.found.io:9243)
                   or domain (e.g., my-cluster.es.us-east-1.aws.found.io)

    Returns:
        (is_valid, base_url, error_message)
    """
    from urllib.parse import urlparse

    if not input_str:
        return False, "", "Elasticsearch URL is required"

    input_str = input_str.strip()

    # If it doesn't start with http, add https://
    if not input_str.startswith(("http://", "https://")):
        input_str = f"https://{input_str}"

    try:
        parsed = urlparse(input_str)
        hostname = parsed.hostname or parsed.netloc.split(":")[0]
        port = parsed.port

        if not hostname:
            return False, "", "Could not parse Elasticsearch URL"

        # Build base URL (scheme + host + optional port)
        # Elasticsearch often uses non-standard ports (9200, 9243, etc.)
        scheme = parsed.scheme or "https"
        if port:
            base_url = f"{scheme}://{hostname}:{port}"
        else:
            base_url = f"{scheme}://{hostname}"

        return True, base_url, ""

    except Exception:
        return False, "", "Invalid URL format"


def extract_datadog_site(input_str: str) -> tuple[bool, str, str]:
    """
    Extract Datadog site from URL or domain string.

    Args:
        input_str: URL (e.g., https://us5.datadoghq.com/logs, https://app.datadoghq.eu/apm)
                   or domain (e.g., us5.datadoghq.com, datadoghq.eu)

    Returns:
        (is_valid, site, error_message)
        site is the normalized site value (e.g., "us5.datadoghq.com", "datadoghq.eu")
    """
    import re
    from urllib.parse import urlparse

    if not input_str:
        return False, "", "Datadog URL is required"

    input_str = input_str.strip()

    # If it looks like a URL, parse it
    if input_str.startswith(("http://", "https://")):
        try:
            parsed = urlparse(input_str)
            hostname = parsed.hostname or parsed.netloc.split(":")[0]
        except Exception:
            return False, "", "Invalid URL format"
    else:
        # Treat as domain directly
        hostname = input_str

    if not hostname:
        return False, "", "Could not parse Datadog URL"

    # Strip "app." prefix if present (e.g., app.datadoghq.com -> datadoghq.com)
    if hostname.startswith("app."):
        hostname = hostname[4:]

    # Valid Datadog sites
    valid_sites = [
        "datadoghq.com",
        "us3.datadoghq.com",
        "us5.datadoghq.com",
        "datadoghq.eu",
        "ap1.datadoghq.com",
        "ddog-gov.com",
    ]

    # Check if hostname matches a valid site
    if hostname in valid_sites:
        return True, hostname, ""

    # Check if hostname ends with a valid site (for subdomains)
    for site in valid_sites:
        if hostname.endswith(f".{site}") or hostname == site:
            return True, site, ""

    return (
        False,
        "",
        f"Invalid Datadog site: {hostname}. Expected one of: {', '.join(valid_sites)}",
    )


def extract_confluence_url(input_str: str) -> tuple[bool, str, str]:
    """
    Extract Confluence base URL from any Confluence page URL.

    Users may paste URLs like:
    - https://myteam.atlassian.net/wiki/home
    - https://myteam.atlassian.net/wiki/spaces/ENG/pages/123456
    - https://myteam.atlassian.net

    We extract just the base URL: https://myteam.atlassian.net

    Args:
        input_str: URL string (any Confluence page URL)

    Returns:
        (is_valid, base_url, error_message)
    """
    import re
    from urllib.parse import urlparse

    if not input_str:
        return False, "", "Confluence URL is required"

    input_str = input_str.strip()

    # If it doesn't start with http, add https://
    if not input_str.startswith(("http://", "https://")):
        input_str = f"https://{input_str}"

    try:
        parsed = urlparse(input_str)
        hostname = parsed.hostname or parsed.netloc.split(":")[0]

        if not hostname:
            return False, "", "Could not parse Confluence URL"

        # Validate it's an Atlassian domain
        if not hostname.endswith(".atlassian.net"):
            return (
                False,
                "",
                f"Invalid Confluence URL: {hostname}. Expected an atlassian.net domain (e.g., myteam.atlassian.net)",
            )

        # Build base URL (just scheme + host, no path)
        scheme = parsed.scheme or "https"
        base_url = f"{scheme}://{hostname}"

        return True, base_url, ""

    except Exception:
        return False, "", "Invalid URL format"


def extract_generic_url(
    input_str: str, service_name: str = "service"
) -> tuple[bool, str, str]:
    """
    Extract and validate a generic service URL.

    Used for Prometheus, Jaeger, Kubernetes, GitHub Enterprise, etc.

    Args:
        input_str: URL string
        service_name: Name of the service for error messages

    Returns:
        (is_valid, base_url, error_message)
    """
    from urllib.parse import urlparse

    if not input_str:
        return False, "", f"{service_name} URL is required"

    input_str = input_str.strip()

    # If it doesn't start with http, add https://
    if not input_str.startswith(("http://", "https://")):
        input_str = f"https://{input_str}"

    try:
        parsed = urlparse(input_str)
        hostname = parsed.hostname or parsed.netloc.split(":")[0]
        port = parsed.port

        if not hostname:
            return False, "", f"Could not parse {service_name} URL"

        # Build base URL (scheme + host + optional port)
        scheme = parsed.scheme or "https"
        if port:
            base_url = f"{scheme}://{hostname}:{port}"
        else:
            base_url = f"{scheme}://{hostname}"

        return True, base_url, ""

    except Exception:
        return False, "", "Invalid URL format"


def build_welcome_message(
    trial_info: Optional[Dict] = None, team_name: str = ""
) -> list:
    """
    Build welcome message sent as DM to installer after OAuth install.

    Args:
        trial_info: Trial status info from config_client
        team_name: Name of the workspace

    Returns:
        Slack Block Kit blocks
    """
    blocks = []

    # Header
    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Welcome to IncidentFox!",
                "emoji": True,
            },
        }
    )

    # Trial status banner
    if trial_info and not trial_info.get("expired"):
        days = trial_info.get("days_remaining", 7)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":gift: *Your {days}-day free trial is active!*\n\n"
                        "I'm an AI-powered SRE assistant that helps investigate incidents."
                    ),
                },
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "I'm an AI-powered SRE assistant that helps investigate incidents.",
                },
            }
        )

    blocks.append({"type": "divider"})

    # What I can do
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*What I can do:*\n"
                    ":zap: *Auto-investigate alerts* — I'll automatically analyze alerts from incident.io, PagerDuty, and other sources posted in channels I'm in\n"
                    ":speech_balloon: *Answer questions* — Mention `@IncidentFox` with your question, error message, or alert link. You can also attach images and files!\n"
                    ":link: *Connect your tools* — I work best when connected to your observability stack (logs, metrics, APM)"
                ),
            },
        }
    )

    blocks.append({"type": "divider"})

    # Quick start
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Quick Start*\n"
                    "1. Invite me to your incident channels\n"
                    "2. Type `@IncidentFox why is this pod crashing?`\n"
                    "3. Share error messages, logs, or screenshots for context"
                ),
            },
        }
    )

    blocks.append({"type": "divider"})

    # Action buttons
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "open_setup_wizard",
                    "text": {
                        "type": "plain_text",
                        "text": "Configure IncidentFox",
                        "emoji": True,
                    },
                    "style": "primary",
                },
                {
                    "type": "button",
                    "action_id": "dismiss_welcome",
                    "text": {"type": "plain_text", "text": "Maybe Later"},
                },
            ],
        }
    )

    # Help footer
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":bulb: Click *Configure* to connect integrations, set up a custom API endpoint, or bring your own Anthropic API key.",
                }
            ],
        }
    )

    return blocks


def build_dm_welcome_message(trial_info: Optional[Dict] = None) -> list:
    """
    Welcome message shown when a user first opens DM with the app.

    This is different from the installer welcome - this is for any user
    opening the Messages tab for the first time.

    Args:
        trial_info: Trial status info (optional)

    Returns:
        Slack Block Kit blocks
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":wave: *Hi! I'm IncidentFox.*\n\n"
                    "I'm an AI-powered SRE assistant that helps investigate incidents.\n\n"
                    "*What I can do:*\n"
                    ":zap: Auto-investigate alerts posted in channels I'm in\n"
                    ":speech_balloon: Answer questions when you `@IncidentFox` (supports images & files!)\n"
                    ":link: Query your observability tools when connected\n\n"
                    "*How DMs work:*\n"
                    "Each thread is a separate session. I start fresh in every thread "
                    "and won't remember previous conversations.\n\n"
                    "Type `help` anytime for more guidance."
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "open_setup_wizard",
                    "text": {
                        "type": "plain_text",
                        "text": "Configure IncidentFox",
                        "emoji": True,
                    },
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":bulb: Click *Configure* to connect integrations, set up a custom API endpoint, or bring your own API key.",
                }
            ],
        },
    ]


def build_help_message() -> list:
    """
    Help message for DM help command.

    Returns:
        Slack Block Kit blocks
    """
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "IncidentFox Help", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*How to investigate incidents:*\n"
                    "1. Go to any channel where an incident is happening\n"
                    "2. Mention `@IncidentFox` with your question\n"
                    "3. Share relevant context (error messages, logs, screenshots)\n\n"
                    "*Example queries:*\n"
                    "• `@IncidentFox why is this pod crashing?`\n"
                    "• `@IncidentFox analyze this error: [paste error]`\n"
                    "• `@IncidentFox what changed in the last hour?`"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*How threads work:*\n"
                    "Each thread is a separate session. I start fresh in every new thread "
                    "and won't remember previous conversations. Keep related questions in the same thread "
                    "to maintain context.\n\n"
                    "*Connected integrations:*\n"
                    "To manage integrations, click on my avatar and select *Open App*.\n\n"
                    "*Need more help?*\n"
                    "• <https://docs.incidentfox.ai|Documentation>\n"
                    "• <mailto:support@incidentfox.ai|Contact Support>"
                ),
            },
        },
    ]


# =============================================================================
# INTEGRATIONS PAGE
# =============================================================================


INTEGRATIONS_PER_PAGE = 10


def build_integrations_page(
    team_id: str,
    category_filter: str = "all",
    configured: Optional[Dict] = None,
    trial_info: Optional[Dict] = None,
    page: int = 0,
) -> Dict[str, Any]:
    """
    Build the integrations page with category filters and integration cards.

    Args:
        team_id: Slack team ID
        category_filter: Category to filter by (default: "all")
        configured: Dict of already configured integrations {id: config}
        trial_info: Trial status info
        page: Page number for pagination (0-indexed)

    Returns:
        Slack modal view object
    """
    configured = configured or {}
    blocks = []

    # Welcome header with trial status
    if trial_info and not trial_info.get("expired"):
        days = trial_info.get("days_remaining", 7)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":gift: *Your {days}-day free trial is active!*\n"
                        "Connect your tools to supercharge investigations."
                    ),
                },
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        ":link: *Connect Your Tools*\n"
                        "Add integrations so I can pull logs, metrics, and context during investigations."
                    ),
                },
            }
        )

    blocks.append({"type": "divider"})

    # Category filter buttons
    category_buttons = []
    for cat_id, cat_info in CATEGORIES.items():
        is_selected = cat_id == category_filter
        emoji = cat_info.get("emoji", "")
        name = cat_info["name"]
        button_text = f"{emoji} {name}".strip() if emoji else name
        button = {
            "type": "button",
            "action_id": f"filter_category_{cat_id}",
            "text": {
                "type": "plain_text",
                "text": button_text,
                "emoji": True,
            },
        }
        if is_selected:
            button["style"] = "primary"
        category_buttons.append(button)

    # Split into rows of 2 for consistent layout (6 categories = 3 rows of 2)
    for i in range(0, len(category_buttons), 2):
        blocks.append({"type": "actions", "elements": category_buttons[i : i + 2]})

    blocks.append({"type": "divider"})

    # Get integrations for selected category
    integrations = get_integrations_by_category(category_filter)

    # Group by status: active first, then coming soon
    active_integrations = [i for i in integrations if i.get("status") == "active"]
    coming_soon_integrations = [
        i for i in integrations if i.get("status") == "coming_soon"
    ]

    # Active integrations section with pagination
    if active_integrations:
        total_active = len(active_integrations)
        total_pages = (
            total_active + INTEGRATIONS_PER_PAGE - 1
        ) // INTEGRATIONS_PER_PAGE
        page = min(page, total_pages - 1)  # Clamp to valid range

        start_idx = page * INTEGRATIONS_PER_PAGE
        end_idx = min(start_idx + INTEGRATIONS_PER_PAGE, total_active)
        page_integrations = active_integrations[start_idx:end_idx]

        if total_pages > 1:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Available Now* — Page {page + 1}/{total_pages}",
                    },
                }
            )
        else:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*Available Now*"},
                }
            )

        # Get done.png URL for status indicator
        from assets_config import get_asset_url

        done_url = get_asset_url("done")

        # Create integration cards with logos
        for idx, integration in enumerate(page_integrations):
            int_id = integration["id"]
            name = integration["name"]
            icon = integration.get("icon_fallback", ":gear:")
            description = integration.get("description", "")
            int_config = configured.get(int_id, {})
            is_configured = int_id in configured
            is_enabled = int_config.get("enabled", True) if is_configured else False
            logo_url = get_integration_logo_url(int_id)

            # For configured integrations, show status with done.png image in context block
            if is_configured and is_enabled and done_url:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "image",
                                "image_url": done_url,
                                "alt_text": "connected",
                            },
                            {
                                "type": "mrkdwn",
                                "text": "*Connected*",
                            },
                        ],
                    }
                )
            elif is_configured and not is_enabled:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": ":white_circle: *Disabled*",
                            },
                        ],
                    }
                )

            # Build section with logo image as accessory if available
            section_block = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{name}*\n{description}",
                },
            }

            # Use logo image if available, otherwise use button as accessory
            if logo_url:
                # Add image accessory
                section_block["accessory"] = {
                    "type": "image",
                    "image_url": logo_url,
                    "alt_text": name,
                }
                blocks.append(section_block)
                # Add button in separate actions block
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "action_id": f"configure_integration_{int_id}",
                                "text": {
                                    "type": "plain_text",
                                    "text": (
                                        "Configure" if not is_configured else "Edit"
                                    ),
                                    "emoji": True,
                                },
                                "style": "primary" if not is_configured else None,
                            }
                        ],
                    }
                )
                # Remove None style from button
                if blocks[-1]["elements"][0].get("style") is None:
                    del blocks[-1]["elements"][0]["style"]
            else:
                # Fallback: use emoji icon and button accessory
                section_block["text"]["text"] = f"{icon} *{name}*\n{description}"
                section_block["accessory"] = {
                    "type": "button",
                    "action_id": f"configure_integration_{int_id}",
                    "text": {
                        "type": "plain_text",
                        "text": "Configure" if not is_configured else "Edit",
                        "emoji": True,
                    },
                    "style": "primary" if not is_configured else None,
                }
                blocks.append(section_block)
                # Remove None style
                if blocks[-1]["accessory"].get("style") is None:
                    del blocks[-1]["accessory"]["style"]

            # Add divider between integrations (not after the last one)
            if idx < len(page_integrations) - 1:
                blocks.append({"type": "divider"})

        # Pagination buttons
        if total_pages > 1:
            pagination_elements = []
            if page > 0:
                pagination_elements.append(
                    {
                        "type": "button",
                        "action_id": "integrations_prev_page",
                        "text": {
                            "type": "plain_text",
                            "text": ":arrow_left: Previous",
                            "emoji": True,
                        },
                    }
                )
            if page < total_pages - 1:
                pagination_elements.append(
                    {
                        "type": "button",
                        "action_id": "integrations_next_page",
                        "text": {
                            "type": "plain_text",
                            "text": "Next :arrow_right:",
                            "emoji": True,
                        },
                    }
                )
            if pagination_elements:
                blocks.append({"type": "divider"})
                blocks.append({"type": "actions", "elements": pagination_elements})

    # Coming soon integrations section (only on last page of active integrations)
    total_pages = (
        (len(active_integrations) + INTEGRATIONS_PER_PAGE - 1) // INTEGRATIONS_PER_PAGE
        if active_integrations
        else 1
    )
    is_last_page = page >= total_pages - 1
    if coming_soon_integrations and is_last_page:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Coming Soon*"},
            }
        )

        # Show coming soon integrations with logos in context blocks
        # Context blocks can have up to 10 elements, use image + text pairs
        # Group into rows of 4 integrations (8 elements: 4 images + 4 texts)
        for i in range(0, len(coming_soon_integrations), 4):
            row_integrations = coming_soon_integrations[i : i + 4]
            context_elements = []
            for integration in row_integrations:
                int_id = integration["id"]
                name = integration["name"]
                logo_url = get_integration_logo_url(int_id)
                if logo_url:
                    context_elements.append(
                        {
                            "type": "image",
                            "image_url": logo_url,
                            "alt_text": name,
                        }
                    )
                context_elements.append(
                    {
                        "type": "plain_text",
                        "text": name,
                        "emoji": True,
                    }
                )
            if context_elements:
                blocks.append(
                    {
                        "type": "context",
                        "elements": context_elements,
                    }
                )

    # No integrations message
    if not active_integrations and not coming_soon_integrations:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_No integrations in this category yet._",
                },
            }
        )

    # Footer with Advanced Settings option
    blocks.append({"type": "divider"})
    web_ui_url = os.environ.get("WEB_UI_URL")
    footer_lines = [
        ":bulb: Add more integrations anytime: click on the IncidentFox avatar → *Open App*.",
    ]
    if web_ui_url:
        footer_lines.append(
            f":computer: Prefer a web UI? Configure integrations at <{web_ui_url}/team/tools|Web Dashboard>"
        )
    footer_lines.append(":lock: All credentials are encrypted and stored securely.")
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "\n".join(footer_lines),
                }
            ],
        }
    )

    # Advanced Settings button (BYOK, HTTP proxy)
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":gear: *Advanced Settings* — Configure LLM proxy or bring your own API key",
                }
            ],
        }
    )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "open_advanced_settings",
                    "text": {
                        "type": "plain_text",
                        "text": "Advanced Settings",
                        "emoji": True,
                    },
                }
            ],
        }
    )

    # Store metadata for the handlers
    private_metadata = json.dumps(
        {
            "team_id": team_id,
            "category_filter": category_filter,
            "page": page,
        }
    )

    return {
        "type": "modal",
        "callback_id": "integrations_page",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Set Up Integrations"},
        "submit": {"type": "plain_text", "text": "Done"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def build_advanced_settings_modal(
    team_id: str,
    existing_api_key: bool = False,
    existing_endpoint: str = None,
) -> Dict[str, Any]:
    """
    Build Advanced Settings modal for BYOK API key and HTTP proxy settings.

    Args:
        team_id: Slack team ID
        existing_api_key: Whether an API key is already configured
        existing_endpoint: Existing API endpoint if configured

    Returns:
        Slack modal view object
    """
    blocks = []

    # Header
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":gear: *Advanced Settings*\n"
                    "Configure your own Anthropic API key or custom API endpoint."
                ),
            },
        }
    )

    blocks.append({"type": "divider"})

    # BYOK Section
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Bring Your Own Key (BYOK)*\n"
                    "By default, IncidentFox uses our API key which includes a "
                    "zero data retention agreement with Anthropic. You can optionally "
                    "provide your own API key if you prefer to use your own account."
                ),
            },
        }
    )

    # Status indicator
    if existing_api_key:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": ":white_check_mark: You have a custom API key configured.",
                    }
                ],
            }
        )

    # API Key input
    blocks.append(
        {
            "type": "input",
            "block_id": "api_key_block",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "api_key_input",
                "placeholder": {"type": "plain_text", "text": "sk-ant-api..."},
            },
            "label": {"type": "plain_text", "text": "Anthropic API Key"},
            "hint": {
                "type": "plain_text",
                "text": "Leave blank to use IncidentFox's API key (recommended).",
            },
        }
    )

    # Security note - close to API key section
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":lock: Your API key is encrypted and stored securely. <https://console.anthropic.com/settings/keys|Get an API key>",
                }
            ],
        }
    )

    blocks.append({"type": "divider"})

    # HTTP Proxy / ML Gateway Section
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Custom API Endpoint*\n"
                    "If your company uses an internal ML gateway or HTTP proxy for API calls, "
                    "configure your custom endpoint here. If your proxy requires an API key, "
                    "set it in the field above."
                ),
            },
        }
    )

    # API Endpoint input
    endpoint_element = {
        "type": "plain_text_input",
        "action_id": "api_endpoint_input",
        "placeholder": {
            "type": "plain_text",
            "text": "https://api.anthropic.com (default)",
        },
    }
    if existing_endpoint:
        endpoint_element["initial_value"] = existing_endpoint

    blocks.append(
        {
            "type": "input",
            "block_id": "api_endpoint_block",
            "optional": True,
            "element": endpoint_element,
            "label": {"type": "plain_text", "text": "API Endpoint (Optional)"},
            "hint": {
                "type": "plain_text",
                "text": "Leave blank to use the default Anthropic API endpoint.",
            },
        }
    )

    # Store metadata
    private_metadata = json.dumps({"team_id": team_id})

    return {
        "type": "modal",
        "callback_id": "advanced_settings_submission",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Advanced Settings"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": blocks,
    }


def build_integration_config_modal(
    team_id: str,
    schema: Dict[str, Any] = None,
    existing_config: Optional[Dict] = None,
    integration_id: str = None,
    category_filter: str = "all",
    entry_point: str = "integrations",
) -> Dict[str, Any]:
    """
    Build integration configuration modal with video tutorial, instructions, and form fields.

    Can accept either:
    - schema: Full integration schema dict (backward compatible)
    - integration_id: ID to look up from INTEGRATIONS constant

    Args:
        team_id: Slack team ID
        schema: Integration schema with fields definition (optional if integration_id provided)
        existing_config: Existing config values to pre-fill
        integration_id: Integration ID to look up from INTEGRATIONS

    Returns:
        Slack modal view object
    """
    existing_config = existing_config or {}

    # Get integration definition
    if integration_id and not schema:
        schema = get_integration_by_id(integration_id)
        if not schema:
            # Return error modal for unknown integration
            return {
                "type": "modal",
                "callback_id": "integration_config_error",
                "title": {"type": "plain_text", "text": "Error"},
                "close": {"type": "plain_text", "text": "Close"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":warning: Integration `{integration_id}` not found.",
                        },
                    }
                ],
            }
    elif not schema:
        raise ValueError("Either schema or integration_id must be provided")

    int_id = schema.get("id", integration_id or "unknown")
    integration_name = schema.get("name", int_id.title())
    description = schema.get("description", "")
    docs_url = schema.get("docs_url")
    video_url = schema.get("video_url")
    setup_instructions = schema.get("setup_instructions", "")
    status = schema.get("status", "active")

    blocks = []

    # Header with integration logo and name
    logo_url = get_integration_logo_url(int_id)
    icon = schema.get("icon_fallback", ":gear:")

    header_block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*{integration_name}*\n{description}"
                if logo_url
                else f"{icon} *{integration_name}*\n{description}"
            ),
        },
    }
    if logo_url:
        header_block["accessory"] = {
            "type": "image",
            "image_url": logo_url,
            "alt_text": integration_name,
        }
    blocks.append(header_block)

    # Coming soon message for inactive integrations
    if status == "coming_soon":
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        ":construction: *Coming Soon!*\n\n"
                        "This integration is under development. "
                        "Want it sooner? Let us know at support@incidentfox.ai"
                    ),
                },
            }
        )

        return {
            "type": "modal",
            "callback_id": "integration_coming_soon",
            "private_metadata": json.dumps(
                {"team_id": team_id, "integration_id": int_id}
            ),
            "title": {"type": "plain_text", "text": integration_name[:24]},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": blocks,
        }

    blocks.append({"type": "divider"})

    # Enabled toggle (checkbox)
    is_enabled = existing_config.get("enabled", True)
    enabled_initial_options = []
    if is_enabled:
        enabled_initial_options = [
            {
                "text": {"type": "mrkdwn", "text": "*Enable this integration*"},
                "description": {
                    "type": "mrkdwn",
                    "text": "When enabled, IncidentFox can use this integration during investigations.",
                },
                "value": "enabled",
            }
        ]

    blocks.append(
        {
            "type": "input",
            "block_id": "field_enabled",
            "optional": True,
            "element": {
                "type": "checkboxes",
                "action_id": "input_enabled",
                "options": [
                    {
                        "text": {"type": "mrkdwn", "text": "*Enable this integration*"},
                        "description": {
                            "type": "mrkdwn",
                            "text": "When enabled, IncidentFox can use this integration during investigations.",
                        },
                        "value": "enabled",
                    }
                ],
                "initial_options": (
                    enabled_initial_options if enabled_initial_options else None
                ),
            },
            "label": {"type": "plain_text", "text": "Status"},
        }
    )
    # Remove None initial_options
    if blocks[-1]["element"].get("initial_options") is None:
        del blocks[-1]["element"]["initial_options"]

    blocks.append({"type": "divider"})

    # Video tutorial section (using Slack's video block for embedded player)
    video_config = schema.get("video")
    if video_config:
        blocks.append(
            {
                "type": "video",
                "title": {
                    "type": "plain_text",
                    "text": video_config.get(
                        "title", f"How to set up {integration_name}"
                    ),
                    "emoji": True,
                },
                "title_url": video_config.get("title_url"),
                "description": {
                    "type": "plain_text",
                    "text": video_config.get("description", "Setup tutorial")[:200],
                    "emoji": True,
                },
                "video_url": video_config.get("video_url"),
                "thumbnail_url": video_config.get("thumbnail_url"),
                "alt_text": video_config.get(
                    "alt_text", f"{integration_name} setup tutorial"
                ),
                "author_name": "IncidentFox",
                "provider_name": "🎬 Video",
            }
        )
        blocks.append({"type": "divider"})

    # Setup instructions
    if setup_instructions:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": setup_instructions},
            }
        )

        # Add docs link if available
        if docs_url:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f":book: <{docs_url}|View full documentation>",
                        }
                    ],
                }
            )

        blocks.append({"type": "divider"})

    # Add GitHub App install button for GitHub App auth type
    auth_type = schema.get("auth_type")
    github_app_url = schema.get("github_app_url")
    if auth_type == "github_app" and github_app_url:
        # Check if already linked
        is_github_linked = existing_config.get("_github_linked", False)
        github_installation = existing_config.get("_github_installation", {})

        if is_github_linked:
            # Show connected status
            linked_org = github_installation.get("account_login", "")
            linked_type = github_installation.get("account_type", "Organization")
            avatar_url = github_installation.get("account_avatar_url")

            status_text = f":white_check_mark: *Connected to GitHub {linked_type.lower()}:* `{linked_org}`"

            status_block = {
                "type": "section",
                "text": {"type": "mrkdwn", "text": status_text},
            }
            if avatar_url:
                status_block["accessory"] = {
                    "type": "image",
                    "image_url": avatar_url,
                    "alt_text": linked_org,
                }
            blocks.append(status_block)

            # Show repos if available
            repos = github_installation.get("repositories")
            repo_selection = github_installation.get("repository_selection")
            if repo_selection == "all":
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": ":file_folder: Access to *all repositories*",
                            }
                        ],
                    }
                )
            elif repos:
                repo_list = ", ".join(repos[:5])
                if len(repos) > 5:
                    repo_list += f" (+{len(repos) - 5} more)"
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f":file_folder: Repositories: {repo_list}",
                            }
                        ],
                    }
                )

            blocks.append({"type": "divider"})

            # Show button to reconnect/change
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":arrows_counterclockwise: To connect a different org, install the app on that org first:",
                        }
                    ],
                }
            )

        # Always show install button (for new installs or reconnecting)
        button_text = (
            "Install on Another Org" if is_github_linked else "Install GitHub App"
        )
        button_style = None if is_github_linked else "primary"

        button_block = {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": button_text,
                        "emoji": True,
                    },
                    "url": github_app_url,
                    "action_id": "github_app_install_button",
                }
            ],
        }
        if button_style:
            button_block["elements"][0]["style"] = button_style
        blocks.append(button_block)

        if not is_github_linked:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":point_up: Click to open GitHub in a new tab. After installing, return here to complete setup.",
                        }
                    ],
                }
            )
        blocks.append({"type": "divider"})

    # Track field names and secret field IDs for submission handler
    field_names = []
    secret_fields = []

    # Generate form fields from schema
    fields = schema.get("fields", [])
    for field in fields:
        field_id = field.get("id")
        field_name = field.get("name", field_id)
        field_type = field.get("type", "string")
        field_hint = field.get("hint", "")
        field_required = field.get("required", False)
        field_placeholder = field.get("placeholder", "")

        field_names.append(field_id)

        # Make field optional if:
        # 1. Field already has a value (editing scenario) - especially for secret fields, OR
        # 2. Field is not originally required
        # Note: We can't make fields optional based on enabled status because the user
        # can change that checkbox in the modal itself
        # Special case: Datadog stores 'site' but UI field is 'domain'
        if int_id == "datadog" and field_id == "domain":
            field_has_value = "site" in existing_config
        else:
            field_has_value = field_id in existing_config
        make_optional = field_has_value or not field_required

        if field_type == "secret":
            # Secret fields: show redacted value if configured, otherwise empty
            secret_fields.append(field_id)
            hint_text = field_hint
            existing_value = existing_config.get(field_id)
            if field_has_value and existing_value:
                redacted = "*" * len(str(existing_value))
                hint_text = (
                    f"{field_hint} (already configured - leave blank to keep existing)"
                    if field_hint
                    else "Already configured - leave blank to keep existing value"
                )
            else:
                redacted = None

            element = {
                "type": "plain_text_input",
                "action_id": f"input_{field_id}",
                "placeholder": {
                    "type": "plain_text",
                    "text": field_placeholder or "Enter value...",
                },
            }
            if redacted:
                element["initial_value"] = redacted

            input_block = {
                "type": "input",
                "block_id": f"field_{field_id}",
                "optional": make_optional,
                "element": element,
                "label": {"type": "plain_text", "text": field_name},
            }
            if hint_text:
                input_block["hint"] = {"type": "plain_text", "text": hint_text}
            blocks.append(input_block)

        elif field_type == "boolean":
            # Boolean fields: checkboxes
            initial_options = []
            if existing_config.get(field_id):
                initial_options = [
                    {
                        "text": {"type": "plain_text", "text": field_name},
                        "value": "true",
                    }
                ]

            element = {
                "type": "checkboxes",
                "action_id": f"input_{field_id}",
                "options": [
                    {
                        "text": {"type": "plain_text", "text": field_name},
                        "value": "true",
                    }
                ],
            }
            if initial_options:
                element["initial_options"] = initial_options

            blocks.append(
                {
                    "type": "input",
                    "block_id": f"field_{field_id}",
                    "optional": True,
                    "element": element,
                    "label": {"type": "plain_text", "text": field_name},
                }
            )

        elif field_type == "select" and field.get("options"):
            # Select fields with predefined options
            options = [
                {"text": {"type": "plain_text", "text": opt}, "value": opt}
                for opt in field.get("options", [])
            ]
            existing_value = existing_config.get(field_id)

            element = {
                "type": "static_select",
                "action_id": f"input_{field_id}",
                "placeholder": {
                    "type": "plain_text",
                    "text": field_placeholder or "Select...",
                },
                "options": options,
            }
            if existing_value:
                element["initial_option"] = {
                    "text": {"type": "plain_text", "text": existing_value},
                    "value": existing_value,
                }

            input_block = {
                "type": "input",
                "block_id": f"field_{field_id}",
                "optional": make_optional,
                "element": element,
                "label": {"type": "plain_text", "text": field_name},
            }
            if field_hint:
                input_block["hint"] = {"type": "plain_text", "text": field_hint}
            blocks.append(input_block)

        else:
            # Default: string field (plain text input, can pre-fill)
            # Special case: Datadog stores 'site' but UI field is 'domain'
            if int_id == "datadog" and field_id == "domain":
                existing_value = existing_config.get("site", "")
            else:
                existing_value = existing_config.get(field_id, "")
            element = {
                "type": "plain_text_input",
                "action_id": f"input_{field_id}",
                "placeholder": {
                    "type": "plain_text",
                    "text": field_placeholder or "Enter value...",
                },
            }
            if existing_value:
                element["initial_value"] = str(existing_value)

            input_block = {
                "type": "input",
                "block_id": f"field_{field_id}",
                "optional": make_optional,
                "element": element,
                "label": {"type": "plain_text", "text": field_name},
            }
            if field_hint:
                input_block["hint"] = {"type": "plain_text", "text": field_hint}

            blocks.append(input_block)

    # Context prompt field (free-form text for LLM context)
    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Custom Context (Optional)*\n"
                    "Provide additional context about this integration that will help IncidentFox "
                    "understand your setup better."
                ),
            },
        }
    )

    context_prompt_value = existing_config.get("context_prompt", "")
    # Use integration-specific placeholder or a generic default
    context_placeholder = schema.get(
        "context_prompt_placeholder",
        "e.g., 'Describe your setup, naming conventions, or any context that helps the AI understand your environment.'",
    )
    context_element = {
        "type": "plain_text_input",
        "action_id": "input_context_prompt",
        "multiline": True,
        "placeholder": {
            "type": "plain_text",
            "text": context_placeholder,
        },
    }
    if context_prompt_value:
        context_element["initial_value"] = context_prompt_value

    blocks.append(
        {
            "type": "input",
            "block_id": "field_context_prompt",
            "optional": True,
            "element": context_element,
            "label": {"type": "plain_text", "text": "Context for AI"},
            "hint": {
                "type": "plain_text",
                "text": "This context will be provided to the AI during investigations to help it query this integration more effectively.",
            },
        }
    )

    # Security note
    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":lock: Credentials are encrypted and stored securely.",
                }
            ],
        }
    )

    # Store metadata for submission handler
    # Include enabled and context_prompt as special fields
    all_field_names = ["enabled"] + field_names + ["context_prompt"]
    private_metadata = json.dumps(
        {
            "team_id": team_id,
            "integration_id": int_id,
            "field_names": all_field_names,
            "secret_fields": secret_fields,
            "category_filter": category_filter,
            "entry_point": entry_point,
        }
    )

    return {
        "type": "modal",
        "callback_id": "integration_config_submission",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": integration_name[:24]},  # Max 24 chars
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": blocks,
    }


# =============================================================================
# KUBERNETES SAAS MODAL BUILDERS
# =============================================================================


def build_k8s_saas_clusters_modal(
    team_id: str,
    clusters: List[Dict[str, Any]],
    category_filter: str = "all",
    entry_point: str = "integrations",
) -> Dict[str, Any]:
    """
    Build the K8s SaaS clusters management modal.

    Shows list of connected clusters with status and allows adding/removing.

    Args:
        team_id: Slack team ID
        clusters: List of cluster summary dicts from config_client
        category_filter: Category filter to preserve on back navigation
        entry_point: Entry point to preserve on back navigation

    Returns:
        Slack modal view object
    """
    blocks = []

    # Header
    logo_url = get_integration_logo_url("kubernetes_saas")
    header_block = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "*Kubernetes (Agent Mode)*\n"
                "Connect your K8s clusters by deploying our lightweight agent. "
                "No inbound firewall rules needed - the agent connects outbound to IncidentFox."
            ),
        },
    }
    if logo_url:
        header_block["accessory"] = {
            "type": "image",
            "image_url": logo_url,
            "alt_text": "Kubernetes",
        }
    blocks.append(header_block)
    blocks.append({"type": "divider"})

    # Add cluster button
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": ":heavy_plus_sign: Add Cluster",
                    },
                    "style": "primary",
                    "action_id": "k8s_saas_add_cluster",
                }
            ],
        }
    )

    blocks.append({"type": "divider"})

    # Clusters list
    if not clusters:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "_No clusters connected yet._\n\n"
                        "Click *Add Cluster* to register your first Kubernetes cluster."
                    ),
                },
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Connected Clusters*"},
            }
        )

        for cluster in clusters:
            cluster_id = cluster.get("cluster_id", "")
            cluster_name = cluster.get("cluster_name", "Unknown")
            display_name = cluster.get("display_name") or cluster_name
            status = cluster.get("status", "disconnected")
            k8s_version = cluster.get("kubernetes_version", "")
            node_count = cluster.get("node_count")
            last_heartbeat = cluster.get("last_heartbeat_at", "")

            # Status indicator
            status_emoji = {
                "connected": ":large_green_circle:",
                "disconnected": ":red_circle:",
                "error": ":warning:",
            }.get(status, ":white_circle:")

            # Build info text
            info_parts = []
            if k8s_version:
                info_parts.append(f"K8s {k8s_version}")
            if node_count:
                info_parts.append(f"{node_count} nodes")
            info_text = " • ".join(info_parts) if info_parts else ""

            cluster_text = f"{status_emoji} *{display_name}*"
            if cluster_name != display_name:
                cluster_text += f" (`{cluster_name}`)"
            if info_text:
                cluster_text += f"\n{info_text}"
            if status == "disconnected" and not last_heartbeat:
                cluster_text += (
                    "\n_Agent not yet connected - deploy using Helm command_"
                )

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": cluster_text},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": ":wastebasket: Remove"},
                        "style": "danger",
                        "action_id": "k8s_saas_remove_cluster",
                        "value": cluster_id,
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Remove Cluster?"},
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"This will disconnect *{display_name}* and revoke its API key.\n\n"
                                    "The agent in your cluster will stop working. "
                                    "You can always add the cluster again later."
                                ),
                            },
                            "confirm": {"type": "plain_text", "text": "Remove"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                }
            )

    # How it works section
    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        ":book: <https://docs.incidentfox.ai/integrations/kubernetes-agent|"
                        "View documentation> • The agent connects outbound via HTTPS - "
                        "no inbound firewall rules needed."
                    ),
                }
            ],
        }
    )

    private_metadata = json.dumps(
        {
            "team_id": team_id,
            "category_filter": category_filter,
            "entry_point": entry_point,
        }
    )

    return {
        "type": "modal",
        "callback_id": "k8s_saas_clusters_modal",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "K8s Clusters"},
        "close": {"type": "plain_text", "text": "Back"},
        "blocks": blocks,
    }


def build_k8s_saas_add_cluster_modal(
    team_id: str,
    category_filter: str = "all",
    entry_point: str = "integrations",
) -> Dict[str, Any]:
    """
    Build modal for adding a new K8s cluster.

    Args:
        team_id: Slack team ID
        category_filter: Category filter to preserve
        entry_point: Entry point to preserve

    Returns:
        Slack modal view object
    """
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Register a New Cluster*\n\n"
                    "Give your cluster a name to identify it in IncidentFox. "
                    "You'll get a Helm command to deploy the agent."
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "input",
            "block_id": "cluster_name",
            "element": {
                "type": "plain_text_input",
                "action_id": "cluster_name_input",
                "placeholder": {
                    "type": "plain_text",
                    "text": "e.g., prod-us-east-1, staging, dev-cluster",
                },
                "max_length": 63,  # K8s naming convention
            },
            "label": {"type": "plain_text", "text": "Cluster Name"},
            "hint": {
                "type": "plain_text",
                "text": "Use lowercase letters, numbers, and hyphens. Must be unique.",
            },
        },
        {
            "type": "input",
            "block_id": "display_name",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "display_name_input",
                "placeholder": {
                    "type": "plain_text",
                    "text": "e.g., Production US East, Staging Environment",
                },
                "max_length": 256,
            },
            "label": {"type": "plain_text", "text": "Display Name (Optional)"},
            "hint": {
                "type": "plain_text",
                "text": "A human-friendly name shown in the UI.",
            },
        },
    ]

    private_metadata = json.dumps(
        {
            "team_id": team_id,
            "category_filter": category_filter,
            "entry_point": entry_point,
        }
    )

    return {
        "type": "modal",
        "callback_id": "k8s_saas_add_cluster_submission",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Add Cluster"},
        "submit": {"type": "plain_text", "text": "Create"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def build_k8s_saas_cluster_created_modal(
    team_id: str,
    cluster_name: str,
    display_name: Optional[str],
    token: str,
    helm_command: str,
    category_filter: str = "all",
    entry_point: str = "integrations",
) -> Dict[str, Any]:
    """
    Build modal showing the Helm install command after creating a cluster.

    Args:
        team_id: Slack team ID
        cluster_name: Cluster name
        display_name: Display name (optional)
        token: API token (shown only once)
        helm_command: Full Helm install command
        category_filter: Category filter to preserve
        entry_point: Entry point to preserve

    Returns:
        Slack modal view object
    """
    name_display = display_name or cluster_name

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: *Cluster '{name_display}' Created!*",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Deploy the Agent*\n\n"
                    "Run this command in your terminal to deploy the IncidentFox agent to your cluster:"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{helm_command}```",
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        ":warning: *Save this command now!* The API key is only shown once.\n"
                        ":lock: The agent connects outbound via HTTPS - no firewall changes needed."
                    ),
                }
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*What happens next?*\n"
                    "1. Run the Helm command above\n"
                    "2. The agent will connect to IncidentFox within ~30 seconds\n"
                    "3. You'll see the cluster status change to :large_green_circle: Connected"
                ),
            },
        },
    ]

    private_metadata = json.dumps(
        {
            "team_id": team_id,
            "cluster_name": cluster_name,
            "category_filter": category_filter,
            "entry_point": entry_point,
        }
    )

    return {
        "type": "modal",
        "callback_id": "k8s_saas_cluster_created_modal",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Deploy Agent"},
        "close": {"type": "plain_text", "text": "Done"},
        "blocks": blocks,
    }
