"""
Slack integration tools.

Provides Slack API access for messages, channels, and threads.
"""

import json
import logging
import os
from typing import Optional

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)


def _get_slack_client():
    """Get Slack client."""
    try:
        from slack_sdk import WebClient
    except ImportError:
        raise RuntimeError("slack-sdk not installed: pip install slack-sdk")

    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        raise ValueError("SLACK_BOT_TOKEN environment variable not set")

    return WebClient(token=token)


@function_tool
def slack_search_messages(query: str, count: int = 20) -> str:
    """
    Search Slack messages.

    Args:
        query: Search query (supports operators like 'from:@user in:#channel')
        count: Number of results to return

    Returns:
        JSON with matching messages
    """
    if not query:
        return json.dumps({"ok": False, "error": "query is required"})

    logger.info(f"slack_search_messages: query={query}")

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

        return json.dumps(
            {
                "ok": True,
                "messages": messages,
                "count": len(messages),
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set SLACK_BOT_TOKEN"})
    except Exception as e:
        logger.error(f"slack_search_messages error: {e}")
        return json.dumps({"ok": False, "error": str(e), "query": query})


@function_tool
def slack_get_channel_history(
    channel_id: str,
    limit: int = 100,
    oldest: str = "",
) -> str:
    """
    Get message history from a Slack channel.

    Args:
        channel_id: Channel ID
        limit: Number of messages to retrieve
        oldest: Optional oldest timestamp

    Returns:
        JSON with messages
    """
    if not channel_id:
        return json.dumps({"ok": False, "error": "channel_id is required"})

    logger.info(f"slack_get_channel_history: channel={channel_id}")

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

        return json.dumps(
            {
                "ok": True,
                "messages": messages,
                "count": len(messages),
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set SLACK_BOT_TOKEN"})
    except Exception as e:
        logger.error(f"slack_get_channel_history error: {e}")
        return json.dumps({"ok": False, "error": str(e), "channel_id": channel_id})


@function_tool
def slack_get_thread_replies(channel_id: str, thread_ts: str) -> str:
    """
    Get all replies in a Slack thread.

    Args:
        channel_id: Channel ID
        thread_ts: Thread timestamp

    Returns:
        JSON with thread messages
    """
    if not channel_id or not thread_ts:
        return json.dumps(
            {"ok": False, "error": "channel_id and thread_ts are required"}
        )

    logger.info(f"slack_get_thread_replies: channel={channel_id}, thread={thread_ts}")

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

        return json.dumps(
            {
                "ok": True,
                "messages": messages,
                "count": len(messages),
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set SLACK_BOT_TOKEN"})
    except Exception as e:
        logger.error(f"slack_get_thread_replies error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


@function_tool
def slack_post_message(
    channel_id: str,
    text: str,
    thread_ts: str = "",
) -> str:
    """
    Post a message to Slack.

    Args:
        channel_id: Channel ID
        text: Message text
        thread_ts: Optional thread timestamp (for replies)

    Returns:
        JSON with posted message info
    """
    if not channel_id or not text:
        return json.dumps({"ok": False, "error": "channel_id and text are required"})

    logger.info(f"slack_post_message: channel={channel_id}, thread={bool(thread_ts)}")

    try:
        client = _get_slack_client()

        kwargs = {"channel": channel_id, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        response = client.chat_postMessage(**kwargs)

        return json.dumps(
            {
                "ok": True,
                "ts": response["ts"],
                "channel": response["channel"],
            }
        )

    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e), "hint": "Set SLACK_BOT_TOKEN"})
    except Exception as e:
        logger.error(f"slack_post_message error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


# Register tools
register_tool("slack_search_messages", slack_search_messages)
register_tool("slack_get_channel_history", slack_get_channel_history)
register_tool("slack_get_thread_replies", slack_get_thread_replies)
register_tool("slack_post_message", slack_post_message)
