"""Slack integration tools for incident communication.

Provides tools for:
- Searching messages for incident context
- Getting channel history
- Reading thread replies
- Posting updates during incidents

Essential for understanding team communication during incidents.
"""

import json

from mcp.server.fastmcp import FastMCP

from ..utils.config import get_env


class SlackConfigError(Exception):
    """Raised when Slack is not configured."""

    def __init__(self, message: str):
        super().__init__(message)


def _get_slack_config():
    """Get Slack configuration from environment or config file."""
    bot_token = get_env("SLACK_BOT_TOKEN")

    if not bot_token:
        raise SlackConfigError(
            "Slack not configured. Missing: SLACK_BOT_TOKEN. "
            "Use save_credential tool to set it, or export as environment variable."
        )

    return {
        "bot_token": bot_token,
        "default_channel": get_env("SLACK_DEFAULT_CHANNEL"),
    }


def _get_slack_client():
    """Get Slack client."""
    try:
        from slack_sdk import WebClient

        config = _get_slack_config()
        return WebClient(token=config["bot_token"])

    except ImportError:
        raise SlackConfigError(
            "slack-sdk not installed. Install with: pip install slack-sdk"
        )


def register_tools(mcp: FastMCP):
    """Register Slack tools with the MCP server."""

    @mcp.tool()
    def slack_search_messages(query: str, count: int = 20) -> str:
        """Search Slack messages for incident context.

        Useful for finding discussions about the incident, error reports,
        or team communication during the incident window.

        Args:
            query: Search query (supports Slack search operators like 'from:@user in:#channel')
            count: Number of results to return (default: 20)

        Returns:
            JSON with matching messages including channel, user, and permalink
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

            return json.dumps(
                {
                    "query": query,
                    "message_count": len(messages),
                    "messages": messages,
                },
                indent=2,
            )

        except SlackConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "query": query})

    @mcp.tool()
    def slack_get_channel_history(
        channel_id: str, limit: int = 100, oldest: str | None = None
    ) -> str:
        """Get message history from a Slack channel.

        Use to see recent conversations in an incident channel
        or team channel.

        Args:
            channel_id: Channel ID (e.g., 'C01234ABCDE')
            limit: Number of messages to retrieve (default: 100)
            oldest: Optional oldest timestamp to start from

        Returns:
            JSON with list of messages
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

            return json.dumps(
                {
                    "channel_id": channel_id,
                    "message_count": len(messages),
                    "messages": messages,
                },
                indent=2,
            )

        except SlackConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "channel_id": channel_id})

    @mcp.tool()
    def slack_get_thread_replies(channel_id: str, thread_ts: str) -> str:
        """Get all replies in a Slack thread.

        Use to follow detailed discussion in an incident thread.

        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp (parent message timestamp)

        Returns:
            JSON with list of thread messages
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

            return json.dumps(
                {
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "reply_count": len(messages),
                    "messages": messages,
                },
                indent=2,
            )

        except SlackConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps(
                {"error": str(e), "channel_id": channel_id, "thread_ts": thread_ts}
            )

    @mcp.tool()
    def slack_post_message(
        channel_id: str, text: str, thread_ts: str | None = None
    ) -> str:
        """Post a message to Slack.

        Use to post incident updates, investigation findings,
        or status updates to a channel.

        Args:
            channel_id: Channel ID to post to
            text: Message text (supports Slack markdown)
            thread_ts: Optional thread timestamp (to reply in a thread)

        Returns:
            JSON with posted message info
        """
        try:
            client = _get_slack_client()

            kwargs = {"channel": channel_id, "text": text}
            if thread_ts:
                kwargs["thread_ts"] = thread_ts

            response = client.chat_postMessage(**kwargs)

            return json.dumps(
                {
                    "ts": response["ts"],
                    "channel": response["channel"],
                    "success": True,
                },
                indent=2,
            )

        except SlackConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except Exception as e:
            return json.dumps({"error": str(e), "channel_id": channel_id})
