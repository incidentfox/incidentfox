"""
Core investigation flow handlers.

Handles @mentions, message events, SSE streaming orchestration,
auto-listen mode, and external alert integrations (Incident.io, Coralogix).
"""

import json
import logging
import os
import re
import threading
from typing import Dict, Optional

import requests

# Service-to-service auth token for sre-agent /investigate endpoint.
# Must match INVESTIGATE_AUTH_TOKEN on the sre-agent side.
SRE_AGENT_AUTH_TOKEN = os.environ.get("INVESTIGATE_AUTH_TOKEN", "")


def _sre_agent_headers() -> dict:
    """Build headers for sre-agent requests (SSE + service auth)."""
    headers = {"Accept": "text/event-stream"}
    if SRE_AGENT_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {SRE_AGENT_AUTH_TOKEN}"
    return headers


from file_handler import (
    _download_slack_image,
    _extract_file_attachments_from_event,
    _extract_images_from_event,
    _get_file_attachment_metadata,
)
from state import (
    MessageState,
    _auto_listen_threads,
    _cache_timestamps,
    _get_user_display_name,
    _investigation_cache,
    _persist_session_to_db,
    save_investigation_snapshot,
)
from stream_handler import (
    SRE_AGENT_URL,
    handle_stream_event,
    parse_sse_event,
    update_slack_message,
)

logger = logging.getLogger(__name__)

INCIDENT_IO_API_BASE = "https://api.incident.io"


def get_config_client():
    from config_client import get_config_client as _get_config_client

    return _get_config_client()


def get_onboarding_modules():
    import onboarding

    return onboarding


def _build_full_thread_context(messages, current_message_ts, bot_user_id, client):
    """
    Build full thread context from ALL messages in the thread.

    Includes every message (human and bot) with text, sender name, timestamp,
    and attachment annotations. Collects image metadata and file attachment
    metadata from non-triggering messages (images are NOT downloaded here —
    the caller decides which to download as base64 vs save as files).

    Args:
        messages: List of thread messages from conversations.replies
        current_message_ts: Timestamp of the current triggering message
        bot_user_id: Bot's user ID
        client: Slack client (for user name lookups)

    Returns:
        tuple: (formatted_text, thread_image_metadata, thread_file_attachments)
        - formatted_text: Full thread history with <thread_context> tags, or None
        - thread_image_metadata: List of dicts with Slack file info + semantic name
          for images from non-triggering messages (not yet downloaded)
        - thread_file_attachments: File attachment metadata from non-triggering messages
    """
    from datetime import datetime

    if not messages:
        return None, [], []

    # Check if there are any messages besides the triggering one
    other_messages = [m for m in messages if m.get("ts") != current_message_ts]
    if not other_messages:
        return None, [], []

    # Resolve user names via LRU-cached helper (avoids redundant API calls)
    def get_name(uid):
        return _get_user_display_name(client, uid)

    context_parts = []
    thread_image_metadata = []
    thread_file_attachments = []

    for msg in messages:
        ts = msg.get("ts", "0")
        is_trigger = ts == current_message_ts
        is_bot = bool(msg.get("bot_id")) or (
            bot_user_id and msg.get("user") == bot_user_id
        )

        # Format timestamp
        try:
            time_str = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
            date_prefix = datetime.fromtimestamp(float(ts)).strftime("%Y%m%d_%H%M")
        except (ValueError, TypeError, OSError, OverflowError):
            time_str = "??:??"
            date_prefix = "unknown"

        text = msg.get("text", "").strip()

        # Determine sender name
        if is_bot:
            sender = "IncidentFox"
            sender_slug = "IncidentFox"
            # Truncate long bot responses to keep context manageable
            # (agent already has its own responses in sandbox conversation history)
            if len(text) > 500:
                text = text[:500] + "... [response truncated]"
        else:
            uid = msg.get("user", "unknown")
            sender = get_name(uid)
            # Sanitize for filenames: keep alphanumeric, replace spaces with _
            sender_slug = re.sub(r"[^a-zA-Z0-9]", "_", sender).strip("_") or uid

        trigger_marker = "  <<< THIS MESSAGE TRIGGERED YOU" if is_trigger else ""

        line = f"[{time_str}] {sender}: {text}{trigger_marker}"

        # Annotate file attachments in the text
        files = msg.get("files", [])
        if files:
            file_descs = []
            for f in files:
                name = f.get("name", "file")
                mimetype = f.get("mimetype", "")
                if mimetype.startswith("image/"):
                    file_descs.append(f"{name} (image)")
                else:
                    file_descs.append(name)
            line += f"\n  Attachments: {', '.join(file_descs)}"

        context_parts.append(line)

        # Collect image metadata and file attachments from non-triggering messages
        # (triggering message's attachments are handled separately in the caller)
        if not is_trigger:
            for file_info in files:
                mimetype = file_info.get("mimetype", "")
                if mimetype.startswith("image/"):
                    # Collect metadata for images (caller decides base64 vs file)
                    original_name = file_info.get("name", "image")
                    semantic_name = f"{date_prefix}_{sender_slug}_{original_name}"
                    thread_image_metadata.append(
                        {
                            "file_info": file_info,
                            "semantic_name": semantic_name,
                            "sender": sender,
                            "time_str": time_str,
                        }
                    )
                else:
                    # Non-image files: collect as file_attachment metadata
                    attachment = _get_file_attachment_metadata(file_info, client)
                    if attachment:
                        thread_file_attachments.append(attachment)

    formatted = (
        "<thread_context>\n"
        "Full conversation history in this thread:\n\n"
        + "\n\n".join(context_parts)
        + "\n</thread_context>\n\n"
    )

    return formatted, thread_image_metadata, thread_file_attachments


def _resolve_mentions(text: str, client, bot_user_id: str):
    """
    Resolve all user and bot mentions in text to human-readable names.

    Converts: "<@U12345> can you ask <@B67890> about this?"
    To:       "@Jimmy Wei can you ask @IncidentFox Claude about this?"

    Returns:
        tuple: (resolved_text, id_to_name_mapping)
    """
    import re

    id_to_name = {}
    resolved_text = text

    # Find all mentions (users and bots)
    mentions = re.findall(r"<@([UBW][A-Z0-9]+)>", text)

    for user_or_bot_id in mentions:
        try:
            # Try users.info first (works for both users and bot users)
            response = client.users_info(user=user_or_bot_id)
            if response["ok"]:
                user = response["user"]
                if user.get("is_bot"):
                    # Bot user
                    name = (
                        user.get("profile", {}).get("display_name")
                        or user.get("real_name")
                        or user.get("name", "Unknown Bot")
                    )
                else:
                    # Regular user
                    profile = user.get("profile", {})
                    name = (
                        profile.get("display_name")
                        or profile.get("real_name")
                        or user.get("name", "Unknown User")
                    )

                id_to_name[user_or_bot_id] = name

                # Mark the bot itself
                if user_or_bot_id == bot_user_id:
                    id_to_name[user_or_bot_id] = f"{name} (you)"

                # Replace in text
                resolved_text = resolved_text.replace(
                    f"<@{user_or_bot_id}>", f"@{name}"
                )
        except Exception as e:
            logger.warning(f"Failed to resolve user/bot {user_or_bot_id}: {e}")
            # Keep the original mention if resolution fails
            id_to_name[user_or_bot_id] = f"User_{user_or_bot_id}"

    return resolved_text, id_to_name


def handle_mention(event, say, client, context):
    """
    Handle @mentions of the bot.

    Immediately ACKs by returning quickly, then processes in a background
    thread so Bolt's listener thread pool stays free for new events.
    """
    logger.info(
        f"🔔 APP_MENTION EVENT RECEIVED: channel={event.get('channel')}, user={event.get('user')}, ts={event.get('ts')}"
    )
    thread = threading.Thread(
        target=_handle_mention_impl,
        args=(event, say, client, context),
        daemon=True,
    )
    thread.start()


