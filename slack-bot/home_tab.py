"""
Home Tab view builders for IncidentFox Slack Bot.

Provides the App Home tab UI for managing integrations and viewing status.
Handles Slack's 100-block limit via pagination.
"""

import json
from typing import Dict, List, Optional

from assets_config import get_integration_logo_url
from onboarding import INTEGRATIONS, get_integration_by_id

# Slack enforces a 100-block limit on Home tab views.
# Paginate at 95 blocks to leave room for pagination controls (divider + page info + buttons).
BLOCKS_PER_PAGE = 95


def build_home_tab_view(
    team_id: str,
    trial_info: Optional[Dict],
    configured_integrations: Dict[str, Dict],
    available_schemas: List[Dict] = None,  # Deprecated - now uses INTEGRATIONS
    user_is_admin: bool = False,
    page: int = 1,
) -> Dict:
    """
    Build the App Home tab view.

    Args:
        team_id: Slack team ID
        trial_info: Trial status info from config_client
        configured_integrations: Dict of configured integration configs
        available_schemas: Deprecated - now uses INTEGRATIONS from onboarding
        user_is_admin: Whether the user is a workspace admin
        page: Page number (1-indexed) for pagination

    Returns:
        Slack Home tab view object
    """
    blocks = []

    # Header
    blocks.append(
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "IncidentFox", "emoji": True},
        }
    )

    # Trial/subscription status banner
    CALENDLY_URL = (
        "https://calendly.com/d/cxd2-4hb-qgp/30-minute-demo-call-w-incidentfox"
    )
    if trial_info and not trial_info.get("expired"):
        days = trial_info.get("days_remaining", 0)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":gift: *Free trial active* — {days} {'day' if days == 1 else 'days'} remaining",
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Book a Demo",
                        "emoji": True,
                    },
                    "action_id": "home_book_demo",
                    "url": CALENDLY_URL,
                },
            }
        )
    elif trial_info and trial_info.get("expired"):
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":warning: *Trial expired* — <"
                    + CALENDLY_URL
                    + "|Book a demo> or configure your API key below",
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Book a Demo",
                        "emoji": True,
                    },
                    "action_id": "home_book_demo",
                    "url": CALENDLY_URL,
                    "style": "primary",
                },
            }
        )

    blocks.append({"type": "divider"})

    # Quick start section
    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Quick Start*\n"
                    "Mention `@IncidentFox` in any channel to start investigating.\n"
                    "Share error messages, logs, or alert links for analysis."
                ),
            },
        }
    )

    blocks.append({"type": "divider"})

    # AI Model section
    blocks.append(
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "AI Model"},
        }
    )

    llm_config = configured_integrations.get("llm", {})
    current_model = llm_config.get("model", "")

    if current_model:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":robot_face: *Current model:* `{current_model}`",
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Change Model",
                        "emoji": True,
                    },
                    "action_id": "home_open_ai_model_selector",
                },
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":robot_face: *Using default:* `claude-sonnet-4-20250514`",
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Change Model",
                        "emoji": True,
                    },
                    "action_id": "home_open_ai_model_selector",
                    "style": "primary",
                },
            }
        )

    blocks.append({"type": "divider"})

    # Connected integrations section
    blocks.append(
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Connected Integrations"},
        }
    )

    # Filter configured integrations to only active, non-LLM, non-orphaned
    displayable_configured = []
    if configured_integrations:
        for int_id, config in configured_integrations.items():
            integration = get_integration_by_id(int_id)
            if not integration:
                continue  # Orphan (in config DB but not in INTEGRATIONS)
            if integration.get("category") == "llm":
                continue  # Shown in AI Model section
            if integration.get("status") != "active":
                continue  # coming_soon shouldn't appear as connected
            displayable_configured.append((int_id, config, integration))

        # Sort alphabetically by display name
        displayable_configured.sort(
            key=lambda item: item[2].get("name", item[0]).lower()
        )

    if displayable_configured:
        for int_id, config, integration in displayable_configured:
            name = integration.get("name", int_id.title())
            description = integration.get("description", "")
            logo_url = get_integration_logo_url(int_id)
            is_enabled = config.get("enabled", True)

            # Truncate description
            if len(description) > 60:
                description = description[:57] + "..."

            # Status prefix in text (avoids a separate context block)
            status_prefix = "" if is_enabled else ":white_circle: "

            section_block = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{status_prefix}*{name}*\n{description}",
                },
            }

            # Add logo if available
            if logo_url:
                section_block["accessory"] = {
                    "type": "image",
                    "image_url": logo_url,
                    "alt_text": name,
                }
                blocks.append(section_block)
                # Add Edit button in separate actions block
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Edit"},
                                "action_id": f"home_edit_integration_{int_id}",
                            }
                        ],
                    }
                )
            else:
                # No logo - use button as accessory
                section_block["accessory"] = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "action_id": f"home_edit_integration_{int_id}",
                }
                blocks.append(section_block)
    else:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_No integrations connected yet_"},
            }
        )

    blocks.append({"type": "divider"})

    # Available integrations section - use INTEGRATIONS from onboarding
    blocks.append(
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Available Integrations"},
        }
    )

    # Get active integrations not yet configured, sorted alphabetically
    active_integrations = sorted(
        [
            i
            for i in INTEGRATIONS
            if i.get("status") == "active"
            and i.get("id") not in configured_integrations
            and i.get("category") != "llm"  # LLM handled in AI Model section
        ],
        key=lambda i: i.get("name", "").lower(),
    )

    if active_integrations:
        for integration in active_integrations:
            int_id = integration["id"]
            name = integration["name"]
            description = integration.get("description", "")
            logo_url = get_integration_logo_url(int_id)

            # Truncate description
            if len(description) > 60:
                description = description[:57] + "..."

            section_block = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{name}*\n{description}",
                },
            }

            # Add logo if available
            if logo_url:
                section_block["accessory"] = {
                    "type": "image",
                    "image_url": logo_url,
                    "alt_text": name,
                }
                blocks.append(section_block)
                # Add Connect button in separate actions block
                blocks.append(
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Connect"},
                                "action_id": f"home_add_integration_{int_id}",
                                "style": "primary",
                            }
                        ],
                    }
                )
            else:
                section_block["accessory"] = {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Connect"},
                    "action_id": f"home_add_integration_{int_id}",
                    "style": "primary",
                }
                blocks.append(section_block)

        blocks.append({"type": "divider"})
    elif not active_integrations and configured_integrations:
        # All active integrations are connected
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":white_check_mark: _All available integrations are connected!_",
                },
            }
        )
        blocks.append({"type": "divider"})

    # Coming Soon section
    coming_soon = [i for i in INTEGRATIONS if i.get("status") == "coming_soon"]
    if coming_soon:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Coming Soon*"},
            }
        )

        # Show coming soon integrations with logos in context blocks
        # Group into rows of 4 integrations
        for i in range(0, len(coming_soon), 4):
            row_integrations = coming_soon[i : i + 4]
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

        blocks.append({"type": "divider"})

    # Advanced Settings section
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
                    "text": {
                        "type": "plain_text",
                        "text": "Advanced Settings",
                        "emoji": True,
                    },
                    "action_id": "open_advanced_settings",
                },
            ],
        }
    )

    # Help footer
    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        ":bulb: <https://docs.incidentfox.ai|Documentation> • "
                        "<mailto:support@incidentfox.ai|Support>"
                    ),
                }
            ],
        }
    )

    # Paginate if over the safe block limit (leaves room for pagination controls)
    total_blocks = len(blocks)
    if total_blocks > BLOCKS_PER_PAGE:
        total_pages = (total_blocks + BLOCKS_PER_PAGE - 1) // BLOCKS_PER_PAGE
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * BLOCKS_PER_PAGE
        end_idx = min(start_idx + BLOCKS_PER_PAGE, total_blocks)
        blocks = blocks[start_idx:end_idx]

        # Pagination controls
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Page {page} of {total_pages}"}
                ],
            }
        )

        pagination_elements = []
        if page > 1:
            pagination_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Previous"},
                    "action_id": "home_page_prev",
                    "value": json.dumps({"team_id": team_id, "page": page - 1}),
                }
            )
        if page < total_pages:
            pagination_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Next"},
                    "action_id": "home_page_next",
                    "value": json.dumps({"team_id": team_id, "page": page + 1}),
                }
            )
        if pagination_elements:
            blocks.append({"type": "actions", "elements": pagination_elements})

    return {"type": "home", "blocks": blocks}
