"""Slack integration tools."""

import os
from typing import Any

from ..core.config_required import handle_integration_not_configured
from ..core.errors import ToolExecutionError
from ..core.execution_context import get_execution_context
from ..core.integration_errors import IntegrationNotConfiguredError
from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_slack_config() -> dict:
    """Get Slack configuration from execution context or environment."""
    # 1. Try execution context (production, thread-safe)
    context = get_execution_context()
    if context:
        config = context.get_integration_config("slack")
        if config and config.get("bot_token"):
            return config

    # 2. Try environment variables (dev/testing fallback)
    if os.getenv("SLACK_BOT_TOKEN"):
        return {
            "bot_token": os.getenv("SLACK_BOT_TOKEN"),
            "default_channel": os.getenv("SLACK_DEFAULT_CHANNEL"),
        }

    # 3. Not configured - raise error
    raise IntegrationNotConfiguredError(
        integration_id="slack", tool_id="slack_tools", missing_fields=["bot_token"]
    )


def _get_slack_client():
    """Get Slack client."""
    try:
        from slack_sdk import WebClient

        config = _get_slack_config()
        return WebClient(token=config["bot_token"])
    except ImportError:
        raise ToolExecutionError(
            "slack", "slack-sdk not installed. Install with: poetry add slack-sdk"
        )


def slack_search_messages(query: str, count: int = 20) -> list[dict[str, Any]]:
    """
    Search Slack messages.

    Args:
        query: Search query (supports operators like 'from:@user in:#channel')
        count: Number of results to return

    Returns:
        List of matching messages
    """
    try:
        client = _get_slack_client()
        response = client.search_messages(query=query, count=count)

        messages = []
        for match in response["messages"]["matches"]:
            messages.append(
                {
                    "text": match["text"],
                    "user": match.get("username"),
                    "channel": match["channel"]["name"],
                    "timestamp": match["ts"],
                    "permalink": match.get("permalink"),
                }
            )

        logger.info("slack_search_completed", query=query, results=len(messages))
        return messages

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "slack_search_messages", "slack")
    except Exception as e:
        logger.error("slack_search_failed", error=str(e), query=query)
        raise ToolExecutionError("slack_search_messages", str(e), e)


def slack_get_channel_history(
    channel_id: str, limit: int = 100, oldest: str | None = None
) -> list[dict[str, Any]]:
    """
    Get message history from a Slack channel.

    Args:
        channel_id: Channel ID
        limit: Number of messages to retrieve
        oldest: Optional oldest timestamp

    Returns:
        List of messages
    """
    try:
        client = _get_slack_client()

        kwargs = {"channel": channel_id, "limit": limit}
        if oldest:
            kwargs["oldest"] = oldest

        response = client.conversations_history(**kwargs)

        messages = []
        for msg in response["messages"]:
            messages.append(
                {
                    "text": msg.get("text", ""),
                    "user": msg.get("user"),
                    "timestamp": msg["ts"],
                    "thread_ts": msg.get("thread_ts"),
                    "reactions": msg.get("reactions", []),
                }
            )

        logger.info("slack_history_fetched", channel=channel_id, messages=len(messages))
        return messages

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(
            e, "slack_get_channel_history", "slack"
        )
    except Exception as e:
        logger.error("slack_history_failed", error=str(e), channel=channel_id)
        raise ToolExecutionError("slack_get_channel_history", str(e), e)


def slack_get_thread_replies(channel_id: str, thread_ts: str) -> list[dict[str, Any]]:
    """
    Get all replies in a Slack thread.

    Args:
        channel_id: Channel ID
        thread_ts: Thread timestamp

    Returns:
        List of thread messages
    """
    try:
        client = _get_slack_client()
        response = client.conversations_replies(channel=channel_id, ts=thread_ts)

        messages = []
        for msg in response["messages"]:
            messages.append(
                {
                    "text": msg.get("text", ""),
                    "user": msg.get("user"),
                    "timestamp": msg["ts"],
                }
            )

        logger.info("slack_thread_fetched", channel=channel_id, messages=len(messages))
        return messages

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "slack_get_thread_replies", "slack")
    except Exception as e:
        logger.error("slack_thread_failed", error=str(e))
        raise ToolExecutionError("slack_get_thread_replies", str(e), e)


def slack_post_message(
    channel_id: str, text: str, thread_ts: str | None = None
) -> dict[str, Any]:
    """
    Post a message to Slack.

    Args:
        channel_id: Channel ID
        text: Message text
        thread_ts: Optional thread timestamp (for replies)

    Returns:
        Posted message info
    """
    try:
        client = _get_slack_client()

        kwargs = {"channel": channel_id, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        response = client.chat_postMessage(**kwargs)

        logger.info("slack_message_posted", channel=channel_id, thread=bool(thread_ts))
        return {
            "ts": response["ts"],
            "channel": response["channel"],
            "success": True,
        }

    except IntegrationNotConfiguredError as e:
        return handle_integration_not_configured(e, "slack_post_message", "slack")
    except Exception as e:
        logger.error("slack_post_failed", error=str(e))
        raise ToolExecutionError("slack_post_message", str(e), e)


# List of all Slack tools for registration
SLACK_TOOLS = [
    slack_search_messages,
    slack_get_channel_history,
    slack_get_thread_replies,
    slack_post_message,
]