def _handle_mention_impl(event, say, client, context):
    """Process an app_mention event (runs in background thread)."""
    user_id = event["user"]
    text = event.get("text", "").strip()
    channel_id = event["channel"]
    team_id = event.get("team") or context.get("team_id", "unknown")

    # Check if trial has expired
    try:
        config_client = get_config_client()
        trial_info = config_client.get_trial_status(team_id)
        if trial_info and trial_info.get("expired"):
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=event.get("thread_ts") or event["ts"],
                text=(
                    ":warning: Your free trial has expired.\n\n"
                    "To continue using IncidentFox, please upgrade your plan. "
                    "Contact us at support@incidentfox.ai to get started."
                ),
            )
            logger.info(f"Trial expired for team {team_id}, skipping investigation")
            return
    except Exception as e:
        # Config service unreachable — log and continue.
        # The credential-proxy enforces trial expiration at runtime,
        # so this check is a UX guardrail, not a security gate.
        logger.warning(f"Failed to check trial status (continuing): {e}")

    # Thread context: use existing thread or create new one
    thread_ts = event.get("thread_ts") or event["ts"]
    message_ts = event["ts"]  # Current message timestamp

    # Generate thread_id for sre-agent (same for entire Slack thread)
    # Use thread_ts so all replies in the same thread route to the same sandbox
    # Sanitize for valid K8s DNS names (RFC 1123):
    sanitized_thread_ts = thread_ts.replace(".", "-")
    sanitized_channel = channel_id.lower()
    thread_id = f"slack-{sanitized_channel}-{sanitized_thread_ts}"

    # Get bot's own user ID (fallback to looking it up if not in context)
    bot_user_id = context.get("bot_user_id")
    if not bot_user_id:
        try:
            auth_response = client.auth_test()
            bot_user_id = auth_response.get("user_id")
        except Exception as e:
            logger.warning(f"Failed to get bot user ID: {e}")
            bot_user_id = None

    # Fetch full thread context when triggered in a thread.
    # Loads ALL messages (human + bot) so the agent sees the complete conversation,
    # and collects image metadata + file metadata from earlier messages in the thread.
    thread_context_text = None
    thread_image_metadata = []
    thread_file_attachments = []
    is_followup = event.get("thread_ts") is not None

    if is_followup:
        try:
            thread_replies = client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                limit=200,
            )
            thread_context_text, thread_image_metadata, thread_file_attachments = (
                _build_full_thread_context(
                    thread_replies.get("messages", []),
                    current_message_ts=event["ts"],
                    bot_user_id=bot_user_id,
                    client=client,
                )
            )
            if thread_context_text:
                logger.info(
                    f"Full thread context loaded for thread {thread_ts} "
                    f"({len(thread_image_metadata)} images, {len(thread_file_attachments)} files from thread)"
                )
        except Exception as e:
            logger.warning(f"Failed to fetch thread context: {e}")

    # Resolve all mentions (users and bots) to human-readable names
    resolved_text, id_to_name_mapping = _resolve_mentions(text, client, bot_user_id)

    # Extract images from the triggering event (downloaded as base64 - always inline)
    images = _extract_images_from_event(event, client)

    # Extract file attachment metadata from triggering event (not downloaded - uses proxy pattern)
    file_attachments = _extract_file_attachments_from_event(event, client)

    # app_mention events don't include files — look up the actual message
    if not images and not file_attachments:
        try:
            result = client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                limit=200,
            )
            for msg in result.get("messages", []):
                if msg.get("ts") == event["ts"]:
                    for file_info in msg.get("files", []):
                        mimetype = file_info.get("mimetype", "")
                        if mimetype.startswith("image/"):
                            img = _download_slack_image(file_info, client)
                            if img:
                                images.append(img)
                                logger.info(
                                    f"Image from message lookup: {img['filename']}"
                                )
                        else:
                            attachment = _get_file_attachment_metadata(
                                file_info, client
                            )
                            if attachment:
                                file_attachments.append(attachment)
                    break
        except Exception as e:
            logger.warning(f"Failed to look up files for app_mention: {e}")

    # Process thread images: last 5 as base64 (LLM sees directly), older ones
    # saved to sandbox as files with semantic filenames via the file_attachment proxy.
    # Claude API allows up to 100 images but 32MB total request, so 5 is practical.
    MAX_INLINE_THREAD_IMAGES = 5
    overflow_image_context = ""

    if thread_image_metadata:
        inline_meta = thread_image_metadata[-MAX_INLINE_THREAD_IMAGES:]
        overflow_meta = (
            thread_image_metadata[:-MAX_INLINE_THREAD_IMAGES]
            if len(thread_image_metadata) > MAX_INLINE_THREAD_IMAGES
            else []
        )

        # Download latest images as base64 for the LLM to see directly
        for meta in inline_meta:
            img = _download_slack_image(meta["file_info"], client, thumbnail_only=True)
            if img:
                images.insert(0, img)  # Thread images before triggering message's

        # Older images → file_attachment metadata (downloaded to sandbox with semantic names)
        for meta in overflow_meta:
            file_info = meta["file_info"]
            url = file_info.get("url_private_download") or file_info.get("url_private")
            if url:
                thread_file_attachments.append(
                    {
                        "filename": meta["semantic_name"],
                        "size": file_info.get("size", 0),
                        "media_type": file_info.get("mimetype", "image/png"),
                        "download_url": url,
                        "auth_header": f"Bearer {client.token}",
                    }
                )

        # Build context about overflow images so LLM knows where they are
        if overflow_meta:
            lines = [
                "\n**Earlier thread images (saved as files):**",
                "These images from earlier in the thread have been saved to your workspace.",
                "You can view them using the Read tool if needed:",
            ]
            for meta in overflow_meta:
                lines.append(
                    f"- `attachments/{meta['semantic_name']}` — from {meta['sender']} at {meta['time_str']}"
                )
            overflow_image_context = "\n".join(lines)

    # Merge thread file attachments with triggering message's
    file_attachments = thread_file_attachments + file_attachments

    # Get the user's name who sent this message (cached)
    sender_name = _get_user_display_name(client, user_id)

    # Remove bot's own mention from the resolved text
    # This handles all cases: "@Bot say hi", "say @Bot hi", "say hi @Bot"
    import re

    bot_mention_pattern = r"@[^@\s]+\s*\(you\)\s*"
    prompt_text = re.sub(bot_mention_pattern, "", resolved_text).strip()

    logger.info(f"Original text: {text}")
    logger.info(f"Resolved text: {resolved_text}")
    logger.info(f"Prompt (bot mention removed): {prompt_text}")
    logger.info(f"Sender: {sender_name} ({user_id})")
    logger.info(f"ID to name mapping: {id_to_name_mapping}")
    logger.info(f"Images attached: {len(images)}")
    logger.info(f"File attachments: {len(file_attachments)}")

    if (
        not prompt_text
        and not images
        and not file_attachments
        and not thread_context_text
    ):
        say(
            text="Hey! What would you like me to investigate?",
            thread_ts=thread_ts,
        )
        return

    # If prompt is empty but we have thread context, use a default prompt
    if not prompt_text and thread_context_text:
        prompt_text = "Based on the thread conversation above, how can I help?"

    # Build enriched prompt with Slack context
    context_lines = ["\n### Slack Context"]
    context_lines.append(f"**Requested by:** {sender_name} (User ID: {user_id})")

    if id_to_name_mapping:
        # Add context about users/bots mentioned in this conversation
        context_lines.append("\n**User/Bot ID to Name Mapping:**")
        for uid, name in id_to_name_mapping.items():
            context_lines.append(f"- {name}: {uid}")

        context_lines.append("\n**How to mention users/bots in your responses:**")
        context_lines.append(
            "To mention a user or bot in Slack, use this syntax: `<@USER_ID>`"
        )
        context_lines.append("Example: `Hey <@U012AB3CD>, thanks for your report.`")

    # Add info about file attachments (will be downloaded into sandbox)
    if file_attachments:
        context_lines.append("\n**File Attachments:**")
        context_lines.append(
            "The user attached the following files, which are being downloaded into your workspace:"
        )
        for att in file_attachments:
            filename = att["filename"]
            size_bytes = att["size"]
            if size_bytes >= 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                size_str = f"{size_bytes / 1024:.1f} KB"
            context_lines.append(f"- `attachments/{filename}` ({size_str})")
        context_lines.append("\nYou can read these files using the Read tool.")
        context_lines.append(
            "For large files still downloading, check `attachments/{filename}.progress` for status."
        )
        context_lines.append(
            "If download failed, check `attachments/{filename}.error` for details."
        )

    # Add info about including images in outputs
    context_lines.append("\n**Including Images in Your Response:**")
    context_lines.append(
        "If you create or save images (charts, diagrams, screenshots, etc.) during your analysis,"
    )
    context_lines.append(
        "you can include them in your response using standard markdown syntax:"
    )
    context_lines.append("  `![description](./path/to/image.png)`")
    context_lines.append(
        "Images saved in `/workspace/` will be automatically extracted and displayed to the user."
    )
    context_lines.append("Example: `![CPU usage chart](./output/cpu_chart.png)`")

    # Add info about sharing files with the user
    context_lines.append("\n**Sharing Files with the User:**")
    context_lines.append(
        "If you generate files the user might want to download (CSVs, reports, scripts, etc.),"
    )
    context_lines.append("you can share them using markdown link syntax:")
    context_lines.append("  `[description](./path/to/file.csv)`")
    context_lines.append(
        "Files in `/workspace/` will be automatically uploaded as Slack attachments."
    )
    context_lines.append("Maximum 10 files per response, 1GB per file.")
    context_lines.append(
        "IMPORTANT: Unlike images which display inline, file links are stripped from your text"
    )
    context_lines.append(
        "and uploaded as separate attachments. Place file links at the END of your response,"
    )
    context_lines.append(
        "not in the middle, so the text flows naturally after the links are removed."
    )
    context_lines.append("Example:")
    context_lines.append(
        "  Good: 'Here is your analysis report! [Report](./report.csv)'"
    )
    context_lines.append(
        "  Bad: 'I created [Report](./report.csv) for you. Let me explain...'"
    )
    context_lines.append("Only share files that are genuinely useful to the user.")

    # Add context about overflow images saved as files in sandbox
    if overflow_image_context:
        context_lines.append(overflow_image_context)

    enriched_prompt = prompt_text + "\n" + "\n".join(context_lines)

    # Prepend full thread context if available (all messages in the thread)
    if thread_context_text:
        enriched_prompt = thread_context_text + enriched_prompt

    # Post minimal initial message with loading indicator
    # Will be updated immediately with first event
    from assets_config import get_asset_url

    loading_url = get_asset_url("loading")

    # Build initial blocks with S3-hosted loading GIF
    initial_blocks = (
        [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "image",
                        "image_url": loading_url,
                        "alt_text": "Loading",
                    },
                    {"type": "mrkdwn", "text": "Investigating..."},
                ],
            }
        ]
        if loading_url
        else [
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "⏳ Investigating..."}],
            }
        ]
    )

    initial_response = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="Investigating...",
        blocks=initial_blocks,
    )

    message_ts = initial_response["ts"]

    # Initialize state
    state = MessageState(
        channel_id=channel_id,
        message_ts=message_ts,
        thread_ts=thread_ts,
        thread_id=thread_id,
    )

    # Enable auto-listen for this thread (bot will respond to follow-ups without @mention)
    _auto_listen_threads[(channel_id, thread_ts)] = True
    logger.info(f"🔔 Auto-listen enabled for thread {thread_ts} in {channel_id}")

    try:
        # Get team token and routing info for config-driven agents
        # Uses channel-based routing: checks if this channel maps to a specific team,
        # falls back to workspace-based routing ("default" team) if no mapping exists.
        routing_result = None
        try:
            config_client = get_config_client()
            routing_result = config_client.get_team_token_for_channel(
                team_id, channel_id
            )
        except Exception as e:
            logger.warning(f"Failed to get team token for {team_id}/{channel_id}: {e}")

        resolved_org_id = routing_result["org_id"] if routing_result else None
        resolved_team_node_id = (
            routing_result["team_node_id"] if routing_result else None
        )
        team_token = routing_result["token"] if routing_result else None

        # Build request payload with prompt and optional images
        request_payload = {
            "prompt": enriched_prompt,
            "thread_id": thread_id,
            "tenant_id": resolved_org_id,
            "team_id": resolved_team_node_id,
        }

        # Add team_token for config-driven agents (enables dynamic config loading)
        if team_token:
            request_payload["team_token"] = team_token

        # Add images if any were attached
        if images:
            # Format images for Claude Agent SDK (base64 format)
            request_payload["images"] = [
                {
                    "type": "base64",
                    "media_type": img["media_type"],
                    "data": img["data"],
                    "filename": img.get("filename", "image"),
                }
                for img in images
            ]
            logger.info(f"Sending {len(images)} image(s) to agent")

        # Add file attachments if any (metadata for proxy download)
        if file_attachments:
            request_payload["file_attachments"] = [
                {
                    "filename": att["filename"],
                    "size": att["size"],
                    "media_type": att["media_type"],
                    "download_url": att["download_url"],
                    "auth_header": att["auth_header"],
                }
                for att in file_attachments
            ]
            logger.info(
                f"Sending {len(file_attachments)} file attachment(s) to agent (via proxy)"
            )

        # Call sre-agent with SSE streaming
        response = requests.post(
            f"{SRE_AGENT_URL}/investigate",
            json=request_payload,
            stream=True,
            timeout=300,  # 5 minutes
            headers=_sre_agent_headers(),
        )

        if response.status_code != 200:
            error_detail = response.text[:200] if response.text else "Unknown error"
            state.error = f"Server error ({response.status_code}): {error_detail}"
            update_slack_message(client, state, team_id, final=True)
            return

        # Process SSE stream
        event_count = 0
        for line in response.iter_lines(decode_unicode=True):
            if line:
                event = parse_sse_event(line)
                if event:
                    event_count += 1
                    handle_stream_event(state, event, client, team_id)

        # Cache state for modal view (keyed by message_ts for per-message uniqueness)
        import time

        _investigation_cache[state.message_ts] = state
        _cache_timestamps[state.message_ts] = time.time()
        _persist_session_to_db(
            state, org_id=resolved_org_id, team_node_id=resolved_team_node_id
        )

        logger.info(
            f"✅ Investigation stream completed (processed {event_count} events, final_result={'present' if state.final_result else 'missing'})"
        )

        # If no events received, something went wrong
        if event_count == 0 and not state.error:
            state.error = "No response received from agent"

        # Final update with feedback buttons
        update_slack_message(client, state, team_id, final=True)
        logger.info("📝 Final update_slack_message called (final=True)")

        # Save snapshot for testing/debugging
        save_investigation_snapshot(state)
        logger.info("📸 Snapshot save attempted")

    except requests.exceptions.ChunkedEncodingError:
        logger.warning("Investigation stream interrupted (server may be restarting)")
        state.error = "Investigation was interrupted (service may be restarting). Please try again."
        update_slack_message(client, state, team_id, final=True)
    except requests.exceptions.ConnectionError:
        state.error = "Could not connect to investigation service. Is it running?"
        update_slack_message(client, state, team_id, final=True)
    except requests.exceptions.Timeout:
        state.error = "Investigation timed out (5 min limit). Try a simpler query?"
        update_slack_message(client, state, team_id, final=True)
    except Exception as e:
        logger.exception(f"Unexpected error during investigation: {e}")
        state.error = f"Unexpected error: {str(e)}"
        update_slack_message(client, state, team_id, final=True)


