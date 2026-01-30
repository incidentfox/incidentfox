"""
Recall.ai Meeting Transcript Summary Poster.

Posts and updates transcript summaries to Slack threads where the meeting
bot was invited. Summaries are auto-updated as new transcript segments arrive.

Architecture:
- When transcripts arrive via webhook, we batch them and periodically update
  a single summary message in the original Slack thread
- The summary message is created on first transcript and updated on subsequent ones
- Updates are debounced to avoid rate limiting (minimum 30s between updates)
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx


def _log(event: str, **fields: Any) -> None:
    """Structured logging."""
    try:
        payload = {
            "service": "orchestrator",
            "component": "recall_summary",
            "event": event,
            **fields,
        }
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


# Minimum time between summary updates (debounce)
SUMMARY_UPDATE_DEBOUNCE_SECONDS = 30

# Maximum number of transcript lines to show in summary
MAX_TRANSCRIPT_LINES = 50


class RecallSummaryPoster:
    """
    Posts transcript summaries to Slack threads.

    This class handles:
    1. Creating initial summary message when first transcript arrives
    2. Updating summary message as new transcripts arrive (debounced)
    3. Building Block Kit message with formatted transcript
    """

    def __init__(
        self,
        *,
        config_service_client: Any,
        admin_token: str,
        slack_bot_token: Optional[str] = None,
    ):
        self.config_service = config_service_client
        self.admin_token = admin_token
        self.slack_bot_token = slack_bot_token or os.getenv("SLACK_BOT_TOKEN", "")

    async def post_or_update_summary(
        self,
        recall_bot_id: str,
        bot_info: Dict[str, Any],
    ) -> Optional[str]:
        """
        Post or update the transcript summary in Slack.

        Args:
            recall_bot_id: The Recall.ai bot ID
            bot_info: Bot record from database

        Returns:
            The Slack message timestamp (ts) if posted/updated, None otherwise
        """
        slack_channel_id = bot_info.get("slack_channel_id")
        slack_thread_ts = bot_info.get("slack_thread_ts")
        slack_summary_ts = bot_info.get("slack_summary_ts")
        last_summary_at = bot_info.get("last_summary_at")

        if not slack_channel_id or not slack_thread_ts:
            _log(
                "recall_summary_no_slack_thread",
                recall_bot_id=recall_bot_id,
            )
            return None

        if not self.slack_bot_token:
            _log(
                "recall_summary_no_slack_token",
                recall_bot_id=recall_bot_id,
            )
            return None

        # Check debounce - don't update too frequently
        if last_summary_at:
            if isinstance(last_summary_at, str):
                last_summary_at = datetime.fromisoformat(
                    last_summary_at.replace("Z", "+00:00")
                )
            if last_summary_at.tzinfo:
                last_summary_at = last_summary_at.replace(tzinfo=None)
            seconds_since_update = (datetime.utcnow() - last_summary_at).total_seconds()
            if seconds_since_update < SUMMARY_UPDATE_DEBOUNCE_SECONDS:
                _log(
                    "recall_summary_debounced",
                    recall_bot_id=recall_bot_id,
                    seconds_since_update=seconds_since_update,
                )
                return slack_summary_ts

        # Fetch transcript segments
        segments_response = await asyncio.to_thread(
            self.config_service.get_recall_transcript_segments,
            admin_token=self.admin_token,
            recall_bot_id=recall_bot_id,
            limit=MAX_TRANSCRIPT_LINES * 2,  # Fetch extra in case of filtering
        )
        segments = segments_response.get("segments", [])

        if not segments:
            _log(
                "recall_summary_no_segments",
                recall_bot_id=recall_bot_id,
            )
            return slack_summary_ts

        # Build the summary message
        blocks = self._build_summary_blocks(
            segments=segments,
            meeting_url=bot_info.get("meeting_url", ""),
            bot_status=bot_info.get("status", "unknown"),
            total_segments=bot_info.get("transcript_segments_count", len(segments)),
        )

        try:
            if slack_summary_ts:
                # Update existing message
                message_ts = await self._update_slack_message(
                    channel_id=slack_channel_id,
                    message_ts=slack_summary_ts,
                    blocks=blocks,
                )
                _log(
                    "recall_summary_updated",
                    recall_bot_id=recall_bot_id,
                    channel_id=slack_channel_id,
                    message_ts=message_ts,
                )
            else:
                # Post new message
                message_ts = await self._post_slack_message(
                    channel_id=slack_channel_id,
                    thread_ts=slack_thread_ts,
                    blocks=blocks,
                )
                _log(
                    "recall_summary_posted",
                    recall_bot_id=recall_bot_id,
                    channel_id=slack_channel_id,
                    message_ts=message_ts,
                )

            # Update the bot record with the summary message timestamp
            if message_ts:
                await asyncio.to_thread(
                    self.config_service.update_recall_bot_slack_summary,
                    admin_token=self.admin_token,
                    recall_bot_id=recall_bot_id,
                    slack_summary_ts=message_ts,
                )

            return message_ts

        except Exception as e:
            _log(
                "recall_summary_slack_error",
                recall_bot_id=recall_bot_id,
                error=str(e),
            )
            return slack_summary_ts

    def _build_summary_blocks(
        self,
        segments: List[Dict[str, Any]],
        meeting_url: str,
        bot_status: str,
        total_segments: int,
    ) -> List[Dict[str, Any]]:
        """
        Build Slack Block Kit blocks for the transcript summary.
        """
        # Status indicator
        if bot_status in ("recording", "in_call"):
            status_emoji = ":red_circle:"
            status_text = "Recording in progress"
        elif bot_status == "done":
            status_emoji = ":white_check_mark:"
            status_text = "Recording complete"
        else:
            status_emoji = ":hourglass_flowing_sand:"
            status_text = f"Status: {bot_status}"

        blocks: List[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Meeting Transcript",
                    "emoji": True,
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"{status_emoji} {status_text} | {total_segments} segments",
                    }
                ],
            },
            {"type": "divider"},
        ]

        # Format transcript lines
        # Group consecutive segments by speaker for cleaner display
        grouped_lines = self._group_by_speaker(segments[-MAX_TRANSCRIPT_LINES:])

        transcript_text = ""
        for speaker, texts in grouped_lines:
            speaker_display = speaker if speaker else "Unknown"
            combined_text = " ".join(texts)
            # Truncate long text
            if len(combined_text) > 300:
                combined_text = combined_text[:297] + "..."
            transcript_text += f"*{speaker_display}:* {combined_text}\n\n"

        # Slack has a 3000 char limit per text block
        if len(transcript_text) > 2900:
            transcript_text = transcript_text[:2897] + "..."

        if transcript_text:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": transcript_text.strip(),
                    },
                }
            )
        else:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "_No transcript content yet..._",
                    },
                }
            )

        # Footer with meeting URL
        if meeting_url:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"<{meeting_url}|Join Meeting> | _Updated {datetime.utcnow().strftime('%H:%M:%S UTC')}_",
                        }
                    ],
                }
            )

        return blocks

    def _group_by_speaker(
        self, segments: List[Dict[str, Any]]
    ) -> List[tuple[str, List[str]]]:
        """
        Group consecutive segments by speaker.

        Returns list of (speaker, [texts]) tuples.
        """
        if not segments:
            return []

        grouped = []
        current_speaker = segments[0].get("speaker")
        current_texts = [segments[0].get("text", "")]

        for segment in segments[1:]:
            speaker = segment.get("speaker")
            text = segment.get("text", "")

            if speaker == current_speaker:
                current_texts.append(text)
            else:
                grouped.append((current_speaker, current_texts))
                current_speaker = speaker
                current_texts = [text]

        # Don't forget the last group
        grouped.append((current_speaker, current_texts))

        return grouped

    async def _post_slack_message(
        self,
        channel_id: str,
        thread_ts: str,
        blocks: List[Dict[str, Any]],
    ) -> Optional[str]:
        """
        Post a new message to Slack.

        Returns the message timestamp (ts) if successful.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {self.slack_bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={
                    "channel": channel_id,
                    "thread_ts": thread_ts,
                    "text": "Meeting Transcript",
                    "blocks": blocks,
                },
            )
            data = response.json()

            if not data.get("ok"):
                raise Exception(f"Slack API error: {data.get('error', 'unknown')}")

            return data.get("ts")

    async def _update_slack_message(
        self,
        channel_id: str,
        message_ts: str,
        blocks: List[Dict[str, Any]],
    ) -> Optional[str]:
        """
        Update an existing Slack message.

        Returns the message timestamp (ts) if successful.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://slack.com/api/chat.update",
                headers={
                    "Authorization": f"Bearer {self.slack_bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={
                    "channel": channel_id,
                    "ts": message_ts,
                    "text": "Meeting Transcript",
                    "blocks": blocks,
                },
            )
            data = response.json()

            if not data.get("ok"):
                # If message_not_found, the original was deleted - post a new one
                if data.get("error") == "message_not_found":
                    _log(
                        "recall_summary_message_not_found",
                        channel_id=channel_id,
                        message_ts=message_ts,
                    )
                    return None
                raise Exception(f"Slack API error: {data.get('error', 'unknown')}")

            return data.get("ts")


async def post_transcript_summary(
    config_service_client: Any,
    admin_token: str,
    recall_bot_id: str,
    bot_info: Dict[str, Any],
    slack_bot_token: Optional[str] = None,
) -> Optional[str]:
    """
    Convenience function to post/update a transcript summary.

    Args:
        config_service_client: ConfigServiceClient instance
        admin_token: Admin token for API calls
        recall_bot_id: Recall.ai bot ID
        bot_info: Bot record from database
        slack_bot_token: Optional Slack bot token override

    Returns:
        The Slack message timestamp if posted/updated, None otherwise
    """
    poster = RecallSummaryPoster(
        config_service_client=config_service_client,
        admin_token=admin_token,
        slack_bot_token=slack_bot_token,
    )
    return await poster.post_or_update_summary(recall_bot_id, bot_info)
