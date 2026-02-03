"""Shared Slack API client with credential proxy support.

This client is designed to work with the IncidentFox credential proxy.
Credentials are injected automatically - scripts should NOT check for
SLACK_BOT_TOKEN in environment variables.
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx


def get_config() -> dict[str, Any]:
    """Load configuration from standard locations."""
    config = {}

    # Check for config file
    config_paths = [
        Path.home() / ".incidentfox" / "config.json",
        Path("/etc/incidentfox/config.json"),
    ]

    for path in config_paths:
        if path.exists():
            with open(path) as f:
                config = json.load(f)
                break

    # Environment overrides
    if os.getenv("TENANT_ID"):
        config["tenant_id"] = os.getenv("TENANT_ID")
    if os.getenv("TEAM_ID"):
        config["team_id"] = os.getenv("TEAM_ID")

    return config


def get_api_url(endpoint: str) -> str:
    """Get the Slack API URL for an endpoint.

    In production, this routes through the credential proxy.
    """
    base_url = os.getenv("SLACK_BASE_URL")
    if not base_url:
        # Fall back to direct API (for local development only)
        base_url = "https://slack.com/api"

    return f"{base_url.rstrip('/')}{endpoint}"


def get_headers() -> dict[str, str]:
    """Get headers for Slack API requests.

    The credential proxy will inject Authorization header.
    """
    config = get_config()

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Tenant-Id": config.get("tenant_id") or "local",
        "X-Team-Id": config.get("team_id") or "local",
    }

    # For local development, allow direct token usage
    token = os.getenv("SLACK_BOT_TOKEN")
    if token and not os.getenv("SLACK_BASE_URL"):
        headers["Authorization"] = f"Bearer {token}"

    return headers


def api_request(
    method: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make a request to the Slack API.

    Args:
        method: HTTP method
        endpoint: API endpoint
        params: Query parameters
        json_data: JSON body

    Returns:
        Parsed JSON response

    Raises:
        RuntimeError: If the request fails
    """
    url = get_api_url(endpoint)
    headers = get_headers()

    with httpx.Client(timeout=60.0) as client:
        response = client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Slack API error {response.status_code}: {response.text}"
            )

        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")

        return data


def search_messages(
    query: str,
    count: int = 20,
    sort: str = "timestamp",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    """Search for messages across channels.

    Args:
        query: Search query (supports Slack search operators)
        count: Number of results to return
        sort: Sort field (score, timestamp)
        sort_dir: Sort direction (asc, desc)

    Returns:
        Search results with messages
    """
    return api_request(
        "GET",
        "/search.messages",
        params={
            "query": query,
            "count": count,
            "sort": sort,
            "sort_dir": sort_dir,
        },
    )


def get_channel_history(
    channel_id: str,
    limit: int = 100,
    oldest: str | None = None,
    latest: str | None = None,
) -> dict[str, Any]:
    """Get message history from a channel.

    Args:
        channel_id: Channel ID (e.g., C123ABC)
        limit: Maximum messages to return
        oldest: Start timestamp (Unix)
        latest: End timestamp (Unix)

    Returns:
        Channel history with messages
    """
    params = {"channel": channel_id, "limit": limit}
    if oldest:
        params["oldest"] = oldest
    if latest:
        params["latest"] = latest

    return api_request("GET", "/conversations.history", params=params)


def get_thread_replies(
    channel_id: str,
    thread_ts: str,
    limit: int = 100,
) -> dict[str, Any]:
    """Get replies to a thread.

    Args:
        channel_id: Channel ID
        thread_ts: Thread parent timestamp
        limit: Maximum replies to return

    Returns:
        Thread replies
    """
    return api_request(
        "GET",
        "/conversations.replies",
        params={
            "channel": channel_id,
            "ts": thread_ts,
            "limit": limit,
        },
    )


def post_message(
    channel_id: str,
    text: str,
    thread_ts: str | None = None,
) -> dict[str, Any]:
    """Post a message to a channel.

    Args:
        channel_id: Channel ID
        text: Message text (supports Slack markdown)
        thread_ts: Optional thread timestamp to reply to

    Returns:
        Posted message details
    """
    data = {"channel": channel_id, "text": text}
    if thread_ts:
        data["thread_ts"] = thread_ts

    return api_request("POST", "/chat.postMessage", json_data=data)


def get_user_info(user_id: str) -> dict[str, Any]:
    """Get user information.

    Args:
        user_id: User ID (e.g., U123ABC)

    Returns:
        User profile information
    """
    return api_request("GET", "/users.info", params={"user": user_id})


def format_message(message: dict[str, Any], include_user: bool = True) -> str:
    """Format a Slack message for display.

    Args:
        message: Message object from API
        include_user: Whether to include user info

    Returns:
        Formatted string
    """
    ts = message.get("ts", "")
    text = message.get("text", "")[:500]  # Truncate long messages
    user = message.get("user", "unknown")
    channel = message.get("channel", {})

    # Convert timestamp to readable format
    if ts:
        import datetime

        try:
            dt = datetime.datetime.fromtimestamp(float(ts))
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            time_str = ts
    else:
        time_str = "unknown"

    output = f"[{time_str}]"
    if include_user:
        output += f" <{user}>"
    output += f": {text}"

    if message.get("reply_count"):
        output += f" ({message['reply_count']} replies)"

    return output