# Track threads where we've already sent a nudge (one nudge per user per thread)
# Key: (thread_ts, user_id), Value: True
_nudge_sent: Dict[tuple, bool] = {}


def _run_auto_listen_investigation(event, client, context):
    """
    Trigger an investigation for a message in an auto-listen thread.
    Called when a user sends a follow-up in a thread where the bot is actively
    listening (without requiring an @mention).
    """
    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts")
    user_id = event.get("user")

    if not user_id or not channel_id or not thread_ts:
        logger.warning("Auto-listen triggered with missing fields, skipping")
        return

    text = event.get("text", "")
    team_id = context.get("team_id") or "unknown"

    logger.info(
        f"🔔 Auto-listen investigation: user={user_id}, "
        f"thread={thread_ts}, text={text[:100]}"
    )

    # Check if trial has expired
    try:
        config_client = get_config_client()
        trial_info = config_client.get_trial_status(team_id)
        if trial_info and trial_info.get("expired"):
            logger.info(
                f"Trial expired for team {team_id}, "
                "skipping auto-listen investigation"
            )
            return
    except Exception as e:
        logger.warning(f"Failed to check trial status (continuing): {e}")

    # Generate thread_id for sre-agent
    sanitized_thread_ts = thread_ts.replace(".", "-")
    sanitized_channel = channel_id.lower()
    thread_id = f"slack-{sanitized_channel}-{sanitized_thread_ts}"

    # Get bot's user ID
    bot_user_id = context.get("bot_user_id")
    if not bot_user_id:
        try:
            auth_response = client.auth_test()
            bot_user_id = auth_response.get("user_id")
        except Exception as e:
            logger.warning(f"Failed to get bot user ID: {e}")

    # Fetch full thread context (all messages in the thread)
    thread_context_text = None
    thread_images = []
    thread_file_attachments = []
    try:
        thread_replies = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=200,
        )
        thread_context_text, thread_images, thread_file_attachments = (
            _build_full_thread_context(
                thread_replies.get("messages", []),
                current_message_ts=event["ts"],
                bot_user_id=bot_user_id,
                client=client,
            )
        )
        if thread_context_text:
            logger.info(
                f"Thread context loaded ({len(thread_images)} images, "
                f"{len(thread_file_attachments)} files)"
            )
    except Exception as e:
        logger.warning(f"Failed to fetch thread context: {e}")

    # Resolve mentions and extract attachments from triggering message
    resolved_text, id_to_name_mapping = _resolve_mentions(text, client, bot_user_id)
    images = _extract_images_from_event(event, client)
    file_attachments = _extract_file_attachments_from_event(event, client)

    # Download thread images (thread_images are metadata, not yet downloaded)
    MAX_INLINE_THREAD_IMAGES = 5
    if thread_images:
        inline_meta = thread_images[-MAX_INLINE_THREAD_IMAGES:]
        overflow_meta = (
            thread_images[:-MAX_INLINE_THREAD_IMAGES]
            if len(thread_images) > MAX_INLINE_THREAD_IMAGES
            else []
        )
        for meta in inline_meta:
            img = _download_slack_image(meta["file_info"], client, thumbnail_only=True)
            if img:
                images.insert(0, img)
        for meta in overflow_meta:
            file_info = meta["file_info"]
            url = file_info.get("url_private_download") or file_info.get("url_private")
            if url:
                thread_file_attachments.append(
                    {
                        "filename": meta["semantic_name"],
                        "size": file_info.get("size", 0),
                        "media_type": file_info.get("mimetype", "image/png"),
                        "download_url": url,
                        "auth_header": f"Bearer {client.token}",
                    }
                )

    # Merge thread file attachments with triggering message's
    file_attachments = thread_file_attachments + file_attachments

    # Get the user's name (cached)
    sender_name = _get_user_display_name(client, user_id)

    prompt_text = resolved_text.strip()

    if not prompt_text and not images and not file_attachments:
        return  # Nothing to investigate

    # Build enriched prompt with Slack context
    context_lines = ["\n### Slack Context"]
    context_lines.append(f"**Requested by:** {sender_name} (User ID: {user_id})")

    if id_to_name_mapping:
        context_lines.append("\n**User/Bot ID to Name Mapping:**")
        for uid, name in id_to_name_mapping.items():
            context_lines.append(f"- {name}: {uid}")
        context_lines.append("\n**How to mention users/bots in your responses:**")
        context_lines.append(
            "To mention a user or bot in Slack, use this syntax: `<@USER_ID>`"
        )

    if file_attachments:
        context_lines.append("\n**File Attachments:**")
        context_lines.append(
            "The user attached the following files, which are being "
            "downloaded into your workspace:"
        )
        for att in file_attachments:
            filename = att["filename"]
            size_bytes = att["size"]
            if size_bytes >= 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                size_str = f"{size_bytes / 1024:.1f} KB"
            context_lines.append(f"- `attachments/{filename}` ({size_str})")
        context_lines.append("\nYou can read these files using the Read tool.")

    context_lines.append("\n**Including Images in Your Response:**")
    context_lines.append("Use `![description](./path/to/image.png)` for images.")
    context_lines.append("\n**Sharing Files with the User:**")
    context_lines.append(
        "Use `[description](./path/to/file)` for files " "(place at end of response)."
    )

    enriched_prompt = prompt_text + "\n" + "\n".join(context_lines)

    # Prepend full thread context
    if thread_context_text:
        enriched_prompt = thread_context_text + enriched_prompt

    # Post initial "Investigating..." message
    from assets_config import get_asset_url

    loading_url = get_asset_url("loading")

    initial_blocks = (
        [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "image",
                        "image_url": loading_url,
                        "alt_text": "Loading",
                    },
                    {"type": "mrkdwn", "text": "Investigating..."},
                ],
            }
        ]
        if loading_url
        else [
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "⏳ Investigating..."}],
            }
        ]
    )

    try:
        initial_response = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Investigating...",
            blocks=initial_blocks,
        )
    except Exception as e:
        logger.error(f"Failed to post auto-listen message: {e}")
        return

    message_ts = initial_response["ts"]

    state = MessageState(
        channel_id=channel_id,
        message_ts=message_ts,
        thread_ts=thread_ts,
        thread_id=thread_id,
    )

    try:
        routing_result = None
        try:
            config_client = get_config_client()
            routing_result = config_client.get_team_token_for_channel(
                team_id, channel_id
            )
        except Exception as e:
            logger.warning(f"Failed to get team token: {e}")

        resolved_org_id = routing_result["org_id"] if routing_result else None
        resolved_team_node_id = (
            routing_result["team_node_id"] if routing_result else None
        )
        team_token = routing_result["token"] if routing_result else None

        request_payload = {
            "prompt": enriched_prompt,
            "thread_id": thread_id,
            "tenant_id": resolved_org_id,
            "team_id": resolved_team_node_id,
        }

        if team_token:
            request_payload["team_token"] = team_token

        if images:
            request_payload["images"] = [
                {
                    "type": "base64",
                    "media_type": img["media_type"],
                    "data": img["data"],
                    "filename": img.get("filename", "image"),
                }
                for img in images
            ]

        if file_attachments:
            request_payload["file_attachments"] = [
                {
                    "filename": att["filename"],
                    "size": att["size"],
                    "media_type": att["media_type"],
                    "download_url": att["download_url"],
                    "auth_header": att["auth_header"],
                }
                for att in file_attachments
            ]

        response = requests.post(
            f"{SRE_AGENT_URL}/investigate",
            json=request_payload,
            stream=True,
            timeout=300,
            headers=_sre_agent_headers(),
        )

        if response.status_code != 200:
            error_detail = response.text[:200] if response.text else "Unknown error"
            state.error = f"Server error ({response.status_code}): {error_detail}"
            update_slack_message(client, state, team_id, final=True)
            return

        event_count = 0
        for line in response.iter_lines(decode_unicode=True):
            if line:
                sse_event = parse_sse_event(line)
                if sse_event:
                    event_count += 1
                    handle_stream_event(state, sse_event, client, team_id)

        import time

        _investigation_cache[state.message_ts] = state
        _cache_timestamps[state.message_ts] = time.time()
        _persist_session_to_db(
            state, org_id=resolved_org_id, team_node_id=resolved_team_node_id
        )

        if event_count == 0 and not state.error:
            state.error = "No response received from agent"

        update_slack_message(client, state, team_id, final=True)
        save_investigation_snapshot(state)

    except requests.exceptions.ChunkedEncodingError:
        logger.warning(
            "Auto-listen investigation stream interrupted (server may be restarting)"
        )
        state.error = "Investigation was interrupted (service may be restarting). Please try again."
        update_slack_message(client, state, team_id, final=True)
    except requests.exceptions.ConnectionError:
        state.error = "Could not connect to investigation service. Is it running?"
        update_slack_message(client, state, team_id, final=True)
    except requests.exceptions.Timeout:
        state.error = "Investigation timed out (5 min limit). Try a simpler query?"
        update_slack_message(client, state, team_id, final=True)
    except Exception as e:
        logger.exception(f"Error during auto-listen investigation: {e}")
        state.error = f"Unexpected error: {str(e)}"
        update_slack_message(client, state, team_id, final=True)


