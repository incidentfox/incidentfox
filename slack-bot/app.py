#!/usr/bin/env python3
"""
IncidentFox Slack Bot

Connects Slack to sre-agent for AI-powered incident investigation.
Uses chat.update for progressive disclosure UI with Block Kit.

Version: 2.0.0 - SSE streaming with structured events
"""

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, Optional

import requests
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize app with timeout
from slack_sdk import WebClient

# Create WebClient with timeout
web_client = WebClient(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    timeout=30,  # 30 second timeout for all API calls
)

app = App(
    client=web_client,
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)

# SRE Agent configuration
SRE_AGENT_URL = os.environ.get("SRE_AGENT_URL", "http://localhost:8000")

# Incident.io API configuration
INCIDENT_IO_API_KEY = os.environ.get("INCIDENT_IO_API_KEY")
INCIDENT_IO_API_BASE = "https://api.incident.io"

# Rate limit updates to avoid Slack API throttling
UPDATE_INTERVAL_SECONDS = 0.5


@dataclass
class ThoughtSection:
    """A thought and its associated tool calls."""

    text: str
    tools: list = field(
        default_factory=list
    )  # Tool dicts: name, input, success, output
    completed: bool = False


@dataclass
class MessageState:
    """Tracks the state of a Slack message during investigation."""

    channel_id: str
    message_ts: str
    thread_ts: str
    thread_id: str

    # Hierarchical structure: thoughts with nested tools
    thoughts: list = field(default_factory=list)  # List of ThoughtSection
    current_tool: Optional[dict] = None  # Tool currently running

    # Final state
    final_result: Optional[str] = None
    result_images: Optional[list] = (
        None  # [{path, data, media_type, alt, file_id?}, ...]
    )
    result_files: Optional[list] = (
        None  # [{path, filename, description, media_type, file_id?}, ...]
    )
    error: Optional[str] = None

    # Chronological timeline for modal view (thoughts + tools interwoven)
    timeline: list = field(default_factory=list)

    # Tracking
    last_update_time: float = 0

    # Trigger context (for nudge-initiated investigations)
    trigger_user_id: Optional[str] = None  # Who clicked "Yes" on the nudge
    trigger_text: Optional[str] = None  # The message that triggered it

    # Subagent tracking
    # Key: tool_use_id of Task tool, Value: {description, subagent_type, completed, tools: [...]}
    subagents: Dict[str, dict] = field(default_factory=dict)

    @property
    def current_thought(self) -> str:
        """Get the current (last) thought text."""
        if self.thoughts:
            return self.thoughts[-1].text
        return ""

    @property
    def current_thought_section(self) -> Optional["ThoughtSection"]:
        """Get the current (last) thought section."""
        if self.thoughts:
            return self.thoughts[-1]
        return None

    @property
    def completed_tools(self) -> list:
        """Get all completed tools across all thoughts (for backward compat)."""
        tools = []
        for thought in self.thoughts:
            tools.extend(thought.tools)
        return tools


# In-memory cache for investigation state (for modal views)
# In production: use Redis keyed by thread_id
_investigation_cache: Dict[str, MessageState] = {}
_cache_timestamps: Dict[str, float] = {}  # Track when entries were added
CACHE_TTL_HOURS = 24  # Keep cache entries for 24 hours


def _cleanup_old_cache_entries():
    """Remove cache entries older than CACHE_TTL_HOURS."""
    import time

    now = time.time()
    ttl_seconds = CACHE_TTL_HOURS * 3600
    expired_keys = []

    for key, timestamp in _cache_timestamps.items():
        if now - timestamp > ttl_seconds:
            expired_keys.append(key)

    for key in expired_keys:
        _investigation_cache.pop(key, None)
        _cache_timestamps.pop(key, None)
        logger.info(f"Cleaned up expired cache entry: {key}")

    if expired_keys:
        logger.info(
            f"Cache cleanup: removed {len(expired_keys)} expired entries, {len(_investigation_cache)} remaining"
        )


def save_investigation_snapshot(state: MessageState):
    """Save investigation state to file for testing/debugging."""
    # Check if snapshot recording is enabled (default: disabled for production)
    if os.getenv("ENABLE_SNAPSHOTS", "false").lower() not in ("true", "1", "yes"):
        return

    try:
        # Create snapshots directory
        snapshots_dir = os.path.join(
            os.path.dirname(__file__), "tests", "snapshots", "data"
        )
        os.makedirs(snapshots_dir, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"investigation_{timestamp}_{state.thread_id[-8:]}.json"
        filepath = os.path.join(snapshots_dir, filename)

        # Convert MessageState to dict (recursively handle dataclasses)
        def to_serializable(obj):
            if hasattr(obj, "__dict__"):
                return {k: to_serializable(v) for k, v in obj.__dict__.items()}
            elif isinstance(obj, list):
                return [to_serializable(item) for item in obj]
            elif isinstance(obj, dict):
                return {k: to_serializable(v) for k, v in obj.items()}
            else:
                return obj

        snapshot = {
            "captured_at": datetime.now().isoformat(),
            "thread_id": state.thread_id,
            "state": to_serializable(state),
        }

        # Save to file
        with open(filepath, "w") as f:
            json.dump(snapshot, f, indent=2)

        logger.info(f"📸 Saved investigation snapshot: {filepath}")
        logger.info(
            f"   Thoughts: {len(state.thoughts)}, Final result: {bool(state.final_result)}"
        )

        return filepath
    except Exception as e:
        logger.warning(f"Failed to save investigation snapshot: {e}")
        return None


def parse_sse_event(event_type: Optional[str], line: str) -> tuple[Optional[str], Optional[dict]]:
    """Parse SSE lines and return (event_type, data_dict)."""
    # Parse event type line
    if line.startswith("event: "):
        return (line[7:].strip(), None)

    # Parse data line
    if line.startswith("data: "):
        try:
            data = json.loads(line[6:])
            # Return complete event with type and data
            if event_type:
                return (None, {"type": event_type, "data": data})
        except json.JSONDecodeError:
            pass

    return (event_type, None)


def build_progress_blocks(state: MessageState, client, team_id: str) -> list:
    """Build Block Kit blocks for in-progress state."""
    from asset_manager import get_asset_file_id
    from message_builder import build_progress_message

    # Get Slack-hosted assets (uploads on first use)
    try:
        loading_file_id = get_asset_file_id(client, team_id, "loading")
    except Exception as e:
        logger.warning(f"Failed to load asset: {e}")
        loading_file_id = None

    try:
        done_file_id = get_asset_file_id(client, team_id, "done")
    except Exception as e:
        logger.warning(f"Failed to load asset: {e}")
        done_file_id = None

    return build_progress_message(
        thoughts=state.thoughts,
        current_tool=state.current_tool,
        loading_file_id=loading_file_id,
        done_file_id=done_file_id,
        thread_id=state.thread_id,
        trigger_user_id=state.trigger_user_id,
        trigger_text=state.trigger_text,
    )


def build_final_blocks(state: MessageState, client, team_id: str) -> list:
    """Build Block Kit blocks for final state."""
    from asset_manager import get_asset_file_id
    from message_builder import build_final_message

    # Get Slack-hosted done icon
    try:
        done_file_id = get_asset_file_id(client, team_id, "done")
    except Exception as e:
        logger.warning(f"Failed to load asset: {e}")
        done_file_id = None

    return build_final_message(
        result_text=state.final_result or state.current_thought,
        thoughts=state.thoughts,
        success=state.error is None,
        error=state.error,
        done_file_id=done_file_id,
        thread_id=state.thread_id,
        result_images=state.result_images,
        result_files=state.result_files,
        trigger_user_id=state.trigger_user_id,
        trigger_text=state.trigger_text,
    )


def update_slack_message(
    client, state: MessageState, team_id: str, final: bool = False
):
    """Update the Slack message with current state."""
    import time

    # ALWAYS cache state for modal access (even if we skip the message update)
    _investigation_cache[state.thread_id] = state
    _cache_timestamps[state.thread_id] = time.time()
    logger.info(
        f"Cached investigation state for thread_id: {state.thread_id} (final={final}, thoughts={len(state.thoughts)})"
    )

    # Rate limit message updates (except for final)
    now = time.time()
    if not final and (now - state.last_update_time) < UPDATE_INTERVAL_SECONDS:
        logger.debug("Skipping message update (rate limited), but cache updated")
        return
    state.last_update_time = now

    # Cleanup old cache entries periodically (only on final updates to avoid overhead)
    if final:
        _cleanup_old_cache_entries()

    # Get fallback text
    if state.error:
        text = f"❌ Error: {state.error}"
    elif state.final_result:
        text = (
            state.final_result[:200] + "..."
            if len(state.final_result or "") > 200
            else state.final_result
        )
    elif state.current_thought:
        text = state.current_thought[:200] + "..."
    else:
        text = "🔄 Processing..."

    # For final updates with images: use progressive enhancement strategy
    if final and state.result_images:
        _update_with_progressive_images(client, state, team_id, text)
    else:
        # Regular update without images
        try:
            if final:
                blocks = build_final_blocks(state, client, team_id)
            else:
                blocks = build_progress_blocks(state, client, team_id)

            logger.debug(
                f"Calling chat.update with {len(blocks)} blocks (final={final})"
            )
            client.chat_update(
                channel=state.channel_id,
                ts=state.message_ts,
                blocks=blocks,
                text=text,
            )
            logger.info(f"✅ chat.update succeeded (final={final})")
        except Exception as e:
            logger.error(f"Failed to update message: {e}")


def _update_with_progressive_images(
    client, state: MessageState, team_id: str, text: str
):
    """
    Progressive enhancement strategy for images:
    1. First update: text only (no images) - immediate, no delay
    2. First image attempt after short delay
    3. Final "settlement" re-render after longer delay to fix broken image renders

    Key insight: Slack's chat.update may accept blocks with slack_file but still
    render a broken image if files aren't propagated. We can't detect this from
    the API response, so we always do a final re-render to force the frontend
    to re-fetch the (now-ready) images.
    """
    import time

    logger.info(
        f"🚀 Starting progressive image update for {len(state.result_images)} images"
    )

    # Step 1: Immediate update with text only (strip images)
    original_images = state.result_images
    state.result_images = None  # Temporarily strip images

    try:
        blocks = build_final_blocks(state, client, team_id)
        client.chat_update(
            channel=state.channel_id,
            ts=state.message_ts,
            blocks=blocks,
            text=text,
        )
        logger.info("✅ Initial text-only update succeeded")
    except Exception as e:
        logger.error(f"Failed text-only update: {e}")
        # Restore images for modal
        state.result_images = original_images
        return

    # Step 2: Image updates with re-renders
    state.result_images = original_images  # Restore images

    # Determine if we need delays (only for newly uploaded images)
    newly_uploaded = [
        img for img in state.result_images if not img.get("reused", False)
    ]

    def do_image_update(attempt_name: str) -> bool:
        """Try to update with images. Returns True if API accepted (might still render broken)."""
        try:
            blocks = build_final_blocks(state, client, team_id)
            client.chat_update(
                channel=state.channel_id,
                ts=state.message_ts,
                blocks=blocks,
                text=text,
            )
            logger.info(f"✅ {attempt_name} - API accepted")
            return True
        except Exception as e:
            error_str = str(e)
            if (
                "invalid_blocks" in error_str.lower()
                and "slack_file" in error_str.lower()
            ):
                logger.warning(f"⚠️ {attempt_name} - slack_file rejected: {e}")
            else:
                logger.error(f"❌ {attempt_name} - error: {e}")
            return False

    if newly_uploaded:
        # New images need propagation time
        # Schedule: 2s (first attempt) + 5s (settlement re-render)
        logger.info(f"📤 {len(newly_uploaded)} newly uploaded images need propagation")

        # First attempt - might show broken image
        time.sleep(2.0)
        first_success = do_image_update("First image attempt (2s)")

        if first_success:
            # API accepted, but image might still be broken due to propagation
            # Do a "settlement" re-render after more time to force frontend refresh
            time.sleep(5.0)
            do_image_update("Settlement re-render (7s total)")
        else:
            # API rejected - retry with longer delays
            for delay, attempt in [(3.0, 2), (5.0, 3)]:
                time.sleep(delay)
                if do_image_update(f"Retry attempt {attempt}"):
                    # Success - do one more settlement re-render
                    time.sleep(3.0)
                    do_image_update(f"Settlement after retry {attempt}")
                    return

            logger.warning(
                "⚠️ All image retries exhausted - images available in modal only"
            )
    else:
        # All images reused - should work immediately, but do a settlement just in case
        logger.info(f"♻️ All {len(state.result_images)} images reused from Read tools")

        first_success = do_image_update("Reused images (immediate)")

        if first_success:
            # Even for reused images, do a quick settlement re-render
            time.sleep(2.0)
            do_image_update("Settlement for reused images")
        else:
            logger.warning("⚠️ Reused images failed - unexpected")


def build_question_blocks(questions: list, thread_id: str) -> list:
    """Build interactive Block Kit blocks for AskUserQuestion."""
    blocks = []

    for q_idx, q in enumerate(questions):
        question_text = q.get("question", "")
        header = q.get("header", "Question")
        options = q.get("options", [])
        multi_select = q.get("multiSelect", False)

        # Question header
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{header}*\n{question_text}"},
            }
        )

        # Option buttons (toggleable) - use checkboxes for multi-select, buttons for single-select
        if options:
            if multi_select:
                # Checkboxes for multi-select (can be deselected)
                blocks.append(
                    {
                        "type": "actions",
                        "block_id": f"question_{q_idx}",
                        "elements": [
                            {
                                "type": "checkboxes",
                                "action_id": f"answer_q{q_idx}_{thread_id}",
                                "options": [
                                    {
                                        "text": {
                                            "type": "plain_text",
                                            "text": opt["label"],
                                        },
                                        "description": {
                                            "type": "plain_text",
                                            "text": opt.get("description", ""),
                                        },
                                        "value": opt["label"],
                                    }
                                    for opt in options
                                ],
                            }
                        ],
                    }
                )
            else:
                # For single-select, use buttons that can be toggled
                # We'll track state in message metadata
                button_elements = []
                for opt_idx, opt in enumerate(options):
                    button_elements.append(
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": opt["label"]},
                            "action_id": f"toggle_q{q_idx}_opt{opt_idx}_{thread_id}",
                            "value": f"{q_idx}:{opt['label']}",
                        }
                    )

                blocks.append(
                    {
                        "type": "actions",
                        "block_id": f"question_{q_idx}",
                        "elements": button_elements,
                    }
                )

        # Text input for "Other"
        blocks.append(
            {
                "type": "input",
                "block_id": f"text_{q_idx}",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": f"text_q{q_idx}_{thread_id}",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Add a comment or type your own answer...",
                    },
                },
                "label": {"type": "plain_text", "text": "Comment (optional)"},
            }
        )

        blocks.append({"type": "divider"})

    # Submit button
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Submit"},
                    "style": "primary",
                    "action_id": f"submit_answer_{thread_id}",
                    "value": thread_id,
                }
            ],
        }
    )

    return blocks


