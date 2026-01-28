"""
Generalized Slack output handler for all agents.

This module provides a unified way for any agent to post rich Block Kit
results directly to Slack, supporting:
- Initial "working" message
- Real-time progress updates (via hooks)
- Final results with structured output

Unlike the investigation-specific InvestigationOrchestrator, this works
with any agent type and adapts output formatting based on the agent.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from agents import Agent, RunHooks, Runner
from agents.run_context import RunContextWrapper
from agents.tool import Tool

from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class SlackContext:
    """Context for posting results to Slack."""

    channel_id: str
    thread_ts: str | None = None
    user_id: str | None = None
    # Bot token can be passed or read from env
    bot_token: str | None = None

    def get_bot_token(self) -> str:
        """Get bot token from context or environment."""
        return self.bot_token or os.getenv("SLACK_BOT_TOKEN", "")


@dataclass
class SlackOutputResult:
    """Result of a Slack output operation."""

    success: bool
    message_ts: str | None = None
    error: str | None = None
    agent_output: Any = None


class SlackOutputHandler:
    """
    Handles posting agent results to Slack with rich Block Kit formatting.

    Works with any agent type, not just investigations.
    """

    def __init__(
        self,
        slack_context: SlackContext,
        agent_name: str = "IncidentFox",
        timeout: int = 600,
        max_turns: int = 100,
    ):
        self.ctx = slack_context
        self.agent_name = agent_name
        self.timeout = timeout
        self.max_turns = max_turns
        self._message_ts: str | None = None
        self._slack_client: Any | None = None

    async def _get_slack_client(self) -> Any:
        """Get or create async Slack client."""
        if self._slack_client is None:
            try:
                from slack_sdk.web.async_client import AsyncWebClient

                token = self.ctx.get_bot_token()
                if not token:
                    raise ValueError("No Slack bot token available")
                self._slack_client = AsyncWebClient(token=token)
            except ImportError:
                # Fallback to httpx if slack_sdk not available
                self._slack_client = _HttpxSlackClient(self.ctx.get_bot_token())
        return self._slack_client

    async def post_initial_message(self, task_description: str) -> str | None:
        """Post initial 'working on it' message, return message_ts."""
        try:
            client = await self._get_slack_client()

            blocks = self._build_working_blocks(task_description)
            mention = f"<@{self.ctx.user_id}> " if self.ctx.user_id else ""

            result = await client.chat_postMessage(
                channel=self.ctx.channel_id,
                thread_ts=self.ctx.thread_ts,
                text=f"{mention}🦊 {self.agent_name} is working on it...",
                blocks=blocks,
            )

            self._message_ts = result.get("ts") or result.get("message", {}).get("ts")

            logger.info(
                "slack_initial_message_posted",
                channel=self.ctx.channel_id,
                message_ts=self._message_ts,
            )

            return self._message_ts

        except Exception as e:
            logger.error("slack_initial_message_failed", error=str(e))
            return None

    async def update_progress(self, status_text: str) -> None:
        """Update the message with progress."""
        if not self._message_ts:
            return

        try:
            client = await self._get_slack_client()

            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🦊 {self.agent_name}",
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
                channel=self.ctx.channel_id,
                ts=self._message_ts,
                text=status_text,
                blocks=blocks,
            )

        except Exception as e:
            logger.warning("slack_progress_update_failed", error=str(e))

    async def post_final_result(
        self,
        output: Any,
        success: bool = True,
        duration_seconds: float | None = None,
        error: str | None = None,
        tool_calls_count: int = 0,
    ) -> None:
        """Post the final result with rich formatting."""
        try:
            client = await self._get_slack_client()

            if success:
                blocks = self._build_success_blocks(
                    output=output,
                    duration_seconds=duration_seconds,
                    tool_calls_count=tool_calls_count,
                )
                fallback_text = "✅ Task completed"
            else:
                blocks = self._build_error_blocks(error or str(output))
                fallback_text = "❌ Task failed"

            if self._message_ts:
                # Update existing message
                await client.chat_update(
                    channel=self.ctx.channel_id,
                    ts=self._message_ts,
                    text=fallback_text,
                    blocks=blocks,
                )
            else:
                # Post new message
                mention = f"<@{self.ctx.user_id}> " if self.ctx.user_id else ""
                await client.chat_postMessage(
                    channel=self.ctx.channel_id,
                    thread_ts=self.ctx.thread_ts,
                    text=f"{mention}{fallback_text}",
                    blocks=blocks,
                )

            logger.info(
                "slack_final_result_posted",
                channel=self.ctx.channel_id,
                success=success,
            )

        except Exception as e:
            logger.error("slack_final_result_failed", error=str(e))

    def _build_working_blocks(self, task_description: str) -> list[dict[str, Any]]:
        """Build blocks for initial 'working' message."""
        mention = f"<@{self.ctx.user_id}> " if self.ctx.user_id else ""
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
                    "text": f"🦊 {self.agent_name}",
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
        duration_seconds: float | None = None,
        tool_calls_count: int = 0,
    ) -> list[dict[str, Any]]:
        """Build blocks for successful result."""
        mention = f"<@{self.ctx.user_id}> " if self.ctx.user_id else ""

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🦊 {self.agent_name}",
                    "emoji": True,
                },
            },
            {"type": "divider"},
        ]

        # Format output based on type
        formatted_output = self._format_output(output)

        # Add formatted output sections
        for section in formatted_output:
            blocks.append(section)

        # Add metadata context
        meta_parts = [f"{mention}:white_check_mark: Complete"]
        if duration_seconds:
            meta_parts.append(f"⏱️ {duration_seconds:.1f}s")
        if tool_calls_count:
            meta_parts.append(f"🔧 {tool_calls_count} tool calls")

        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": " | ".join(meta_parts)}],
            }
        )

        return blocks

    def _build_error_blocks(self, error: str) -> list[dict[str, Any]]:
        """Build blocks for error result."""
        mention = f"<@{self.ctx.user_id}> " if self.ctx.user_id else ""
        error_preview = error[:500] if len(error) > 500 else error

        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🦊 {self.agent_name}",
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

        # Handle different output types
        if output is None:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "_No output returned_"},
                }
            )
        elif isinstance(output, str):
            # String output - convert markdown to Slack mrkdwn
            try:
                from ..integrations.slack_mrkdwn import (
                    chunk_mrkdwn,
                    markdown_to_slack_mrkdwn,
                )

                mrkdwn = markdown_to_slack_mrkdwn(output)
                for chunk in chunk_mrkdwn(mrkdwn, limit=2900):
                    blocks.append(
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": chunk},
                        }
                    )
            except ImportError:
                # Fallback if converter not available
                chunks = self._chunk_text(output, 2900)
                for chunk in chunks:
                    blocks.append(
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": chunk},
                        }
                    )
        elif isinstance(output, dict):
            # Dict output - extract structured data
            blocks.extend(self._format_dict_output(output))
        elif hasattr(output, "summary"):
            # Pydantic model with summary
            blocks.extend(self._format_investigation_output(output))
        else:
            # Fallback: convert to JSON
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
        from ..integrations.slack_mrkdwn import markdown_to_slack_mrkdwn

        blocks = []

        # Look for common structured fields
        summary = output.get("summary") or output.get("result") or output.get("message")
        root_cause = output.get("root_cause") or output.get("cause")
        recommendations = (
            output.get("recommendations") or output.get("next_steps") or []
        )
        confidence = output.get("confidence")

        if summary:
            # Convert any markdown in the summary value
            summary_mrkdwn = markdown_to_slack_mrkdwn(str(summary))
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Summary*\n{summary_mrkdwn}"},
                }
            )

        if root_cause:
            # Convert any markdown in the root cause value
            if isinstance(root_cause, dict):
                # Handle structured root cause
                rc_parts = []
                if root_cause.get("description"):
                    rc_parts.append(
                        markdown_to_slack_mrkdwn(str(root_cause["description"]))
                    )
                if root_cause.get("confidence"):
                    rc_parts.append(f"_Confidence: {root_cause['confidence']}_")
                if root_cause.get("evidence"):
                    rc_parts.append(
                        f"Evidence: {markdown_to_slack_mrkdwn(str(root_cause['evidence']))}"
                    )
                rc_text = "\n".join(rc_parts) if rc_parts else str(root_cause)
            else:
                rc_text = markdown_to_slack_mrkdwn(str(root_cause))
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Root Cause*\n{rc_text}"},
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

        # If no structured fields found, dump the dict
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

    def _format_investigation_output(self, output: Any) -> list[dict[str, Any]]:
        """Format investigation-style pydantic output."""
        from ..integrations.slack_mrkdwn import markdown_to_slack_mrkdwn

        blocks = []

        if hasattr(output, "summary") and output.summary:
            summary_mrkdwn = markdown_to_slack_mrkdwn(str(output.summary))
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Summary*\n{summary_mrkdwn}"},
                }
            )

        if hasattr(output, "root_cause"):
            rc = output.root_cause
            if hasattr(rc, "description"):
                rc_mrkdwn = markdown_to_slack_mrkdwn(str(rc.description))
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Root Cause*\n{rc_mrkdwn}",
                        },
                    }
                )
            elif rc:
                rc_mrkdwn = markdown_to_slack_mrkdwn(str(rc))
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Root Cause*\n{rc_mrkdwn}",
                        },
                    }
                )

        if hasattr(output, "recommendations") and output.recommendations:
            # Convert markdown in each recommendation
            recs = [
                markdown_to_slack_mrkdwn(str(r)) for r in output.recommendations[:10]
            ]
            rec_text = "\n".join([f"• {r}" for r in recs])
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


class SlackProgressHooks(RunHooks):
    """
    Lightweight hooks that update Slack with tool progress.

    Less detailed than SlackUpdateHooks (investigation-specific),
    but works with any agent.
    """

    def __init__(self, handler: SlackOutputHandler):
        self.handler = handler
        self._tool_count = 0
        self._current_tool: str | None = None

    async def on_tool_start(
        self,
        context: RunContextWrapper,
        agent: Any,
        tool: Tool,
    ) -> None:
        """Called when a tool is about to run."""
        tool_name = getattr(tool, "name", str(tool))
        self._current_tool = tool_name
        self._tool_count += 1

        try:
            await self.handler.update_progress(
                f"Using tool: *{tool_name}* (#{self._tool_count})"
            )
        except Exception as e:
            logger.debug("slack_hook_update_failed", error=str(e))

    async def on_tool_end(
        self,
        context: RunContextWrapper,
        agent: Any,
        tool: Tool,
        result: str,
    ) -> None:
        """Called when a tool finishes."""
        pass  # We update on start, not end


async def run_agent_with_slack_output(
    agent: Agent,
    message: str,
    slack_context: SlackContext,
    *,
    agent_name: str = "IncidentFox",
    timeout: int = 600,
    max_turns: int = 100,
    show_progress: bool = True,
) -> SlackOutputResult:
    """
    Run an agent and post results directly to Slack.

    This is the main entry point for Slack-integrated agent execution.

    Args:
        agent: The agent to run
        message: User message/task
        slack_context: Slack channel/thread info
        agent_name: Display name in Slack (default: "IncidentFox")
        timeout: Execution timeout in seconds
        max_turns: Maximum agent turns
        show_progress: Whether to show tool progress updates

    Returns:
        SlackOutputResult with success status and agent output
    """
    import time

    handler = SlackOutputHandler(
        slack_context=slack_context,
        agent_name=agent_name,
        timeout=timeout,
        max_turns=max_turns,
    )

    start_time = time.time()

    try:
        # Post initial message
        message_ts = await handler.post_initial_message(message)

        # Set up hooks if showing progress
        hooks = SlackProgressHooks(handler) if show_progress else None

        # Run agent
        runner = Runner()

        result = await asyncio.wait_for(
            runner.run(
                agent,
                message,
                hooks=hooks,
                max_turns=max_turns,
            ),
            timeout=timeout,
        )

        duration = time.time() - start_time
        output = getattr(result, "final_output", None) or getattr(
            result, "output", None
        )
        tool_calls = getattr(hooks, "_tool_count", 0) if hooks else 0

        # Post final result
        await handler.post_final_result(
            output=output,
            success=True,
            duration_seconds=duration,
            tool_calls_count=tool_calls,
        )

        logger.info(
            "slack_agent_run_completed",
            agent_name=agent_name,
            duration=round(duration, 2),
            tool_calls=tool_calls,
        )

        return SlackOutputResult(
            success=True,
            message_ts=message_ts,
            agent_output=output,
        )

    except TimeoutError:
        duration = time.time() - start_time
        error_msg = f"Execution timed out after {timeout} seconds"

        await handler.post_final_result(
            output=None,
            success=False,
            error=error_msg,
            duration_seconds=duration,
        )

        return SlackOutputResult(
            success=False,
            message_ts=handler._message_ts,
            error=error_msg,
        )

    except Exception as e:
        duration = time.time() - start_time
        error_msg = str(e)

        logger.error(
            "slack_agent_run_failed",
            agent_name=agent_name,
            error=error_msg,
            exc_info=True,
        )

        await handler.post_final_result(
            output=None,
            success=False,
            error=error_msg,
            duration_seconds=duration,
        )

        return SlackOutputResult(
            success=False,
            message_ts=handler._message_ts,
            error=error_msg,
        )