def handle_stop_listening(ack, body, client):
    """Handle 'Stop listening' button click."""
    ack()

    value = json.loads(body["actions"][0]["value"])
    channel_id = value["channel_id"]
    thread_ts = value["thread_ts"]
    user_id = body["user"]["id"]

    # Disable auto-listen for this thread
    _auto_listen_threads.pop((channel_id, thread_ts), None)

    logger.info(f"🔇 Auto-listen disabled for thread {thread_ts} by user {user_id}")

    # Post a visible message in the thread
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="🔇 Stopped listening in this thread. @mention me to re-enable.",
    )


def fetch_incidentio_alert_details(
    description: str = None,
    deduplication_key: str = None,
    api_key: str = None,
) -> Optional[dict]:
    """
    Fetch alert details from Incident.io API.

    Args:
        description: Alert description to search for
        deduplication_key: Deduplication key from the alert
        api_key: incident.io API key (must be configured per-workspace via config-service)

    Returns:
        Alert details dict or None if not found or API unavailable
    """
    if not api_key:
        logger.info("No incident.io API key configured, skipping alert enrichment")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        # Build query parameters
        params = {
            "page_size": 10,
            "status[one_of]": "firing",  # Only get actively firing alerts
        }

        if deduplication_key:
            params["deduplication_key[is]"] = deduplication_key

        # Make API request
        response = requests.get(
            f"{INCIDENT_IO_API_BASE}/v2/alerts",
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code != 200:
            logger.error(
                f"Incident.io API error: {response.status_code} - {response.text}"
            )
            return None

        data = response.json()
        alerts = data.get("alerts", [])

        if not alerts:
            logger.info("No matching alerts found in Incident.io")
            return None

        # If we have a deduplication_key, return exact match
        if deduplication_key and len(alerts) > 0:
            return alerts[0]

        # Otherwise, try to match by description or return most recent
        if description and len(alerts) > 1:
            # Try to find alert matching description
            for alert in alerts:
                alert_title = alert.get("title", "").lower()
                alert_desc = alert.get("description", "").lower()
                desc_lower = description.lower()

                if desc_lower in alert_title or desc_lower in alert_desc:
                    return alert

        # Return most recent alert (first in list)
        return alerts[0]

    except requests.exceptions.Timeout:
        logger.error("Incident.io API request timed out")
        return None
    except Exception as e:
        logger.error(f"Error fetching Incident.io alert details: {e}", exc_info=True)
        return None


def _trigger_incident_io_investigation(event, client, context):
    """
    Helper function to trigger investigation for Incident.io alerts.
    Extracted from handle_message to be reusable.
    """
    # Extract alert details from Slack message
    text = event.get("text", "")
    blocks = event.get("blocks", [])
    channel_id = event.get("channel")
    message_ts = event.get("ts")

    alert_title = "Unknown Alert"
    alert_source = "Unknown Source"
    priority = "Unknown"
    deduplication_key = None

    # Parse from text
    if "New alert from" in text:
        parts = text.split("New alert from")
        if len(parts) > 1:
            alert_source = parts[1].strip()

    # Parse from blocks
    for block in blocks:
        block_type = block.get("type")

        # Look for text blocks
        if block_type == "section" and block.get("text"):
            block_text = block["text"].get("text", "")

            # Check for alert title (usually after the "New alert" line)
            if (
                block_text
                and "New alert" not in block_text
                and "Priority:" not in block_text
            ):
                alert_title = block_text.strip()

            # Check for priority
            if "Priority:" in block_text:
                priority_match = re.search(r"Priority:\s*(\w+)", block_text)
                if priority_match:
                    priority = priority_match.group(1)

    # Get workspace-specific incident.io API key from config-service
    team_id = event.get("team") or context.get("team_id")
    incidentio_api_key = None
    if team_id:
        try:
            config_client = get_config_client()
            incidentio_config = config_client.get_integration_config(
                team_id, "incident_io"
            )
            if incidentio_config and incidentio_config.get("api_key"):
                incidentio_api_key = incidentio_config["api_key"]
                logger.info(
                    f"Using workspace-configured incident.io API key for team {team_id}"
                )
            else:
                logger.info(f"No incident.io integration configured for team {team_id}")
        except Exception as e:
            logger.warning(f"Failed to get incident.io config from config-service: {e}")

    # Fetch enriched alert details from Incident.io API
    logger.info("Fetching alert details from Incident.io API...")
    incidentio_alert = fetch_incidentio_alert_details(
        description=alert_title,
        deduplication_key=deduplication_key,
        api_key=incidentio_api_key,
    )

    # Build enhanced context from Incident.io API
    enriched_context = []

    if incidentio_alert:
        logger.info(
            f"Enriched alert with Incident.io data: {incidentio_alert.get('id')}"
        )

        # Extract enriched details
        api_title = incidentio_alert.get("title", alert_title)
        api_description = incidentio_alert.get("description", "")
        api_source_url = incidentio_alert.get("source_url", "")
        api_status = incidentio_alert.get("status", "")
        api_created_at = incidentio_alert.get("created_at", "")
        api_dedup_key = incidentio_alert.get("deduplication_key", "")

        # Extract custom attributes
        api_attributes = incidentio_alert.get("attributes", [])

        enriched_context.append("\n### Enriched Alert Details from Incident.io\n")
        enriched_context.append(f"**Alert ID:** {incidentio_alert.get('id')}")
        enriched_context.append(f"**Title:** {api_title}")
        if api_description:
            enriched_context.append(f"**Description:** {api_description}")
        enriched_context.append(f"**Status:** {api_status}")
        if api_created_at:
            enriched_context.append(f"**Created At:** {api_created_at}")
        if api_source_url:
            enriched_context.append(f"**Source URL:** {api_source_url}")
        if api_dedup_key:
            enriched_context.append(f"**Deduplication Key:** {api_dedup_key}")

        # Include custom attributes if available
        if api_attributes:
            enriched_context.append("\n**Custom Attributes:**")
            for attr in api_attributes:
                attr_info = attr.get("attribute", {})
                attr_name = attr_info.get("name", "Unknown")

                # Get the value
                value_obj = attr.get("value", {})
                if "literal" in value_obj:
                    attr_value = value_obj["literal"]
                elif "label" in value_obj:
                    attr_value = value_obj["label"]
                elif "catalog_entry" in value_obj:
                    attr_value = value_obj["catalog_entry"].get("name", "Unknown")
                else:
                    attr_value = str(value_obj)

                enriched_context.append(f"- **{attr_name}:** {attr_value}")

        # Use enriched title if available
        if api_title:
            alert_title = api_title
    else:
        logger.info(
            "Could not enrich alert with Incident.io API (no matching alert found or API unavailable)"
        )

    # Construct investigation prompt
    investigation_prompt = f"""🚨 **New Alert from Incident.io**

**Source:** {alert_source}
**Alert:** {alert_title}
**Priority:** {priority}
{chr(10).join(enriched_context) if enriched_context else ""}

Please investigate this alert and provide:
1. Root cause analysis
2. Impact assessment  
3. Recommended remediation steps
4. Any relevant logs or metrics

Use all available tools to gather context about this issue."""

    logger.info(f"Triggering auto-investigation with prompt: {investigation_prompt}")

    # Get team_id for asset management
    team_id = event.get("team") or context.get("team_id", "unknown")

    # Get bot's user ID
    bot_user_id = context.get("bot_user_id")
    if not bot_user_id:
        try:
            auth_response = client.auth_test()
            bot_user_id = auth_response.get("user_id")
        except Exception as e:
            logger.warning(f"Failed to get bot user ID: {e}")

    # Thread context: start a new thread from this message
    thread_ts = message_ts  # Use the incident.io message as the thread root

    # Generate thread_id for sre-agent
    sanitized_thread_ts = thread_ts.replace(".", "-")
    sanitized_channel = channel_id.lower()
    thread_id = f"slack-{sanitized_channel}-{sanitized_thread_ts}"

    # Post initial investigation message
    from assets_config import get_asset_url

    loading_url = get_asset_url("loading")

    # Build initial blocks with S3-hosted loading GIF
    initial_blocks = (
        [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "image",
                        "image_url": loading_url,
                        "alt_text": "Loading",
                    },
                    {"type": "mrkdwn", "text": "Investigating alert..."},
                ],
            }
        ]
        if loading_url
        else [
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "⏳ Investigating alert..."}],
            }
        ]
    )

    initial_response = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="Investigating alert...",
        blocks=initial_blocks,
    )

    response_message_ts = initial_response["ts"]

    # Initialize state
    state = MessageState(
        channel_id=channel_id,
        message_ts=response_message_ts,
        thread_ts=thread_ts,
        thread_id=thread_id,
    )

    # Enable auto-listen for this thread (users can follow up without @mention)
    _auto_listen_threads[(channel_id, thread_ts)] = True
    logger.info(f"🔔 Auto-listen enabled for alert thread {thread_ts} in {channel_id}")

    try:
        # Get team token and routing info for config-driven agents
        routing_result = None
        try:
            config_client = get_config_client()
            routing_result = config_client.get_team_token_for_channel(
                team_id, channel_id
            )
        except Exception as e:
            logger.warning(f"Failed to get team token for {team_id}/{channel_id}: {e}")

        resolved_org_id = routing_result["org_id"] if routing_result else None
        resolved_team_node_id = (
            routing_result["team_node_id"] if routing_result else None
        )
        team_token = routing_result["token"] if routing_result else None

        # Call sre-agent to investigate
        request_payload = {
            "prompt": investigation_prompt,
            "thread_id": thread_id,
            "tenant_id": resolved_org_id,
            "team_id": resolved_team_node_id,
        }

        # Add team_token for config-driven agents
        if team_token:
            request_payload["team_token"] = team_token

        response = requests.post(
            f"{SRE_AGENT_URL}/investigate",
            json=request_payload,
            stream=True,
            timeout=300,
            headers=_sre_agent_headers(),
        )

        if response.status_code != 200:
            error_detail = response.text[:200] if response.text else "Unknown error"
            state.error = f"Server error ({response.status_code}): {error_detail}"
            update_slack_message(client, state, team_id, final=True)
            return

        # Process SSE stream
        event_count = 0
        for line in response.iter_lines(decode_unicode=True):
            if line:
                sse_event = parse_sse_event(line)
                if sse_event:
                    event_count += 1
                    handle_stream_event(state, sse_event, client, team_id)

        # Cache state for modal view (keyed by message_ts for per-message uniqueness)
        import time

        _investigation_cache[state.message_ts] = state
        _cache_timestamps[state.message_ts] = time.time()
        _persist_session_to_db(
            state, org_id=resolved_org_id, team_node_id=resolved_team_node_id
        )

        logger.info(
            f"✅ Auto-investigation completed for Incident.io alert (processed {event_count} events, final_result={'present' if state.final_result else 'missing'})"
        )

        # If no events received, something went wrong
        if event_count == 0 and not state.error:
            state.error = "No response received from agent"

        # Final update with feedback buttons
        update_slack_message(client, state, team_id, final=True)
        logger.info("📝 Final update_slack_message called (final=True)")

        # Save snapshot for testing/debugging
        save_investigation_snapshot(state)
        logger.info("📸 Snapshot save attempted")

    except requests.exceptions.ChunkedEncodingError:
        logger.warning(
            "Auto-investigation stream interrupted (server may be restarting)"
        )
        state.error = "Investigation was interrupted (service may be restarting). Please try again."
        update_slack_message(client, state, team_id, final=True)
    except requests.exceptions.Timeout:
        logger.error("Request to sre-agent timed out")
        state.error = "Investigation timed out after 5 minutes"
        update_slack_message(client, state, team_id, final=True)
    except requests.exceptions.RequestException as e:
        logger.error(f"Request to sre-agent failed: {e}")
        state.error = f"Failed to connect to investigation service: {str(e)}"
        update_slack_message(client, state, team_id, final=True)
    except Exception as e:
        logger.error(f"Unexpected error during auto-investigation: {e}", exc_info=True)
        state.error = f"Unexpected error: {str(e)}"
        update_slack_message(client, state, team_id, final=True)


