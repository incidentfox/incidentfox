"""
Slack output handler - posts agent results as Block Kit messages.

Supports:
- Initial "working on it" message
- Progress updates
- Final rich Block Kit result
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable, TypeVar

from ..logging import get_logger
from ..output_handler import OutputHandler, OutputResult

logger = get_logger(__name__)

T = TypeVar("T")


async def _retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_errors: tuple = (Exception,),
) -> T:
    """
    Retry an async function with exponential backoff.

    Args:
        func: Async function to call
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        retryable_errors: Tuple of exception types to retry on

    Returns:
        Result of the function

    Raises:
        The last exception if all retries fail
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except retryable_errors as e:
            last_error = e
            error_msg = str(e).lower()

            # Check if this is a rate limit error (429) or transient error (5xx)
            is_rate_limit = "rate" in error_msg or "429" in error_msg
            is_server_error = any(
                code in error_msg for code in ["500", "502", "503", "504"]
            )

            if attempt < max_retries and (is_rate_limit or is_server_error):
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning(
                    "slack_api_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay_seconds=delay,
                    error=str(e),
                    is_rate_limit=is_rate_limit,
                )
                await asyncio.sleep(delay)
            else:
                raise

    raise last_error  # Should not reach here, but for type safety


class SlackOutputHandler(OutputHandler):
    """
    Posts agent output to Slack using Block Kit.

    Config:
        channel_id: Slack channel ID (required)
        thread_ts: Thread timestamp for replies (optional)
        user_id: User to mention (optional)
        bot_token: Slack bot token (optional, defaults to SLACK_BOT_TOKEN env)
    """

    @property
    def destination_type(self) -> str:
        return "slack"

    def _get_token(self, config: dict[str, Any]) -> str:
        return config.get("bot_token") or os.getenv("SLACK_BOT_TOKEN", "")

    async def _get_client(self, config: dict[str, Any]):
        """Get async Slack client."""
        token = self._get_token(config)
        if not token:
            raise ValueError("No Slack bot token available")

        try:
            from slack_sdk.web.async_client import AsyncWebClient

            return AsyncWebClient(token=token)
        except ImportError:
            # Fallback to httpx
            return _HttpxSlackClient(token)

    async def post_initial(
        self,
        config: dict[str, Any],
        task_description: str,
        agent_name: str = "IncidentFox",
    ) -> str | None:
        """Post initial working message, return message_ts."""
        channel_id = config.get("channel_id")
        if not channel_id:
            logger.error(
                "slack_output_missing_channel",
                config_keys=list(config.keys()),
                has_bot_token=bool(config.get("bot_token")),
                has_thread_ts=bool(config.get("thread_ts")),
            )
            return None

        try:
            client = await self._get_client(config)

            user_id = config.get("user_id")
            thread_ts = config.get("thread_ts")

            blocks = self._build_working_blocks(task_description, agent_name, user_id)
            mention = f"<@{user_id}> " if user_id else ""

            # Use retry with backoff for transient errors
            async def _post():
                return await client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"{mention}🦊 {agent_name} is working on it...",
                    blocks=blocks,
                )

            result = await _retry_with_backoff(_post, max_retries=3)

            message_ts = result.get("ts") or result.get("message", {}).get("ts")

            logger.info(
                "slack_initial_posted",
                channel=channel_id,
                message_ts=message_ts,
            )

            return message_ts

        except Exception as e:
            logger.error(
                "slack_initial_failed",
                error=str(e),
                channel_id=channel_id,
                exc_info=True,
            )
            return None

    async def update_progress(
        self,
        config: dict[str, Any],
        message_id: str,
        status_text: str,
    ) -> None:
        """Update message with progress."""
        channel_id = config.get("channel_id")
        if not channel_id or not message_id:
            return

        try:
            client = await self._get_client(config)

            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🦊 IncidentFox",
                        "emoji": True,
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":hourglass_flowing_sand: {status_text}",
                    },
                },
            ]

            await client.chat_update(
                channel=channel_id,
                ts=message_id,
                text=status_text,
                blocks=blocks,
            )

        except Exception as e:
            logger.warning(
                "slack_progress_failed",
                error=str(e),
                channel_id=channel_id,
                message_id=message_id,
            )

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
        """Post final result with Block Kit formatting."""
        channel_id = config.get("channel_id")
        if not channel_id:
            logger.error(
                "slack_final_missing_channel",
                config_keys=list(config.keys()),
                has_bot_token=bool(config.get("bot_token")),
                has_run_id=bool(config.get("run_id")),
            )
            return OutputResult(
                success=False,
                destination_type="slack",
                error=f"Missing channel_id in config (keys: {list(config.keys())})",
            )

        try:
            client = await self._get_client(config)
            user_id = config.get("user_id")
            thread_ts = config.get("thread_ts")

            # Get run_id and correlation_id for feedback buttons
            run_id = config.get("run_id")
            correlation_id = config.get("correlation_id")

            if success:
                blocks = self._build_success_blocks(
                    output,
                    agent_name,
                    user_id,
                    duration_seconds,
                    run_id=run_id,
                    correlation_id=correlation_id,
                )
                fallback_text = "✅ Task completed"
            else:
                blocks = self._build_error_blocks(
                    error or str(output), agent_name, user_id
                )
                fallback_text = "❌ Task failed"

            if message_id:
                # Update existing message with retry
                async def _update():
                    return await client.chat_update(
                        channel=channel_id,
                        ts=message_id,
                        text=fallback_text,
                        blocks=blocks,
                    )

                result = await _retry_with_backoff(_update, max_retries=3)
                final_ts = message_id
            else:
                # Post new message with retry
                async def _post():
                    return await client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=thread_ts,
                        text=fallback_text,
                        blocks=blocks,
                    )

                result = await _retry_with_backoff(_post, max_retries=3)
                final_ts = result.get("ts") or result.get("message", {}).get("ts")

            logger.info(
                "slack_final_posted",
                channel=channel_id,
                success=success,
            )

            return OutputResult(
                success=True,
                destination_type="slack",
                message_id=final_ts,
            )

        except Exception as e:
            logger.error(
                "slack_final_failed",
                error=str(e),
                channel_id=channel_id,
                message_id=message_id,
                exc_info=True,
            )
            return OutputResult(
                success=False,
                destination_type="slack",
                error=str(e),
            )

    def _build_working_blocks(
        self,
        task_description: str,
        agent_name: str,
        user_id: str | None,
    ) -> list[dict[str, Any]]:
        """Build blocks for initial working message."""
        mention = f"<@{user_id}> " if user_id else ""
        task_preview = (
            task_description[:200] + "..."
            if len(task_description) > 200
            else task_description
        )

        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🦊 {agent_name}",
                    "emoji": True,
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{mention}:hourglass_flowing_sand: *Working on your request...*",
                },
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_{task_preview}_"}],
            },
        ]

    def _build_success_blocks(
        self,
        output: Any,
        agent_name: str,
        user_id: str | None,
        duration_seconds: float | None,
        run_id: str | None = None,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build blocks for successful result."""
        mention = f"<@{user_id}> " if user_id else ""

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🦊 {agent_name}",
                    "emoji": True,
                },
            },
            {"type": "divider"},
        ]

        # Format output
        blocks.extend(self._format_output(output))

        # Metadata
        meta_parts = [f"{mention}:white_check_mark: Complete"]
        if duration_seconds:
            meta_parts.append(f"⏱️ {duration_seconds:.1f}s")

        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": " | ".join(meta_parts)}],
            }
        )

        # Add feedback buttons if run_id is available
        if run_id:
            blocks.extend(self._build_feedback_buttons(run_id, correlation_id))

        return blocks

    def _build_feedback_buttons(
        self,
        run_id: str,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build feedback button blocks for user feedback collection.

        These buttons trigger feedback_positive/feedback_negative actions
        which are handled by the orchestrator's Slack Bolt handlers.
        """
        feedback_value = json.dumps(
            {
                "run_id": run_id,
                "correlation_id": correlation_id,
            }
        )

        return [
            {
                "type": "actions",
                "block_id": f"feedback_{run_id[:8]}",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Helpful",
                            "emoji": True,
                        },
                        "style": "primary",
                        "action_id": "feedback_positive",
                        "value": feedback_value,
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Not Helpful",
                            "emoji": True,
                        },
                        "action_id": "feedback_negative",
                        "value": feedback_value,
                    },
                ],
            },
        ]

    def _build_error_blocks(
        self,
        error: str,
        agent_name: str,
        user_id: str | None,
    ) -> list[dict[str, Any]]:
        """Build blocks for error result."""
        mention = f"<@{user_id}> " if user_id else ""
        error_preview = error[:500] if len(error) > 500 else error

        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🦊 {agent_name}",
                    "emoji": True,
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{mention}:x: *Something went wrong*\n\n```{error_preview}```",
                },
            },
        ]

    def _format_output(self, output: Any) -> list[dict[str, Any]]:
        """Format agent output into Slack blocks."""
        blocks = []

        if output is None:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "_No output returned_"},
                }
            )
        elif isinstance(output, str):
            # String output - chunk if needed
            chunks = self._chunk_text(output, 2900)
            for chunk in chunks:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": chunk},
                    }
                )
        elif isinstance(output, dict):
            blocks.extend(self._format_dict_output(output))
        elif hasattr(output, "summary"):
            blocks.extend(self._format_structured_output(output))
        else:
            # Fallback: JSON dump
            try:
                json_str = json.dumps(output, indent=2, default=str, ensure_ascii=False)
                if len(json_str) > 2900:
                    json_str = json_str[:2900] + "..."
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"```{json_str}```"},
                    }
                )
            except Exception:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": str(output)[:2900]},
                    }
                )

        return blocks

    def _format_dict_output(self, output: dict) -> list[dict[str, Any]]:
        """Format dict output with smart extraction."""
        blocks = []

        # Look for common structured fields
        summary = output.get("summary") or output.get("result") or output.get("message")
        root_cause = output.get("root_cause") or output.get("cause")
        recommendations = (
            output.get("recommendations") or output.get("next_steps") or []
        )
        confidence = output.get("confidence")

        if summary:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Summary*\n{summary}"},
                }
            )

        if root_cause:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Root Cause*\n{root_cause}"},
                }
            )

        if recommendations:
            rec_text = "\n".join([f"• {r}" for r in recommendations[:10]])
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Recommendations*\n{rec_text}",
                    },
                }
            )

        if confidence is not None:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"*Confidence:* {confidence}%"}
                    ],
                }
            )

        # If no structured fields, dump the dict
        if not blocks:
            try:
                json_str = json.dumps(output, indent=2, default=str, ensure_ascii=False)
                if len(json_str) > 2900:
                    json_str = json_str[:2900] + "..."
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"```{json_str}```"},
                    }
                )
            except Exception:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": str(output)[:2900]},
                    }
                )

        return blocks

    def _format_structured_output(self, output: Any) -> list[dict[str, Any]]:
        """Format pydantic/structured output."""
        blocks = []

        if hasattr(output, "summary") and output.summary:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Summary*\n{output.summary}"},
                }
            )

        if hasattr(output, "root_cause"):
            rc = output.root_cause
            if hasattr(rc, "description"):
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Root Cause*\n{rc.description}",
                        },
                    }
                )
            elif rc:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*Root Cause*\n{rc}"},
                    }
                )

        if hasattr(output, "recommendations") and output.recommendations:
            rec_text = "\n".join([f"• {r}" for r in output.recommendations[:10]])
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Recommendations*\n{rec_text}",
                    },
                }
            )

        if hasattr(output, "confidence") and output.confidence is not None:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Confidence:* {output.confidence}%",
                        }
                    ],
                }
            )

        return blocks

    def _chunk_text(self, text: str, limit: int = 2900) -> list[str]:
        """Split text into chunks respecting word boundaries."""
        if len(text) <= limit:
            return [text]

        chunks = []
        current = ""

        for word in text.split():
            if len(current) + len(word) + 1 > limit:
                chunks.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()

        if current:
            chunks.append(current)

        return chunks


class _HttpxSlackClient:
    """Fallback Slack client using httpx."""

    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://slack.com/api"

    async def chat_postMessage(self, **kwargs) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=kwargs,
            )
            return resp.json()

    async def chat_update(self, **kwargs) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat.update",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=kwargs,
            )
            return resp.json()
