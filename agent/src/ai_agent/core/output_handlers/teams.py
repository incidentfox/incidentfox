"""
MS Teams output handler - posts agent results as Adaptive Card messages.

Supports:
- Initial "working on it" message
- Progress updates
- Final result with Adaptive Card formatting

Uses Bot Framework SDK for proactive messaging.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..logging import get_logger
from ..output_handler import OutputHandler, OutputResult

logger = get_logger(__name__)


class TeamsOutputHandler(OutputHandler):
    """
    Posts agent output to MS Teams.

    Config:
        conversation_reference: Serialized ConversationReference for proactive messaging
        initial_message_id: Message ID to update (optional)
        app_id: Bot MicrosoftAppId (optional, defaults to env)
        app_password: Bot MicrosoftAppPassword (optional, defaults to env)
    """

    @property
    def destination_type(self) -> str:
        return "teams"

    def _get_credentials(self, config: dict[str, Any]) -> tuple[str, str]:
        """Get app credentials."""
        app_id = config.get("app_id") or os.getenv("TEAMS_APP_ID", "")
        app_password = config.get("app_password") or os.getenv("TEAMS_APP_PASSWORD", "")
        return app_id, app_password

    async def _get_adapter(self, config: dict[str, Any]):
        """Get BotFrameworkAdapter."""
        try:
            from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
        except ImportError:
            raise ImportError(
                "Bot Framework SDK not installed. "
                "Install with: pip install botbuilder-core botbuilder-schema"
            )

        app_id, app_password = self._get_credentials(config)
        settings = BotFrameworkAdapterSettings(app_id=app_id, app_password=app_password)
        return BotFrameworkAdapter(settings)

    def _deserialize_conversation_reference(self, conv_ref: dict[str, Any]):
        """Deserialize conversation reference from dict."""
        from botbuilder.schema import (
            ChannelAccount,
            ConversationAccount,
            ConversationReference,
        )

        user_data = conv_ref.get("user")
        bot_data = conv_ref.get("bot")
        conv_data = conv_ref.get("conversation")

        return ConversationReference(
            activity_id=conv_ref.get("activity_id"),
            user=(
                ChannelAccount(
                    id=user_data.get("id") if user_data else None,
                    name=user_data.get("name") if user_data else None,
                )
                if user_data
                else None
            ),
            bot=(
                ChannelAccount(
                    id=bot_data.get("id") if bot_data else None,
                    name=bot_data.get("name") if bot_data else None,
                )
                if bot_data
                else None
            ),
            conversation=(
                ConversationAccount(
                    id=conv_data.get("id") if conv_data else None,
                    name=conv_data.get("name") if conv_data else None,
                    is_group=conv_data.get("is_group") if conv_data else None,
                )
                if conv_data
                else None
            ),
            channel_id=conv_ref.get("channel_id"),
            service_url=conv_ref.get("service_url"),
        )

    async def post_initial(
        self,
        config: dict[str, Any],
        task_description: str,
        agent_name: str = "IncidentFox",
    ) -> str | None:
        """Post initial working message."""
        conv_ref = config.get("conversation_reference")
        if not conv_ref:
            logger.error(
                "teams_output_missing_conversation_reference",
                config_keys=list(config.keys()),
            )
            return None

        try:
            from botbuilder.schema import Activity

            adapter = await self._get_adapter(config)

            # Deserialize conversation reference
            if isinstance(conv_ref, dict):
                ref = self._deserialize_conversation_reference(conv_ref)
            else:
                ref = conv_ref

            task_preview = (
                task_description[:200] + "..."
                if len(task_description) > 200
                else task_description
            )

            message_id = None
            app_id, _ = self._get_credentials(config)

            async def callback(turn_context):
                nonlocal message_id
                activity = Activity(
                    type="message",
                    text=f"**{agent_name}**\n\nWorking on: _{task_preview}_",
                )
                response = await turn_context.send_activity(activity)
                message_id = response.id if response else None

            await adapter.continue_conversation(ref, callback, app_id)

            logger.info("teams_initial_posted", message_id=message_id)
            return message_id

        except Exception as e:
            logger.error("teams_initial_failed", error=str(e), exc_info=True)
            return None

    async def update_progress(
        self,
        config: dict[str, Any],
        message_id: str,
        status_text: str,
    ) -> None:
        """Update message with progress."""
        # Teams message updates are complex; skip for MVP
        pass

    async def post_final(
        self,
        config: dict[str, Any],
        message_id: str | None,
        output: Any,
        success: bool = True,
        duration_seconds: float | None = None,
        error: str | None = None,
        agent_name: str = "IncidentFox",
    ) -> OutputResult:
        """Post final result with Adaptive Card."""
        conv_ref = config.get("conversation_reference")
        if not conv_ref:
            return OutputResult(
                success=False,
                destination_type="teams",
                error="Missing conversation_reference",
            )

        try:
            from botbuilder.schema import Activity, Attachment

            adapter = await self._get_adapter(config)

            if isinstance(conv_ref, dict):
                ref = self._deserialize_conversation_reference(conv_ref)
            else:
                ref = conv_ref

            # Build Adaptive Card
            if success:
                card = self._build_success_card(output, agent_name, duration_seconds)
            else:
                card = self._build_error_card(error or str(output), agent_name)

            final_id = None
            app_id, _ = self._get_credentials(config)

            async def callback(turn_context):
                nonlocal final_id
                activity = Activity(
                    type="message",
                    attachments=[
                        Attachment(
                            content_type="application/vnd.microsoft.card.adaptive",
                            content=card,
                        )
                    ],
                )

                # Post new message (updating is complex in Teams)
                response = await turn_context.send_activity(activity)
                final_id = response.id if response else None

            await adapter.continue_conversation(ref, callback, app_id)

            logger.info("teams_final_posted", success=success)

            return OutputResult(
                success=True,
                destination_type="teams",
                message_id=final_id,
            )

        except Exception as e:
            logger.error("teams_final_failed", error=str(e), exc_info=True)
            return OutputResult(
                success=False,
                destination_type="teams",
                error=str(e),
            )

    def _build_success_card(
        self,
        output: Any,
        agent_name: str,
        duration_seconds: float | None,
    ) -> dict[str, Any]:
        """Build Adaptive Card for success result."""
        body: list[dict[str, Any]] = [
            {
                "type": "TextBlock",
                "text": f"{agent_name}",
                "weight": "Bolder",
                "size": "Large",
            },
        ]

        if isinstance(output, str):
            # Truncate long outputs
            text = output[:4000] if len(output) > 4000 else output
            body.append(
                {
                    "type": "TextBlock",
                    "text": text,
                    "wrap": True,
                }
            )
        elif isinstance(output, dict):
            if output.get("summary"):
                body.append(
                    {
                        "type": "TextBlock",
                        "text": "**Summary**",
                        "weight": "Bolder",
                    }
                )
                body.append(
                    {
                        "type": "TextBlock",
                        "text": str(output["summary"])[:2000],
                        "wrap": True,
                    }
                )

            if output.get("root_cause"):
                body.append(
                    {
                        "type": "TextBlock",
                        "text": "**Root Cause**",
                        "weight": "Bolder",
                    }
                )
                body.append(
                    {
                        "type": "TextBlock",
                        "text": str(output["root_cause"])[:2000],
                        "wrap": True,
                    }
                )

            if output.get("recommendations"):
                body.append(
                    {
                        "type": "TextBlock",
                        "text": "**Recommendations**",
                        "weight": "Bolder",
                    }
                )
                for rec in output["recommendations"][:5]:
                    body.append(
                        {
                            "type": "TextBlock",
                            "text": f"- {rec}",
                            "wrap": True,
                        }
                    )

            # Fallback if no structured fields
            if len(body) == 1:
                try:
                    json_str = json.dumps(output, indent=2, default=str)[:3000]
                    body.append(
                        {
                            "type": "TextBlock",
                            "text": json_str,
                            "wrap": True,
                            "fontType": "Monospace",
                        }
                    )
                except Exception:
                    body.append(
                        {
                            "type": "TextBlock",
                            "text": str(output)[:3000],
                            "wrap": True,
                        }
                    )
        else:
            body.append(
                {
                    "type": "TextBlock",
                    "text": str(output)[:3000],
                    "wrap": True,
                }
            )

        # Footer with metadata
        meta = "Complete"
        if duration_seconds:
            meta += f" | {duration_seconds:.1f}s"

        body.append(
            {
                "type": "TextBlock",
                "text": meta,
                "isSubtle": True,
                "size": "Small",
            }
        )

        return {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
        }

    def _build_error_card(self, error: str, agent_name: str) -> dict[str, Any]:
        """Build Adaptive Card for error result."""
        return {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"{agent_name}",
                    "weight": "Bolder",
                    "size": "Large",
                },
                {
                    "type": "TextBlock",
                    "text": "**Something went wrong**",
                    "color": "Attention",
                },
                {
                    "type": "TextBlock",
                    "text": f"`{error[:1000]}`",
                    "wrap": True,
                    "fontType": "Monospace",
                },
            ],
        }
