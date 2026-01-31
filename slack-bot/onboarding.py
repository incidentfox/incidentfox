"""
Onboarding Flow for IncidentFox Slack Bot

Handles:
1. Workspace provisioning when OAuth completes
2. API key setup modal
3. Free trial management
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


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

    # Header section
    if trial_info and not trial_info.get("expired"):
        days = trial_info.get("days_remaining", 0)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":rocket: *You're on a free trial!*\n"
                    f"You have *{days} days* remaining. "
                    f"Add your own API key to continue using IncidentFox after the trial."
                )
            }
        })
        blocks.append({"type": "divider"})
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":key: *Set up your Anthropic API key*\n\n"
                    "IncidentFox uses Claude to investigate incidents. "
                    "Enter your Anthropic API key below to get started."
                )
            }
        })
        blocks.append({"type": "divider"})

    # Error message if any
    if error_message:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Error:* {error_message}"
            }
        })

    # API Key input
    blocks.append({
        "type": "input",
        "block_id": "api_key_block",
        "element": {
            "type": "plain_text_input",
            "action_id": "api_key_input",
            "placeholder": {
                "type": "plain_text",
                "text": "sk-ant-api..."
            }
        },
        "label": {
            "type": "plain_text",
            "text": "Anthropic API Key"
        },
        "hint": {
            "type": "plain_text",
            "text": "Get your API key from console.anthropic.com"
        }
    })

    # Optional API endpoint (for enterprise ML gateways)
    blocks.append({
        "type": "input",
        "block_id": "api_endpoint_block",
        "optional": True,
        "element": {
            "type": "plain_text_input",
            "action_id": "api_endpoint_input",
            "placeholder": {
                "type": "plain_text",
                "text": "https://api.anthropic.com (default)"
            }
        },
        "label": {
            "type": "plain_text",
            "text": "API Endpoint (Optional)"
        },
        "hint": {
            "type": "plain_text",
            "text": "Leave blank to use the default Anthropic API. Set this if your company uses an internal ML gateway."
        }
    })

    # Help text
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    ":lock: Your API key is encrypted and stored securely. "
                    "<https://console.anthropic.com/settings/keys|Get an API key>"
                )
            }
        ]
    })

    return {
        "type": "modal",
        "callback_id": "api_key_submission",
        "private_metadata": team_id,  # Store team_id for submission handler
        "title": {
            "type": "plain_text",
            "text": "IncidentFox Setup"
        },
        "submit": {
            "type": "plain_text",
            "text": "Save"
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel"
        },
        "blocks": blocks
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
        # Trial expired
        header_text = ":warning: *Your free trial has ended*"
        if show_upgrade:
            body_text = (
                "To continue using IncidentFox, you'll need to:\n"
                "1. Upgrade to a paid subscription\n"
                "2. Add your Anthropic API key\n\n"
                "Click the button below to set up your API key, then upgrade your plan."
            )
        else:
            body_text = (
                "To continue using IncidentFox, please add your Anthropic API key.\n\n"
                "Click the button below to set up your API key."
            )
    elif trial_info and trial_info.get("days_remaining", 0) <= 3:
        # Trial expiring soon
        days = trial_info.get("days_remaining", 0)
        header_text = f":hourglass: *Your free trial expires in {days} days*"
        body_text = (
            "Add your Anthropic API key now to ensure uninterrupted service.\n\n"
            "Click the button below to set up your API key."
        )
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

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": header_text
        }
    })

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": body_text
        }
    })

    # Build action buttons based on whether upgrade is needed
    action_elements = [
        {
            "type": "button",
            "action_id": "open_api_key_modal",
            "text": {
                "type": "plain_text",
                "text": ":key: Set Up API Key",
                "emoji": True
            },
            "style": "primary"
        }
    ]

    if show_upgrade:
        action_elements.append({
            "type": "button",
            "action_id": "open_upgrade_page",
            "text": {
                "type": "plain_text",
                "text": ":credit_card: View Pricing",
                "emoji": True
            },
            "url": "https://incidentfox.ai/pricing"
        })
    else:
        action_elements.append({
            "type": "button",
            "action_id": "dismiss_setup_message",
            "text": {
                "type": "plain_text",
                "text": "Later"
            }
        })

    blocks.append({
        "type": "actions",
        "elements": action_elements
    })

    help_text = ":bulb: Need help? Visit <https://docs.incidentfox.ai|our docs> or contact support."
    if show_upgrade:
        help_text = ":bulb: Questions about pricing? Email us at support@incidentfox.ai"

    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": help_text
            }
        ]
    })

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
                )
            }
        }
    ]


def build_upgrade_required_message(trial_info: Optional[Dict] = None) -> list:
    """
    Build a message prompting user to upgrade their subscription.

    This is shown when trial has expired and they have an API key but no subscription.
    They need to pay for a subscription to continue using the service.
    """
    blocks = []

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": ":warning: *Subscription required*"
        }
    })

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "Your free trial has ended. We noticed you've already set up your "
                "API key - great!\n\n"
                "To continue using IncidentFox, please upgrade to a paid subscription. "
                "Your API key will be used once the subscription is active."
            )
        }
    })

    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "action_id": "open_upgrade_page",
                "text": {
                    "type": "plain_text",
                    "text": ":credit_card: Upgrade Now",
                    "emoji": True
                },
                "style": "primary",
                "url": "https://incidentfox.ai/pricing"
            },
            {
                "type": "button",
                "action_id": "contact_sales",
                "text": {
                    "type": "plain_text",
                    "text": "Contact Sales"
                },
                "url": "https://incidentfox.ai/contact"
            }
        ]
    })

    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    ":bulb: Plans start at $X/month. "
                    "Questions? Email us at support@incidentfox.ai"
                )
            }
        ]
    })

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
