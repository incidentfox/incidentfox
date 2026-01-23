"""Microsoft Teams integration tools for notifications and collaboration."""

import os
from typing import Any

import requests

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_msteams_config() -> dict:
    """Get Microsoft Teams configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("msteams")
        if config and config.get("webhook_url"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("MSTEAMS_WEBHOOK_URL"):
        return {
            "webhook_url": os.getenv("MSTEAMS_WEBHOOK_URL"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="msteams",
        tool_id="msteams_tools",
        missing_fields=["webhook_url"],
    )


def send_teams_message(
    message: str, title: str | None = None, color: str = "0078D4"
) -> dict[str, Any]:
    """
    Send a message to Microsoft Teams via incoming webhook.

    Args:
        message: Message text (supports markdown)
        title: Optional title for the message card
        color: Hex color for the card accent (default: Microsoft blue)

    Returns:
        Send operation result
    """
    try:
        config = _get_msteams_config()

        # Build message card
        card = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "themeColor": color,
            "text": message,
        }

        if title:
            card["title"] = title

        # Send to webhook
        response = requests.post(
            config["webhook_url"],
            json=card,
            headers={"Content-Type": "application/json"},
        )

        response.raise_for_status()

        logger.info("teams_message_sent", title=title or "untitled")

        return {
            "success": True,
            "status_code": response.status_code,
            "message": "Message sent successfully",
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "send_teams_message", "msteams")
    except Exception as e:
        logger.error("teams_message_failed", error=str(e))
        raise ToolExecutionError("send_teams_message", str(e), e)


def send_teams_adaptive_card(
    title: str, body: list, actions: list | None = None
) -> dict[str, Any]:
    """
    Send an Adaptive Card to Microsoft Teams.

    Args:
        title: Card title
        body: List of card body elements (see Adaptive Cards schema)
        actions: Optional list of card actions

    Returns:
        Send operation result

    Example body:
        [
            {"type": "TextBlock", "text": "This is some text", "wrap": True},
            {"type": "FactSet", "facts": [
                {"title": "Status:", "value": "Active"},
                {"title": "Region:", "value": "US-West"}
            ]}
        ]
    """
    try:
        config = _get_msteams_config()

        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.2",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": title,
                                "weight": "Bolder",
                                "size": "Medium",
                            }
                        ]
                        + body,
                    },
                }
            ],
        }

        if actions:
            card["attachments"][0]["content"]["actions"] = actions

        response = requests.post(
            config["webhook_url"],
            json=card,
            headers={"Content-Type": "application/json"},
        )

        response.raise_for_status()

        logger.info("teams_adaptive_card_sent", title=title)

        return {
            "success": True,
            "status_code": response.status_code,
            "message": "Adaptive card sent successfully",
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "send_teams_adaptive_card", "msteams"
        )
    except Exception as e:
        logger.error("teams_adaptive_card_failed", error=str(e))
        raise ToolExecutionError("send_teams_adaptive_card", str(e), e)


def send_teams_alert(
    alert_title: str,
    alert_message: str,
    severity: str = "info",
    details: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Send a formatted alert message to Microsoft Teams.

    Args:
        alert_title: Alert title
        alert_message: Alert description
        severity: Alert severity (info, warning, error, critical)
        details: Optional key-value pairs for additional details

    Returns:
        Send operation result
    """
    try:
        # Map severity to colors
        severity_colors = {
            "info": "0078D4",  # Blue
            "warning": "FFA500",  # Orange
            "error": "E81123",  # Red
            "critical": "B00020",  # Dark red
        }

        color = severity_colors.get(severity.lower(), "0078D4")

        # Build body with details
        body = [{"type": "TextBlock", "text": alert_message, "wrap": True}]

        if details:
            facts = [
                {"title": f"{key}:", "value": value} for key, value in details.items()
            ]
            body.append({"type": "FactSet", "facts": facts})

        # Send as adaptive card
        config = _get_msteams_config()

        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.2",
                        "body": [
                            {
                                "type": "Container",
                                "style": (
                                    "emphasis" if severity != "info" else "default"
                                ),
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": (
                                            f"⚠️ {alert_title}"
                                            if severity != "info"
                                            else alert_title
                                        ),
                                        "weight": "Bolder",
                                        "size": "Large",
                                        "color": (
                                            "attention"
                                            if severity in ["error", "critical"]
                                            else "default"
                                        ),
                                    }
                                ]
                                + body,
                            }
                        ],
                    },
                }
            ],
        }

        response = requests.post(
            config["webhook_url"],
            json=card,
            headers={"Content-Type": "application/json"},
        )

        response.raise_for_status()

        logger.info("teams_alert_sent", severity=severity, title=alert_title)

        return {
            "success": True,
            "status_code": response.status_code,
            "severity": severity,
            "message": "Alert sent successfully",
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "send_teams_alert", "msteams")
    except Exception as e:
        logger.error("teams_alert_failed", error=str(e))
        raise ToolExecutionError("send_teams_alert", str(e), e)


# List of all MS Teams tools for registration
MSTEAMS_TOOLS = [
    send_teams_message,
    send_teams_adaptive_card,
    send_teams_alert,
]