def handle_stream_event(state: MessageState, event: dict, client, team_id: str):
    """Process a single SSE event and update state."""
    event_type = event.get("type")
    data = event.get("data", {})

    if event_type == "thought":
        # New thought = new section
        text = data.get("text", "")
        if text:
            # Mark previous thought as completed
            if state.thoughts:
                state.thoughts[-1].completed = True

            # Create new thought section
            state.thoughts.append(ThoughtSection(text=text))

            # Add to timeline
            state.timeline.append({"type": "thought", "text": text})
            update_slack_message(client, state, team_id)

    elif event_type == "tool_start":
        # New tool starting - capture full input for display
        tool_input = data.get("input", {})
        tool_name = data.get("name", "Unknown")
        tool_use_id = data.get("tool_use_id")
        parent_tool_use_id = data.get(
            "parent_tool_use_id"
        )  # Set if this tool is within a subagent

        tool_data = {
            "name": tool_name,
            "tool_use_id": tool_use_id,  # Unique ID for matching with tool_end
            "parent_tool_use_id": parent_tool_use_id,  # Parent subagent's Task tool_use_id
            "input": tool_input,
            "running": True,
            # Extract key fields for quick display
            "command": tool_input.get("command"),
            "file_path": tool_input.get("file_path"),
            "pattern": tool_input.get("pattern"),
            "description": tool_input.get("description"),
        }

        # If this is a Task tool, track it as a subagent
        if tool_name == "Task" and tool_use_id:
            state.subagents[tool_use_id] = {
                "description": tool_input.get("description", "Subagent task"),
                "subagent_type": tool_input.get("subagent_type", "general-purpose"),
                "completed": False,
                "tools": [],  # Tools executed within this subagent
            }
            logger.info(
                f"🤖 Subagent started: {tool_use_id} - {tool_input.get('description', 'task')}"
            )

        # If this tool has a parent (is within a subagent), add it to the subagent's tools
        if parent_tool_use_id and parent_tool_use_id in state.subagents:
            state.subagents[parent_tool_use_id]["tools"].append(tool_data)

        # Ensure we have a thought section (edge case: tools before thoughts)
        if not state.thoughts:
            state.thoughts.append(ThoughtSection(text="Investigating..."))
            state.timeline.append({"type": "thought", "text": "Investigating..."})

        # Add tool to current thought section
        state.thoughts[-1].tools.append(tool_data)
        state.current_tool = tool_data
        update_slack_message(client, state, team_id)

    elif event_type == "tool_end":
        # Tool completed - update in thought section by matching tool_use_id
        tool_name = data.get("name", "Unknown")
        tool_use_id = data.get("tool_use_id")
        tool_output = data.get("output")
        logger.info(
            f"tool_end received: name={tool_name}, tool_use_id={tool_use_id}, thoughts_count={len(state.thoughts)}"
        )

        # Check if output contains an image (e.g., from Read tool on image files)
        if _is_image_output(tool_output):
            logger.info(
                f"Tool {tool_name} output contains an image - uploading to Slack"
            )
            # Get filename from tool input if available
            tool_input = (
                state.current_tool.get("input", {}) if state.current_tool else {}
            )
            file_path = tool_input.get("file_path", "image")
            filename = file_path.split("/")[-1] if "/" in file_path else file_path

            # Upload image to Slack (kept private - no public URL)
            # Image will show as emoji in main message, full image in modal
            file_id = _upload_image_to_slack(
                tool_output, client, state.channel_id, state.thread_ts, filename
            )
            if file_id:
                data["_image_file_id"] = file_id
                logger.info(f"Image uploaded (private): file_id={file_id}")

        if state.thoughts:
            # Find and update the tool by tool_use_id (or by name as fallback)
            found = False
            for thought in state.thoughts:
                for tool in thought.tools:
                    # Match by tool_use_id if available, otherwise fall back to name
                    if tool_use_id and tool.get("tool_use_id") == tool_use_id:
                        tool["running"] = False
                        tool["success"] = data.get("success", True)
                        tool["summary"] = data.get("summary")
                        tool["output"] = data.get("output")
                        tool["_image_file_id"] = data.get("_image_file_id")
                        found = True
                        logger.info(
                            f"Updated tool {tool_name} (id={tool_use_id}): running=False, output_len={len(str(data.get('output', '')))}"
                        )
                        break
                    elif (
                        not tool_use_id
                        and tool.get("running")
                        and tool["name"] == tool_name
                    ):
                        # Fallback: match by name if no tool_use_id (backwards compatibility)
                        tool["running"] = False
                        tool["success"] = data.get("success", True)
                        tool["summary"] = data.get("summary")
                        tool["output"] = data.get("output")
                        tool["_image_file_id"] = data.get("_image_file_id")
                        found = True
                        logger.info(
                            f"Updated tool {tool_name} (by name): running=False, output_len={len(str(data.get('output', '')))}"
                        )
                        break
                if found:
                    break

            if not found:
                logger.warning(
                    f"Could not find tool to update: name={tool_name}, id={tool_use_id}"
                )

            # If this is a Task tool completing, mark the subagent as completed
            if tool_name == "Task" and tool_use_id and tool_use_id in state.subagents:
                state.subagents[tool_use_id]["completed"] = True
                subagent_tools_count = len(state.subagents[tool_use_id]["tools"])
                logger.info(
                    f"🤖 Subagent completed: {tool_use_id} - {subagent_tools_count} tools executed"
                )

            # Add to timeline
            if state.current_tool:
                state.timeline.append(
                    {
                        "type": "tool",
                        "name": state.current_tool["name"],
                        "input": state.current_tool.get("input", {}),
                        "success": data.get("success", True),
                        "summary": data.get("summary"),
                        "output": data.get("output"),
                        "_image_file_id": data.get("_image_file_id"),
                        "_image_url": data.get("_image_url"),
                        "parent_tool_use_id": state.current_tool.get(
                            "parent_tool_use_id"
                        ),
                    }
                )
        state.current_tool = None
        update_slack_message(client, state, team_id)

    elif event_type == "result":
        # Final result - mark last thought as completed
        logger.info(
            f"📋 Result event received: text_length={len(data.get('text', ''))}, thoughts={len(state.thoughts)}"
        )
        if state.thoughts:
            state.thoughts[-1].completed = True
        state.final_result = data.get("text", "")
        state.current_tool = None
        logger.info(
            f"📋 state.final_result set: length={len(state.final_result) if state.final_result else 0}"
        )

        # Handle images in result
        result_images = data.get("images", [])
        if result_images:
            logger.info(f"📷 Result contains {len(result_images)} image(s)")

            # Build map of already-uploaded images from Read tool outputs
            # Key: image path, Value: file_id
            already_uploaded = {}
            if state.thoughts:
                for thought in state.thoughts:
                    for tool in thought.tools:
                        if tool.get("name") == "Read" and tool.get("_image_file_id"):
                            # Extract path from tool input
                            tool_input = tool.get("input", {})
                            file_path = tool_input.get(
                                "file_path", ""
                            ) or tool_input.get("path", "")
                            if file_path:
                                # Normalize path for matching
                                normalized_path = file_path.lstrip("./")
                                already_uploaded[file_path] = tool["_image_file_id"]
                                already_uploaded[normalized_path] = tool[
                                    "_image_file_id"
                                ]
                                if file_path.startswith("./"):
                                    already_uploaded[file_path[2:]] = tool[
                                        "_image_file_id"
                                    ]
                                logger.info(
                                    f"♻️ Found already-uploaded image: {file_path} -> {tool['_image_file_id']}"
                                )

            # Upload or reuse file IDs
            uploaded_images = []
            for img in result_images:
                img_path = img.get("path", "")
                normalized_path = img_path.lstrip("./")

                # Check if this image was already uploaded in a Read tool
                existing_file_id = already_uploaded.get(
                    img_path
                ) or already_uploaded.get(normalized_path)

                if existing_file_id:
                    logger.info(
                        f"♻️ Reusing file_id for {img_path}: {existing_file_id}"
                    )
                    uploaded_images.append(
                        {
                            **img,
                            "file_id": existing_file_id,
                            "reused": True,  # Mark as reused
                        }
                    )
                else:
                    # Need to upload
                    try:
                        file_id = _upload_base64_image_to_slack(
                            client=client,
                            image_data=img["data"],
                            filename=img.get("alt", "image"),
                            media_type=img["media_type"],
                        )
                        if file_id:
                            uploaded_images.append(
                                {
                                    **img,
                                    "file_id": file_id,
                                    "reused": False,  # Mark as newly uploaded
                                }
                            )
                            logger.info(
                                f"✅ Uploaded result image: {img.get('path')} -> {file_id}"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to upload result image: {e}")

            state.result_images = uploaded_images if uploaded_images else None

        # Handle files in result
        result_files = data.get("files", [])
        if result_files:
            logger.info(f"📎 Result contains {len(result_files)} file(s)")

            # Upload files to Slack
            uploaded_files = []
            for file in result_files:
                try:
                    file_id = _upload_base64_file_to_slack(
                        client=client,
                        file_data=file["data"],
                        filename=file.get("filename", "file"),
                        media_type=file.get("media_type", "application/octet-stream"),
                        channel_id=state.channel_id,
                        thread_ts=state.thread_ts,
                    )
                    if file_id:
                        uploaded_files.append(
                            {
                                "path": file.get("path"),
                                "filename": file.get("filename"),
                                "description": file.get("description"),
                                "media_type": file.get("media_type"),
                                "size": file.get("size"),
                                "file_id": file_id,
                            }
                        )
                        logger.info(
                            f"✅ Uploaded result file: {file.get('filename')} -> {file_id}"
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to upload result file {file.get('filename')}: {e}"
                    )

            state.result_files = uploaded_files if uploaded_files else None

        # Don't update yet - we'll do final update after loop

    elif event_type == "error":
        # Error occurred
        state.error = data.get("message", "Unknown error")
        state.current_tool = None
        # Don't update yet - we'll do final update after loop

    elif event_type == "question":
        # Agent is asking a clarifying question
        questions = data.get("questions", [])

        # Store questions for later summary when user submits answers
        _pending_questions[state.thread_id] = questions

        # Build interactive message with Block Kit
        blocks = build_question_blocks(questions, state.thread_id)

        # Post as new message in thread (not update - needs interaction)
        try:
            response = client.chat_postMessage(
                channel=state.channel_id,
                thread_ts=state.thread_ts,
                text="I have some questions:",
                blocks=blocks,
            )
            # Store message info for timeout updates
            _question_messages[state.thread_id] = {
                "message_ts": response["ts"],
                "channel_id": state.channel_id,
            }
        except Exception as e:
            logger.error(f"Failed to post question: {e}")

    elif event_type == "question_timeout":
        # Agent timed out waiting for user response
        logger.info(
            f"[question_timeout] Received timeout event for thread {state.thread_id}"
        )

        # 1. Update the AskUserQuestion tool state - find ALL AskUserQuestion tools and mark as timed out
        #    (tool_end may have already set running=False, so we don't check that)
        updated_tools = 0
        if state.thoughts:
            for thought in state.thoughts:
                for tool in thought.tools:
                    if tool.get("name") == "AskUserQuestion" and not tool.get("output"):
                        # No output means it timed out (answered tools have output with answers)
                        tool["running"] = False
                        tool["timed_out"] = True
                        thought.completed = True
                        updated_tools += 1
                        logger.info(
                            f"[question_timeout] Marked tool as timed_out: {tool.get('name')}"
                        )

        logger.info(f"[question_timeout] Updated {updated_tools} AskUserQuestion tools")

        # 2. Update the question form message
        msg_info = _question_messages.get(state.thread_id)
        if msg_info:
            try:
                client.chat_update(
                    channel=msg_info["channel_id"],
                    ts=msg_info["message_ts"],
                    text="Question timed out",
                    blocks=[
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": "⏱️ *Question timed out* — Agent waited 60 seconds and continued without your response.",
                                }
                            ],
                        }
                    ],
                )
            except Exception as e:
                logger.error(f"Failed to update question message for timeout: {e}")
            finally:
                # Cleanup
                del _question_messages[state.thread_id]
                if state.thread_id in _pending_questions:
                    del _pending_questions[state.thread_id]

        # 3. Update the main investigation message to reflect timeout status
        update_slack_message(client, state, team_id)


