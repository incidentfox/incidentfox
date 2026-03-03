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

import httpx

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
    Sanitized for use as K8s resource names (RFC 1123: lowercase alphanumeric
    and hyphens only, max 63 chars for labels).

    Example:
        space_id="ABC123", thread_key="spaces/ABC123/threads/xyz"
        -> "gchat-abc123-xyz"
    """
    import re

    def _sanitize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    # Extract thread ID from full thread name
    thread_id = thread_key.split("/")[-1] if thread_key else "main"
    sanitized_space = _sanitize(space_id)[:20]
    sanitized_thread = _sanitize(thread_id)[:30]
    # "gchat-" (6) + space (≤20) + "-" (1) + thread (≤30) = ≤57, under 63
    return f"gchat-{sanitized_space}-{sanitized_thread}"


WEB_UI_URL = os.getenv("WEB_UI_URL", "").rstrip("/")

WELCOME_MESSAGE = (
    "*Welcome to IncidentFox!*\n\n"
    "IncidentFox is an AI-powered incident investigation assistant "
    "for Google Chat\u2122.\n\n"
    "Get started by mentioning me with a question or issue:\n"
    "- `@IncidentFox investigate high error rate on checkout service`\n"
    "- `@IncidentFox why is pod X crashing in namespace Y?`\n"
    "- `@IncidentFox help` — see all available commands\n"
    "- `@IncidentFox setup` — configure integrations\n\n"
    "I'll analyze logs, metrics, and infrastructure to help you "
    "triage incidents faster."
    + (
        f"\n\nConfigure your team at: {WEB_UI_URL}/team/integrations"
        if WEB_UI_URL
        else ""
    )
)

HELP_MESSAGE = (
    "*IncidentFox Help*\n\n"
    "I\u2019m an AI-powered incident investigation assistant. "
    "Mention me with a description of the issue and I\u2019ll investigate.\n\n"
    "*Example prompts:*\n"
    "- `@IncidentFox investigate high latency on the payments service`\n"
    "- `@IncidentFox why are pods restarting in the production namespace?`\n"
    "- `@IncidentFox check the error logs for the auth service`\n"
    "- `@IncidentFox triage this alert: <paste alert details>`\n"
    "- `@IncidentFox help` \u2014 show this help message\n\n"
    "I can access your team\u2019s Kubernetes clusters, logs, metrics, and more "
    "to help you find the root cause faster."
)


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
            return await self._handle_added_to_space(event_data, correlation_id)
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

        # Static help response — no LLM call
        if text.lower() == "help":
            _log(
                "gchat_help_requested",
                correlation_id=correlation_id,
                space_id=space_id,
            )
            return {"text": HELP_MESSAGE}

        # Setup command — link to web UI configuration
        if text.lower() == "setup":
            _log(
                "gchat_setup_requested",
                correlation_id=correlation_id,
                space_id=space_id,
            )
            if WEB_UI_URL:
                setup_text = (
                    "*IncidentFox Setup*\n\n"
                    f"Configure your integrations and tools at:\n"
                    f"- Team Integrations: {WEB_UI_URL}/team/integrations\n"
                    f"- Tools & Prompts: {WEB_UI_URL}/team/tools\n"
                    f"- Dashboard: {WEB_UI_URL}/team\n"
                )
            else:
                setup_text = (
                    "*IncidentFox Setup*\n\n"
                    "Web UI is not configured. Contact your administrator to set up "
                    "the WEB_UI_URL environment variable."
                )
            return {"text": setup_text}

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

        # Return empty — sync createMessageAction can't reply in threads.
        # The async handler sends a "working on it" + result via REST API.
        return {}

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
                    "gchat_no_routing_attempting_provision",
                    correlation_id=correlation_id,
                    space_id=space_id,
                    tried=routing.get("tried", []),
                )
                provision = await self._auto_provision(
                    space_id=space_id,
                    correlation_id=correlation_id,
                )
                if not provision:
                    try:
                        await self._send_message_to_space(
                            space_name=space_name,
                            text=(
                                "Sorry, I couldn't set up IncidentFox automatically. "
                                "Please contact your administrator to configure the integration."
                            ),
                            thread_key="",
                            effective_config={},
                            correlation_id=correlation_id,
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

            # Send "working on it" in the thread via REST API
            working_msg_name = await self._send_message_to_space(
                space_name=space_name,
                text="IncidentFox is working on it...",
                thread_key=thread_key,
                effective_config=effective_config,
                correlation_id=correlation_id,
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

            # Set up investigation state for streaming progress
            from incidentfox_orchestrator.message_builder import (
                build_final_content,
                build_progress_content,
                build_question_content,
            )
            from incidentfox_orchestrator.message_builder.gchat_formatter import (
                to_card_v2,
            )
            from incidentfox_orchestrator.message_state import InvestigationState
            from incidentfox_orchestrator.stream_handler import handle_event

            state = InvestigationState(
                session_id=session_id,
                run_id=run_id,
                correlation_id=correlation_id,
            )

            import queue as _queue_mod
            import time as _time_mod

            update_queue: _queue_mod.Queue[dict | None] = _queue_mod.Queue()

            # Rate-limited update interval (Google Chat is more restrictive)
            UPDATE_INTERVAL = 3.0

            def on_event(event: dict) -> None:
                """SSE event callback — runs in thread pool."""
                changed = handle_event(state, event)
                if not changed:
                    return

                event_type = event.get("type", "")
                now = _time_mod.time()
                is_final = event_type in ("result", "error")

                # Question events get sent immediately as a new card
                if event_type == "question" and state.pending_questions:
                    content = build_question_content(
                        state.pending_questions,
                        thread_id=session_id,
                    )
                    card = to_card_v2(content)
                    update_queue.put(
                        {
                            "card": card,
                            "text": "IncidentFox needs your input",
                            "is_final": False,
                            "is_question": True,
                        }
                    )
                    return

                # Question timeout — update the progress card
                if event_type == "question_timeout":
                    state.last_update_time = now
                    content = build_progress_content(state)
                    card = to_card_v2(content)
                    update_queue.put(
                        {
                            "card": card,
                            "text": "Agent continued without your response",
                            "is_final": False,
                        }
                    )
                    return

                if not is_final and (now - state.last_update_time) < UPDATE_INTERVAL:
                    return
                state.last_update_time = now

                if is_final:
                    content = build_final_content(state, run_id=run_id)
                else:
                    content = build_progress_content(state)

                card = to_card_v2(content)
                fallback = state.final_result or "Investigation in progress..."

                update_queue.put(
                    {
                        "card": card,
                        "text": fallback,
                        "is_final": is_final,
                    }
                )

            # Background task to drain update queue and update the "working" message
            async def _drain_updates() -> None:
                while True:
                    try:
                        item = await asyncio.to_thread(update_queue.get, timeout=1.0)
                    except Exception:
                        if state.is_complete:
                            break
                        continue

                    if item is None:
                        break

                    if item.get("is_question"):
                        # Question cards are sent as new messages in the thread
                        try:
                            await self._send_message_to_space(
                                space_name=space_name,
                                text=item["text"],
                                thread_key=thread_key,
                                effective_config=effective_config,
                                correlation_id=correlation_id,
                                cards_v2=[
                                    {
                                        "cardId": f"question-{run_id}",
                                        "card": item["card"],
                                    }
                                ],
                            )
                        except Exception as q_err:
                            _log(
                                "gchat_question_send_failed",
                                correlation_id=correlation_id,
                                error=str(q_err),
                            )
                    elif working_msg_name:
                        try:
                            await self._update_message_in_space(
                                message_name=working_msg_name,
                                text=item["text"],
                                effective_config=effective_config,
                                correlation_id=correlation_id,
                                cards_v2=[
                                    {
                                        "cardId": f"progress-{run_id}",
                                        "card": item["card"],
                                    }
                                ],
                            )
                        except Exception as update_err:
                            _log(
                                "gchat_progress_update_failed",
                                correlation_id=correlation_id,
                                error=str(update_err),
                            )

                    if item.get("is_final"):
                        break

            drain_task = asyncio.create_task(_drain_updates())

            # Run agent with streaming
            try:
                result = await asyncio.to_thread(
                    partial(
                        agent_api.run_agent_streaming,
                        team_token=team_token,
                        agent_name=entrance_agent_name,
                        message=text,
                        on_event=on_event,
                        tenant_id=org_id,
                        team_id=team_node_id,
                        timeout=int(
                            os.getenv("ORCHESTRATOR_GCHAT_AGENT_TIMEOUT_SECONDS", "300")
                        ),
                        correlation_id=correlation_id,
                        agent_base_url=dedicated_agent_url,
                        session_id=session_id,
                    )
                )
            except RuntimeError:
                result = {"result": "", "success": False}
            finally:
                update_queue.put(None)
                try:
                    await asyncio.wait_for(drain_task, timeout=10.0)
                except asyncio.TimeoutError:
                    pass

            # Send final result as a new message with rich card + feedback
            result_text = result.get("result", "") or state.final_result or ""
            if result_text and state.is_complete:
                content = build_final_content(state, run_id=run_id)
                card = to_card_v2(content)

                await self._send_message_to_space(
                    space_name=space_name,
                    text=result_text,
                    thread_key=thread_key,
                    effective_config=effective_config,
                    correlation_id=correlation_id,
                    cards_v2=[{"cardId": f"result-{run_id}", "card": card}],
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
            # Send error feedback to user so they don't stare at "working on it" forever
            try:
                await self._send_message_to_space(
                    space_name=space_name,
                    text=(
                        "Sorry, the investigation timed out or encountered an error. "
                        "Please try again."
                    ),
                    thread_key=thread_key,
                    effective_config=effective_config,
                    correlation_id=correlation_id,
                )
            except Exception:
                pass  # Best-effort error feedback

    def _get_access_token(self, effective_config: Dict[str, Any]) -> Optional[str]:
        """
        Get an OAuth2 access token from service account credentials.

        Credentials come from team config or environment.
        """
        sa_key_json = (
            (effective_config or {})
            .get("integrations", {})
            .get("google_chat", {})
            .get("service_account_key")
        ) or os.getenv("GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", "")

        if not sa_key_json:
            return None

        # Parse key — may be raw JSON, base64-encoded JSON, or a dict
        if isinstance(sa_key_json, str):
            try:
                sa_key_info = json.loads(sa_key_json)
            except json.JSONDecodeError:
                import base64

                sa_key_info = json.loads(base64.b64decode(sa_key_json))
        else:
            sa_key_info = sa_key_json

        from google.auth.transport import requests as google_requests
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(
            sa_key_info,
            scopes=["https://www.googleapis.com/auth/chat.bot"],
        )
        credentials.refresh(google_requests.Request())
        return credentials.token

    async def _send_message_to_space(
        self,
        space_name: str,
        text: str,
        thread_key: str,
        effective_config: Dict[str, Any],
        correlation_id: str,
        cards_v2: Optional[list] = None,
    ) -> Optional[str]:
        """
        Send a message to a Google Chat space via REST API.

        Returns the message name (e.g. "spaces/X/messages/Y") for later updates,
        or None on failure.
        """
        try:
            access_token = await asyncio.to_thread(
                self._get_access_token, effective_config
            )
            if not access_token:
                _log(
                    "gchat_send_no_credentials",
                    correlation_id=correlation_id,
                    space_name=space_name,
                )
                return None

            url = f"https://chat.googleapis.com/v1/{space_name}/messages"
            payload: Dict[str, Any] = {"text": text}
            if cards_v2:
                payload["cardsV2"] = cards_v2
            if thread_key:
                payload["thread"] = {"name": thread_key}

            params: Dict[str, str] = {}
            if thread_key:
                params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

            result = await asyncio.to_thread(
                self._post_gchat_message,
                url=url,
                access_token=access_token,
                payload=payload,
                params=params,
            )

            _log(
                "gchat_message_sent",
                correlation_id=correlation_id,
                space_name=space_name,
                result_length=len(text),
                message_name=result.get("name") if isinstance(result, dict) else None,
            )

            # Return message name for updates
            if isinstance(result, dict):
                return result.get("name")
            return None

        except Exception as e:
            _log(
                "gchat_send_failed",
                correlation_id=correlation_id,
                space_name=space_name,
                error=str(e),
            )
            return None

    async def _update_message_in_space(
        self,
        message_name: str,
        text: str,
        effective_config: Dict[str, Any],
        correlation_id: str,
        cards_v2: Optional[list] = None,
    ) -> None:
        """Update an existing message in Google Chat via PATCH."""
        try:
            access_token = await asyncio.to_thread(
                self._get_access_token, effective_config
            )
            if not access_token:
                return

            url = f"https://chat.googleapis.com/v1/{message_name}"
            payload: Dict[str, Any] = {"text": text}
            if cards_v2:
                payload["cardsV2"] = cards_v2

            update_mask = "text"
            if cards_v2:
                update_mask = "text,cardsV2"

            await asyncio.to_thread(
                self._patch_gchat_message,
                url=url,
                access_token=access_token,
                payload=payload,
                update_mask=update_mask,
            )

        except Exception as e:
            _log(
                "gchat_update_failed",
                correlation_id=correlation_id,
                message_name=message_name,
                error=str(e),
            )

    @staticmethod
    def _post_gchat_message(
        url: str,
        access_token: str,
        payload: Dict[str, Any],
        params: Dict[str, str],
    ) -> Dict[str, Any]:
        """Sync helper to POST a message to Google Chat API. Returns response body."""
        with httpx.Client(timeout=15.0) as c:
            r = c.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                params=params,
            )
            r.raise_for_status()
            return r.json()

    @staticmethod
    def _patch_gchat_message(
        url: str,
        access_token: str,
        payload: Dict[str, Any],
        update_mask: str,
    ) -> Dict[str, Any]:
        """Sync helper to PATCH (update) a message in Google Chat API."""
        with httpx.Client(timeout=15.0) as c:
            r = c.patch(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                params={"updateMask": update_mask},
            )
            r.raise_for_status()
            return r.json()

    async def _auto_provision(
        self,
        space_id: str,
        correlation_id: str,
    ) -> Optional[Dict[str, str]]:
        """Auto-provision an org + team for a new Google Chat space.

        Creates the org and default team in config-service, then registers
        the routing identifier so subsequent messages are routed correctly.

        Returns ``{"org_id": ..., "team_node_id": ...}`` on success, or None.
        """
        try:
            admin_token = (os.getenv("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN") or "").strip()
            if not admin_token:
                _log(
                    "gchat_auto_provision_no_admin_token", correlation_id=correlation_id
                )
                return None

            cfg = self.config_service

            org_id = f"gchat-{space_id}"
            org_name = f"Google Chat {space_id[:16]}"
            team_node_id = "default"

            # Step 1: Create org (idempotent)
            await asyncio.to_thread(cfg.create_org_node, admin_token, org_id, org_name)

            # Step 2: Create default team (idempotent)
            await asyncio.to_thread(
                cfg.create_team_node, admin_token, org_id, team_node_id, "Default Team"
            )

            # Step 3: Update routing to include this space ID.
            existing_ids: list[str] = []
            try:
                eff = await asyncio.to_thread(
                    cfg.get_effective_config_for_node,
                    admin_token,
                    org_id,
                    team_node_id,
                )
                existing_ids = list(
                    eff.get("routing", {}).get("google_chat_space_ids", [])
                )
            except Exception:
                pass

            if space_id not in existing_ids:
                existing_ids.append(space_id)

            await asyncio.to_thread(
                cfg.patch_node_config,
                admin_token,
                org_id,
                team_node_id,
                {
                    "routing": {"google_chat_space_ids": existing_ids},
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
                "gchat_auto_provision_success",
                correlation_id=correlation_id,
                org_id=org_id,
                team_node_id=team_node_id,
                space_id=space_id,
            )
            return {"org_id": org_id, "team_node_id": team_node_id}

        except Exception as e:
            _log(
                "gchat_auto_provision_failed",
                correlation_id=correlation_id,
                error=str(e),
            )
            return None

    async def _handle_added_to_space(
        self,
        event_data: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """Handle ADDED_TO_SPACE event (bot added to a space)."""
        space = event_data.get("space", {})
        space_name = space.get("name", "")
        space_type = space.get("type", "")  # ROOM, DM, etc.
        space_id = space_name.split("/")[-1] if space_name else ""

        user = event_data.get("user", {})
        user_display_name = user.get("displayName", "")

        _log(
            "gchat_added_to_space",
            correlation_id=correlation_id,
            space_name=space_name,
            space_type=space_type,
            added_by=user_display_name,
        )

        # Proactively provision so first message routes correctly
        if space_id:
            asyncio.create_task(
                self._auto_provision(
                    space_id=space_id,
                    correlation_id=correlation_id,
                )
            )

        return {"text": WELCOME_MESSAGE}

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

        # Handle answer submission (AskUserQuestion)
        if action_method_name == "submit_answer":
            thread_id = params.get("thread_id", "")
            # Collect answers from common inputs in the action parameters
            common_inputs = event_data.get("common", {}).get("formInputs", {})
            answers: Dict[str, str] = {}
            for key, val_obj in common_inputs.items():
                if key.startswith("q") and key[1:].isdigit():
                    # formInputs values are {"stringInputs": {"value": [...]}}
                    string_inputs = val_obj.get("stringInputs", {})
                    values = string_inputs.get("value", [])
                    answers[key] = values[0] if len(values) == 1 else ",".join(values)

            _log(
                "gchat_answer_submitted",
                correlation_id=correlation_id,
                thread_id=thread_id,
                answer_count=len(answers),
            )

            if thread_id and answers:
                try:
                    await asyncio.to_thread(
                        self.agent_api.submit_answer,
                        thread_id=thread_id,
                        answers=answers,
                    )
                except Exception as answer_err:
                    _log(
                        "gchat_answer_submit_failed",
                        correlation_id=correlation_id,
                        error=str(answer_err),
                    )

            return {
                "actionResponse": {
                    "type": "UPDATE_MESSAGE",
                },
                "text": "Your answers have been submitted!",
            }

        return {}
