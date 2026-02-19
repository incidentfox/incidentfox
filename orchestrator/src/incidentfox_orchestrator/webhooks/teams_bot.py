"""
MS Teams Bot for multi-tenant webhook handling.

Uses botbuilder-python SDK for:
- Activity handling (Message, ConversationUpdate, etc.)
- Auth validation via BotFrameworkAdapter
- Adaptive Card responses

Multi-tenant routing via teams_channel_id in ConfigService.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from functools import partial
from typing import TYPE_CHECKING, Any, Dict, Optional

from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import Activity, ActivityTypes, ConversationReference

if TYPE_CHECKING:
    from incidentfox_orchestrator.clients import (
        AgentApiClient,
        AuditApiClient,
        ConfigServiceClient,
    )


def _log(event: str, **fields: Any) -> None:
    """Structured logging."""
    try:
        payload = {
            "service": "orchestrator",
            "component": "teams_bot",
            "event": event,
            **fields,
        }
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


def generate_session_id(channel_id: str, conversation_id: str) -> str:
    """
    Generate session ID for conversation context.

    Uses channel + conversation ID for stable ID across follow-up messages.
    Sanitized for use as K8s resource names (RFC 1123: lowercase alphanumeric
    and hyphens only, max 63 chars for labels).
    """
    import re

    def _sanitize(value: str) -> str:
        """Replace non-alphanumeric chars with hyphens, strip leading/trailing."""
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    sanitized_channel = _sanitize(channel_id)[:20] if channel_id else "dm"
    sanitized_conv = _sanitize(conversation_id)[:30]
    # "teams-" (6) + channel (≤20) + "-" (1) + conv (≤30) = ≤57, well under 63
    return f"teams-{sanitized_channel}-{sanitized_conv}"


def _strip_mentions(activity: Activity) -> str:
    """
    Remove @mentions from message text.

    Teams includes mentions in the text as <at>BotName</at>.
    We remove all mentions to get the actual user message.
    """
    text = activity.text or ""

    # Remove mentions using entities
    if activity.entities:
        for entity in activity.entities:
            if entity.type == "mention":
                # Get the mention text from additional_properties
                mention_text = entity.additional_properties.get("text", "")
                if mention_text:
                    text = text.replace(mention_text, "")

    return text.strip()


WELCOME_MESSAGE = (
    "**Welcome to IncidentFox!**\n\n"
    "IncidentFox is an AI-powered incident investigation assistant "
    "for Microsoft Teams.\n\n"
    "Get started by mentioning me with a question or issue:\n"
    "- `@IncidentFox investigate high error rate on checkout service`\n"
    "- `@IncidentFox why is pod X crashing in namespace Y?`\n"
    "- `@IncidentFox help` \u2014 see all available commands\n\n"
    "I\u2019ll analyze logs, metrics, and infrastructure to help you "
    "triage incidents faster."
)

HELP_MESSAGE = (
    "**IncidentFox Help**\n\n"
    "I\u2019m an AI-powered incident investigation assistant. "
    "Mention me with a description of the issue and I\u2019ll investigate.\n\n"
    "**Example prompts:**\n"
    "- `@IncidentFox investigate high latency on the payments service`\n"
    "- `@IncidentFox why are pods restarting in the production namespace?`\n"
    "- `@IncidentFox check the error logs for the auth service`\n"
    "- `@IncidentFox triage this alert: <paste alert details>`\n"
    "- `@IncidentFox help` \u2014 show this help message\n\n"
    "I can access your team\u2019s Kubernetes clusters, logs, metrics, and more "
    "to help you find the root cause faster."
)


class TeamsIntegration:
    """
    Manages MS Teams Bot Framework integration.

    Key differences from Slack:
    - Uses BotFrameworkAdapter for auth and message handling
    - Credentials come from MicrosoftAppId/MicrosoftAppPassword
    - Responses use Adaptive Cards for rich formatting
    """

    def __init__(
        self,
        config_service: ConfigServiceClient,
        agent_api: AgentApiClient,
        audit_api: AuditApiClient | None,
        app_id: str,
        app_password: str,
        tenant_id: str = "",
    ):
        self.config_service = config_service
        self.agent_api = agent_api
        self.audit_api = audit_api
        self.app_id = app_id
        self.app_password = app_password

        # Create adapter with credentials
        # channel_auth_tenant is required for single-tenant Azure Bots
        settings = BotFrameworkAdapterSettings(
            app_id=app_id,
            app_password=app_password,
            channel_auth_tenant=tenant_id or None,
        )
        self.adapter = BotFrameworkAdapter(settings)

    async def process_activity(self, req_body: bytes, auth_header: str) -> None:
        """
        Process incoming Teams activity.

        BotFrameworkAdapter handles:
        - JWT validation against Azure AD
        - Activity deserialization
        - Response routing
        """
        activity = Activity().deserialize(json.loads(req_body))

        async def turn_handler(turn_context: TurnContext):
            await self._on_turn(turn_context)

        await self.adapter.process_activity(activity, auth_header, turn_handler)

    async def _on_turn(self, turn_context: TurnContext) -> None:
        """Handle activity based on type."""
        activity = turn_context.activity

        if activity.type == ActivityTypes.message:
            await self._handle_message(turn_context)
        elif activity.type == ActivityTypes.conversation_update:
            await self._handle_conversation_update(turn_context)
        elif activity.type == ActivityTypes.invoke:
            await self._handle_invoke(turn_context)
        else:
            _log("teams_unknown_activity", activity_type=activity.type)

    async def _handle_message(self, turn_context: TurnContext) -> None:
        """
        Handle incoming message.

        Flow mirrors Slack/Google Chat:
        1. Extract channel_id, conversation_id, text
        2. Generate session ID
        3. Route via ConfigService (teams_channel_id)
        4. Send immediate "working" response
        5. Process async and post result when done
        """
        activity = turn_context.activity
        correlation_id = uuid.uuid4().hex

        # Extract identifiers
        channel_data = activity.channel_data or {}
        channel_info = channel_data.get("channel", {})
        channel_id = (
            channel_info.get("id", "") if isinstance(channel_info, dict) else ""
        )

        team_info = channel_data.get("team", {})
        team_id = team_info.get("id", "") if isinstance(team_info, dict) else ""

        conversation = activity.conversation
        conversation_id = conversation.id if conversation else ""

        # Check if this is a thread reply (conversation_id includes ";messageid=")
        is_thread_reply = ";messageid=" in conversation_id

        # Check if the bot was @mentioned
        bot_id = activity.recipient.id if activity.recipient else ""
        is_mentioned = False
        if activity.entities:
            for entity in activity.entities:
                if entity.type == "mention":
                    mentioned = getattr(entity, "mentioned", None)
                    mentioned_id = (
                        getattr(mentioned, "id", None)
                        if mentioned
                        else entity.additional_properties.get("mentioned", {}).get("id")
                    )
                    if mentioned_id == bot_id:
                        is_mentioned = True
                        break

        # With RSC ChannelMessage.Read.Group, the bot receives ALL channel
        # messages.  Only process messages that either @mention the bot or are
        # thread replies (follow-ups to a conversation the bot is likely in).
        if not is_mentioned and not is_thread_reply:
            _log(
                "teams_message_ignored_no_mention",
                correlation_id=correlation_id,
                conversation_id=conversation_id[:50],
            )
            return

        # Strip @mention from text
        text = _strip_mentions(activity)

        # Get user info
        from_user = activity.from_property
        user_id = from_user.id if from_user else ""
        user_name = from_user.name if from_user else ""

        # For thread replies, conversation_id includes ";messageid=XXX".
        # Strip it so all messages in the same thread share the same session.
        base_conversation_id = conversation_id.split(";")[0]
        session_id = generate_session_id(channel_id or team_id, base_conversation_id)

        _log(
            "teams_message_processing",
            correlation_id=correlation_id,
            channel_id=channel_id,
            team_id=team_id,
            conversation_id=conversation_id[:50],
            user_id=user_id,
            session_id=session_id,
            text_length=len(text),
            is_mentioned=is_mentioned,
            is_thread_reply=is_thread_reply,
        )

        if not text:
            await turn_context.send_activity(
                "Hey! What would you like me to investigate?"
            )
            return

        # Static help response — no LLM call
        if text.lower() == "help":
            _log(
                "teams_help_requested",
                correlation_id=correlation_id,
                channel_id=channel_id,
            )
            await turn_context.send_activity(HELP_MESSAGE)
            return

        # Send typing indicator
        await turn_context.send_activity(Activity(type=ActivityTypes.typing))

        # Send "working on it" message
        initial_response = await turn_context.send_activity(
            "IncidentFox is working on it..."
        )
        initial_message_id = initial_response.id if initial_response else None
        _log(
            "teams_initial_response_sent",
            correlation_id=correlation_id,
            initial_message_id=initial_message_id,
            service_url=getattr(activity, "service_url", "unknown"),
        )

        # Extract tenant_id (Azure AD tenant) for auto-provisioning
        tenant_id = getattr(conversation, "tenant_id", "") or ""

        # Get conversation reference for proactive messaging
        conversation_ref = TurnContext.get_conversation_reference(activity)

        # Fire off background processing
        # Use base_conversation_id (without ;messageid=) for routing so
        # thread replies match the same org/team as the parent message.
        asyncio.create_task(
            self._process_message_async(
                channel_id=channel_id or team_id,
                conversation_id=base_conversation_id,
                conversation_ref=conversation_ref,
                text=text,
                user_id=user_id,
                user_name=user_name,
                session_id=session_id,
                correlation_id=correlation_id,
                initial_message_id=initial_message_id,
                tenant_id=tenant_id,
            )
        )

    async def _process_message_async(
        self,
        channel_id: str,
        conversation_id: str,
        conversation_ref: ConversationReference,
        text: str,
        user_id: str,
        user_name: str,
        session_id: str,
        correlation_id: str,
        initial_message_id: Optional[str],
        tenant_id: str = "",
    ) -> None:
        """Process message asynchronously."""
        try:
            cfg = self.config_service
            agent_api = self.agent_api

            # Route lookup - try channel_id first, then conversation_id
            routing_id = channel_id or conversation_id
            routing = await asyncio.to_thread(
                cfg.lookup_routing,
                internal_service_name="orchestrator",
                identifiers={"teams_channel_id": routing_id},
            )

            if not routing.get("found"):
                _log(
                    "teams_no_routing_attempting_provision",
                    correlation_id=correlation_id,
                    routing_id=routing_id,
                    channel_id=channel_id,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    tried=routing.get("tried", []),
                )
                provision = await self._auto_provision(
                    routing_id=routing_id,
                    tenant_id=tenant_id,
                    correlation_id=correlation_id,
                )
                if not provision:
                    try:

                        async def _send_error(tc: TurnContext):
                            await tc.send_activity(
                                "Sorry, I couldn't set up IncidentFox automatically. "
                                "Please contact your administrator to configure the integration."
                            )

                        await self.adapter.continue_conversation(
                            conversation_ref, _send_error, self.app_id
                        )
                    except Exception:
                        pass
                    return
                org_id = provision["org_id"]
                team_node_id = provision["team_node_id"]
            else:
                org_id = routing["org_id"]
                team_node_id = routing["team_node_id"]

            _log(
                "teams_routing_found",
                correlation_id=correlation_id,
                channel_id=channel_id,
                org_id=org_id,
                team_node_id=team_node_id,
                matched_by=routing.get("matched_by"),
            )

            # Get impersonation token
            admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
            if not admin_token:
                _log("teams_missing_admin_token", correlation_id=correlation_id)
                return

            imp = await asyncio.to_thread(
                cfg.issue_team_impersonation_token,
                admin_token,
                org_id=org_id,
                team_node_id=team_node_id,
            )
            team_token = str(imp.get("token") or "")
            if not team_token:
                _log("teams_impersonation_failed", correlation_id=correlation_id)
                return

            # Get effective config
            entrance_agent_name = "planner"
            dedicated_agent_url: Optional[str] = None
            effective_config: Dict[str, Any] = {}
            try:
                effective_config = await asyncio.to_thread(
                    cfg.get_effective_config, team_token=team_token
                )
                entrance_agent_name = effective_config.get("entrance_agent", "planner")
                dedicated_agent_url = effective_config.get("agent", {}).get(
                    "dedicated_service_url"
                )
                if dedicated_agent_url:
                    _log(
                        "teams_using_dedicated_agent",
                        correlation_id=correlation_id,
                        dedicated_url=dedicated_agent_url,
                    )
            except Exception as e:
                _log(
                    "teams_config_fetch_failed",
                    correlation_id=correlation_id,
                    error=str(e),
                )

            run_id = uuid.uuid4().hex

            # Resolve output destinations
            from incidentfox_orchestrator.output_resolver import (
                resolve_output_destinations,
            )

            # Serialize conversation reference for output handler
            conv_ref_dict = {
                "activity_id": conversation_ref.activity_id,
                "user": (
                    {
                        "id": (
                            conversation_ref.user.id if conversation_ref.user else None
                        ),
                        "name": (
                            conversation_ref.user.name
                            if conversation_ref.user
                            else None
                        ),
                    }
                    if conversation_ref.user
                    else None
                ),
                "bot": (
                    {
                        "id": conversation_ref.bot.id if conversation_ref.bot else None,
                        "name": (
                            conversation_ref.bot.name if conversation_ref.bot else None
                        ),
                    }
                    if conversation_ref.bot
                    else None
                ),
                "conversation": (
                    {
                        "id": (
                            conversation_ref.conversation.id
                            if conversation_ref.conversation
                            else None
                        ),
                        "name": (
                            conversation_ref.conversation.name
                            if conversation_ref.conversation
                            else None
                        ),
                        "is_group": (
                            conversation_ref.conversation.is_group
                            if conversation_ref.conversation
                            else None
                        ),
                    }
                    if conversation_ref.conversation
                    else None
                ),
                "channel_id": conversation_ref.channel_id,
                "service_url": conversation_ref.service_url,
            }

            trigger_payload = {
                "channel_id": channel_id,
                "conversation_id": conversation_id,
                "conversation_reference": conv_ref_dict,
                "user_id": user_id,
                "user_name": user_name,
                "initial_message_id": initial_message_id,
            }

            output_destinations = resolve_output_destinations(
                trigger_source="teams",
                trigger_payload=trigger_payload,
                team_config=effective_config,
            )

            # Add run_id and correlation_id to Teams destinations
            for dest in output_destinations:
                if dest.get("type") == "teams":
                    dest["run_id"] = run_id
                    dest["correlation_id"] = correlation_id

            _log(
                "teams_output_destinations",
                correlation_id=correlation_id,
                destinations=[d.get("type") for d in output_destinations],
            )

            # Run agent in thread pool — calls /investigate and streams SSE
            result = await asyncio.to_thread(
                partial(
                    agent_api.run_agent,
                    team_token=team_token,
                    agent_name=entrance_agent_name,
                    message=text,
                    tenant_id=org_id,
                    team_id=team_node_id,
                    timeout=int(
                        os.getenv("ORCHESTRATOR_TEAMS_AGENT_TIMEOUT_SECONDS", "300")
                    ),
                    correlation_id=correlation_id,
                    agent_base_url=dedicated_agent_url,
                    session_id=session_id,
                )
            )

            # Send agent result back to Teams conversation
            result_text = result.get("result", "")

            if result_text:
                try:
                    _log(
                        "teams_sending_result",
                        correlation_id=correlation_id,
                        result_length=len(result_text),
                        service_url=getattr(conversation_ref, "service_url", "unknown"),
                        conversation_id=(
                            conversation_ref.conversation.id
                            if conversation_ref.conversation
                            else "unknown"
                        ),
                    )

                    send_response = None

                    async def _send_result(turn_context: TurnContext):
                        nonlocal send_response
                        reply = Activity(
                            type=ActivityTypes.message,
                            text=result_text,
                            reply_to_id=initial_message_id,
                        )
                        send_response = await turn_context.send_activity(reply)
                        _log(
                            "teams_send_activity_response",
                            correlation_id=correlation_id,
                            response_id=(send_response.id if send_response else None),
                        )

                    await self.adapter.continue_conversation(
                        conversation_ref,
                        _send_result,
                        self.app_id,
                    )
                    _log(
                        "teams_result_sent",
                        correlation_id=correlation_id,
                        result_length=len(result_text),
                        response_id=(send_response.id if send_response else None),
                    )
                except Exception as send_err:
                    _log(
                        "teams_result_send_failed",
                        correlation_id=correlation_id,
                        error=str(send_err),
                        error_type=type(send_err).__name__,
                    )

            _log(
                "teams_message_completed",
                correlation_id=correlation_id,
                channel_id=channel_id,
                org_id=org_id,
                team_node_id=team_node_id,
                session_id=session_id,
            )

        except Exception as e:
            _log(
                "teams_message_failed",
                correlation_id=correlation_id,
                channel_id=channel_id,
                error=str(e),
            )

    async def _auto_provision(
        self,
        routing_id: str,
        tenant_id: str,
        correlation_id: str,
    ) -> Optional[Dict[str, str]]:
        """Auto-provision an org + team for a new Teams channel/conversation.

        Creates the org and default team in config-service, then registers
        the routing identifier so subsequent messages are routed correctly.

        Returns ``{"org_id": ..., "team_node_id": ...}`` on success, or None.
        """
        try:
            admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
            if not admin_token:
                _log(
                    "teams_auto_provision_no_admin_token", correlation_id=correlation_id
                )
                return None

            cfg = self.config_service

            # Derive org_id from tenant (Azure AD tenant groups all channels)
            if tenant_id:
                org_id = f"teams-{tenant_id}"
                org_name = f"Teams Tenant {tenant_id[:8]}"
            else:
                org_id = f"teams-{routing_id[:40]}"
                org_name = f"Teams {routing_id[:16]}"

            team_node_id = "default"

            # Step 1: Create org (idempotent — returns exists=True if already there)
            await asyncio.to_thread(cfg.create_org_node, admin_token, org_id, org_name)

            # Step 2: Create default team (idempotent)
            await asyncio.to_thread(
                cfg.create_team_node, admin_token, org_id, team_node_id, "Default Team"
            )

            # Step 3: Update routing to include this channel/conversation ID.
            # Fetch current routing first so we don't clobber existing entries.
            existing_ids: list[str] = []
            try:
                eff = await asyncio.to_thread(
                    cfg.get_effective_config_for_node,
                    admin_token,
                    org_id,
                    team_node_id,
                )
                existing_ids = list(eff.get("routing", {}).get("teams_channel_ids", []))
            except Exception:
                pass  # New team — no config yet

            if routing_id not in existing_ids:
                existing_ids.append(routing_id)

            await asyncio.to_thread(
                cfg.patch_node_config,
                admin_token,
                org_id,
                team_node_id,
                {
                    "routing": {"teams_channel_ids": existing_ids},
                    "integrations": {
                        "anthropic": {
                            "is_trial": True,
                            "trial_expires_at": "2030-12-31T23:59:59.000000",
                            "subscription_status": "active",
                        },
                    },
                },
            )

            _log(
                "teams_auto_provision_success",
                correlation_id=correlation_id,
                org_id=org_id,
                team_node_id=team_node_id,
                routing_id=routing_id,
            )
            return {"org_id": org_id, "team_node_id": team_node_id}

        except Exception as e:
            _log(
                "teams_auto_provision_failed",
                correlation_id=correlation_id,
                error=str(e),
            )
            return None

    async def _handle_conversation_update(self, turn_context: TurnContext) -> None:
        """Handle conversation update (bot added/removed, members changed)."""
        activity = turn_context.activity
        correlation_id = uuid.uuid4().hex

        members_added = activity.members_added or []
        members_removed = activity.members_removed or []

        # Check if bot was added
        bot_id = activity.recipient.id if activity.recipient else None
        bot_added = any(m.id == bot_id for m in members_added)

        if bot_added:
            _log(
                "teams_bot_added",
                correlation_id=correlation_id,
                conversation_id=(
                    activity.conversation.id if activity.conversation else None
                ),
            )
            await turn_context.send_activity(WELCOME_MESSAGE)

            # Proactively provision so first message routes correctly
            channel_data = activity.channel_data or {}
            ch_info = channel_data.get("channel", {})
            ch_id = ch_info.get("id", "") if isinstance(ch_info, dict) else ""
            conv_id = activity.conversation.id if activity.conversation else ""
            t_id = getattr(activity.conversation, "tenant_id", "") or ""
            routing_id = ch_id or conv_id
            if routing_id:
                asyncio.create_task(
                    self._auto_provision(
                        routing_id=routing_id,
                        tenant_id=t_id,
                        correlation_id=correlation_id,
                    )
                )

        if members_removed:
            _log(
                "teams_members_removed",
                correlation_id=correlation_id,
                count=len(members_removed),
            )

    async def _handle_invoke(self, turn_context: TurnContext) -> None:
        """
        Handle invoke activities (Adaptive Card actions, etc.).

        Used for handling card button clicks like feedback.
        """
        activity = turn_context.activity
        correlation_id = uuid.uuid4().hex

        invoke_name = activity.name
        invoke_value = activity.value or {}

        _log(
            "teams_invoke_received",
            correlation_id=correlation_id,
            invoke_name=invoke_name,
        )

        # Handle adaptive card action submit
        if invoke_name == "adaptiveCard/action":
            action_data = invoke_value.get("action", {}).get("data", {})
            action_type = action_data.get("action_type")

            if action_type == "feedback":
                feedback_type = action_data.get("feedback")
                run_id = action_data.get("run_id")
                user_id = activity.from_property.id if activity.from_property else ""

                if self.audit_api and feedback_type and run_id:
                    await asyncio.to_thread(
                        self.audit_api.record_feedback,
                        run_id=run_id,
                        correlation_id=correlation_id,
                        feedback=feedback_type,
                        user_id=user_id,
                        source="teams",
                    )

                # Return adaptive card action response
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.invoke_response,
                        value={
                            "status": 200,
                            "body": {
                                "statusCode": 200,
                                "type": "application/vnd.microsoft.activity.message",
                                "value": "Thanks for your feedback!",
                            },
                        },
                    )
                )