def _is_image_output(tool_output) -> bool:
    """
    Check if a tool output contains an image.

    SDK format: {'type': 'image', 'file': {'base64': '...'}}
    Alternative format: {'image': base64_data, 'mime_type': str}
    """
    import ast
    import json

    if not tool_output:
        return False

    # Try parsing as JSON or dict
    data = None
    try:
        if isinstance(tool_output, str):
            data = json.loads(tool_output)
        elif isinstance(tool_output, dict):
            data = tool_output
    except (json.JSONDecodeError, TypeError):
        try:
            if isinstance(tool_output, str) and tool_output.strip().startswith("{"):
                data = ast.literal_eval(tool_output)
        except (ValueError, SyntaxError):
            pass

    if isinstance(data, dict):
        # SDK format: {'type': 'image', 'file': {'base64': '...'}}
        if data.get("type") == "image" and "file" in data:
            return True
        # Alternative format: {'image': base64_data, 'mime_type': str}
        if "image" in data and "mime_type" in data:
            return True

    return False


def _upload_image_to_slack(
    tool_output, client, channel_id: str, thread_ts: str, filename: str = "image"
) -> dict | None:
    """
    Upload a base64-encoded image from tool output to Slack.

    Args:
        tool_output: Tool output in one of these formats:
            - SDK format: {'type': 'image', 'file': {'base64': '...'}}
            - Alternative: {'image': base64, 'mime_type': str}
        client: Slack client
        channel_id: Channel to upload to (unused - we upload without channel for embedding)
        thread_ts: Thread timestamp (unused)
        filename: Name for the uploaded file

    Returns:
        Dict with 'file_id' and 'permalink_public' if successful, None otherwise
    """
    import ast
    import base64
    import json
    import os as temp_os
    import tempfile

    # Parse the output
    data = None
    try:
        if isinstance(tool_output, str):
            data = json.loads(tool_output)
        elif isinstance(tool_output, dict):
            data = tool_output
    except (json.JSONDecodeError, TypeError):
        try:
            if isinstance(tool_output, str) and tool_output.strip().startswith("{"):
                data = ast.literal_eval(tool_output)
        except (ValueError, SyntaxError):
            pass

    if not data:
        logger.warning("Could not parse tool output as dict")
        return None

    # Extract base64 data and mime_type based on format
    base64_data = None
    mime_type = None

    # SDK format: {'type': 'image', 'file': {'base64': '...'}}
    if data.get("type") == "image" and "file" in data:
        file_info = data["file"]
        base64_data = file_info.get("base64")
        # SDK may not include mime_type, guess from filename or default to jpeg
        mime_type = file_info.get("mime_type") or data.get("mime_type")
        if not mime_type:
            # Guess from filename extension
            if filename.lower().endswith(".png"):
                mime_type = "image/png"
            elif filename.lower().endswith(".gif"):
                mime_type = "image/gif"
            elif filename.lower().endswith(".webp"):
                mime_type = "image/webp"
            else:
                mime_type = "image/jpeg"  # Default
        logger.info(f"Detected SDK image format, mime_type={mime_type}")
    # Alternative format: {'image': base64, 'mime_type': str}
    elif "image" in data and "mime_type" in data:
        base64_data = data["image"]
        mime_type = data["mime_type"]
        logger.info(f"Detected alternative image format, mime_type={mime_type}")

    if not base64_data:
        logger.warning(
            f"Invalid image output format - could not extract base64 data. Keys: {list(data.keys())}"
        )
        return None

    try:
        # Decode base64 image
        image_data = base64.b64decode(base64_data)

        # Determine file extension
        ext = mime_type.split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(image_data)
            tmp_path = tmp.name

        try:
            # Upload to Slack WITHOUT channel - makes it embeddable via slack_file
            # We intentionally do NOT call files.sharedPublicURL to keep images private
            # (only accessible within the Slack workspace)
            response = client.files_upload_v2(
                file=tmp_path,
                filename=f"{filename}.{ext}",
                title=filename,
            )

            if response["ok"]:
                file_info = response["file"]
                file_id = file_info["id"]
                logger.info(f"Image uploaded to Slack (private): file_id={file_id}")
                return file_id
            else:
                logger.warning(f"Failed to upload image: {response}")
                return None
        finally:
            # Cleanup temp file
            temp_os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Error uploading image to Slack: {e}")
        return None


