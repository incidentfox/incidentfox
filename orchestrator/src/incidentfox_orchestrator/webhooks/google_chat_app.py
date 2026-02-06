"""
Google Chat App for multi-tenant webhook handling.

Handles Google Chat events:
- MESSAGE: User sends a message mentioning the bot
- ADDED_TO_SPACE: Bot added to a space
- REMOVED_FROM_SPACE: Bot removed
- CARD_CLICKED: User clicks an interactive card button

Multi-tenant routing via google_chat_space_id in ConfigService.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from functools import partial
from typing import TYPE_CHECKING, Any, Dict, Optional

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
            "component": "google_chat",
            "event": event,
            **fields,
        }
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


def generate_session_id(space_id: str, thread_key: str) -> str:
    """
    Generate session ID for thread-based conversational context.

    Uses space + thread key for stable ID across follow-up messages.
    Sanitized for use as K8s DNS names (RFC 1123).

    Example:
        space_id="ABC123", thread_key="spaces/ABC123/threads/xyz"
        -> "gchat-abc123-xyz"
    """
    # Extract thread ID from full thread name
    thread_id = thread_key.split("/")[-1] if thread_key else "main"
    sanitized = thread_id.replace("/", "-").replace(".", "-").lower()[:50]
    return f"gchat-{space_id.lower()[:20]}-{sanitized}"


class GoogleChatIntegration:
    """
    Manages Google Chat integration lifecycle.

    Similar to SlackBoltIntegration but for Google Chat.
    """

    def __init__(
        self,
        config_service: ConfigServiceClient,
        agent_api: AgentApiClient,
        audit_api: AuditApiClient | None,
        google_chat_project_id: str,
    ):
        self.config_service = config_service
        self.agent_api = agent_api
        self.audit_api = audit_api
        self.project_id = google_chat_project_id

    async def handle_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle incoming Google Chat event.

        Returns: Response to send back to Google Chat (sync response)
        """
        if event_type == "MESSAGE":
            return await self._handle_message(event_data, correlation_id)
        elif event_type == "ADDED_TO_SPACE":
            return self._handle_added_to_space(event_data, correlation_id)
        elif event_type == "REMOVED_FROM_SPACE":
            return self._handle_removed_from_space(event_data, correlation_id)
        elif event_type == "CARD_CLICKED":
            return await self._handle_card_clicked(event_data, correlation_id)
        else:
            _log(
                "gchat_unknown_event",
                event_type=event_type,
                correlation_id=correlation_id,
            )
            return {}

    async def _handle_message(
        self,
        event_data: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle MESSAGE event (user mentions bot or DMs bot).

        Flow mirrors slack_handlers.py:
        1. Extract space_id, thread_key, message text
        2. Generate session ID for thread context
        3. Look up team via Config Service routing (google_chat_space_id)
        4. Get impersonation token
        5. Resolve output destinations
        6. Call agent API (in background task)
        7. Return immediate "working on it" response
        """
        space = event_data.get("space", {})
        space_name = space.get("name", "")  # Format: "spaces/XXXXX"
        space_id = space_name.split("/")[-1] if space_name else ""

        message = event_data.get("message", {})
        # argumentText has the message with @mention removed
        text = message.get("argumentText", "") or message.get("text", "")
        text = text.strip()

        thread = message.get("thread", {})
        thread_key = thread.get("name", "")  # Format: "spaces/XXX/threads/YYY"

        message_name = message.get("name", "")

        user = event_data.get("user", {})
        user_id = user.get("name", "")  # Format: "users/XXXXX"
        user_display_name = user.get("displayName", "")

        session_id = generate_session_id(space_id, thread_key or message_name)

        _log(
            "gchat_message_processing",
            correlation_id=correlation_id,
            space_id=space_id,
            user_id=user_id,
            session_id=session_id,
            text_length=len(text),
        )

        if not text:
            return {
                "text": "Hey! What would you like me to investigate?",
                "thread": {"name": thread_key} if thread_key else None,
            }

        # Fire off background processing
        asyncio.create_task(
            self._process_message_async(
                space_id=space_id,
                space_name=space_name,
                thread_key=thread_key,
                text=text,
                user_id=user_id,
                user_display_name=user_display_name,
                session_id=session_id,
                correlation_id=correlation_id,
            )
        )

        # Return immediate response
        response: Dict[str, Any] = {
            "text": "IncidentFox is working on it...",
        }
        if thread_key:
            response["thread"] = {"name": thread_key}

        return response

    async def _process_message_async(
        self,
        space_id: str,
        space_name: str,
        thread_key: str,
        text: str,
        user_id: str,
        user_display_name: str,
        session_id: str,
        correlation_id: str,
    ) -> None:
        """Process message asynchronously (mirrors slack_handlers pattern)."""
        try:
            cfg = self.config_service
            agent_api = self.agent_api

            # Look up team via routing
            routing = await asyncio.to_thread(
                cfg.lookup_routing,
                internal_service_name="orchestrator",
                identifiers={"google_chat_space_id": space_id},
            )

            if not routing.get("found"):
                _log(
                    "gchat_no_routing",
                    correlation_id=correlation_id,
                    space_id=space_id,
                    tried=routing.get("tried", []),
                )
                return

            org_id = routing["org_id"]
            team_node_id = routing["team_node_id"]

            _log(
                "gchat_routing_found",
                correlation_id=correlation_id,
                space_id=space_id,
                org_id=org_id,
                team_node_id=team_node_id,
                matched_by=routing.get("matched_by"),
            )

            # Get impersonation token
            admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
            if not admin_token:
                _log("gchat_missing_admin_token", correlation_id=correlation_id)
                return

            imp = await asyncio.to_thread(
                cfg.issue_team_impersonation_token,
                admin_token,
                org_id=org_id,
                team_node_id=team_node_id,
            )
            team_token = str(imp.get("token") or "")
            if not team_token:
                _log("gchat_impersonation_failed", correlation_id=correlation_id)
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
                        "gchat_using_dedicated_agent",
                        correlation_id=correlation_id,
                        dedicated_url=dedicated_agent_url,
                    )
            except Exception as e:
                _log(
                    "gchat_config_fetch_failed",
                    correlation_id=correlation_id,
                    error=str(e),
                )

            run_id = uuid.uuid4().hex

            # Resolve output destinations
            from incidentfox_orchestrator.output_resolver import (
                resolve_output_destinations,
            )

            trigger_payload = {
                "space_id": space_id,
                "space_name": space_name,
                "thread_key": thread_key,
                "user_id": user_id,
                "user_display_name": user_display_name,
            }

            output_destinations = resolve_output_destinations(
                trigger_source="google_chat",
                trigger_payload=trigger_payload,
                team_config=effective_config,
            )

            # Add run_id and correlation_id to Google Chat destinations
            for dest in output_destinations:
                if dest.get("type") == "google_chat":
                    dest["run_id"] = run_id
                    dest["correlation_id"] = correlation_id

            _log(
                "gchat_output_destinations",
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
                            "google_chat": {
                                "space_id": space_id,
                                "space_name": space_name,
                                "thread_key": thread_key,
                            },
                            "trigger": "google_chat",
                        },
                    },
                    timeout=int(
                        os.getenv("ORCHESTRATOR_GCHAT_AGENT_TIMEOUT_SECONDS", "300")
                    ),
                    max_turns=int(
                        os.getenv("ORCHESTRATOR_GCHAT_AGENT_MAX_TURNS", "50")
                    ),
                    correlation_id=correlation_id,
                    agent_base_url=dedicated_agent_url,
                    output_destinations=output_destinations,
                    trigger_source="google_chat",
                )
            )

            _log(
                "gchat_message_completed",
                correlation_id=correlation_id,
                space_id=space_id,
                org_id=org_id,
                team_node_id=team_node_id,
                session_id=session_id,
            )

        except Exception as e:
            _log(
                "gchat_message_failed",
                correlation_id=correlation_id,
                space_id=space_id,
                error=str(e),
            )

    def _handle_added_to_space(
        self,
        event_data: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """Handle ADDED_TO_SPACE event (bot added to a space)."""
        space = event_data.get("space", {})
        space_name = space.get("name", "")
        space_type = space.get("type", "")  # ROOM, DM, etc.

        user = event_data.get("user", {})
        user_display_name = user.get("displayName", "")

        _log(
            "gchat_added_to_space",
            correlation_id=correlation_id,
            space_name=space_name,
            space_type=space_type,
            added_by=user_display_name,
        )

        return {
            "text": (
                "Hi! I'm IncidentFox, your AI incident investigation assistant. "
                "Mention me with a question or issue description, and I'll help investigate!"
            ),
        }

    def _handle_removed_from_space(
        self,
        event_data: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """Handle REMOVED_FROM_SPACE event (bot removed from a space)."""
        space = event_data.get("space", {})
        space_name = space.get("name", "")

        _log(
            "gchat_removed_from_space",
            correlation_id=correlation_id,
            space_name=space_name,
        )

        # No response needed when removed
        return {}

    async def _handle_card_clicked(
        self,
        event_data: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle CARD_CLICKED event (user clicks an interactive card button).

        Used for feedback buttons similar to Slack.
        """
        action = event_data.get("action", {})
        action_method_name = action.get("actionMethodName", "")
        action_parameters = action.get("parameters", [])

        # Convert parameters list to dict
        params = {p.get("key"): p.get("value") for p in action_parameters}
        run_id = params.get("run_id")
        feedback_type = params.get("feedback_type")

        user = event_data.get("user", {})
        user_id = user.get("name", "")

        _log(
            "gchat_card_clicked",
            correlation_id=correlation_id,
            action_method_name=action_method_name,
            run_id=run_id,
            feedback_type=feedback_type,
            user_id=user_id,
        )

        # Handle feedback actions
        if action_method_name == "submit_feedback" and feedback_type and run_id:
            if self.audit_api:
                await asyncio.to_thread(
                    self.audit_api.record_feedback,
                    run_id=run_id,
                    correlation_id=correlation_id,
                    feedback=feedback_type,
                    user_id=user_id,
                    source="google_chat",
                )

            return {
                "actionResponse": {
                    "type": "UPDATE_MESSAGE",
                },
                "text": "Thanks for your feedback!",
            }

        return {}
