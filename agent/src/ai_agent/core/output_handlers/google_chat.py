"""
Google Chat output handler - posts agent results as Card messages.

Supports:
- Initial "working on it" message
- Progress updates (by editing message)
- Final result with Card v2 formatting

Uses Google Chat API via service account credentials.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..logging import get_logger
from ..output_handler import OutputHandler, OutputResult

logger = get_logger(__name__)


class GoogleChatOutputHandler(OutputHandler):
    """
    Posts agent output to Google Chat.

    Config:
        space_id: Google Chat space ID (required)
        space_name: Full space name e.g. "spaces/XXXXX" (optional)
        thread_key: Thread key for replies (optional)
        service_account_key: Service account JSON or path (optional, defaults to env)
    """

    @property
    def destination_type(self) -> str:
        return "google_chat"

    async def _get_chat_service(self, config: dict[str, Any]):
        """Get Google Chat API service."""
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError:
            raise ImportError(
                "Google Chat SDK not installed. "
                "Install with: pip install google-api-python-client google-auth"
            )

        # Get credentials
        creds_json = config.get("service_account_key") or os.getenv(
            "GOOGLE_CHAT_SERVICE_ACCOUNT_KEY", ""
        )

        if creds_json:
            if creds_json.startswith("{"):
                # JSON string
                creds_info = json.loads(creds_json)
            else:
                # File path
                with open(creds_json) as f:
                    creds_info = json.load(f)

            credentials = service_account.Credentials.from_service_account_info(
                creds_info,
                scopes=["https://www.googleapis.com/auth/chat.bot"],
            )
        else:
            # Default credentials (GKE Workload Identity or local ADC)
            from google.auth import default

            credentials, _ = default(
                scopes=["https://www.googleapis.com/auth/chat.bot"]
            )

        return build("chat", "v1", credentials=credentials)

    def _get_space_name(self, config: dict[str, Any]) -> str:
        """Get full space name from config."""
        space_name = config.get("space_name")
        if space_name:
            return space_name
        space_id = config.get("space_id", "")
        return f"spaces/{space_id}" if space_id else ""

    async def post_initial(
        self,
        config: dict[str, Any],
        task_description: str,
        agent_name: str = "IncidentFox",
    ) -> str | None:
        """Post initial working message, return message name for updates."""
        space_name = self._get_space_name(config)
        if not space_name:
            logger.error("gchat_output_missing_space", config_keys=list(config.keys()))
            return None

        try:
            service = await self._get_chat_service(config)

            thread_key = config.get("thread_key")
            task_preview = (
                task_description[:200] + "..."
                if len(task_description) > 200
                else task_description
            )

            message_body: dict[str, Any] = {
                "text": f"*{agent_name}*\n\nWorking on: _{task_preview}_"
            }

            # If thread_key, reply in thread
            if thread_key:
                message_body["thread"] = {"name": thread_key}

            result = (
                service.spaces()
                .messages()
                .create(
                    parent=space_name,
                    body=message_body,
                )
                .execute()
            )

            message_name = result.get("name")
            logger.info(
                "gchat_initial_posted", space=space_name, message_name=message_name
            )

            return message_name

        except Exception as e:
            logger.error("gchat_initial_failed", error=str(e), exc_info=True)
            return None

    async def update_progress(
        self,
        config: dict[str, Any],
        message_id: str,
        status_text: str,
    ) -> None:
        """Update message with progress."""
        if not message_id:
            return

        try:
            service = await self._get_chat_service(config)

            service.spaces().messages().update(
                name=message_id,
                updateMask="text",
                body={"text": f"*IncidentFox*\n\n{status_text}"},
            ).execute()

        except Exception as e:
            logger.warning("gchat_progress_failed", error=str(e))

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
        """Post final result."""
        space_name = self._get_space_name(config)
        if not space_name:
            return OutputResult(
                success=False,
                destination_type="google_chat",
                error="Missing space_id",
            )

        try:
            service = await self._get_chat_service(config)
            thread_key = config.get("thread_key")

            # Build message with card
            if success:
                card = self._build_success_card(output, agent_name, duration_seconds)
                text = "Investigation complete"
            else:
                card = self._build_error_card(error or str(output), agent_name)
                text = "Investigation encountered an error"

            message_body: dict[str, Any] = {
                "text": text,
                "cardsV2": [card],
            }

            if thread_key:
                message_body["thread"] = {"name": thread_key}

            if message_id:
                # Update existing message
                result = (
                    service.spaces()
                    .messages()
                    .update(
                        name=message_id,
                        updateMask="text,cardsV2",
                        body=message_body,
                    )
                    .execute()
                )
                final_id = message_id
            else:
                # Post new message
                result = (
                    service.spaces()
                    .messages()
                    .create(
                        parent=space_name,
                        body=message_body,
                    )
                    .execute()
                )
                final_id = result.get("name")

            logger.info("gchat_final_posted", space=space_name, success=success)

            return OutputResult(
                success=True,
                destination_type="google_chat",
                message_id=final_id,
            )

        except Exception as e:
            logger.error("gchat_final_failed", error=str(e), exc_info=True)
            return OutputResult(
                success=False,
                destination_type="google_chat",
                error=str(e),
            )

    def _build_success_card(
        self,
        output: Any,
        agent_name: str,
        duration_seconds: float | None,
    ) -> dict[str, Any]:
        """Build Google Chat card for success result."""
        sections = []

        if isinstance(output, str):
            # Truncate long outputs
            text = output[:4000] if len(output) > 4000 else output
            sections.append({"widgets": [{"textParagraph": {"text": text}}]})
        elif isinstance(output, dict):
            if output.get("summary"):
                sections.append(
                    {
                        "header": "Summary",
                        "widgets": [
                            {"textParagraph": {"text": str(output["summary"])[:2000]}}
                        ],
                    }
                )
            if output.get("root_cause"):
                sections.append(
                    {
                        "header": "Root Cause",
                        "widgets": [
                            {
                                "textParagraph": {
                                    "text": str(output["root_cause"])[:2000]
                                }
                            }
                        ],
                    }
                )
            if output.get("recommendations"):
                recs = output["recommendations"][:5]
                rec_text = "\n".join(f"- {r}" for r in recs)
                sections.append(
                    {
                        "header": "Recommendations",
                        "widgets": [{"textParagraph": {"text": rec_text}}],
                    }
                )
            # Fallback if no structured fields
            if not sections:
                try:
                    json_str = json.dumps(output, indent=2, default=str)[:3000]
                    sections.append(
                        {
                            "widgets": [
                                {"textParagraph": {"text": f"<pre>{json_str}</pre>"}}
                            ]
                        }
                    )
                except Exception:
                    sections.append(
                        {"widgets": [{"textParagraph": {"text": str(output)[:3000]}}]}
                    )
        else:
            sections.append(
                {"widgets": [{"textParagraph": {"text": str(output)[:3000]}}]}
            )

        # Footer with metadata
        meta = "Complete"
        if duration_seconds:
            meta += f" | {duration_seconds:.1f}s"

        sections.append({"widgets": [{"textParagraph": {"text": f"<i>{meta}</i>"}}]})

        return {
            "cardId": "result",
            "card": {
                "header": {
                    "title": f"{agent_name}",
                    "subtitle": "Investigation Result",
                },
                "sections": sections,
            },
        }

    def _build_error_card(self, error: str, agent_name: str) -> dict[str, Any]:
        """Build Google Chat card for error result."""
        return {
            "cardId": "error",
            "card": {
                "header": {
                    "title": f"{agent_name}",
                    "subtitle": "Error",
                },
                "sections": [
                    {
                        "widgets": [
                            {
                                "textParagraph": {
                                    "text": f"<b>Something went wrong</b>\n\n<pre>{error[:1000]}</pre>"
                                }
                            }
                        ]
                    }
                ],
            },
        }