def _upload_base64_image_to_slack(
    client, image_data: str, filename: str, media_type: str
) -> str | None:
    """
    Upload a base64-encoded image to Slack and return the file ID.

    Args:
        client: Slack client
        image_data: Base64-encoded image data
        filename: Filename for the uploaded file
        media_type: MIME type (e.g., 'image/png')

    Returns:
        Slack file ID if successful, None otherwise
    """
    import base64
    import os as temp_os
    import tempfile

    try:
        # Decode base64 image
        decoded_data = base64.b64decode(image_data)

        # Determine file extension
        ext = media_type.split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"

        # Ensure filename has correct extension
        if not filename.lower().endswith(f".{ext}"):
            filename = f"{filename}.{ext}"

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(decoded_data)
            tmp_path = tmp.name

        try:
            # Upload to Slack WITHOUT channel - makes it embeddable via slack_file
            response = client.files_upload_v2(
                file=tmp_path,
                filename=filename,
                title=filename,
            )

            if response["ok"]:
                file_info = response["file"]
                file_id = file_info["id"]
                logger.info(
                    f"Image uploaded to Slack: file_id={file_id}, filename={filename}"
                )
                return file_id
            else:
                logger.warning(f"Failed to upload image: {response}")
                return None
        finally:
            # Cleanup temp file
            temp_os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Error uploading image to Slack: {e}")
        return None


def _upload_base64_file_to_slack(
    client,
    file_data: str,
    filename: str,
    media_type: str,
    channel_id: str,
    thread_ts: str,
) -> str | None:
    """
    Upload a base64-encoded file to Slack and return the file ID.

    Unlike images (which are uploaded without a channel for embedding via slack_file),
    files are uploaded TO a channel/thread so they appear as attachments.

    Args:
        client: Slack client
        file_data: Base64-encoded file data
        filename: Filename for the uploaded file
        media_type: MIME type (e.g., 'text/csv')
        channel_id: Channel to upload to
        thread_ts: Thread timestamp to attach to

    Returns:
        Slack file ID if successful, None otherwise
    """
    import base64
    import os as temp_os
    import tempfile

    try:
        # Decode base64 file
        decoded_data = base64.b64decode(file_data)

        # Determine file extension from media type or filename
        ext = filename.split(".")[-1] if "." in filename else ""
        if not ext:
            # Try to guess from media type
            type_to_ext = {
                "text/csv": "csv",
                "text/plain": "txt",
                "application/json": "json",
                "application/pdf": "pdf",
                "application/zip": "zip",
            }
            ext = type_to_ext.get(media_type, "bin")

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(decoded_data)
            tmp_path = tmp.name

        try:
            # Upload to Slack WITH channel - appears as attachment in thread
            response = client.files_upload_v2(
                file=tmp_path,
                filename=filename,
                title=filename,
                channel=channel_id,
                thread_ts=thread_ts,
            )

            if response["ok"]:
                file_info = response["file"]
                file_id = file_info["id"]
                logger.info(
                    f"File uploaded to Slack: file_id={file_id}, filename={filename}"
                )
                return file_id
            else:
                logger.warning(f"Failed to upload file: {response}")
                return None
        finally:
            # Cleanup temp file
            temp_os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Error uploading file to Slack: {e}")
        return None


def _get_image_extension(media_type: str) -> str:
    """Get file extension for a media type."""
    ext = media_type.split("/")[-1] if "/" in media_type else "png"
    if ext == "jpeg":
        ext = "jpg"
    return f".{ext}"


def _download_slack_image(file_info: dict, client) -> dict | None:
    """
    Download an image from Slack and return its content as base64.

    Images are small enough to send as base64 directly.

    Args:
        file_info: File object from Slack event
        client: Slack client

    Returns:
        dict with {data: base64_string, media_type: str, filename: str, size: int} or None
    """
    import base64

    import requests

    mimetype = file_info.get("mimetype", "")
    filename = file_info.get("name", "image")

    # Only handle images
    if not mimetype.startswith("image/"):
        return None

    # Get the download URL (requires bot token)
    url_private = file_info.get("url_private_download") or file_info.get("url_private")
    if not url_private:
        logger.warning(f"No download URL for image: {filename}")
        return None

    try:
        # Download the image using the bot token
        response = requests.get(
            url_private, headers={"Authorization": f"Bearer {client.token}"}, timeout=60
        )
        response.raise_for_status()

        # Convert to base64
        image_data = base64.b64encode(response.content).decode("utf-8")

        return {
            "data": image_data,
            "media_type": mimetype,
            "filename": filename,
            "size": len(response.content),
        }
    except Exception as e:
        logger.error(f"Failed to download image {filename}: {e}")
        return None


def _get_file_attachment_metadata(file_info: dict, client) -> dict | None:
    """
    Get metadata for a non-image file attachment.

    Instead of downloading the file (which could be huge), we return metadata
    that the sre-agent server will use to set up a proxy download.
    The actual download happens in the sandbox via the proxy pattern.

    Args:
        file_info: File object from Slack event
        client: Slack client

    Returns:
        dict with {filename, size, media_type, download_url, auth_header} or None
    """
    mimetype = file_info.get("mimetype", "")
    filename = file_info.get("name", "file")
    file_size = file_info.get("size", 0)

    # Skip images (handled separately)
    if mimetype.startswith("image/"):
        return None

    # Get the download URL
    url_private = file_info.get("url_private_download") or file_info.get("url_private")
    if not url_private:
        logger.warning(f"No download URL for file: {filename}")
        return None

    return {
        "filename": filename,
        "size": file_size,
        "media_type": mimetype,
        "download_url": url_private,
        "auth_header": f"Bearer {client.token}",
    }


def _extract_images_from_event(event: dict, client) -> list:
    """
    Extract all images from a Slack event.

    Images are downloaded and converted to base64 (they're typically small).

    Args:
        event: Slack event object
        client: Slack client

    Returns:
        List of image dicts: [{data: base64, media_type: str, filename: str}, ...]
    """
    images = []
    files = event.get("files", [])

    for file_info in files:
        image = _download_slack_image(file_info, client)
        if image:
            images.append(image)
            logger.info(
                f"Downloaded image: {image['filename']} ({image['size']} bytes)"
            )

    return images


def _extract_file_attachments_from_event(event: dict, client) -> list:
    """
    Extract metadata for all non-image file attachments from a Slack event.

    Instead of downloading files (which could be very large), we extract metadata
    that will be used by the sre-agent server to set up proxy downloads.
    Files are downloaded in the sandbox via the proxy pattern.

    Args:
        event: Slack event object
        client: Slack client

    Returns:
        List of file attachment metadata dicts:
        [{filename, size, media_type, download_url, auth_header}, ...]
    """
    attachments = []
    files = event.get("files", [])

    for file_info in files:
        attachment = _get_file_attachment_metadata(file_info, client)
        if attachment:
            attachments.append(attachment)
            logger.info(
                f"File attachment: {attachment['filename']} ({attachment['size']} bytes, {attachment['media_type']})"
            )

    return attachments


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


