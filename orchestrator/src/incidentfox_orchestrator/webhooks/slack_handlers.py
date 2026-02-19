"""
Slack event and interaction handlers using Bolt SDK.

Handlers for:
- app_mention: Bot @mentions trigger agent runs
- feedback_positive/feedback_negative: User feedback on agent responses

Features:
- Bot mention stripping: Removes <@BOT_ID> from message text
- Session ID generation: Thread-based ID for conversational context
- Multi-tenant routing: Via Config Service lookup
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from functools import partial
from typing import TYPE_CHECKING, Any, Dict, Optional

from slack_bolt.async_app import AsyncApp

if TYPE_CHECKING:
    from incidentfox_orchestrator.webhooks.slack_bolt_app import SlackBoltIntegration


# Bot mention pattern: <@UXXXXXXXXX> or <@WXXXXXXXXX> (workspace apps)
BOT_MENTION_PATTERN = re.compile(r"<@[UW][A-Z0-9]+>")


def _log(event: str, **fields: Any) -> None:
    """Structured logging."""
    try:
        payload = {
            "service": "orchestrator",
            "component": "slack_bolt",
            "event": event,
            **fields,
        }
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


def strip_bot_mentions(text: str) -> str:
    """
    Remove all @bot mentions from message text.

    Slack mentions are formatted as <@UXXXXXXXXX> where U is for users
    and W is for workspace apps.

    Example:
        "<@U123ABC> investigate the error" -> "investigate the error"
    """
    return BOT_MENTION_PATTERN.sub("", text).strip()


def generate_session_id(channel_id: str, thread_ts: str) -> str:
    """
    Generate session ID for thread-based conversational context.

    Uses channel + thread timestamp to create a stable ID that persists
    across follow-up messages in the same Slack thread.

    The ID is sanitized for use as K8s DNS names (RFC 1123):
    - Lowercase alphanumeric, hyphens allowed
    - Must start/end with alphanumeric

    Example:
        channel_id="C0A4967KRBM", thread_ts="1234567890.123456"
        -> "slack-c0a4967krbm-1234567890-123456"
    """
    sanitized_ts = thread_ts.replace(".", "-")
    return f"slack-{channel_id.lower()}-{sanitized_ts}"


def register_handlers(app: AsyncApp, integration: SlackBoltIntegration) -> None:
    """
    Register all Slack event and action handlers on the Bolt app.

    Args:
        app: The Slack Bolt AsyncApp instance
        integration: SlackBoltIntegration with service client references
    """

    @app.event("app_mention")
    async def handle_app_mention(event: dict, ack, say):
        """
        Handle @mentions of the bot.

        Flow:
        1. Ack immediately (Bolt requirement for 3s timeout)
        2. Extract event details
        3. Strip bot mention from text
        4. Generate session ID for thread context
        5. Look up team via Config Service routing
        6. Get impersonation token
        7. Resolve output destinations
        8. Call agent API
        9. Record audit trail
        """
        await ack()

        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        raw_text = event.get("text", "")
        event_ts = event.get("event_ts", "")
        thread_ts = event.get("thread_ts") or event_ts

        # Strip bot mentions from text
        text = strip_bot_mentions(raw_text)

        # Generate session ID for conversational context
        session_id = generate_session_id(channel_id, thread_ts)

        correlation_id = uuid.uuid4().hex

        _log(
            "slack_event_processing",
            correlation_id=correlation_id,
            channel_id=channel_id,
            user_id=user_id,
            session_id=session_id,
            raw_text_length=len(raw_text),
            cleaned_text_length=len(text),
        )

        if not text:
            # Empty message after stripping mention
            await say(
                text="Hey! What would you like me to investigate?",
                thread_ts=thread_ts,
            )
            return

        try:
            cfg = integration.config_service
            agent_api = integration.agent_api

            # Look up team via routing
            # Use asyncio.to_thread() for sync HTTP calls to avoid blocking the event loop
            routing = await asyncio.to_thread(
                cfg.lookup_routing,
                internal_service_name="orchestrator",
                identifiers={"slack_channel_id": channel_id},
            )

            if not routing.get("found"):
                _log(
                    "slack_event_no_routing",
                    correlation_id=correlation_id,
                    channel_id=channel_id,
                    tried=routing.get("tried", []),
                )
                return

            org_id = routing["org_id"]
            team_node_id = routing["team_node_id"]

            _log(
                "slack_event_routing_found",
                correlation_id=correlation_id,
                channel_id=channel_id,
                org_id=org_id,
                team_node_id=team_node_id,
                matched_by=routing.get("matched_by"),
            )

            # Get impersonation token
            admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
            if not admin_token:
                _log("slack_event_missing_admin_token", correlation_id=correlation_id)
                return

            # Run sync HTTP call in thread pool to avoid blocking event loop
            imp = await asyncio.to_thread(
                cfg.issue_team_impersonation_token,
                admin_token,
                org_id=org_id,
                team_node_id=team_node_id,
            )
            team_token = str(imp.get("token") or "")
            if not team_token:
                _log("slack_event_impersonation_failed", correlation_id=correlation_id)
                return

            # Check for entrance agent name and dedicated agent URL
            entrance_agent_name = "planner"  # Default fallback
            dedicated_agent_url: Optional[str] = None
            effective_config: Dict[str, Any] = {}
            try:
                # Run sync HTTP call in thread pool to avoid blocking event loop
                effective_config = await asyncio.to_thread(
                    cfg.get_effective_config, team_token=team_token
                )
                entrance_agent_name = effective_config.get("entrance_agent", "planner")
                dedicated_agent_url = effective_config.get("agent", {}).get(
                    "dedicated_service_url"
                )
                if dedicated_agent_url:
                    _log(
                        "slack_event_using_dedicated_agent",
                        correlation_id=correlation_id,
                        dedicated_url=dedicated_agent_url,
                    )
            except Exception as e:
                _log(
                    "slack_event_config_fetch_failed",
                    correlation_id=correlation_id,
                    error=str(e),
                )

            run_id = uuid.uuid4().hex

            # Note: Agent service now handles agent run creation.
            # We pass trigger_source to ensure proper attribution.

            # Resolve output destinations
            from incidentfox_orchestrator.output_resolver import (
                resolve_output_destinations,
            )

            trigger_payload = {
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "event_ts": event_ts,
                "user_id": user_id,
            }

            output_destinations = resolve_output_destinations(
                trigger_source="slack",
                trigger_payload=trigger_payload,
                team_config=effective_config,
            )

            # Add run_id and correlation_id to Slack destinations for feedback buttons
            # Note: Add at top level (flat format) to match output_resolver format
            for dest in output_destinations:
                if dest.get("type") == "slack":
                    dest["run_id"] = run_id
                    dest["correlation_id"] = correlation_id

            _log(
                "slack_event_output_destinations",
                correlation_id=correlation_id,
                destinations=[d.get("type") for d in output_destinations],
            )

            # CRITICAL: Run agent in thread pool to avoid blocking the event loop.
            # agent_api.run_agent() uses sync httpx and can take several minutes.
            await asyncio.to_thread(
                partial(
                    agent_api.run_agent,
                    team_token=team_token,
                    agent_name=entrance_agent_name,
                    message=text,
                    context={
                        "user_id": user_id,
                        "session_id": session_id,
                        "metadata": {
                            "slack": {
                                "channel_id": channel_id,
                                "event_ts": event_ts,
                                "thread_ts": thread_ts,
                            },
                            "trigger": "slack",
                        },
                    },
                    timeout=int(
                        os.getenv("ORCHESTRATOR_SLACK_AGENT_TIMEOUT_SECONDS", "300")
                    ),
                    max_turns=int(
                        os.getenv("ORCHESTRATOR_SLACK_AGENT_MAX_TURNS", "50")
                    ),
                    correlation_id=correlation_id,
                    agent_base_url=dedicated_agent_url,
                    output_destinations=output_destinations,
                    trigger_source="slack",
                )
            )

            # Note: Agent service handles run completion recording

            _log(
                "slack_event_completed",
                correlation_id=correlation_id,
                channel_id=channel_id,
                org_id=org_id,
                team_node_id=team_node_id,
                session_id=session_id,
            )

        except Exception as e:
            _log(
                "slack_event_failed",
                correlation_id=correlation_id,
                channel_id=channel_id,
                error=str(e),
            )
            # Note: Agent service handles run failure recording

    @app.action("feedback_positive")
    async def handle_feedback_positive(ack, body, respond):
        """Handle positive feedback button click."""
        await ack()
        await _handle_feedback(body, respond, "positive", integration)

    @app.action("feedback_negative")
    async def handle_feedback_negative(ack, body, respond):
        """Handle negative feedback button click."""
        await ack()
        await _handle_feedback(body, respond, "negative", integration)

    @app.action(re.compile(r"^view_"))
    async def handle_view_phase(ack, body, client):
        """
        Handle View button clicks for investigation phases.

        These buttons show tool calls for the clicked phase by fetching
        them from the config service using the run_id embedded in the button value.
        """
        await ack()
        action = (body.get("actions") or [{}])[0]
        action_id = action.get("action_id", "view_unknown")
        button_value = action.get("value", "unknown")
        trigger_id = body.get("trigger_id")

        # Parse run_id and phase_key from button value
        # Format: "{run_id}:{phase_key}" or just "{phase_key}" (legacy)
        if ":" in button_value:
            run_id, phase_key = button_value.split(":", 1)
        else:
            run_id = None
            phase_key = button_value

        _log(
            "slack_view_phase_clicked",
            action_id=action_id,
            phase_key=phase_key,
            run_id=run_id,
        )

        # Map phase keys to friendly names
        phase_labels = {
            "kubernetes": "Kubernetes",
            "coralogix_tools": "Coralogix",
            "aws_tools": "AWS",
            "datadog_tools": "Datadog",
            "github_tools": "GitHub",
            "github_app_tools": "GitHub",
            "postgres_tools": "PostgreSQL",
            "snowflake_tools": "Snowflake",
            "elasticsearch_tools": "Elasticsearch",
            "grafana_tools": "Grafana",
            "splunk_tools": "Splunk",
            "sentry_tools": "Sentry",
            "pagerduty_tools": "PagerDuty",
            "jira_tools": "Jira",
            "slack_tools": "Slack",
            "git_tools": "Git",
            "log_analysis_tools": "Log Analysis",
            "root_cause_analysis": "Root Cause Analysis",
        }
        phase_name = phase_labels.get(phase_key, phase_key.replace("_", " ").title())

        # Open a modal with tool call details
        if trigger_id:
            try:
                modal_blocks = await _build_tool_calls_modal_blocks(
                    integration, run_id, phase_key, phase_name
                )

                await client.views_open(
                    trigger_id=trigger_id,
                    view={
                        "type": "modal",
                        "title": {"type": "plain_text", "text": phase_name[:24]},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": modal_blocks[:100],  # Max 100 blocks
                    },
                )
            except Exception as e:
                _log(
                    "slack_view_phase_modal_failed",
                    action_id=action_id,
                    error=str(e),
                )


async def _build_tool_calls_modal_blocks(
    integration: SlackBoltIntegration,
    run_id: Optional[str],
    phase_key: str,
    phase_name: str,
) -> list:
    """
    Build modal blocks showing tool calls for a phase.

    Fetches tool calls from config service and filters by category.
    """
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{phase_name} Tool Calls*"},
        },
    ]

    if not run_id:
        # No run_id - show legacy message
        blocks.extend(
            [
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "The detailed findings for this phase are included "
                            "in the investigation summary above.\n\n"
                            "_Tool call details are available for newer investigations._"
                        ),
                    },
                },
            ]
        )
        return blocks

    # Fetch tool calls from config service
    tool_calls = []
    try:
        tool_calls = await asyncio.to_thread(
            integration.config_service.get_tool_calls,
            run_id=run_id,
        )
    except Exception as e:
        _log("slack_view_fetch_tool_calls_error", run_id=run_id, error=str(e))

    if not tool_calls:
        blocks.extend(
            [
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "_No tool calls found for this phase._",
                    },
                },
            ]
        )
        return blocks

    # Filter tool calls by category (phase_key matches tool module)
    # Tool names typically contain the category: e.g., "list_pods" -> kubernetes
    category_patterns = {
        "kubernetes": [
            "k8s",
            "pod",
            "deployment",
            "namespace",
            "kubectl",
            "list_pods",
            "get_pod",
            "describe_",
        ],
        "coralogix_tools": ["coralogix", "search_coralogix", "get_coralogix"],
        "aws_tools": ["aws", "ec2", "cloudwatch", "lambda", "ecs", "rds", "s3"],
        "datadog_tools": ["datadog"],
        "github_tools": ["github", "gh_"],
        "github_app_tools": ["github", "gh_"],
        "postgres_tools": ["postgres", "pg_", "query_postgres"],
        "snowflake_tools": ["snowflake", "query_snowflake"],
        "elasticsearch_tools": ["elasticsearch", "es_"],
        "grafana_tools": ["grafana"],
        "splunk_tools": ["splunk"],
        "sentry_tools": ["sentry"],
        "pagerduty_tools": ["pagerduty", "pd_"],
        "jira_tools": ["jira"],
        "slack_tools": ["slack", "search_slack"],
        "git_tools": ["git_log", "git_diff", "git_blame"],
        "log_analysis_tools": ["log_", "get_log_", "search_log"],
    }

    patterns = category_patterns.get(phase_key, [phase_key.replace("_tools", "")])

    # Filter tool calls matching this category
    filtered_calls = []
    for tc in tool_calls:
        tool_name = tc.get("tool_name", "").lower()
        if any(p.lower() in tool_name for p in patterns):
            filtered_calls.append(tc)

    # If no filtered calls but we have tool calls, show all (for root_cause_analysis)
    if not filtered_calls and phase_key == "root_cause_analysis":
        filtered_calls = tool_calls

    if not filtered_calls:
        blocks.extend(
            [
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "_No tool calls found matching this category._",
                    },
                },
            ]
        )
        return blocks

    # Show tool call count
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*{len(filtered_calls)} tool call(s)*"}
            ],
        }
    )
    blocks.append({"type": "divider"})

    # Display each tool call
    for i, tc in enumerate(filtered_calls):
        if len(blocks) >= 95:  # Leave room for truncation notice
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"_... and {len(filtered_calls) - i} more tool calls (truncated)_",
                    },
                }
            )
            break

        tool_name = tc.get("tool_name", "unknown")
        status = tc.get("status", "success")
        duration_ms = tc.get("duration_ms")
        error_msg = tc.get("error_message")

        # Status indicator
        status_icon = "✅" if status == "success" else "❌"
        duration_text = f" ({duration_ms}ms)" if duration_ms else ""

        # Tool name header
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{status_icon} *{tool_name}*{duration_text}",
                },
            }
        )

        # Input parameters (truncated)
        tool_input = tc.get("tool_input")
        if tool_input:
            try:
                input_str = json.dumps(tool_input, indent=2)
                if len(input_str) > 500:
                    input_str = input_str[:500] + "\n... (truncated)"
                # Escape backticks
                input_str = input_str.replace("```", "` ` `")
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Input:*\n```{input_str}```",
                        },
                    }
                )
            except (TypeError, ValueError):
                pass

        # Output or error
        if error_msg:
            error_display = (
                error_msg[:500] + "..." if len(error_msg) > 500 else error_msg
            )
            error_display = error_display.replace("```", "` ` `")
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Error:*\n```{error_display}```",
                    },
                }
            )
        else:
            tool_output = tc.get("tool_output", "")
            if tool_output:
                output_display = (
                    tool_output[:1000] + "\n... (truncated)"
                    if len(tool_output) > 1000
                    else tool_output
                )
                # Escape backticks
                output_display = output_display.replace("```", "` ` `")
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Output:*\n```{output_display}```",
                        },
                    }
                )

        blocks.append({"type": "divider"})

    return blocks


async def _handle_feedback(
    body: dict,
    respond,
    feedback_type: str,
    integration: SlackBoltIntegration,
) -> None:
    """
    Process feedback button clicks.

    Records feedback to audit service and updates the message
    to show feedback was received.
    """
    action = (body.get("actions") or [{}])[0]
    value_str = action.get("value", "{}")

    try:
        value = json.loads(value_str)
    except json.JSONDecodeError:
        value = {}

    run_id = value.get("run_id")
    correlation_id = value.get("correlation_id")
    user_id = body.get("user", {}).get("id", "")

    _log(
        "slack_feedback_received",
        feedback_type=feedback_type,
        run_id=run_id,
        correlation_id=correlation_id,
        user_id=user_id,
    )

    # Record feedback to audit service
    if integration.audit_api and run_id:
        # Run sync HTTP call in thread pool to avoid blocking event loop
        await asyncio.to_thread(
            integration.audit_api.record_feedback,
            run_id=run_id,
            correlation_id=correlation_id,
            feedback=feedback_type,
            user_id=user_id,
            source="slack",
        )

    # Send ephemeral response (only visible to the user who clicked)
    await respond(
        text="Thanks for your feedback!",
        response_type="ephemeral",
    )
