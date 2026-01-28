"""
Slack Block Kit UI helpers for investigation dashboards.

Builds rich, interactive Slack messages with:
- Progressive status updates during investigation
- Expandable modals for detailed findings
- Action buttons for remediation
- Dynamic phases based on tools used (not hardcoded)
"""

from __future__ import annotations

from typing import Any

from .slack_mrkdwn import chunk_mrkdwn

# Default investigation phases (used if no dynamic phases provided)
# These are for backwards compatibility - the new system uses dynamic phases
# detected from tool modules automatically.
DEFAULT_INVESTIGATION_PHASES: dict[str, dict[str, str]] = {
    "snowflake_history": {
        "label": "Snowflake: Historical incident patterns",
        "action_id": "view_snowflake_history",
        "icon": "❄️",
    },
    "coralogix_logs": {
        "label": "Coralogix: Error logs & traces",
        "action_id": "view_coralogix_logs",
        "icon": "📊",
    },
    "coralogix_metrics": {
        "label": "Coralogix: Service metrics",
        "action_id": "view_coralogix_metrics",
        "icon": "📈",
    },
    "kubernetes": {
        "label": "Kubernetes: Pod health & events",
        "action_id": "view_kubernetes",
        "icon": "☸️",
    },
    "root_cause_analysis": {
        "label": "Root cause analysis",
        "action_id": "view_rca",
        "icon": "🎯",
    },
}

# Alias for backwards compatibility
INVESTIGATION_PHASES = DEFAULT_INVESTIGATION_PHASES


def icon_for_status(status: str) -> str:
    """Get emoji icon for investigation phase status."""
    if status == "running":
        return ":hourglass_flowing_sand:"
    if status == "done":
        return ":white_check_mark:"
    if status == "failed":
        return ":x:"
    return ":white_circle:"  # pending


def build_investigation_header(
    title: str = "IncidentFox Investigation",
    incident_id: str | None = None,
    severity: str | None = None,
) -> list[dict[str, Any]]:
    """Build the header section of the investigation message."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🦊 {title}", "emoji": True},
        },
    ]

    # Add context with incident details if provided
    context_parts = []
    if incident_id:
        context_parts.append(f"*Incident:* `{incident_id}`")
    if severity:
        severity_emoji = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
        }.get(severity.lower(), "⚪")
        context_parts.append(f"*Severity:* {severity_emoji} {severity}")

    if context_parts:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": " | ".join(context_parts)}],
            }
        )

    blocks.append({"type": "divider"})

    return blocks


def build_progress_section(
    phase_status: dict[str, str],
    show_pending: bool = False,
    phases: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Build the investigation progress section with status indicators.

    Args:
        phase_status: Dict mapping phase key to status ('pending', 'running', 'done', 'failed')
        show_pending: Whether to show pending phases
        phases: Optional dict of phase key -> display info. If None, uses DEFAULT_INVESTIGATION_PHASES.
                Each phase should have 'label', 'icon', and 'action_id' keys.
    """
    # Use provided phases or fall back to defaults
    active_phases = phases if phases is not None else DEFAULT_INVESTIGATION_PHASES

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Investigation Progress:*"},
        },
    ]

    for key, meta in active_phases.items():
        status = phase_status.get(key, "pending")

        if status == "pending" and not show_pending:
            continue

        status_icon = icon_for_status(status)
        phase_icon = meta.get("icon", "")
        label = meta.get("label", key.replace("_", " ").title())

        # Combine phase icon with label
        display_text = f"{phase_icon} {label}" if phase_icon else label

        if status == "running":
            # Running items shown as context (no button)
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"{status_icon} _{display_text}_"}
                    ],
                }
            )
        elif status in ("done", "failed"):
            # Completed items shown with View button
            action_id = meta.get("action_id", f"view_{key}")
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"{status_icon} {display_text}"},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View"},
                        "value": key,
                        "action_id": action_id,
                    },
                }
            )

    return blocks


def build_findings_section(
    findings: str,
    confidence: int | None = None,
) -> list[dict[str, Any]]:
    """Build the root cause analysis / findings section."""
    blocks: list[dict[str, Any]] = [
        {"type": "divider"},
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🎯 Root Cause Analysis",
                "emoji": True,
            },
        },
    ]

    # Split findings into chunks if too long
    for chunk in chunk_mrkdwn(findings, limit=2900):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk},
            }
        )

    if confidence is not None:
        # Simple confidence display
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"*Confidence:* {confidence}%"}
                ],
            }
        )

    return blocks