@app.event("app_mention")
def handle_mention(event, say, client, context):
    """
    Handle @mentions of the bot.

    Flow:
    1. Post initial message
    2. Stream SSE events from sre-agent
    3. Update message as events arrive (using chat.update)
    4. Final update with result and feedback buttons
    """
    # DEBUG: Log every app_mention event
    logger.info(
        f"🔔 APP_MENTION EVENT RECEIVED: channel={event.get('channel')}, user={event.get('user')}, ts={event.get('ts')}"
    )
    user_id = event["user"]
    text = event.get("text", "").strip()
    channel_id = event["channel"]
    team_id = event.get("team") or context.get("team_id", "unknown")

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

    # Resolve all mentions (users and bots) to human-readable names
    resolved_text, id_to_name_mapping = _resolve_mentions(text, client, bot_user_id)

    # Extract images from the event (downloaded as base64 - typically small)
    images = _extract_images_from_event(event, client)

    # Extract file attachment metadata (not downloaded - uses proxy pattern for large files)
    file_attachments = _extract_file_attachments_from_event(event, client)

    # Get the user's name who sent this message
    sender_name = "Unknown User"
    try:
        user_response = client.users_info(user=user_id)
        if user_response["ok"]:
            user = user_response["user"]
            profile = user.get("profile", {})
            sender_name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("name", "Unknown User")
            )
    except Exception as e:
        logger.warning(f"Failed to get sender name for {user_id}: {e}")

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

    if not prompt_text and not images and not file_attachments:
        say(
            text="Hey! What would you like me to investigate?",
            thread_ts=thread_ts,
        )
        return

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

    enriched_prompt = prompt_text + "\n" + "\n".join(context_lines)

    # Post minimal initial message with loading indicator
    # Will be updated immediately with first event
    from asset_manager import clear_asset_cache, get_asset_file_id

    logger.info("Getting loading asset...")
    loading_file_id = None
    try:
        loading_file_id = get_asset_file_id(client, team_id, "loading")
        logger.info(f"Got loading asset: {loading_file_id}")
    except Exception as e:
        logger.warning(f"Failed to get loading asset: {e}")

    # Build initial blocks - try with slack_file, fall back to emoji
    def build_initial_blocks(use_slack_file: bool):
        if use_slack_file and loading_file_id:
            return [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "image",
                            "slack_file": {"id": loading_file_id},
                            "alt_text": "Loading",
                        },
                        {"type": "mrkdwn", "text": "Investigating..."},
                    ],
                }
            ]
        else:
            return [
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "⏳ Investigating..."}],
                }
            ]

    # Try with slack_file first, fall back to emoji if it fails
    logger.info("Posting initial message...")
    try:
        initial_response = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Investigating...",
            blocks=build_initial_blocks(use_slack_file=True),
        )
        logger.info(f"Initial message posted: {initial_response.get('ts')}")
    except Exception as e:
        logger.warning(f"Failed to post with slack_file, falling back to emoji: {e}")
        # Clear cached asset (might be invalid)
        clear_asset_cache(team_id)
        initial_response = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Investigating...",
            blocks=build_initial_blocks(use_slack_file=False),
        )
        logger.info(f"Initial message posted (fallback): {initial_response.get('ts')}")

    message_ts = initial_response["ts"]

    # Initialize state
    state = MessageState(
        channel_id=channel_id,
        message_ts=message_ts,
        thread_ts=thread_ts,
        thread_id=thread_id,
    )

    try:
        # Build request payload with prompt and optional images
        request_payload = {
            "prompt": enriched_prompt,
            "thread_id": thread_id,
        }

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
            headers={"Accept": "text/event-stream"},
        )

        if response.status_code != 200:
            error_detail = response.text[:200] if response.text else "Unknown error"
            state.error = f"Server error ({response.status_code}): {error_detail}"
            update_slack_message(client, state, team_id, final=True)
            return

        # Process SSE stream
        event_count = 0
        current_event_type = None
        for line in response.iter_lines(decode_unicode=True):
            if line:
                current_event_type, event = parse_sse_event(current_event_type, line)
                if event:
                    event_count += 1
                    handle_stream_event(state, event, client, team_id)
                    current_event_type = None  # Reset after processing

        # Cache state for modal view
        import time

        _investigation_cache[thread_id] = state
        _cache_timestamps[thread_id] = time.time()

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


def fetch_incidentio_alert_details(
    description: str = None, deduplication_key: str = None
) -> Optional[dict]:
    """
    Fetch alert details from Incident.io API.

    Args:
        description: Alert description to search for
        deduplication_key: Deduplication key from the alert

    Returns:
        Alert details dict or None if not found or API unavailable
    """
    if not INCIDENT_IO_API_KEY:
        logger.warning("INCIDENT_IO_API_KEY not configured, skipping alert enrichment")
        return None

    headers = {
        "Authorization": f"Bearer {INCIDENT_IO_API_KEY}",
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
    attachments = event.get("attachments", [])
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

    # Fetch enriched alert details from Incident.io API
    logger.info("Fetching alert details from Incident.io API...")
    incidentio_alert = fetch_incidentio_alert_details(
        description=alert_title, deduplication_key=deduplication_key
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
        api_alert_source_id = incidentio_alert.get("alert_source_id", "")

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
    from asset_manager import clear_asset_cache, get_asset_file_id

    loading_file_id = None
    try:
        loading_file_id = get_asset_file_id(client, team_id, "loading")
    except Exception as e:
        logger.warning(f"Failed to get loading asset: {e}")

    # Build initial blocks
    def build_initial_blocks(use_slack_file: bool):
        if use_slack_file and loading_file_id:
            return [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "image",
                            "slack_file": {"id": loading_file_id},
                            "alt_text": "Loading",
                        },
                        {"type": "mrkdwn", "text": "Investigating alert..."},
                    ],
                }
            ]
        else:
            return [
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "⏳ Investigating alert..."}
                    ],
                }
            ]

    # Try to post initial message
    try:
        initial_response = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Investigating alert...",
            blocks=build_initial_blocks(use_slack_file=True),
        )
    except Exception as e:
        logger.warning(f"Failed to post with slack_file, falling back to emoji: {e}")
        clear_asset_cache(team_id)
        initial_response = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Investigating alert...",
            blocks=build_initial_blocks(use_slack_file=False),
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
        # Call sre-agent to investigate
        request_payload = {
            "prompt": investigation_prompt,
            "thread_id": thread_id,
        }

        response = requests.post(
            f"{SRE_AGENT_URL}/investigate",
            json=request_payload,
            stream=True,
            timeout=300,
            headers={"Accept": "text/event-stream"},
        )

        if response.status_code != 200:
            error_detail = response.text[:200] if response.text else "Unknown error"
            state.error = f"Server error ({response.status_code}): {error_detail}"
            update_slack_message(client, state, team_id, final=True)
            return

        # Process SSE stream
        event_count = 0
        current_event_type = None
        for line in response.iter_lines(decode_unicode=True):
            if line:
                current_event_type, sse_event = parse_sse_event(current_event_type, line)
                if sse_event:
                    event_count += 1
                    handle_stream_event(state, sse_event, client, team_id)
                    current_event_type = None  # Reset after processing

        # Cache state for modal view
        import time

        _investigation_cache[thread_id] = state
        _cache_timestamps[thread_id] = time.time()

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


@app.event("message")
def handle_message(event, client, context):
    """
    Handle regular messages (not @mentions).

    Special case: Auto-trigger investigation for Incident.io alerts.

    If the bot has already participated in this thread and the user
    didn't mention us, send ONE private ephemeral nudge asking if they
    want to invoke IncidentFox. Only nudge once per user per thread.
    """
    # DEBUG: Log EVERY message event received - this should print for ALL messages
    logger.info("=" * 60)
    logger.info("📨 MESSAGE EVENT RECEIVED")
    logger.info(f"   type={event.get('type')}")
    logger.info(f"   subtype={event.get('subtype')}")
    logger.info(f"   channel={event.get('channel')}")
    logger.info(f"   user={event.get('user')}")
    logger.info(f"   bot_id={event.get('bot_id')}")
    logger.info(f"   text={event.get('text', '')[:100]}")
    logger.info("=" * 60)

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
            logger.info("✅ Confirmed: NEW ALERT - triggering investigation")
            _trigger_incident_io_investigation(event, client, context)
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

    # Skip subtypes (message edits, bot_message, etc.) for nudge logic
    if subtype:
        return

    # Only handle threaded messages (not top-level channel messages)
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return

    user_id = event.get("user")
    channel_id = event.get("channel")
    text = event.get("text", "")

    # Skip if user mentioned the bot (will be handled by app_mention handler)
    bot_user_id = context.get("bot_user_id")
    if bot_user_id and f"<@{bot_user_id}>" in text:
        return

    # Skip if we've already sent a nudge to this user in this thread
    if _nudge_sent.get((thread_ts, user_id)):
        return

    # Check if the bot has participated in this thread
    try:
        replies = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=50,  # Check recent messages
        )

        bot_has_replied = False
        for msg in replies.get("messages", []):
            # Check if any message is from our bot
            if msg.get("bot_id") or (msg.get("user") == bot_user_id):
                bot_has_replied = True
                break

        if not bot_has_replied:
            return  # Bot hasn't participated, no need to nudge

    except Exception as e:
        logger.warning(f"Failed to check thread history: {e}")
        return

    # Send ephemeral nudge to the user (only once per thread)
    logger.info(f"Sending nudge to {user_id} in thread {thread_ts}")

    # Truncate text for display (keep it short)
    display_text = text[:50] + "..." if len(text) > 50 else text

    # Get bot's name for the @mention hint
    bot_name = "IncidentFox"

    try:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            thread_ts=thread_ts,
            text=f"Did you want to ask me '{display_text}'?",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"👋 Did you want to ask me _{display_text}_?",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Yes"},
                            "style": "primary",
                            "action_id": "nudge_invoke",
                            "value": json.dumps(
                                {
                                    "channel_id": channel_id,
                                    "thread_ts": thread_ts,
                                    "user_id": user_id,
                                    "text": text,
                                }
                            ),
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "No"},
                            "action_id": "nudge_dismiss",
                            "value": json.dumps(
                                {
                                    "thread_ts": thread_ts,
                                    "user_id": user_id,
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
                            "text": f"_You can <@{bot_user_id}> to ask me followup questions. I won't ask again in this thread._",
                        }
                    ],
                },
            ],
        )

        # Mark that we've sent a nudge to this user in this thread
        _nudge_sent[(thread_ts, user_id)] = True

    except Exception as e:
        logger.warning(f"Failed to send nudge: {e}")


