"""
Output destination resolver for multi-destination output.

Determines where agent output should go based on:
1. Explicit override in request
2. Trigger-specific defaults (Slack → same thread, GitHub → same PR)
3. Team's configured default output
4. No output (silent)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def resolve_output_destinations(
    trigger_source: str,
    trigger_payload: Dict[str, Any],
    team_config: Optional[Dict[str, Any]] = None,
    explicit_override: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Resolve output destinations with priority:
    1. Explicit override
    2. Team trigger-specific overrides (from output_config)
    3. Trigger-specific defaults (reply in same thread/PR)
    4. Team default destinations (from output_config)
    5. Empty (no output)

    Args:
        trigger_source: Source of the trigger (slack, github, pagerduty, incidentio, api)
        trigger_payload: Payload from the trigger with relevant context
        team_config: Team's effective configuration (may contain output_config)
        explicit_override: Explicit list of destinations to use

    Returns:
        List of output destination dicts: [{"type": "slack", "channel_id": "...", ...}]
    """

    # 1. Explicit override wins
    if explicit_override:
        return explicit_override

    destinations: List[Dict[str, Any]] = []

    # Get output config (new structure) and notifications (legacy)
    output_config = (team_config or {}).get("output_config", {})
    trigger_overrides = output_config.get("trigger_overrides", {})
    default_destinations = output_config.get("default_destinations", [])

    # Extract Slack bot_token from team integrations config
    # This enables multi-tenant scenarios where teams use different Slack workspaces
    # Fall back to SLACK_BOT_TOKEN env var for single-tenant deployments
    slack_bot_token = (
        (team_config or {}).get("integrations", {}).get("slack", {}).get("bot_token")
    ) or os.getenv("SLACK_BOT_TOKEN")

    # Legacy notifications config (for backward compatibility)
    notifications = (team_config or {}).get("notifications", {})

    # 2. Check team trigger-specific overrides (NEW)
    trigger_override = trigger_overrides.get(trigger_source)

    if trigger_override == "reply_in_thread" and trigger_source == "slack":
        # Override: reply in Slack thread
        dest = {
            "type": "slack",
            "channel_id": trigger_payload.get("channel_id"),
            "thread_ts": trigger_payload.get("thread_ts")
            or trigger_payload.get("event_ts"),
            "user_id": trigger_payload.get("user_id"),
        }
        if slack_bot_token:
            dest["bot_token"] = slack_bot_token
        destinations.append(dest)
        return destinations

    elif trigger_override == "comment_on_pr" and trigger_source == "github":
        # Override: comment on GitHub PR/issue
        if trigger_payload.get("pr_number"):
            destinations.append(
                {
                    "type": "github_pr_comment",
                    "repo": trigger_payload.get("repo"),
                    "pr_number": trigger_payload.get("pr_number"),
                }
            )
        elif trigger_payload.get("issue_number"):
            destinations.append(
                {
                    "type": "github_issue_comment",
                    "repo": trigger_payload.get("repo"),
                    "issue_number": trigger_payload.get("issue_number"),
                }
            )
        return destinations

    elif trigger_override == "use_default":
        # Override: use team default destinations
        return list(default_destinations)

    # 3. Trigger-specific defaults (built-in behavior)
    if trigger_source == "slack":
        # Default: reply in same thread
        dest = {
            "type": "slack",
            "channel_id": trigger_payload.get("channel_id"),
            "thread_ts": trigger_payload.get("thread_ts")
            or trigger_payload.get("event_ts"),
            "user_id": trigger_payload.get("user_id"),
        }
        if slack_bot_token:
            dest["bot_token"] = slack_bot_token
        destinations.append(dest)

    elif trigger_source == "github":
        # Default: post back to same PR/issue
        if trigger_payload.get("pr_number"):
            destinations.append(
                {
                    "type": "github_pr_comment",
                    "repo": trigger_payload.get("repo"),
                    "pr_number": trigger_payload.get("pr_number"),
                }
            )
        elif trigger_payload.get("issue_number"):
            destinations.append(
                {
                    "type": "github_issue_comment",
                    "repo": trigger_payload.get("repo"),
                    "issue_number": trigger_payload.get("issue_number"),
                }
            )

        # Optionally also notify in Slack (legacy config)
        gh_output = notifications.get("github_output", {})
        gh_slack = gh_output.get("slack_channel_id")
        if gh_slack:
            dest = {
                "type": "slack",
                "channel_id": gh_slack,
            }
            if slack_bot_token:
                dest["bot_token"] = slack_bot_token
            destinations.append(dest)

    elif trigger_source == "pagerduty":
        # Use PD-specific config or fallback to default (legacy)
        pd_output = notifications.get("pagerduty_output", {})
        slack_channel = pd_output.get("slack_channel_id") or notifications.get(
            "default_slack_channel_id"
        )

        if slack_channel:
            dest = {
                "type": "slack",
                "channel_id": slack_channel,
            }
            if slack_bot_token:
                dest["bot_token"] = slack_bot_token
            destinations.append(dest)

        # Optionally add PagerDuty note
        if pd_output.get("post_pagerduty_note") and trigger_payload.get("incident_id"):
            destinations.append(
                {
                    "type": "pagerduty_note",
                    "incident_id": trigger_payload.get("incident_id"),
                }
            )

    elif trigger_source == "incidentio":
        # Use Incident.io-specific config or fallback to default (legacy)
        io_output = notifications.get("incidentio_output", {})
        slack_channel = io_output.get("slack_channel_id") or notifications.get(
            "default_slack_channel_id"
        )

        if slack_channel:
            dest = {
                "type": "slack",
                "channel_id": slack_channel,
            }
            if slack_bot_token:
                dest["bot_token"] = slack_bot_token
            destinations.append(dest)

        # Optionally add Incident.io timeline entry
        if io_output.get("post_timeline") and trigger_payload.get("incident_id"):
            destinations.append(
                {
                    "type": "incidentio_timeline",
                    "incident_id": trigger_payload.get("incident_id"),
                }
            )

    elif trigger_source == "api":
        # API calls: use team default destinations (NEW) or legacy default
        if default_destinations:
            return list(default_destinations)

        # Legacy fallback
        default_channel = notifications.get("default_slack_channel_id")
        if default_channel:
            dest = {
                "type": "slack",
                "channel_id": default_channel,
            }
            if slack_bot_token:
                dest["bot_token"] = slack_bot_token
            destinations.append(dest)

    # 4. If still empty after trigger-specific handling, check for team default destinations (NEW)
    if not destinations and default_destinations:
        return list(default_destinations)

    # 5. Legacy fallback: check for default_slack_channel_id
    if not destinations:
        default_channel = notifications.get("default_slack_channel_id")
        if default_channel:
            dest = {
                "type": "slack",
                "channel_id": default_channel,
            }
            if slack_bot_token:
                dest["bot_token"] = slack_bot_token
            destinations.append(dest)

    # 6. Return whatever we have (could be empty = no output)
    return destinations
