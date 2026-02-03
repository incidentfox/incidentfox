"""
Onboarding Flow for IncidentFox Slack Bot

Handles:
1. Workspace provisioning when OAuth completes
2. Integration setup wizard
3. Free trial management
"""

import json
import logging
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
    # COMING SOON INTEGRATIONS
    {
        "id": "datadog",
        "name": "Datadog",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":datadog:",
        "icon_fallback": ":dog:",
        "description": "Query logs, metrics, and APM traces from Datadog.",
    },
    {
        "id": "cloudwatch",
        "name": "CloudWatch",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":cloudwatch:",
        "icon_fallback": ":cloud:",
        "description": "Query AWS CloudWatch logs and metrics.",
    },
    {
        "id": "pagerduty",
        "name": "PagerDuty",
        "category": "incident",
        "status": "coming_soon",
        "icon": ":pagerduty:",
        "icon_fallback": ":bell:",
        "description": "Acknowledge alerts and pull incident context.",
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
        "id": "github",
        "name": "GitHub",
        "category": "scm",
        "status": "coming_soon",
        "icon": ":github:",
        "icon_fallback": ":octocat:",
        "description": "Search code, PRs, and recent deployments.",
    },
    {
        "id": "kubernetes",
        "name": "Kubernetes",
        "category": "infra",
        "status": "coming_soon",
        "icon": ":kubernetes:",
        "icon_fallback": ":wheel_of_dharma:",
        "description": "Query pods, deployments, and cluster state.",
    },
    {
        "id": "prometheus",
        "name": "Prometheus",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":prometheus:",
        "icon_fallback": ":fire:",
        "description": "Query metrics and alerts from Prometheus.",
    },
    {
        "id": "grafana",
        "name": "Grafana",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":grafana:",
        "icon_fallback": ":bar_chart:",
        "description": "Query dashboards and annotations.",
    },
    {
        "id": "splunk",
        "name": "Splunk",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":splunk:",
        "icon_fallback": ":mag:",
        "description": "Query logs and metrics from Splunk.",
    },
    {
        "id": "elasticsearch",
        "name": "Elasticsearch",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":elasticsearch:",
        "icon_fallback": ":mag:",
        "description": "Query logs and search data from Elasticsearch.",
    },
    {
        "id": "opensearch",
        "name": "OpenSearch",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":opensearch:",
        "icon_fallback": ":mag:",
        "description": "Query logs and search data from OpenSearch.",
    },
    {
        "id": "newrelic",
        "name": "New Relic",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":newrelic:",
        "icon_fallback": ":chart:",
        "description": "Query APM, logs, and infrastructure metrics.",
    },
    {
        "id": "honeycomb",
        "name": "Honeycomb",
        "category": "observability",
        "status": "coming_soon",
        "icon": ":honeycomb:",
        "icon_fallback": ":honeybee:",
        "description": "Query observability data and traces.",
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
        "status": "coming_soon",
        "icon": ":sentry:",
        "icon_fallback": ":bug:",
        "description": "Query application errors and performance issues.",
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
        "status": "coming_soon",
        "icon": ":jira:",
        "icon_fallback": ":ticket:",
        "description": "Query issues and project data.",
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


def build_integrations_page(
    team_id: str,
    category_filter: str = "all",
    configured: Optional[Dict] = None,
    trial_info: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Build the integrations page with category filters and integration cards.

    Args:
        team_id: Slack team ID
        category_filter: Category to filter by (default: "all")
        configured: Dict of already configured integrations {id: config}
        trial_info: Trial status info

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

    # Active integrations section
    if active_integrations:
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
        for idx, integration in enumerate(active_integrations):
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
            if idx < len(active_integrations) - 1:
                blocks.append({"type": "divider"})

    # Coming soon integrations section
    if coming_soon_integrations:
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
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        ":bulb: Add more integrations anytime: click on the IncidentFox avatar → *Open App*.\n"
                        ":lock: All credentials are encrypted and stored securely."
                    ),
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
                "provider_name": "YouTube",
                "provider_icon_url": "https://www.youtube.com/s/desktop/b3c2a2a0/img/favicon_144x144.png",
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

    # Track field names for submission handler
    field_names = []

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
        field_has_value = field_id in existing_config
        make_optional = field_has_value or not field_required

        if field_type == "secret":
            # Secret fields: plain text input, don't pre-fill
            # Always optional when editing (field_has_value) to avoid forcing re-entry
            hint_text = field_hint
            if field_has_value:
                hint_text = (
                    f"{field_hint} (already configured - leave blank to keep existing)"
                    if field_hint
                    else "Already configured - leave blank to keep existing value"
                )

            input_block = {
                "type": "input",
                "block_id": f"field_{field_id}",
                "optional": make_optional,
                "element": {
                    "type": "plain_text_input",
                    "action_id": f"input_{field_id}",
                    "placeholder": {
                        "type": "plain_text",
                        "text": field_placeholder or "Enter value...",
                    },
                },
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