@app.action("nudge_invoke")
def handle_nudge_invoke(ack, body, client, context, respond):
    """Handle 'Yes, ask IncidentFox' button from nudge."""
    ack()

    # Delete this ephemeral message
    respond({"delete_original": True})

    # Parse the value
    value = json.loads(body["actions"][0]["value"])
    channel_id = value["channel_id"]
    thread_ts = value["thread_ts"]
    user_id = value["user_id"]
    text = value["text"]

    logger.info(f"Nudge accepted by {user_id} in thread {thread_ts}")

    # Get team_id
    team_id = body.get("team", {}).get("id") or "unknown"

    # Get the user's name
    sender_name = "Unknown User"
    try:
        user_response = client.users_info(user=user_id)
        if user_response["ok"]:
            user = user_response["user"]
            profile = user.get("profile", {})
            sender_name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("name", "Unknown User")
            )
    except Exception as e:
        logger.warning(f"Failed to get sender name: {e}")

    # Generate thread_id
    sanitized_thread_ts = thread_ts.replace(".", "-")
    sanitized_channel = channel_id.lower()
    thread_id = f"slack-{sanitized_channel}-{sanitized_thread_ts}"

    # Build a simple prompt with context
    context_lines = ["\n### Slack Context"]
    context_lines.append(f"**Requested by:** {sender_name} (User ID: {user_id})")
    context_lines.append("\n**Including Images in Your Response:**")
    context_lines.append("Use `![description](./path/to/image.png)` for images.")
    context_lines.append("\n**Sharing Files with the User:**")
    context_lines.append(
        "Use `[description](./path/to/file)` for files (place at end of response)."
    )

    enriched_prompt = text + "\n" + "\n".join(context_lines)

    # Post initial "Investigating..." message
    from asset_manager import clear_asset_cache, get_asset_file_id

    loading_file_id = None
    try:
        loading_file_id = get_asset_file_id(client, team_id, "loading")
    except Exception:
        pass

    # Truncate text for display
    display_text = text[:80] + "..." if len(text) > 80 else text

    # Build initial blocks with context about who triggered it
    trigger_context = {
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"_Triggered by <@{user_id}>: {display_text}_"}
        ],
    }

    if loading_file_id:
        initial_blocks = [
            trigger_context,
            {
                "type": "context",
                "elements": [
                    {
                        "type": "image",
                        "slack_file": {"id": loading_file_id},
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
            text=f"Investigating (triggered by <@{user_id}>)...",
            blocks=initial_blocks,
        )
    except Exception as e:
        logger.error(f"Failed to post initial message: {e}")
        return

    message_ts = initial_response["ts"]

    # Initialize state with trigger context (for nudge-initiated investigations)
    state = MessageState(
        channel_id=channel_id,
        message_ts=message_ts,
        thread_ts=thread_ts,
        thread_id=thread_id,
        trigger_user_id=user_id,
        trigger_text=text,
    )

    # Call sre-agent with SSE streaming
    try:
        request_payload = {
            "prompt": enriched_prompt,
            "thread_id": thread_id,
        }

        response = requests.post(
            f"{SRE_AGENT_URL}/investigate",
            json=request_payload,
            stream=True,
            timeout=300,
            headers={"Accept": "text/event-stream"},
        )

        if response.status_code != 200:
            state.error = f"Server error ({response.status_code})"
            update_slack_message(client, state, team_id, final=True)
            return

        # Process SSE stream
        for line in response.iter_lines(decode_unicode=True):
            if line:
                event = parse_sse_event(line)
                if event:
                    handle_stream_event(state, event, client, team_id)

        # Cache state for modal
        import time

        _investigation_cache[thread_id] = state
        _cache_timestamps[thread_id] = time.time()

        # Final update
        update_slack_message(client, state, team_id, final=True)
        save_investigation_snapshot(state)

    except Exception as e:
        logger.exception(f"Error during investigation: {e}")
        state.error = f"Error: {str(e)}"
        update_slack_message(client, state, team_id, final=True)


@app.action("nudge_dismiss")
def handle_nudge_dismiss(ack, body, respond):
    """Handle 'No' button from nudge."""
    ack()

    # Delete this ephemeral message
    respond({"delete_original": True})

    # Parse the value
    value = json.loads(body["actions"][0]["value"])
    thread_ts = value["thread_ts"]
    user_id = value["user_id"]

    logger.info(f"Nudge dismissed by {user_id} in thread {thread_ts}")


@app.action("coralogix_investigate")
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

    # Get the user's name
    sender_name = "Unknown User"
    try:
        user_response = client.users_info(user=user_id)
        if user_response["ok"]:
            user = user_response["user"]
            profile = user.get("profile", {})
            sender_name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("name", "Unknown User")
            )
    except Exception as e:
        logger.warning(f"Failed to get sender name: {e}")

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
    from asset_manager import clear_asset_cache, get_asset_file_id

    loading_file_id = None
    try:
        loading_file_id = get_asset_file_id(client, team_id, "loading")
    except Exception:
        pass

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

    if loading_file_id:
        initial_blocks = [
            trigger_context,
            {
                "type": "context",
                "elements": [
                    {
                        "type": "image",
                        "slack_file": {"id": loading_file_id},
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

    try:
        # Call sre-agent to investigate
        request_payload = {
            "prompt": investigation_prompt,
            "thread_id": thread_id,
        }

        response = requests.post(
            f"{SRE_AGENT_URL}/investigate",
            json=request_payload,
            stream=True,
            timeout=300,
            headers={"Accept": "text/event-stream"},
        )

        if response.status_code != 200:
            error_detail = response.text[:200] if response.text else "Unknown error"
            state.error = f"Server error ({response.status_code}): {error_detail}"
            update_slack_message(client, state, team_id, final=True)
            return

        # Process SSE stream
        event_count = 0
        current_event_type = None
        for line in response.iter_lines(decode_unicode=True):
            if line:
                current_event_type, sse_event = parse_sse_event(current_event_type, line)
                if sse_event:
                    event_count += 1
                    handle_stream_event(state, sse_event, client, team_id)
                    current_event_type = None  # Reset after processing

        # Cache state for modal view
        import time

        _investigation_cache[thread_id] = state
        _cache_timestamps[thread_id] = time.time()

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


@app.action("coralogix_dismiss")
def handle_coralogix_dismiss(ack, body, respond):
    """Handle 'No thanks' button for Coralogix insights."""
    ack()

    # Delete the ephemeral message
    respond({"delete_original": True})

    # Parse the value
    value = json.loads(body["actions"][0]["value"])
    thread_ts = value["thread_ts"]
    url = value["url"]

    logger.info(f"Coralogix investigation dismissed for: {url[:50]}...")


@app.action("feedback_positive")
def handle_positive_feedback(ack, body):
    """Handle positive feedback."""
    ack()
    logger.info(f"Positive feedback: {body.get('message', {}).get('ts')}")


@app.action("feedback_negative")
def handle_negative_feedback(ack, body):
    """Handle negative feedback."""
    ack()
    logger.info(f"Negative feedback: {body.get('message', {}).get('ts')}")


@app.action("view_investigation_session")
def handle_view_session(ack, body, client):
    """Handle "View Session" button - open modal with chronological timeline."""
    ack()

    # Get thread_id from button value
    thread_id = body["actions"][0].get("value", "unknown")

    # Lookup investigation state
    logger.info(f"View Session clicked: thread_id={thread_id}")
    logger.info(f"Cache keys: {list(_investigation_cache.keys())}")
    state = _investigation_cache.get(thread_id)
    if not state:
        logger.warning(f"No cached state for thread_id: {thread_id}")
        # Show error modal
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Error"},
                "close": {"type": "plain_text", "text": "Close"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "❌ Session not found (may have expired).",
                        },
                    }
                ],
            },
        )
        return

    # Get Slack-hosted assets for modal
    from asset_manager import get_asset_file_id

    team_id = body.get("team", {}).get("id") or body.get("user", {}).get("team_id")

    try:
        loading_file_id = get_asset_file_id(client, team_id, "loading")
    except Exception as e:
        logger.warning(f"Failed to load loading asset: {e}")
        loading_file_id = None

    try:
        done_file_id = get_asset_file_id(client, team_id, "done")
    except Exception as e:
        logger.warning(f"Failed to load done asset: {e}")
        done_file_id = None

    # Build modal with hierarchical thoughts (same formatting as main message)
    from modal_builder import build_session_modal

    modal = build_session_modal(
        thread_id=thread_id,
        thoughts=state.thoughts,
        result=state.final_result,
        loading_file_id=loading_file_id,
        done_file_id=done_file_id,
        result_images=state.result_images,
        result_files=state.result_files,
    )

    # Open modal
    try:
        client.views_open(trigger_id=body["trigger_id"], view=modal)
    except Exception as e:
        logger.error(f"Failed to open modal: {e}")
        # Log modal blocks for debugging invalid_blocks errors
        if "invalid_blocks" in str(e) or "invalid_block" in str(e).lower():
            import json

            logger.error(
                f"Invalid modal blocks payload:\n{json.dumps(modal.get('blocks', []), indent=2, default=str)}"
            )


@app.action("modal_page_prev")
@app.action("modal_page_next")
def handle_modal_pagination(ack, body, client):
    """Handle pagination buttons in the investigation modal."""
    ack()

    import json

    # Get page info from button value
    try:
        action_value = body["actions"][0].get("value", "{}")
        page_data = json.loads(action_value)
        thread_id = page_data.get("thread_id")
        page = page_data.get("page", 1)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse pagination data: {e}")
        return

    # Lookup investigation state
    state = _investigation_cache.get(thread_id)
    if not state:
        logger.warning(f"No cached state for pagination: {thread_id}")
        return

    # Get Slack-hosted assets for modal
    from asset_manager import get_asset_file_id

    team_id = body.get("team", {}).get("id") or body.get("user", {}).get("team_id")

    try:
        loading_file_id = get_asset_file_id(client, team_id, "loading")
    except Exception:
        loading_file_id = None

    try:
        done_file_id = get_asset_file_id(client, team_id, "done")
    except Exception:
        done_file_id = None

    # Build modal for requested page
    from modal_builder import build_session_modal

    modal = build_session_modal(
        thread_id=thread_id,
        thoughts=state.thoughts,
        result=state.final_result,
        loading_file_id=loading_file_id,
        done_file_id=done_file_id,
        page=page,
        result_images=state.result_images,
        result_files=state.result_files,
    )

    # Update the modal view
    try:
        client.views_update(view_id=body["view"]["id"], view=modal)
    except Exception as e:
        logger.error(f"Failed to update modal for pagination: {e}")
        # Log modal blocks for debugging invalid_blocks errors
        if "invalid_blocks" in str(e) or "invalid_block" in str(e).lower():
            import json

            logger.error(
                f"Invalid modal blocks payload:\n{json.dumps(modal.get('blocks', []), indent=2, default=str)}"
            )


@app.action("modal_page_info")
def handle_modal_page_info(ack):
    """Handle click on page info button (no-op, just acknowledge)."""
    ack()


@app.action("view_tool_output")
def handle_view_tool_output(ack, body, client):
    """Handle "View Full Output" button - push a new view with complete tool output."""
    ack()

    import json

    # Get thread_id from modal's private_metadata (may be JSON or plain string)
    private_metadata = body["view"]["private_metadata"]
    try:
        metadata = json.loads(private_metadata)
        thread_id = metadata.get("thread_id", private_metadata)
    except (json.JSONDecodeError, TypeError):
        thread_id = private_metadata

    # Get tool index from button value
    try:
        tool_idx = int(body["actions"][0].get("value", "0"))
    except (ValueError, KeyError):
        logger.warning("Invalid tool index in view_tool_output")
        return

    # Lookup investigation state
    state = _investigation_cache.get(thread_id)
    if not state or tool_idx >= len(state.timeline):
        logger.warning(f"Tool not found: thread_id={thread_id}, idx={tool_idx}")
        return

    # Get the tool from timeline
    event = state.timeline[tool_idx]
    if event.get("type") != "tool":
        logger.warning(f"Event at index {tool_idx} is not a tool")
        return

    # Build tool output modal
    from modal_builder import build_tool_output_modal

    modal = build_tool_output_modal(
        tool_name=event.get("name", "Unknown"),
        tool_input=event.get("input", {}),
        output=event.get("output", "No output available"),
        success=event.get("success", True),
    )

    # Push new view onto stack
    try:
        client.views_push(trigger_id=body["trigger_id"], view=modal)
    except Exception as e:
        logger.error(f"Failed to push tool output view: {e}")


@app.action("view_full_output")
def handle_view_full_output(ack, body, client):
    """Handle "View Full" button - show complete untruncated file content."""
    ack()

    import json

    # Parse button value: thread_id|thought_idx|tool_idx
    button_value = body["actions"][0].get("value", "")
    try:
        thread_id, thought_idx, tool_idx = button_value.split("|")
        thought_idx = int(thought_idx)
        tool_idx = int(tool_idx)
    except (ValueError, AttributeError):
        logger.warning(f"Invalid button value: {button_value}")
        return

    # Lookup investigation state
    state = _investigation_cache.get(thread_id)
    if not state:
        logger.warning(f"No cached state for thread_id: {thread_id}")
        return

    # Get the tool
    if thought_idx >= len(state.thoughts):
        logger.warning(
            f"Invalid thought index: {thought_idx} (have {len(state.thoughts)})"
        )
        return

    thought = state.thoughts[thought_idx]
    if tool_idx >= len(thought.tools):
        logger.warning(f"Invalid tool index: {tool_idx} (have {len(thought.tools)})")
        return

    tool = thought.tools[tool_idx]
    tool_name = tool.get("name", "Unknown")
    tool_input = tool.get("input", {})
    tool_output = tool.get("output", "")

    # Extract full content based on tool type
    if tool_name == "WebSearch":
        # For WebSearch, use query as the "file_path" and format the full output
        file_path = tool_input.get("query", "Search Results")
        # Re-format with full content (no truncation)
        from modal_builder import _format_websearch_output_compact

        full_content = _format_websearch_output_compact(tool_output)
        # Strip code block markers since build_full_output_modal will add them
        if full_content.startswith("```\n") and full_content.endswith("\n```"):
            full_content = full_content[4:-4]
    elif tool_name == "WebFetch":
        # For WebFetch, use URL as the "file_path" and format the full output
        file_path = tool_input.get("url", "Fetched Content")
        # Re-format with full content (no truncation)
        from modal_builder import _format_webfetch_output_compact

        full_content = _format_webfetch_output_compact(tool_output)
        # Strip code block markers since build_full_output_modal will add them
        if full_content.startswith("```\n") and full_content.endswith("\n```"):
            full_content = full_content[4:-4]
    elif tool_name == "Read":
        file_path = tool_input.get("file_path", "unknown")
        # Parse Read output to get full content
        full_content = _extract_full_read_content(tool_output)
    elif tool_name == "Write":
        file_path = tool_input.get("file_path", "unknown")
        # For Write, extract from output (input is often truncated)
        full_content = _extract_full_write_content(tool_output)
    else:
        # For other tools, just use output as-is
        file_path = tool_input.get("file_path", "unknown")
        full_content = str(tool_output)

    # Build full output modal
    from modal_builder import build_full_output_modal

    modal = build_full_output_modal(
        tool_name=tool_name,
        file_path=file_path,
        full_content=full_content,
        add_line_numbers=(
            tool_name in ["Read", "Write"]
        ),  # Only for file tools, not WebFetch/WebSearch
    )

    # Push new view onto modal stack
    try:
        client.views_push(trigger_id=body["trigger_id"], view=modal)
        logger.info(f"Pushed full output modal for {tool_name} {file_path}")
    except Exception as e:
        logger.error(f"Failed to push full output modal: {e}")


@app.action("view_subagent_details")
def handle_view_subagent_details(ack, body, client):
    """Handle "View Details" button for subagent - show all child tool calls."""
    ack()

    import json

    # Parse button value: thread_id|thought_idx|task_idx|subagent_id
    button_value = body["actions"][0].get("value", "")
    try:
        parts = button_value.split("|")
        thread_id = parts[0]
        thought_idx = int(parts[1])
        task_idx = int(parts[2])
        subagent_id = parts[3] if len(parts) > 3 else None
    except (ValueError, AttributeError, IndexError):
        logger.warning(f"Invalid button value for subagent details: {button_value}")
        return

    # Lookup investigation state
    state = _investigation_cache.get(thread_id)
    if not state:
        logger.warning(f"No cached state for thread_id: {thread_id}")
        return

    # Get the thought
    if thought_idx >= len(state.thoughts):
        logger.warning(
            f"Invalid thought index: {thought_idx} (have {len(state.thoughts)})"
        )
        return

    thought = state.thoughts[thought_idx]

    # Get the Task tool
    if task_idx >= len(thought.tools):
        logger.warning(f"Invalid task index: {task_idx} (have {len(thought.tools)})")
        return

    task_tool = thought.tools[task_idx]

    if task_tool.get("name") != "Task":
        logger.warning(
            f"Tool at index {task_idx} is not a Task tool: {task_tool.get('name')}"
        )
        return

    # Find children of this subagent (exclude nested Task tools which are other subagents)
    children = []
    for idx, tool in enumerate(thought.tools):
        parent_id = tool.get("parent_tool_use_id")
        tool_name = tool.get("name", "")
        # Only include if parent matches AND it's not another Task (subagent)
        if parent_id == subagent_id and tool_name != "Task":
            children.append((idx, tool))

    logger.info(
        f"Building subagent detail modal: {subagent_id} with {len(children)} children"
    )

    # Build subagent detail modal
    from modal_builder import build_subagent_detail_modal

    # Get icon file IDs from state
    loading_file_id = (
        state.loading_file_id if hasattr(state, "loading_file_id") else None
    )
    done_file_id = state.done_file_id if hasattr(state, "done_file_id") else None

    modal = build_subagent_detail_modal(
        thread_id=thread_id,
        task_tool=task_tool,
        children=children,
        loading_file_id=loading_file_id,
        done_file_id=done_file_id,
        thought_idx=thought_idx,
    )

    # Push new view onto modal stack
    try:
        client.views_push(trigger_id=body["trigger_id"], view=modal)
        logger.info(f"Pushed subagent detail modal for {subagent_id}")
    except Exception as e:
        logger.error(f"Failed to push subagent detail modal: {e}")


@app.action("subagent_modal_page_prev")
@app.action("subagent_modal_page_next")
def handle_subagent_modal_pagination(ack, body, client):
    """Handle pagination buttons in the subagent detail modal."""
    ack()

    import json

    # Get page info from button value
    try:
        action_value = body["actions"][0].get("value", "{}")
        page_data = json.loads(action_value)
        thread_id = page_data.get("thread_id")
        thought_idx = page_data.get("thought_idx", 0)
        subagent_id = page_data.get("subagent_id")
        page = page_data.get("page", 1)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse subagent pagination data: {e}")
        return

    # Lookup investigation state
    state = _investigation_cache.get(thread_id)
    if not state:
        logger.warning(f"No cached state for subagent pagination: {thread_id}")
        return

    # Get the thought and task tool
    if thought_idx >= len(state.thoughts):
        logger.warning(f"Invalid thought index for pagination: {thought_idx}")
        return

    thought = state.thoughts[thought_idx]

    # Find the task tool by subagent_id
    task_tool = None
    for tool in thought.tools:
        if tool.get("tool_use_id") == subagent_id:
            task_tool = tool
            break

    if not task_tool:
        logger.warning(f"Could not find task tool for subagent: {subagent_id}")
        return

    # Find children of this subagent
    children = []
    for idx, tool in enumerate(thought.tools):
        parent_id = tool.get("parent_tool_use_id")
        tool_name = tool.get("name", "")
        if parent_id == subagent_id and tool_name != "Task":
            children.append((idx, tool))

    # Get icon file IDs
    loading_file_id = (
        state.loading_file_id if hasattr(state, "loading_file_id") else None
    )
    done_file_id = state.done_file_id if hasattr(state, "done_file_id") else None

    # Build modal for requested page
    from modal_builder import build_subagent_detail_modal

    modal = build_subagent_detail_modal(
        thread_id=thread_id,
        task_tool=task_tool,
        children=children,
        loading_file_id=loading_file_id,
        done_file_id=done_file_id,
        thought_idx=thought_idx,
        page=page,
    )

    # Update the modal view
    try:
        client.views_update(view_id=body["view"]["id"], view=modal)
    except Exception as e:
        logger.error(f"Failed to update subagent modal for pagination: {e}")


# Track button selections in memory (thread_id -> {q_idx: selected_value})
_button_selections = {}

# Track pending questions for displaying in submitted answer summary (thread_id -> questions list)
_pending_questions = {}

# Track question message timestamps for timeout updates (thread_id -> {message_ts, channel_id})
_question_messages = {}


@app.action(re.compile(r"^answer_q\d+_.*"))
def handle_checkbox_action(ack, body, client):
    """Handle checkbox selections - just acknowledge, state is read on submit."""
    ack()
    # No action needed - checkbox state is captured in body["state"]["values"] on submit


def _unescape_html(text: str) -> str:
    """Unescape HTML entities that Slack may have added to block text."""
    import html

    return html.unescape(text)


@app.action(re.compile(r"^toggle_q\d+_opt\d+_.*"))
def handle_toggle_button(ack, body, client):
    """Handle toggle button clicks for single-select questions."""
    ack()

    action = body["actions"][0]
    action_id = action["action_id"]
    value = action["value"]  # Format: "q_idx:label"

    # Parse thread_id from action_id (format: toggle_q{q_idx}_opt{opt_idx}_{thread_id})
    # Thread ID may contain dashes but not underscores in our format
    # Find position after "toggle_qX_optY_" prefix
    prefix_match = re.match(r"toggle_q\d+_opt\d+_(.+)", action_id)
    thread_id = prefix_match.group(1) if prefix_match else ""

    q_idx, label = value.split(":", 1)

    # Initialize selections for this thread if needed
    if thread_id not in _button_selections:
        _button_selections[thread_id] = {}

    # Toggle selection (if already selected, deselect; otherwise select)
    current = _button_selections[thread_id].get(q_idx)
    if current == label:
        # Deselect
        _button_selections[thread_id].pop(q_idx, None)
    else:
        # Select this option
        _button_selections[thread_id][q_idx] = label

    # Update message to show selection state
    try:
        message = body["message"]
        blocks = message["blocks"]

        # Find the button block and update button styles
        # Also fix HTML encoding that Slack may have added to button text
        for block in blocks:
            if block.get("block_id") == f"question_{q_idx}":
                for element in block.get("elements", []):
                    if element.get("type") == "button":
                        # Unescape HTML entities in button text to prevent double-encoding
                        if "text" in element and "text" in element["text"]:
                            element["text"]["text"] = _unescape_html(
                                element["text"]["text"]
                            )

                        button_value = element.get("value", "")
                        button_q_idx, button_label = button_value.split(":", 1)

                        # Set style based on selection
                        if button_q_idx == q_idx and button_label == _button_selections[
                            thread_id
                        ].get(q_idx):
                            element["style"] = "primary"
                        else:
                            element.pop("style", None)  # Remove style (default)

        # Update message
        client.chat_update(
            channel=body["channel"]["id"],
            ts=message["ts"],
            blocks=blocks,
            text="I have some questions:",
        )
    except Exception as e:
        logger.error(f"Failed to update button state: {e}")


@app.action(re.compile(r"^submit_answer_.*"))
def handle_answer_submit(ack, body, client):
    """Handle answer submission for AskUserQuestion."""
    ack()

    thread_id = body["actions"][0]["value"]
    state_values = body["state"]["values"]

    logger.info(f"[SUBMIT] thread_id={thread_id}")
    logger.info(f"[SUBMIT] state_values keys: {list(state_values.keys())}")
    logger.info(f"[SUBMIT] _button_selections: {_button_selections.get(thread_id, {})}")

    # Extract answers from form
    answers = {}

    # Count questions by looking at text blocks (every question has a text input)
    # and button selections
    max_questions = 10  # Safety limit

    for q_idx in range(max_questions):
        question_block = state_values.get(f"question_{q_idx}")
        text_block = state_values.get(f"text_{q_idx}")
        has_button_selection = (
            thread_id in _button_selections
            and str(q_idx) in _button_selections[thread_id]
        )

        # If no data for this question, we're done
        if not question_block and not text_block and not has_button_selection:
            # Check if there might be more questions (sparse data)
            # If we haven't found any questions yet, keep looking
            if q_idx > 0 and not answers:
                continue
            elif q_idx > len(answers) + 2:  # Allow some gaps
                break
            continue

        # Get selected value (checkboxes)
        selected = None
        if question_block:
            for action_id, action_data in question_block.items():
                if "selected_options" in action_data:
                    # Checkboxes (multi-select)
                    selected = ", ".join(
                        [opt["value"] for opt in action_data["selected_options"]]
                    )

        # Check for button selection (single-select toggle buttons)
        if not selected and has_button_selection:
            selected = _button_selections[thread_id][str(q_idx)]

        # Check for text input (comment)
        text_value = None
        if text_block:
            for action_id, action_data in text_block.items():
                text_value = action_data.get("value")

        # Combine selection + comment if both provided
        if selected and text_value:
            # Both: use " // " separator (unlikely to appear in labels)
            answer = f"{selected} // {text_value}"
        elif text_value:
            # Only text (custom answer)
            answer = text_value
        else:
            # Only selection
            answer = selected

        # Store answer with index-based key (server will match by index)
        if answer:
            answers[f"question_{q_idx}"] = answer
            logger.info(f"[SUBMIT] question_{q_idx} = {answer}")

    logger.info(f"[SUBMIT] Final answers: {answers}")

    # Clean up button selections
    if thread_id in _button_selections:
        del _button_selections[thread_id]

    # Send answers to server
    try:
        response = requests.post(
            f"{SRE_AGENT_URL}/answer",
            json={"thread_id": thread_id, "answers": answers},
            timeout=5,
        )

        if response.status_code == 200:
            # Get user who submitted
            user_id = body.get("user", {}).get("id")

            # Build Q&A summary with user mention
            questions = _pending_questions.get(thread_id, [])
            summary_blocks = _build_submitted_answer_blocks(
                questions, answers, client, body, user_id
            )

            # Clean up stored data
            if thread_id in _pending_questions:
                del _pending_questions[thread_id]
            if thread_id in _question_messages:
                del _question_messages[thread_id]

            # Update message to show submission with Q&A summary
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text="Answer submitted!",
                blocks=summary_blocks,
            )
        else:
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text="Failed to submit answer",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"❌ Failed to submit: {response.text}",
                        },
                    }
                ],
            )
    except Exception as e:
        logger.error(f"Failed to send answer: {e}")
        # Clean up on error too
        if thread_id in _pending_questions:
            del _pending_questions[thread_id]
        try:
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text="Error submitting answer",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"❌ Error: {str(e)}"},
                    }
                ],
            )
        except:
            pass