def handle_message(event, client, context):
    """
    Handle regular messages (not @mentions).

    Special cases:
    - Auto-trigger investigation for Incident.io alerts
    - Auto-listen: respond to follow-ups in threads where the bot is active
    - Coralogix insight detection: prompt to investigate shared links
    """
    # DEBUG: Log EVERY message event received - this should print for ALL messages
    logger.info("=" * 60)
    logger.info("📨 MESSAGE EVENT RECEIVED")
    logger.info(f"   type={event.get('type')}")
    logger.info(f"   subtype={event.get('subtype')}")
    logger.info(f"   channel={event.get('channel')}")
    logger.info(f"   channel_type={event.get('channel_type')}")
    logger.info(f"   user={event.get('user')}")
    logger.info(f"   bot_id={event.get('bot_id')}")
    logger.info(f"   text={event.get('text', '')[:100]}")
    logger.info("=" * 60)

    # ============================================================================
    # DM HANDLING - First-time welcome, help command, and investigations
    # ============================================================================
    channel_type = event.get("channel_type")
    if channel_type == "im":
        user_id = event.get("user")
        team_id = context.get("team_id")
        channel_id = event.get("channel")
        dm_text = event.get("text", "").strip()

        # Skip bot's own messages
        if event.get("bot_id"):
            return

        # Handle help command first
        if dm_text.lower() == "help":
            try:
                onboarding = get_onboarding_modules()
                help_blocks = onboarding.build_help_message()
                client.chat_postMessage(
                    channel=channel_id,
                    text="IncidentFox Help",
                    blocks=help_blocks,
                )
                logger.info(f"Sent help message to user {user_id}")
            except Exception as e:
                logger.warning(f"Failed to send help message: {e}")
            return  # Don't process further

        # Check if this is first-time DM (no previous bot messages in this channel)
        is_first_time = False
        try:
            history = client.conversations_history(channel=channel_id, limit=10)
            bot_has_messaged = any(
                msg.get("bot_id") for msg in history.get("messages", [])
            )

            if not bot_has_messaged:
                # First interaction! Send welcome message
                is_first_time = True
                onboarding = get_onboarding_modules()
                config_client = get_config_client()
                trial_info = (
                    config_client.get_trial_status(team_id) if team_id else None
                )
                welcome_blocks = onboarding.build_dm_welcome_message(trial_info)
                client.chat_postMessage(
                    channel=channel_id,
                    text="Welcome to IncidentFox!",
                    blocks=welcome_blocks,
                )
                logger.info(f"Sent first-time DM welcome to user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to check/send DM welcome: {e}")

        # If this is first-time and message is empty/short greeting, don't investigate
        if is_first_time and dm_text.lower() in ["hi", "hello", "hey", ""]:
            return

        # Check if trial has expired before proceeding with investigation
        try:
            config_client = get_config_client()
            trial_info = config_client.get_trial_status(team_id)
            if trial_info and trial_info.get("expired"):
                client.chat_postMessage(
                    channel=channel_id,
                    text=(
                        ":warning: Your free trial has expired.\n\n"
                        "To continue using IncidentFox, please upgrade your plan. "
                        "Contact us at support@incidentfox.ai to get started."
                    ),
                )
                logger.info(
                    f"Trial expired for team {team_id}, skipping DM investigation"
                )
                return
        except Exception as e:
            # Config service unreachable — log and continue.
            # The credential-proxy enforces trial expiration at runtime.
            logger.warning(f"Failed to check trial status for DM (continuing): {e}")

        # Continue to DM investigation below
        # (Extract images, build prompt, trigger investigation)
        logger.info(f"🔵 DM INVESTIGATION: user={user_id}, text={dm_text[:100]}")

        # Thread context: DMs use message timestamp as thread
        thread_ts = event.get("thread_ts") or event["ts"]
        message_ts = event["ts"]

        # Generate thread_id for DM (use channel ID which is unique per DM)
        sanitized_thread_ts = thread_ts.replace(".", "-")
        sanitized_channel = channel_id.lower()
        thread_id = f"slack-dm-{sanitized_channel}-{sanitized_thread_ts}"

        # Get bot's own user ID
        bot_user_id = context.get("bot_user_id")
        if not bot_user_id:
            try:
                auth_response = client.auth_test()
                bot_user_id = auth_response.get("user_id")
            except Exception as e:
                logger.warning(f"Failed to get bot user ID: {e}")
                bot_user_id = None

        # Fetch full thread context for DM threads
        thread_context_text = None
        thread_image_metadata = []
        thread_file_attachments = []
        is_dm_thread = event.get("thread_ts") is not None

        if is_dm_thread:
            try:
                thread_replies = client.conversations_replies(
                    channel=channel_id,
                    ts=thread_ts,
                    limit=200,
                )
                thread_context_text, thread_image_metadata, thread_file_attachments = (
                    _build_full_thread_context(
                        thread_replies.get("messages", []),
                        current_message_ts=event["ts"],
                        bot_user_id=bot_user_id,
                        client=client,
                    )
                )
                if thread_context_text:
                    logger.info(
                        f"Full DM thread context loaded for thread {thread_ts} "
                        f"({len(thread_image_metadata)} images, {len(thread_file_attachments)} files)"
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch DM thread context: {e}")

        # Resolve mentions in DM text (if any)
        resolved_text, id_to_name_mapping = _resolve_mentions(
            dm_text, client, bot_user_id
        )

        # Extract images from the triggering event (always inline)
        images = _extract_images_from_event(event, client)

        # Extract file attachments from the triggering event
        file_attachments = _extract_file_attachments_from_event(event, client)

        # Process thread images: last 5 as base64, older ones saved as files
        MAX_INLINE_THREAD_IMAGES = 5
        overflow_image_context = ""

        if thread_image_metadata:
            inline_meta = thread_image_metadata[-MAX_INLINE_THREAD_IMAGES:]
            overflow_meta = (
                thread_image_metadata[:-MAX_INLINE_THREAD_IMAGES]
                if len(thread_image_metadata) > MAX_INLINE_THREAD_IMAGES
                else []
            )

            for meta in inline_meta:
                img = _download_slack_image(
                    meta["file_info"], client, thumbnail_only=True
                )
                if img:
                    images.insert(0, img)

            for meta in overflow_meta:
                file_info = meta["file_info"]
                url = file_info.get("url_private_download") or file_info.get(
                    "url_private"
                )
                if url:
                    thread_file_attachments.append(
                        {
                            "filename": meta["semantic_name"],
                            "size": file_info.get("size", 0),
                            "media_type": file_info.get("mimetype", "image/png"),
                            "download_url": url,
                            "auth_header": f"Bearer {client.token}",
                        }
                    )

            if overflow_meta:
                lines = [
                    "\n**Earlier thread images (saved as files):**",
                    "These images from earlier in the thread have been saved to your workspace.",
                    "You can view them using the Read tool if needed:",
                ]
                for meta in overflow_meta:
                    lines.append(
                        f"- `attachments/{meta['semantic_name']}` — from {meta['sender']} at {meta['time_str']}"
                    )
                overflow_image_context = "\n".join(lines)

        # Merge thread file attachments with triggering message's
        file_attachments = thread_file_attachments + file_attachments

        # Get sender's name (cached)
        sender_name = _get_user_display_name(client, user_id)

        prompt_text = resolved_text.strip()

        if not prompt_text and not images and not file_attachments:
            client.chat_postMessage(
                channel=channel_id,
                text="What would you like me to help you investigate?",
                thread_ts=thread_ts,
            )
            return

        # Build enriched prompt with DM context
        context_lines = ["\n### Slack Context"]
        context_lines.append(f"**Requested by:** {sender_name} (User ID: {user_id})")
        context_lines.append("**Channel:** Private DM with IncidentFox")
        context_lines.append(
            "\nThis is a private one-on-one conversation. The user is messaging you directly "
            "in a DM rather than in a public channel."
        )

        if id_to_name_mapping:
            context_lines.append("\n**User/Bot ID to Name Mapping:**")
            for uid, name in id_to_name_mapping.items():
                context_lines.append(f"- {name}: {uid}")

        # Add file attachments context
        if file_attachments:
            context_lines.append("\n**File Attachments:**")
            context_lines.append(
                "The user attached the following files, which are being downloaded into your workspace:"
            )
            for att in file_attachments:
                filename = att["filename"]
                size_bytes = att["size"]
                if size_bytes >= 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                context_lines.append(f"- `attachments/{filename}` ({size_str})")
            context_lines.append("\nYou can read these files using the Read tool.")

        # Add image/file sharing context
        context_lines.append("\n**Including Images in Your Response:**")
        context_lines.append(
            "If you create images during analysis, include them using: `![description](./path/to/image.png)`"
        )
        context_lines.append("\n**Sharing Files with the User:**")
        context_lines.append(
            "If you generate files, share them using: `[description](./path/to/file.csv)`"
        )

        # Add context about overflow images saved as files in sandbox
        if overflow_image_context:
            context_lines.append(overflow_image_context)

        enriched_prompt = prompt_text + "\n" + "\n".join(context_lines)

        # Prepend full thread context if available (all messages in the DM thread)
        if thread_context_text:
            enriched_prompt = thread_context_text + enriched_prompt

        # Post initial message
        from assets_config import get_asset_url

        loading_url = get_asset_url("loading")

        initial_blocks = (
            [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "image",
                            "image_url": loading_url,
                            "alt_text": "Loading",
                        },
                        {"type": "mrkdwn", "text": "Investigating..."},
                    ],
                }
            ]
            if loading_url
            else [
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "⏳ Investigating..."}],
                }
            ]
        )

        initial_response = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Investigating...",
            blocks=initial_blocks,
        )

        response_message_ts = initial_response["ts"]

        # Initialize state
        state = MessageState(
            channel_id=channel_id,
            message_ts=response_message_ts,
            thread_ts=thread_ts,
            thread_id=thread_id,
        )

        try:
            # Get team token and routing info for config-driven agents
            # For DMs, channel routing won't match, falls back to workspace-based routing
            routing_result = None
            try:
                config_client = get_config_client()
                routing_result = config_client.get_team_token_for_channel(
                    team_id, channel_id
                )
            except Exception as e:
                logger.warning(
                    f"Failed to get team token for {team_id}/{channel_id}: {e}"
                )

            resolved_org_id = routing_result["org_id"] if routing_result else None
            resolved_team_node_id = (
                routing_result["team_node_id"] if routing_result else None
            )
            team_token = routing_result["token"] if routing_result else None

            # Build request payload
            request_payload = {
                "prompt": enriched_prompt,
                "thread_id": thread_id,
                "tenant_id": resolved_org_id,
                "team_id": resolved_team_node_id,
            }

            # Add team_token for config-driven agents
            if team_token:
                request_payload["team_token"] = team_token

            # Add images if present
            if images:
                request_payload["images"] = [
                    {
                        "type": "base64",
                        "media_type": img["media_type"],
                        "data": img["data"],
                        "filename": img.get("filename", "image"),
                    }
                    for img in images
                ]
                logger.info(f"Sending {len(images)} image(s) to agent (DM)")

            # Add file attachments if present
            if file_attachments:
                request_payload["file_attachments"] = [
                    {
                        "filename": att["filename"],
                        "size": att["size"],
                        "media_type": att["media_type"],
                        "download_url": att["download_url"],
                        "auth_header": att["auth_header"],
                    }
                    for att in file_attachments
                ]
                logger.info(
                    f"Sending {len(file_attachments)} file attachment(s) to agent (DM)"
                )

            # Call sre-agent with SSE streaming
            response = requests.post(
                f"{SRE_AGENT_URL}/investigate",
                json=request_payload,
                stream=True,
                timeout=300,  # 5 minutes
                headers=_sre_agent_headers(),
            )

            if response.status_code != 200:
                error_detail = response.text[:200] if response.text else "Unknown error"
                state.error = f"Server error ({response.status_code}): {error_detail}"
                update_slack_message(client, state, team_id, final=True)
                return

            # Process SSE stream
            event_count = 0
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    event = parse_sse_event(line)
                    if event:
                        event_count += 1
                        handle_stream_event(state, event, client, team_id)

            # Cache state for modal view (keyed by message_ts for per-message uniqueness)
            import time

            _investigation_cache[state.message_ts] = state
            _cache_timestamps[state.message_ts] = time.time()
            _persist_session_to_db(
                state, org_id=resolved_org_id, team_node_id=resolved_team_node_id
            )

            logger.info(
                f"✅ DM investigation completed (processed {event_count} events)"
            )

            # If no events received, something went wrong
            if event_count == 0 and not state.error:
                state.error = "No response received from agent"

            # Final update with feedback buttons
            update_slack_message(client, state, team_id, final=True)

            # Save snapshot
            save_investigation_snapshot(state)

        except requests.exceptions.ChunkedEncodingError:
            logger.warning(
                "DM investigation stream interrupted (server may be restarting)"
            )
            state.error = "Investigation was interrupted (service may be restarting). Please try again."
            update_slack_message(client, state, team_id, final=True)
        except requests.exceptions.ConnectionError:
            state.error = "Could not connect to investigation service. Is it running?"
            update_slack_message(client, state, team_id, final=True)
        except requests.exceptions.Timeout:
            state.error = "Investigation timed out (5 min limit). Try a simpler query?"
            update_slack_message(client, state, team_id, final=True)
        except Exception as e:
            logger.exception(f"Unexpected error during DM investigation: {e}")
            state.error = f"Unexpected error: {str(e)}"
            update_slack_message(client, state, team_id, final=True)

        return  # DM handled, don't process further

    # ============================================================================
    # INCIDENT.IO ALERT DETECTION - Check for "New alert" messages from bots
    # ============================================================================
    subtype = event.get("subtype")
    bot_id = event.get("bot_id")
    text = event.get("text", "")

    # Check if this is a "New alert from" message (from any bot)
    # Incident.io alerts have this pattern regardless of which bot posts them
    if bot_id and "New alert from" in text:
        logger.info(f"🚨 Detected 'New alert from' message from bot: {bot_id}")

        blocks = event.get("blocks", [])

        # Confirm this looks like an Incident.io alert
        is_new_alert = "New alert from" in text or any(
            "New alert" in str(block.get("text", {})) for block in blocks
        )

        if is_new_alert:
            # Check if trial has expired - silently skip auto-investigation
            team_id = context.get("team_id")
            try:
                config_client = get_config_client()
                trial_info = config_client.get_trial_status(team_id)
                if trial_info and trial_info.get("expired"):
                    logger.info(
                        f"Trial expired for team {team_id}, skipping auto-investigation"
                    )
                    return
            except Exception as e:
                logger.warning(
                    f"Failed to check trial status for alert (continuing): {e}"
                )

            logger.info("✅ Confirmed: NEW ALERT - triggering investigation")
            threading.Thread(
                target=_trigger_incident_io_investigation,
                args=(event, client, context),
                daemon=True,
            ).start()
            return
        else:
            logger.info("ℹ️  Has bot_id but not a new alert pattern")

    # ============================================================================
    # END INCIDENT.IO DETECTION
    # ============================================================================

    # ============================================================================
    # CORALOGIX INSIGHTS URL DETECTION - Prompt user to investigate
    # ============================================================================
    # Pattern: https://*.coralogix.com/#/insights?id=...
    coralogix_pattern = r"https?://[^\s]*coralogix\.com[^\s]*#/insights\?id=[a-f0-9-]+"
    coralogix_match = re.search(coralogix_pattern, text)

    if coralogix_match:
        coralogix_url = coralogix_match.group(0)
        logger.info(f"🔗 Detected Coralogix insights URL: {coralogix_url}")

        user_id = event.get("user")
        channel_id = event.get("channel")
        message_ts = event.get("ts")
        thread_ts = event.get("thread_ts")  # None if top-level message

        # Don't prompt for bot messages (only human-shared links)
        if not bot_id and user_id:
            # Get bot's user ID for checking mentions
            bot_user_id = context.get("bot_user_id")

            # Skip if user mentioned the bot (will be handled by app_mention handler)
            if bot_user_id and f"<@{bot_user_id}>" in text:
                logger.info(
                    "⏭️  Skipping Coralogix nudge - bot was @mentioned, app_mention handler will trigger investigation"
                )
                # Don't return here - let the message continue through normal processing
            else:
                # Check if we've already prompted for this URL
                prompt_key = (message_ts, coralogix_url)
                if not _nudge_sent.get(prompt_key):
                    logger.info(
                        f"📨 Sending Coralogix investigation prompt to {user_id} (thread_ts={thread_ts})"
                    )

                    # Build the ephemeral message kwargs
                    ephemeral_kwargs = {
                        "channel": channel_id,
                        "user": user_id,
                        "text": "Would you like me to investigate this Coralogix insight?",
                    }

                    # Only add thread_ts if we're actually in a thread
                    if thread_ts:
                        ephemeral_kwargs["thread_ts"] = thread_ts

                    # For the button values, use the thread or message ts
                    response_thread_ts = thread_ts or message_ts

                    ephemeral_kwargs["blocks"] = [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "🔍 I noticed you shared a Coralogix insight. Would you like me to investigate it?",
                            },
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"_{coralogix_url[:80]}{'...' if len(coralogix_url) > 80 else ''}_",
                                }
                            ],
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {
                                        "type": "plain_text",
                                        "text": "Yes, investigate",
                                    },
                                    "style": "primary",
                                    "action_id": "coralogix_investigate",
                                    "value": json.dumps(
                                        {
                                            "channel_id": channel_id,
                                            "thread_ts": response_thread_ts,
                                            "user_id": user_id,
                                            "url": coralogix_url,
                                            "text": text,
                                        }
                                    ),
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "No thanks"},
                                    "action_id": "coralogix_dismiss",
                                    "value": json.dumps(
                                        {
                                            "thread_ts": response_thread_ts,
                                            "url": coralogix_url,
                                        }
                                    ),
                                },
                            ],
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"_Or mention <@{bot_user_id}> with your question._",
                                }
                            ],
                        },
                    ]

                    try:
                        result = client.chat_postEphemeral(**ephemeral_kwargs)
                        logger.info(f"✅ Ephemeral message sent: {result.get('ok')}")

                        # Mark that we've prompted for this URL
                        _nudge_sent[prompt_key] = True

                    except Exception as e:
                        logger.error(
                            f"❌ Failed to send Coralogix investigation prompt: {e}",
                            exc_info=True,
                        )

        # Don't return here - let the message continue through normal processing

    # ============================================================================
    # END CORALOGIX DETECTION
    # ============================================================================

    # Skip subtypes (message edits, bot_message, etc.) — but allow file_share
    # (file_share = user sent a message with an image/file attachment)
    if subtype and subtype != "file_share":
        return

    # Skip bot messages (prevents infinite loop in auto-listen threads)
    if event.get("bot_id"):
        return

    # Only handle threaded messages (not top-level channel messages)
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return

    user_id = event.get("user")
    if not user_id:
        return

    channel_id = event.get("channel")
    text = event.get("text", "")

    # Skip if user mentioned the bot (will be handled by app_mention handler)
    bot_user_id = context.get("bot_user_id")
    if bot_user_id and f"<@{bot_user_id}>" in text:
        return

    # Auto-listen: if this thread has auto-listen enabled, trigger investigation directly
    if _auto_listen_threads.get((channel_id, thread_ts)):
        logger.info(
            f"🔔 Auto-listen triggered for thread {thread_ts} by user {user_id}"
        )
        threading.Thread(
            target=_run_auto_listen_investigation,
            args=(event, client, context),
            daemon=True,
        ).start()


