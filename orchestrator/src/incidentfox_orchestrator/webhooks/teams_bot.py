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
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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
    Sanitized for use as K8s DNS names (RFC 1123).
    """
    # Sanitize the conversation_id (can be very long with special chars)
    sanitized_conv = (
        conversation_id.replace(":", "-")
        .replace(";", "-")
        .replace("@", "-")
        .lower()[:40]
    )
    sanitized_channel = channel_id.lower()[:20] if channel_id else "dm"
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

        # Strip @mention from text
        text = _strip_mentions(activity)

        # Get user info
        from_user = activity.from_property
        user_id = from_user.id if from_user else ""
        user_name = from_user.name if from_user else ""

        session_id = generate_session_id(channel_id or team_id, conversation_id)

        _log(
            "teams_message_processing",
            correlation_id=correlation_id,
            channel_id=channel_id,
            team_id=team_id,
            conversation_id=conversation_id[:50],
            user_id=user_id,
            session_id=session_id,
            text_length=len(text),
        )

        if not text:
            await turn_context.send_activity(
                "Hey! What would you like me to investigate?"
            )
            return

        # Send typing indicator
        await turn_context.send_activity(Activity(type=ActivityTypes.typing))

        # Send "working on it" message
        initial_response = await turn_context.send_activity(
            "IncidentFox is working on it..."
        )
        initial_message_id = initial_response.id if initial_response else None

        # Get conversation reference for proactive messaging
        conversation_ref = TurnContext.get_conversation_reference(activity)

        # Fire off background processing
        asyncio.create_task(
            self._process_message_async(
                channel_id=channel_id or team_id,
                conversation_id=conversation_id,
                conversation_ref=conversation_ref,
                text=text,
                user_id=user_id,
                user_name=user_name,
                session_id=session_id,
                correlation_id=correlation_id,
                initial_message_id=initial_message_id,
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
                    "teams_no_routing",
                    correlation_id=correlation_id,
                    channel_id=channel_id,
                    conversation_id=conversation_id[:50],
                    tried=routing.get("tried", []),
                )
                return

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

            # Run agent in thread pool
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
                            "teams": {
                                "channel_id": channel_id,
                                "conversation_id": conversation_id[:100],
                            },
                            "trigger": "teams",
                        },
                    },
                    timeout=int(
                        os.getenv("ORCHESTRATOR_TEAMS_AGENT_TIMEOUT_SECONDS", "300")
                    ),
                    max_turns=int(
                        os.getenv("ORCHESTRATOR_TEAMS_AGENT_MAX_TURNS", "50")
                    ),
                    correlation_id=correlation_id,
                    agent_base_url=dedicated_agent_url,
                    output_destinations=output_destinations,
                    trigger_source="teams",
                )
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
            await turn_context.send_activity(
                "Hi! I'm IncidentFox, your AI incident investigation assistant. "
                "Mention me with a question or issue description, and I'll help investigate!"
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