def _build_submitted_answer_blocks(
    questions: list, answers: dict, client, body, user_id: str = None
) -> list:
    """Build blocks showing the submitted Q&A summary with checkmark image and user mention."""
    from asset_manager import get_asset_file_id

    # Get team ID for asset loading
    team_id = body.get("team", {}).get("id")

    # Try to get checkmark image
    done_file_id = None
    try:
        done_file_id = get_asset_file_id(client, team_id, "done")
    except Exception as e:
        logger.warning(f"Failed to load done asset: {e}")

    blocks = []

    # Header with checkmark and user mention
    if user_id:
        header_text = f"*Answer submitted by <@{user_id}>!* Processing your response..."
    else:
        header_text = "*Answer submitted!* Processing your response..."

    header_elements = []
    if done_file_id:
        header_elements.append(
            {"type": "image", "slack_file": {"id": done_file_id}, "alt_text": "Done"}
        )
    header_elements.append({"type": "mrkdwn", "text": header_text})

    blocks.append({"type": "context", "elements": header_elements})

    # Q&A Summary
    if questions:
        blocks.append({"type": "divider"})

        for q_idx, q in enumerate(questions):
            header = q.get("header", f"Question {q_idx + 1}")
            question_text = q.get("question", "")
            answer = answers.get(f"question_{q_idx}", "")

            # Parse answer - check for "Selection // comment" format
            if answer:
                if " // " in answer:
                    parts = answer.split(" // ", 1)
                    selection = parts[0]
                    comment = parts[1]
                    answer_text = f"A: `{selection}`\n_Comment: {comment}_"
                else:
                    answer_text = f"A: `{answer}`"
            else:
                answer_text = "A: _(no answer)_"

            # Format: Header + Question + Answer
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{header}*\nQ: {question_text}\n{answer_text}",
                    },
                }
            )

    return blocks