def handle_coralogix_investigate(ack, body, client, context, respond):
    """Handle 'Yes, investigate' button for Coralogix insights."""
    ack()

    # Delete the ephemeral message
    respond({"delete_original": True})

    # Parse the value
    value = json.loads(body["actions"][0]["value"])
    channel_id = value["channel_id"]
    thread_ts = value["thread_ts"]
    user_id = value["user_id"]
    coralogix_url = value["url"]
    original_text = value.get("text", "")

    logger.info(f"🔍 Coralogix investigation requested by {user_id}: {coralogix_url}")

    # Get team_id
    team_id = body.get("team", {}).get("id") or "unknown"

    # Get the user's name (cached)
    sender_name = _get_user_display_name(client, user_id)

    # Generate thread_id
    sanitized_thread_ts = thread_ts.replace(".", "-")
    sanitized_channel = channel_id.lower()
    thread_id = f"slack-{sanitized_channel}-{sanitized_thread_ts}"

    # Build investigation prompt with Coralogix context
    investigation_prompt = f"""🔍 **Coralogix Insight Investigation**

**URL:** {coralogix_url}
**Shared by:** {sender_name}
**Original message:** {original_text[:500] if original_text else 'No additional context'}

Please investigate this Coralogix insight and provide:
1. What is this insight showing?
2. What is the root cause or pattern identified?
3. What is the impact?
4. Recommended actions or remediation steps

Use the Coralogix tools to fetch details about this insight and gather relevant logs/metrics."""

    logger.info("Triggering Coralogix investigation with prompt")

    # Post initial "Investigating..." message
    from assets_config import get_asset_url

    loading_url = get_asset_url("loading")

    # Build initial blocks with context
    trigger_context = {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"🔗 Investigating Coralogix insight (requested by <@{user_id}>)",
            }
        ],
    }

    if loading_url:
        initial_blocks = [
            trigger_context,
            {
                "type": "context",
                "elements": [
                    {
                        "type": "image",
                        "image_url": loading_url,
                        "alt_text": "Loading",
                    },
                    {"type": "mrkdwn", "text": "Investigating..."},
                ],
            },
        ]
    else:
        initial_blocks = [
            trigger_context,
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "⏳ Investigating..."}],
            },
        ]

    try:
        initial_response = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Investigating Coralogix insight (requested by <@{user_id}>)...",
            blocks=initial_blocks,
        )
    except Exception as e:
        logger.error(f"Failed to post initial message: {e}")
        return

    message_ts = initial_response["ts"]

    # Initialize state
    state = MessageState(
        channel_id=channel_id,
        message_ts=message_ts,
        thread_ts=thread_ts,
        thread_id=thread_id,
        trigger_user_id=user_id,
        trigger_text=original_text,
    )

    # Enable auto-listen for this thread
    _auto_listen_threads[(channel_id, thread_ts)] = True
    logger.info(
        f"🔔 Auto-listen enabled for Coralogix thread {thread_ts} in {channel_id}"
    )

    try:
        # Get team token and routing info for config-driven agents
        routing_result = None
        try:
            config_client = get_config_client()
            routing_result = config_client.get_team_token_for_channel(
                team_id, channel_id
            )
        except Exception as e:
            logger.warning(f"Failed to get team token for {team_id}/{channel_id}: {e}")

        resolved_org_id = routing_result["org_id"] if routing_result else None
        resolved_team_node_id = (
            routing_result["team_node_id"] if routing_result else None
        )
        team_token = routing_result["token"] if routing_result else None

        # Call sre-agent to investigate
        request_payload = {
            "prompt": investigation_prompt,
            "thread_id": thread_id,
            "tenant_id": resolved_org_id,
            "team_id": resolved_team_node_id,
        }

        # Add team_token for config-driven agents
        if team_token:
            request_payload["team_token"] = team_token

        response = requests.post(
            f"{SRE_AGENT_URL}/investigate",
            json=request_payload,
            stream=True,
            timeout=300,
            headers=_sre_agent_headers(),
        )

        if response.status_code != 200:
            error_detail = response.text[:200] if response.text else "Unknown error"
            state.error = f"Server error ({response.status_code}): {error_detail}"
            update_slack_message(client, state, team_id, final=True)
            return

        # Process SSE stream
        event_count = 0
        for line in response.iter_lines(decode_unicode=True):
            if line:
                sse_event = parse_sse_event(line)
                if sse_event:
                    event_count += 1
                    handle_stream_event(state, sse_event, client, team_id)

        # Cache state for modal view (keyed by message_ts for per-message uniqueness)
        import time

        _investigation_cache[state.message_ts] = state
        _cache_timestamps[state.message_ts] = time.time()
        _persist_session_to_db(
            state, org_id=resolved_org_id, team_node_id=resolved_team_node_id
        )

        logger.info(
            f"✅ Coralogix investigation completed (processed {event_count} events, final_result={'present' if state.final_result else 'missing'})"
        )

        # If no events received, something went wrong
        if event_count == 0 and not state.error:
            state.error = "No response received from agent"

        # Final update with feedback buttons
        update_slack_message(client, state, team_id, final=True)
        logger.info("📝 Final update_slack_message called (final=True)")

        # Save snapshot for testing/debugging
        save_investigation_snapshot(state)
        logger.info("📸 Snapshot save attempted")

    except requests.exceptions.ChunkedEncodingError:
        logger.warning(
            "Coralogix investigation stream interrupted (server may be restarting)"
        )
        state.error = "Investigation was interrupted (service may be restarting). Please try again."
        update_slack_message(client, state, team_id, final=True)
    except requests.exceptions.Timeout:
        logger.error("Request to sre-agent timed out")
        state.error = "Investigation timed out after 5 minutes"
        update_slack_message(client, state, team_id, final=True)
    except requests.exceptions.RequestException as e:
        logger.error(f"Request to sre-agent failed: {e}")
        state.error = f"Failed to connect to investigation service: {str(e)}"
        update_slack_message(client, state, team_id, final=True)
    except Exception as e:
        logger.error(
            f"Unexpected error during Coralogix investigation: {e}", exc_info=True
        )
        state.error = f"Unexpected error: {str(e)}"
        update_slack_message(client, state, team_id, final=True)


def handle_coralogix_dismiss(ack, body, respond):
    """Handle 'No thanks' button for Coralogix insights."""
    ack()

    # Delete the ephemeral message
    respond({"delete_original": True})

    # Parse the value
    value = json.loads(body["actions"][0]["value"])
    url = value["url"]

    logger.info(f"Coralogix investigation dismissed for: {url[:50]}...")
