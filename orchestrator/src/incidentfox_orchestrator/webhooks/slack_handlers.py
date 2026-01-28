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

        # Track whether agent run was created so we can mark it failed on exception
        agent_run_created = False
        run_id = None
        org_id = None

        try:
            cfg = integration.config_service
            agent_api = integration.agent_api
            audit_api = integration.audit_api

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

            # Record agent run start
            if audit_api:
                # Run sync HTTP call in thread pool to avoid blocking event loop
                await asyncio.to_thread(
                    partial(
                        audit_api.create_agent_run,
                        run_id=run_id,
                        org_id=org_id,
                        team_node_id=team_node_id,
                        correlation_id=correlation_id,
                        trigger_source="slack",
                        trigger_actor=user_id,
                        trigger_message=text,
                        trigger_channel_id=channel_id,
                        agent_name=entrance_agent_name,
                        metadata={
                            "event_ts": event_ts,
                            "thread_ts": thread_ts,
                            "session_id": session_id,
                        },
                    )
                )
                agent_run_created = True

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
            result = await asyncio.to_thread(
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
                )
            )

            # Record completion
            if audit_api:
                out = result.get("output") or result.get("agent_output")
                output_summary = None
                if isinstance(out, dict):
                    output_summary = out.get("summary") or out.get("root_cause")
                elif isinstance(out, str):
                    output_summary = out[:200] if len(out) > 200 else out

                status = "completed" if result.get("success", True) else "failed"
                # Run audit call in thread pool as well
                await asyncio.to_thread(
                    partial(
                        audit_api.complete_agent_run,
                        org_id=org_id,
                        run_id=run_id,
                        status=status,
                        tool_calls_count=result.get("tool_calls_count"),
                        output_summary=(
                            output_summary[:200]
                            if output_summary and len(output_summary) > 200
                            else output_summary
                        ),
                    )
                )

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
            # Mark agent run as failed if it was created
            if agent_run_created and audit_api and run_id and org_id:
                try:
                    await asyncio.to_thread(
                        audit_api.complete_agent_run,
                        org_id=org_id,
                        run_id=run_id,
                        status="failed",
                        error_message=str(e)[:500],  # Truncate long errors
                    )
                except Exception as completion_err:
                    _log(
                        "slack_event_failed_completion_error",
                        correlation_id=correlation_id,
                        run_id=run_id,
                        error=str(completion_err),
                    )

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

        These buttons allow users to see detailed results for each phase.
        Since phase results are not persisted after the agent run, we show
        an informational modal directing users to the main response.
        """
        await ack()
        action = (body.get("actions") or [{}])[0]
        action_id = action.get("action_id", "view_unknown")
        phase_key = action.get("value", "unknown")
        trigger_id = body.get("trigger_id")

        _log(
            "slack_view_phase_clicked",
            action_id=action_id,
            phase_key=phase_key,
        )

        # Map phase keys to friendly names
        phase_labels = {
            "kubernetes": "Kubernetes",
            "coralogix_tools": "Coralogix",
            "aws_tools": "AWS",
            "datadog_tools": "Datadog",
            "github_tools": "GitHub",
            "postgres_tools": "PostgreSQL",
            "snowflake_tools": "Snowflake",
            "root_cause_analysis": "Root Cause Analysis",
        }
        phase_name = phase_labels.get(phase_key, phase_key.replace("_", " ").title())

        # Open a modal with phase info
        if trigger_id:
            try:
                await client.views_open(
                    trigger_id=trigger_id,
                    view={
                        "type": "modal",
                        "title": {"type": "plain_text", "text": phase_name[:24]},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"*{phase_name} Results*",
                                },
                            },
                            {"type": "divider"},
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": (
                                        "The detailed findings for this phase are included "
                                        "in the investigation summary above.\n\n"
                                        "Look for the *Sources Consulted* and *Hypotheses* "
                                        "sections in the main response for specific queries "
                                        "and evidence from this data source."
                                    ),
                                },
                            },
                            {
                                "type": "context",
                                "elements": [
                                    {
                                        "type": "mrkdwn",
                                        "text": (
                                            "_Future: Real-time phase details will be "
                                            "available in a persistent view._"
                                        ),
                                    }
                                ],
                            },
                        ],
                    },
                )
            except Exception as e:
                _log(
                    "slack_view_phase_modal_failed",
                    action_id=action_id,
                    error=str(e),
                )


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