def _extract_full_read_content(tool_output) -> str:
    """Extract full content from Read tool output."""
    import ast
    import json

    # Try parsing as JSON
    try:
        if isinstance(tool_output, str):
            data = json.loads(tool_output)
        else:
            data = tool_output

        # Handle nested structure
        if isinstance(data, dict):
            if "file" in data and "content" in data["file"]:
                return data["file"]["content"]
            elif "content" in data:
                return data["content"]
    except (json.JSONDecodeError, TypeError):
        pass

    # Try parsing as Python dict repr
    try:
        if isinstance(tool_output, str) and tool_output.strip().startswith("{"):
            data = ast.literal_eval(tool_output)
            if isinstance(data, dict):
                if "file" in data and "content" in data["file"]:
                    return data["file"]["content"]
                elif "content" in data:
                    return data["content"]
    except (ValueError, SyntaxError):
        pass

    # Fallback: return as-is
    return str(tool_output) if tool_output else ""


def _extract_full_write_content(tool_output) -> str:
    """Extract full content from Write tool output."""
    import ast
    import json

    # Try parsing as JSON
    try:
        if isinstance(tool_output, str):
            data = json.loads(tool_output)
        else:
            data = tool_output

        # Handle nested structure - Write output has 'content' field
        if isinstance(data, dict):
            if "content" in data:
                return data["content"]
            # Fallback to other common keys
            for key in ["text", "body", "data", "fileContent"]:
                if key in data and data[key]:
                    val = data[key]
                    if isinstance(val, str):
                        return val
    except (json.JSONDecodeError, TypeError):
        pass

    # Try parsing as Python dict repr
    try:
        if isinstance(tool_output, str) and tool_output.strip().startswith("{"):
            data = ast.literal_eval(tool_output)
            if isinstance(data, dict):
                if "content" in data:
                    return data["content"]
                # Fallback to other common keys
                for key in ["text", "body", "data", "fileContent"]:
                    if key in data and data[key]:
                        val = data[key]
                        if isinstance(val, str):
                            return val
    except (ValueError, SyntaxError):
        pass

    # Fallback: return as-is
    return str(tool_output) if tool_output else ""


@app.action("feedback")
def handle_feedback(ack, body, client):
    """Handle feedback button clicks."""
    ack()
    action = body.get("actions", [{}])[0]
    value = action.get("value", "")
    message_ts = body.get("message", {}).get("ts")
    channel_id = body.get("channel", {}).get("id")

    if value == "positive":
        logger.info(f"Positive feedback for message {message_ts}")
    else:
        logger.info(f"Negative feedback for message {message_ts}")

    # Optionally update the message to show feedback was received
    # For now, just acknowledge


# Keep simple examples for testing
@app.message("hello")
def message_hello(message, say):
    """Respond to messages containing 'hello'."""
    say(
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Hey there <@{message['user']}>!"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Click Me"},
                    "action_id": "button_click",
                },
            }
        ],
        text=f"Hey there <@{message['user']}>!",
    )


@app.action("button_click")
def action_button_click(body, ack, say):
    """Handle button click action."""
    ack()
    say(f"<@{body['user']['id']}> clicked the button")


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("IncidentFox Slack Bot v2.0.0")
    logger.info("=" * 50)
    logger.info("Mode: Socket Mode")
    logger.info(f"SRE Agent URL: {SRE_AGENT_URL}")
    logger.info("Starting...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