def build_action_buttons(
    actions: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Build action buttons for remediation.

    Args:
        actions: List of action dicts with 'label', 'action_id', 'value', 'style' (optional)
                 If None or empty, returns empty list (no hardcoded defaults).

    Note:
        Actions should be dynamically determined based on investigation findings.
        For example, only show "Rollback Deployment" if a recent deployment was
        identified as a potential cause.
    """
    if not actions:
        # No hardcoded defaults - actions should be contextually relevant
        # based on investigation findings
        return []

    elements = []
    for action in actions[:5]:  # Max 5 buttons per block
        btn: dict[str, Any] = {
            "type": "button",
            "text": {"type": "plain_text", "text": action["label"], "emoji": True},
            "action_id": action["action_id"],
            "value": action.get("value", action["action_id"]),
        }
        if action.get("style") in ("primary", "danger"):
            btn["style"] = action["style"]
        elements.append(btn)

    return [{"type": "actions", "elements": elements}]


def build_investigation_dashboard(
    phase_status: dict[str, str],
    *,
    title: str = "IncidentFox Investigation",
    incident_id: str | None = None,
    severity: str | None = None,
    context_text: str | None = None,
    findings: str | None = None,
    confidence: int | None = None,
    show_actions: bool = False,
    custom_actions: list[dict[str, str]] | None = None,
    phases: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Build the complete investigation dashboard.

    This is the main entry point for building Slack messages during investigation.

    Args:
        phase_status: Dict mapping phase key to status
        title: Dashboard title
        incident_id: Optional incident ID to display
        severity: Optional severity level
        context_text: Optional context/description text
        findings: Optional RCA findings (shown when investigation complete)
        confidence: Optional confidence score 0-100
        show_actions: Whether to show action buttons
        custom_actions: Custom action buttons to show
        phases: Optional dict of phase key -> display info for dynamic phases.
                If None, uses DEFAULT_INVESTIGATION_PHASES.

    Returns:
        List of Slack Block Kit blocks
    """
    blocks: list[dict[str, Any]] = []

    # Header
    blocks.extend(
        build_investigation_header(
            title=title,
            incident_id=incident_id,
            severity=severity,
        )
    )

    # Context
    if context_text:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": context_text}],
            }
        )

    # Progress section with dynamic phases
    blocks.extend(build_progress_section(phase_status, phases=phases))

    # Findings (if investigation complete)
    if findings:
        blocks.extend(build_findings_section(findings, confidence=confidence))

    # Action buttons
    if show_actions:
        blocks.extend(build_action_buttons(custom_actions))

    return blocks


def build_phase_modal(
    title: str,
    body_mrkdwn: str,
) -> dict[str, Any]:
    """
    Build a modal view for displaying phase details.

    Args:
        title: Modal title (max 24 chars)
        body_mrkdwn: Modal body content in mrkdwn format

    Returns:
        Slack modal view payload
    """
    blocks: list[dict[str, Any]] = []
    for chunk in chunk_mrkdwn(body_mrkdwn, limit=2900):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})

    # Slack modal title must be plain_text <= 24 chars
    safe_title = title[:24]

    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": safe_title},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks[:100],  # Max 100 blocks per modal
    }


def build_all_phases_modal(
    results_by_phase: dict[str, str],
    phases: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Build a modal showing all investigation phases and their results.

    Args:
        results_by_phase: Dict mapping phase key to result text
        phases: Optional dict of phase key -> display info for dynamic phases.
                If None, uses DEFAULT_INVESTIGATION_PHASES.

    Returns:
        Slack modal view payload
    """
    # Use provided phases or fall back to defaults
    active_phases = phases if phases is not None else DEFAULT_INVESTIGATION_PHASES

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📋 Investigation Details",
                "emoji": True,
            },
        },
        {"type": "divider"},
    ]

    for key, meta in active_phases.items():
        text = results_by_phase.get(key)
        if not text:
            continue

        icon = meta.get("icon", "")
        label = meta.get("label", key.replace("_", " ").title())

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{icon} {label}*"},
            }
        )

        for chunk in chunk_mrkdwn(text, limit=2900):
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": chunk}}
            )

        blocks.append({"type": "divider"})

        # Slack has a 100 block limit
        if len(blocks) >= 95:
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": "_(truncated)_"}}
            )
            break

    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Investigation"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks[:100],
    }


def format_tool_update(
    tool_name: str,
    status: str = "running",
    summary: str | None = None,
    url: str | None = None,
) -> str:
    """
    Format a single-line tool update for Slack.

    Args:
        tool_name: Name of the tool being used
        status: 'running', 'done', or 'failed'
        summary: Optional one-line summary of result
        url: Optional URL for user to view more details

    Returns:
        Formatted mrkdwn string
    """
    icon = icon_for_status(status)

    # Map tool names to friendly labels
    tool_labels = {
        "search_coralogix_logs": "Coralogix Logs",
        "get_coralogix_error_logs": "Coralogix Errors",
        "query_coralogix_metrics": "Coralogix Metrics",
        "search_coralogix_traces": "Coralogix Traces",
        "list_coralogix_services": "Coralogix Services",
        "get_coralogix_service_health": "Service Health",
        "query_snowflake": "Snowflake Query",
        "get_snowflake_schema": "Snowflake Schema",
        "search_incidents_by_service": "Incident History",
        "get_recent_incidents": "Recent Incidents",
        "list_pods": "K8s Pods",
        "get_pod_logs": "K8s Logs",
        "get_pod_events": "K8s Events",
    }
    label = tool_labels.get(tool_name, tool_name.replace("_", " ").title())

    parts = [f"{icon} {label}"]

    if summary:
        parts.append(f"— {summary}")

    if url:
        parts.append(f"<{url}|View>")

    return " ".join(parts)
