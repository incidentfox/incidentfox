"""
SSE stream processing and Slack message updates.

Handles parsing SSE events from sre-agent, building Slack Block Kit messages
for progressive investigation updates, and managing the streaming lifecycle.
"""

import json
import logging
import os
from typing import Optional

from file_handler import (
    _is_image_output,
    _upload_base64_file_to_slack,
    _upload_base64_image_to_slack,
    _upload_image_to_slack,
)
from state import (
    MessageState,
    ThoughtSection,
    _auto_listen_threads,
    _cache_timestamps,
    _cleanup_old_cache_entries,
    _investigation_cache,
    _pending_questions,
    _question_messages,
)

logger = logging.getLogger(__name__)

SRE_AGENT_URL = os.environ.get("SRE_AGENT_URL", "http://localhost:8000")
UPDATE_INTERVAL_SECONDS = 0.5


def parse_sse_event(line: str) -> Optional[dict]:
    """Parse an SSE data line into a dict."""
    if not line.startswith("data: "):
        return None
    try:
        return json.loads(line[6:])
    except json.JSONDecodeError:
        return None


def build_progress_blocks(state: MessageState, client, team_id: str) -> list:
    """Build Block Kit blocks for in-progress state."""
    from assets_config import get_asset_url
    from message_builder import build_progress_message

    # Get S3-hosted asset URLs (no per-workspace uploads needed)
    loading_url = get_asset_url("loading")
    done_url = get_asset_url("done")

    return build_progress_message(
        thoughts=state.thoughts,
        current_tool=state.current_tool,
        loading_url=loading_url,
        done_url=done_url,
        thread_id=state.thread_id,
        message_ts=state.message_ts,
        trigger_user_id=state.trigger_user_id,
        trigger_text=state.trigger_text,
    )


def build_final_blocks(state: MessageState, client, team_id: str) -> list:
    """Build Block Kit blocks for final state."""
    from assets_config import get_asset_url
    from message_builder import build_final_message

    # Get S3-hosted done icon URL
    done_url = get_asset_url("done")

    # Check if auto-listen is active for this thread
    auto_listen_active = _auto_listen_threads.get(
        (state.channel_id, state.thread_ts), False
    )

    return build_final_message(
        result_text=state.final_result or state.current_thought,
        thoughts=state.thoughts,
        success=state.error is None,
        error=state.error,
        done_url=done_url,
        thread_id=state.thread_id,
        message_ts=state.message_ts,
        result_images=state.result_images,
        result_files=state.result_files,
        trigger_user_id=state.trigger_user_id,
        trigger_text=state.trigger_text,
        auto_listen_channel_id=state.channel_id if auto_listen_active else None,
        auto_listen_thread_ts=state.thread_ts if auto_listen_active else None,
    )


def update_slack_message(
    client, state: MessageState, team_id: str, final: bool = False
):
    """Update the Slack message with current state."""
    import time

    # ALWAYS cache state for modal access (even if we skip the message update)
    # Use message_ts as key (unique per message, unlike thread_id which is shared in threads)
    _investigation_cache[state.message_ts] = state
    _cache_timestamps[state.message_ts] = time.time()
    logger.info(
        f"Cached investigation state for message_ts: {state.message_ts} (final={final}, thoughts={len(state.thoughts)})"
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
        # Regular update (using S3-hosted URLs - no caching issues)
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
