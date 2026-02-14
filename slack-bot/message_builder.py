#!/usr/bin/env python3
"""
Message Builder - Slack Block Kit builders for IncidentFox

Constructs Block Kit layouts for different message states:
- Progress messages (in-flight investigation)
- Final messages (completed with result)
- Error messages

Uses hierarchical display: thoughts with nested tool calls.
"""

import logging
import re
from typing import List, Optional

from markdown_utils import slack_mrkdwn
from table_converter import PreformattedText, extract_and_convert_all_tables

logger = logging.getLogger(__name__)

# Em space character for consistent indentation in Slack (doesn't collapse)
EM_SPACE = "\u2003"


def _strip_file_links(text: str, files: Optional[List[dict]] = None) -> str:
    """
    Strip markdown file links from text.

    Files are uploaded as Slack attachments directly to the thread,
    so we don't need to render them in blocks. We just strip the markdown
    to keep the text clean.

    Pattern: [description](./path/to/file.ext) - but NOT images (which start with !)

    Args:
        text: Text that may contain [desc](path) markdown links
        files: Optional list of files that were uploaded (for reference)

    Returns:
        Text with file links stripped
    """
    if not text:
        return text

    # Pattern to match markdown links (not images): [text](path)
    # Uses negative lookbehind to exclude ![...](...)
    # Also exclude http/https URLs
    file_link_pattern = r"(?<!!)\[([^\]]+)\]\((?!https?://|mailto:|tel:|#)([^)]+)\)"

    # Strip file links from text
    cleaned_text = re.sub(file_link_pattern, "", text)

    # Clean up extra whitespace that might result from removal
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)

    return cleaned_text


def _process_text_with_images(text: str, images: Optional[List[dict]] = None) -> list:
    """
    Process text that may contain markdown image references.

    Splits text on image references and returns a list of segments:
    - {"type": "text", "content": "..."} for text parts
    - {"type": "image", "file_id": "...", "alt": "..."} for image parts

    IMPORTANT: This must be called BEFORE slack_mrkdwn() to prevent
    image markdown from being converted to link syntax.

    Args:
        text: Text that may contain ![alt](path) markdown
        images: List of image dicts with {path, file_id, alt, media_type}

    Returns:
        List of segments in order of appearance
    """
    import logging

    logger = logging.getLogger(__name__)

    # Pattern to match markdown images: ![alt](path)
    image_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"

    if not images:
        # Even without images, we need to strip image markdown to prevent
        # slack_mrkdwn() from converting it to <path|alt> link format
        cleaned_text = re.sub(image_pattern, "", text)
        logger.debug(
            "_process_text_with_images: No images provided, stripped image markdown from text"
        )
        return [{"type": "text", "content": cleaned_text}]

    # Build a map of path -> image info
    # Normalize paths to handle ./path, /path, path variations
    path_to_image = {}
    for img in images:
        path = img.get("path", "")
        if path and img.get("file_id"):
            # Store with original path
            path_to_image[path] = img
            # Also map without leading ./
            if path.startswith("./"):
                path_to_image[path[2:]] = img
            # Also map with leading ./
            elif not path.startswith("./"):
                path_to_image[f"./{path}"] = img

    logger.debug(
        f"_process_text_with_images: Built path map with {len(path_to_image)} entries: {list(path_to_image.keys())}"
    )

    if not path_to_image:
        logger.warning(
            "_process_text_with_images: No valid images with file_id, returning text as-is"
        )
        return [{"type": "text", "content": text}]

    # Pattern to match markdown images: ![alt](path)
    pattern = r"!\[([^\]]*)\]\(([^)]+)\)"

    segments = []
    last_end = 0

    for match in re.finditer(pattern, text):
        alt = match.group(1)
        path = match.group(2)

        # Add text before this match
        if match.start() > last_end:
            text_before = text[last_end : match.start()]
            if text_before and text_before.strip():
                segments.append({"type": "text", "content": text_before})

        # Check if this is a local image we have
        img_info = path_to_image.get(path)
        if img_info:
            logger.debug(
                f"_process_text_with_images: Matched image path '{path}' -> file_id={img_info['file_id']}"
            )
            segments.append(
                {
                    "type": "image",
                    "file_id": img_info["file_id"],
                    "alt": alt or img_info.get("alt", "Image"),
                }
            )
        else:
            # Remove the markdown if we don't have the image (don't show broken refs)
            # This prevents slack_mrkdwn from converting it to <path|image> link
            logger.warning(
                f"_process_text_with_images: Image path '{path}' not found in path_to_image map (available: {list(path_to_image.keys())})"
            )
            pass

        last_end = match.end()

    # Add remaining text
    if last_end < len(text):
        remaining = text[last_end:]
        if remaining and remaining.strip():
            segments.append({"type": "text", "content": remaining})

    return segments


def _render_image_block(image_ref: str, alt: str) -> dict:
    """
    Create a Slack image block using either file_id (Slack-uploaded) or image_url (external).

    Args:
        image_ref: Either a Slack file_id (starts with 'F') or an external image URL
        alt: Alt text for the image

    Returns:
        Slack image block dict
    """
    if image_ref.startswith("F"):
        # Slack-uploaded file - use slack_file format
        return {
            "type": "image",
            "slack_file": {"id": image_ref},
            "alt_text": alt[:2000],
        }
    else:
        # External URL - use image_url format
        return {
            "type": "image",
            "image_url": image_ref,
            "alt_text": alt[:2000],
        }


def build_progress_message(
    thoughts: Optional[List] = None,
    current_tool: Optional[dict] = None,
    loading_url: Optional[str] = None,
    done_url: Optional[str] = None,
    thread_id: Optional[str] = None,
    message_ts: Optional[str] = None,
    trigger_user_id: Optional[str] = None,
    trigger_text: Optional[str] = None,
) -> list:
    """
    Build Block Kit blocks for an in-progress investigation.

    Layout (hierarchical - thoughts with nested tools):
    ✓ Completed thought 1
      ↳ Used 2 tools
    ✓ Completed thought 2
      ↳ Used 5 tools

    ◐ Current thought...
      ↳ ✓ Run: `ls`
      ↳ ◐ Read: `file.py`
        +N more

    [View Session]
    """
    blocks = []
    thoughts = thoughts or []

    # Use URL parameters (ignore deprecated file_id params)
    loading_icon = loading_url
    done_icon = done_url

    # Add trigger context if this was a prompt-initiated investigation (e.g. Coralogix)
    if trigger_user_id and trigger_text:
        display_text = (
            trigger_text[:80] + "..." if len(trigger_text) > 80 else trigger_text
        )
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_Triggered by <@{trigger_user_id}>: {display_text}_",
                    }
                ],
            }
        )

    # Get last 3 thoughts for display
    display_thoughts = thoughts[-3:] if len(thoughts) > 3 else thoughts

    for i, thought in enumerate(display_thoughts):
        is_current = i == len(display_thoughts) - 1  # Last one is current
        is_completed = thought.completed

        # Build thought line - show full text (may wrap to multiple lines)
        thought_text = slack_mrkdwn(thought.text)

        # Choose icon based on state
        if is_completed:
            icon_url = done_icon
            icon_alt = "Done"
        else:
            icon_url = loading_icon
            icon_alt = "Loading"

        # Build thought block
        thought_elements = []
        if icon_url:
            thought_elements.append(
                {
                    "type": "image",
                    "image_url": icon_url,
                    "alt_text": icon_alt,
                }
            )
        thought_elements.append({"type": "mrkdwn", "text": thought_text})
        blocks.append({"type": "context", "elements": thought_elements})

        tool_count = len(thought.tools)

        # For completed thoughts: show tool info
        # 1 tool: show actual tool name (more informative)
        # 2+ tools: show count summary (avoid clutter)
        if is_completed and tool_count == 1:
            tool = thought.tools[0]
            tool_text = _format_tool_for_thought(tool, thought_completed=is_completed)
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"   ↳  ✓ {tool_text}"}],
                }
            )
        elif is_completed and tool_count > 1:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"   ↳  Used {tool_count} tools"}
                    ],
                }
            )

        # For current (non-completed) thought: show actual tools
        # Option C: Per-subagent sections - group tools by subagent for clarity
        elif is_current and not is_completed and thought.tools:
            tools = thought.tools

            # Separate tools into categories:
            # 1. Top-level tools (non-Task, no parent)
            # 2. Subagent tools (Task tools) with their children
            top_level_tools = []
            subagents = {}  # tool_use_id -> {"task": tool, "children": [...]}

            for tool in tools:
                tool_name = tool.get("name", "")
                parent_id = tool.get("parent_tool_use_id")
                tool_use_id = tool.get("tool_use_id")

                if tool_name == "Task" and tool_use_id:
                    # This is a subagent - create entry for it
                    if tool_use_id not in subagents:
                        subagents[tool_use_id] = {"task": tool, "children": []}
                    else:
                        subagents[tool_use_id]["task"] = tool
                elif parent_id and parent_id in subagents:
                    # This tool belongs to a subagent
                    subagents[parent_id]["children"].append(tool)
                elif parent_id:
                    # Parent not seen yet - create placeholder
                    if parent_id not in subagents:
                        subagents[parent_id] = {"task": None, "children": []}
                    subagents[parent_id]["children"].append(tool)
                else:
                    # Top-level tool
                    top_level_tools.append(tool)

            # Helper to render a single tool line
            def render_tool(tool, indent_level=1):
                tool_text = _format_tool_for_thought(
                    tool, thought_completed=is_completed
                )
                is_running = tool.get("running", False)
                tool_image_url = tool.get("_image_url")  # URL for image output

                icon_element = None
                if is_running and loading_icon:
                    icon_element = {
                        "type": "image",
                        "image_url": loading_icon,
                        "alt_text": "Loading",
                    }
                elif not is_running and done_icon:
                    icon_element = {
                        "type": "image",
                        "image_url": done_icon,
                        "alt_text": "Done",
                    }

                # Indentation based on level (1=normal, 2=nested under subagent)
                if indent_level == 2:
                    arrow_text = "      ↳" if icon_element else "      ↳  "
                else:
                    arrow_text = "   ↳" if icon_element else "   ↳  "

                tool_elements = [{"type": "mrkdwn", "text": arrow_text}]
                if icon_element:
                    tool_elements.append(icon_element)
                tool_elements.append({"type": "mrkdwn", "text": tool_text})

                if tool_image_url and not is_running:
                    tool_elements.append(
                        {
                            "type": "image",
                            "image_url": tool_image_url,
                            "alt_text": "Image output",
                        }
                    )

                return {"type": "context", "elements": tool_elements}

            # Show "+N older" at TOP if we're hiding tools
            # We'll show: last 2 top-level + each subagent with last 2 children
            max_top_level = 2
            max_children_per_subagent = 2

            # Calculate what we'll display
            display_top_level = (
                top_level_tools[-max_top_level:]
                if len(top_level_tools) > max_top_level
                else top_level_tools
            )
            hidden_top_level = len(top_level_tools) - len(display_top_level)

            # Count hidden in subagents
            hidden_in_subagents = 0
            for sa_id, sa_data in subagents.items():
                children = sa_data["children"]
                if len(children) > max_children_per_subagent:
                    hidden_in_subagents += len(children) - max_children_per_subagent

            total_hidden = hidden_top_level + hidden_in_subagents
            if total_hidden > 0:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"{EM_SPACE}{EM_SPACE}{EM_SPACE}↳{EM_SPACE}{EM_SPACE}+{total_hidden} older",
                            }
                        ],
                    }
                )

            # Render top-level tools first
            for tool in display_top_level:
                blocks.append(render_tool(tool, indent_level=1))

            # Render each subagent section
            for sa_id, sa_data in subagents.items():
                task_tool = sa_data["task"]
                children = sa_data["children"]

                # Show subagent header (the Task tool itself)
                if task_tool:
                    blocks.append(render_tool(task_tool, indent_level=1))

                # Show last N children indented
                display_children = (
                    children[-max_children_per_subagent:]
                    if len(children) > max_children_per_subagent
                    else children
                )
                for child in display_children:
                    blocks.append(render_tool(child, indent_level=2))

    # Safety check: Ensure we don't exceed Slack's 50 block limit
    MAX_BLOCKS = 50
    view_session_blocks = 1

    if len(blocks) >= MAX_BLOCKS - view_session_blocks:
        # Truncate to make room for View Session button
        blocks = blocks[: MAX_BLOCKS - view_session_blocks - 1]
        # Add truncation note
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "_Progress truncated. See full session in View Session._",
                    }
                ],
            }
        )
        logger.warning(f"Progress message truncated. Had {len(blocks)} blocks.")

    # View Session button - use message_ts as unique key for each message
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Session"},
                    "action_id": "view_investigation_session",
                    "value": message_ts or thread_id or "unknown",
                }
            ],
        }
    )

    return blocks


def build_final_message(
    result_text: str = "",
    thoughts: Optional[List] = None,
    success: bool = True,
    error: Optional[str] = None,
    done_url: Optional[str] = None,
    thread_id: Optional[str] = None,
    message_ts: Optional[str] = None,
    result_images: Optional[List[dict]] = None,
    result_files: Optional[List[dict]] = None,
    trigger_user_id: Optional[str] = None,
    trigger_text: Optional[str] = None,
    auto_listen_channel_id: Optional[str] = None,
    auto_listen_thread_ts: Optional[str] = None,
) -> list:
    """
    Build Block Kit blocks for a completed investigation.

    Layout:
    ✓ Thought 1
    ↳ Used 2 tools
    ✓ Thought 2
    ↳ Used 5 tools

    [Result text - last thought combined with final result]
    [Images (if any)]
    [📎 N file(s) attached (if any)]

    [View Session] [Feedback buttons]

    Args:
        result_text: The final result text (may contain markdown image/file refs)
        thoughts: List of thought objects
        success: Whether the investigation succeeded
        error: Error message if any
        done_url: URL for done icon (S3-hosted)
        thread_id: Thread ID for View Session button
        result_images: List of image dicts with {path, file_id/image_url, alt, media_type}
    """
    blocks = []
    thoughts = thoughts or []

    # Use URL parameter (ignore deprecated file_id param)
    done_icon = done_url

    # Add trigger context if this was a prompt-initiated investigation (e.g. Coralogix)
    if trigger_user_id and trigger_text:
        display_text = (
            trigger_text[:80] + "..." if len(trigger_text) > 80 else trigger_text
        )
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_Triggered by <@{trigger_user_id}>: {display_text}_",
                    }
                ],
            }
        )

    # Error state
    if error:
        error_elements = []
        if done_icon:
            error_elements.append(
                {
                    "type": "image",
                    "image_url": done_icon,
                    "alt_text": "Done",
                }
            )
        error_elements.append(
            {"type": "mrkdwn", "text": f"*Error:* {slack_mrkdwn(error)}"}
        )
        blocks.append({"type": "context", "elements": error_elements})
        blocks.extend(_create_feedback_blocks())
        return blocks

    # Show thoughts EXCEPT the last one (which we'll combine with final result)
    # Only show if there's more than 1 thought
    if len(thoughts) > 1:
        display_thoughts = thoughts[-3:-1] if len(thoughts) > 3 else thoughts[:-1]

        for thought in display_thoughts:
            thought_text = slack_mrkdwn(thought.text)

            thought_elements = []
            if done_icon:
                thought_elements.append(
                    {
                        "type": "image",
                        "image_url": done_icon,
                        "alt_text": "Done",
                    }
                )
            thought_elements.append({"type": "mrkdwn", "text": thought_text})
            blocks.append({"type": "context", "elements": thought_elements})

            # Add tool count summary
            tool_count = len(thought.tools)
            if tool_count == 1:
                tool = thought.tools[0]
                tool_text = _format_tool_for_thought(tool, thought_completed=True)
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": f"   ↳  ✓ {tool_text}"}
                        ],
                    }
                )
            elif tool_count > 1:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": f"   ↳  Used {tool_count} tools"}
                        ],
                    }
                )

    # Extract clean final text - strip out all previous thoughts from result
    final_text = _extract_clean_result(result_text, thoughts)

    # Calculate dynamic block budget (Slack limit: 50 blocks)
    MAX_BLOCKS = 50
    used_blocks = len(blocks)
    view_session_blocks = 1  # View Session button
    feedback_blocks = 1  # Feedback buttons
    truncation_note_blocks = 1  # Truncation note (if needed)

    # Reserve space for footer blocks
    max_result_blocks = (
        MAX_BLOCKS
        - used_blocks
        - view_session_blocks
        - feedback_blocks
        - truncation_note_blocks
    )

    # Track if result was truncated
    was_truncated = False

    # Render the combined final text (with embedded images if any)
    if final_text and max_result_blocks > 0:
        # First, strip file links (files are uploaded as Slack attachments separately)
        final_text = _strip_file_links(final_text, result_files)

        # Then, process text for inline images
        content_segments = _process_text_with_images(final_text, result_images)

        # Debug logging
        logger.info(f"Final text length: {len(final_text)}")
        logger.info(f"Found {len(content_segments)} content segments (text + images)")
        logger.info(f"Max result blocks: {max_result_blocks}")

        # Process each content segment (text or image)
        for content_seg in content_segments:
            if max_result_blocks <= 0:
                was_truncated = True
                break

            if content_seg["type"] == "image":
                # Render image block
                blocks.append(
                    _render_image_block(content_seg["file_id"], content_seg["alt"])
                )
                max_result_blocks -= 1
            else:
                # Text segment - extract tables and process
                text_content = content_seg["content"]
                segments = extract_and_convert_all_tables(text_content)

                # Process each segment (alternating text and table blocks)
                for segment in segments:
                    if max_result_blocks <= 0:
                        was_truncated = True
                        break

                    if isinstance(segment, dict):
                        # This is a native Slack table block
                        blocks.append(segment)
                        max_result_blocks -= 1
                    elif isinstance(segment, PreformattedText):
                        # This is pre-formatted text (already in Slack mrkdwn format) - skip markdown conversion
                        text_blocks, text_truncated = _add_text_blocks(
                            segment.text, max_blocks=max_result_blocks
                        )
                        blocks.extend(text_blocks)
                        was_truncated = was_truncated or text_truncated
                        max_result_blocks -= len(text_blocks)
                    elif isinstance(segment, str) and segment.strip():
                        # This is raw text - needs markdown conversion
                        formatted_text = slack_mrkdwn(segment)
                        text_blocks, text_truncated = _add_text_blocks(
                            formatted_text, max_blocks=max_result_blocks
                        )
                        blocks.extend(text_blocks)
                        was_truncated = was_truncated or text_truncated
                        max_result_blocks -= len(text_blocks)
    elif max_result_blocks <= 0:
        # No room for result blocks at all
        was_truncated = True
        logger.warning(f"No room for result blocks. Used {used_blocks} blocks already.")

    # Add truncation note if needed
    if was_truncated:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "_Response truncated. See full content in View Session._",
                    }
                ],
            }
        )

    # Add file attachment note if there are files
    if result_files:
        file_count = len(result_files)
        file_names = [f.get("filename", "file") for f in result_files[:3]]
        if file_count > 3:
            file_list = ", ".join(file_names) + f" +{file_count - 3} more"
        else:
            file_list = ", ".join(file_names)
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"📎 _{file_count} file(s) attached: {file_list}_",
                    }
                ],
            }
        )

    # View Session button - use message_ts as unique key for each message
    action_elements = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "View Session"},
            "action_id": "view_investigation_session",
            "value": message_ts or thread_id or "unknown",
        }
    ]

    # Add "Stop listening" button when auto-listen is active and investigation succeeded
    if auto_listen_channel_id and auto_listen_thread_ts and success:
        import json as _json

        action_elements.append(
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "\U0001f507 Stop listening",
                },
                "action_id": "stop_listening",
                "value": _json.dumps(
                    {
                        "channel_id": auto_listen_channel_id,
                        "thread_ts": auto_listen_thread_ts,
                    }
                ),
            }
        )

    blocks.append({"type": "actions", "elements": action_elements})

    # Feedback buttons
    blocks.extend(_create_feedback_blocks())

    return blocks


def _format_tool_for_thought(tool: dict, thought_completed: bool = False) -> str:
    """Format a tool call for display under a thought.

    Args:
        tool: The tool dict from the thought
        thought_completed: Whether the containing thought is completed
    """
    name = tool.get("name", "Unknown")
    tool_input = tool.get("input", {})
    is_running = tool.get("running", False)

    # Format based on tool type using pipe separator
    if name == "Bash":
        cmd = tool_input.get("command", "")
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        return f"Bash | `{cmd}`"

    elif name == "Read":
        file_path = tool_input.get("file_path", "")
        if len(file_path) > 50:
            file_path = "..." + file_path[-47:]
        return f"Read | `{file_path}`"

    elif name == "Write":
        file_path = tool_input.get("file_path", "")
        if len(file_path) > 50:
            file_path = "..." + file_path[-47:]
        return f"Write | `{file_path}`"

    elif name == "Edit":
        file_path = tool_input.get("file_path", "")
        if len(file_path) > 50:
            file_path = "..." + file_path[-47:]
        return f"Update | `{file_path}`"

    elif name == "Glob":
        # Format like Claude Code: Search | pattern: "*.py"
        pattern = tool_input.get("pattern", "")
        if len(pattern) > 40:
            pattern = pattern[:37] + "..."
        return f"Search | pattern: `{pattern}`"

    elif name == "Grep":
        # Format like Claude Code: Search | pattern: "TODO", type: "py"
        pattern = tool_input.get("pattern", "")
        if len(pattern) > 30:
            pattern = pattern[:27] + "..."
        parts = [f"pattern: `{pattern}`"]
        if tool_input.get("type"):
            parts.append(f'type: `{tool_input["type"]}`')
        if tool_input.get("head_limit"):
            parts.append(f'head_limit: {tool_input["head_limit"]}')
        return f"Search | {', '.join(parts)}"

    elif name == "Task":
        desc = tool_input.get("description", "subtask")
        if len(desc) > 50:
            desc = desc[:47] + "..."
        return f"Subagent | {desc}"

    elif name == "TodoWrite":
        # Show number of tasks if available
        todos = tool_input.get("todos", [])
        if todos:
            return f"Tasks | {len(todos)} item{'s' if len(todos) != 1 else ''}"
        return "Tasks"

    elif name == "WebFetch":
        url = tool_input.get("url", "")
        if len(url) > 50:
            url = url[:47] + "..."
        return f"Fetch | `{url}`"

    elif name == "WebSearch":
        query = tool_input.get("query", "")
        if len(query) > 50:
            query = query[:47] + "..."
        return f"Search | `{query}`"

    elif name == "AskUserQuestion":
        questions = tool_input.get("questions", [])
        num_questions = len(questions)
        q_word = "question" if num_questions == 1 else "questions"

        # Check if there's output with answers
        output = tool.get("output", "")
        timed_out = tool.get("timed_out", False)

        if output and "answers" in str(output):
            return f"AskUserQuestion | {num_questions} {q_word} → answered"
        elif timed_out or (thought_completed and not output):
            # Explicitly timed out or thought completed without output
            return f"AskUserQuestion | {num_questions} {q_word} (timed out)"
        elif is_running:
            # Still waiting for user response
            return f"AskUserQuestion | {num_questions} {q_word} (waiting...)"
        else:
            return f"AskUserQuestion | {num_questions} {q_word}"

    # Handle MCP tools: mcp__server__toolname format
    elif name.startswith("mcp__"):
        parts = name.split(
            "__", 2
        )  # Split into max 3 parts: "mcp", "server", "toolname"
        if len(parts) == 3:
            server = parts[1]
            tool = parts[2]

            # Format server name nicely (capitalize)
            server_display = server.replace("_", " ").title()

            # Format tool name nicely (remove common prefixes, clean up underscores)
            tool_clean = tool
            for prefix in [f"{server}_", "get_", "list_", "search_", "query_"]:
                if tool_clean.startswith(prefix):
                    tool_clean = tool_clean[len(prefix) :]
                    break

            tool_display = tool_clean.replace("_", " ")

            # Try to extract key parameter for context
            params_display = ""
            if tool_input:
                # Show first meaningful parameter
                if "service" in tool_input or "service_name" in tool_input:
                    svc = tool_input.get("service") or tool_input.get("service_name")
                    params_display = f" `{svc}`"
                elif "query" in tool_input:
                    q = str(tool_input["query"])
                    if len(q) < 40:
                        params_display = f" `{q}`"
                elif "pod_name" in tool_input:
                    params_display = f" `{tool_input['pod_name']}`"
                elif "namespace" in tool_input:
                    params_display = f" `{tool_input['namespace']}`"

            return f"{server_display} | {tool_display}{params_display}"

        # Fallback if parsing fails
        return name.replace("mcp__", "").replace("__", " | ").replace("_", " ")

    else:
        return f"{name}..."


def _add_text_blocks(
    text: str, max_len: int = 2900, max_blocks: Optional[int] = None
) -> tuple:
    """
    Add section blocks for text, splitting on paragraphs and dividers.

    Strategy:
    1. Split on horizontal rules (---) → divider blocks
    2. Within each segment, split on double newlines (\n\n) → separate section blocks
    3. This creates natural spacing between paragraphs (Slack-native way)
    4. If max_blocks is set, truncate and return truncation status

    Returns:
        tuple: (blocks, was_truncated)
    """
    import re

    blocks = []

    # Split on horizontal rules (---) - they become divider blocks
    # Pattern: newlines + --- + newlines, but NOT when:
    # - Inside code blocks (between ``` markers)
    # - Part of a table separator (contains | characters)

    # First, protect code blocks by temporarily replacing them
    # Code blocks should NEVER be split - keep them intact
    code_blocks = []

    def save_code_block(match):
        code_blocks.append(match.group(0))
        return f"___CODE_BLOCK_{len(code_blocks)-1}___"

    text = re.sub(r"```[\s\S]*?```", save_code_block, text)

    # Now split on standalone horizontal rules (not in tables)
    # Only match --- when it's on its own line without pipe characters
    segments = re.split(r"\n+(?!.*\|)---+(?!.*\|)\n+", text)

    for i, segment in enumerate(segments):
        segment = segment.strip()
        if not segment:
            continue

        # Split segment on double newlines to create separate blocks per paragraph
        # BUT: Don't split code block placeholders
        paragraphs = segment.split("\n\n")

        for para in paragraphs:
            # Strip trailing whitespace but preserve leading spaces/Em spaces (for indented content like nested lists)
            para = para.rstrip()
            # Strip leading only if it doesn't start with spaces or Em spaces (which indicate indentation)
            if not para.startswith(" ") and not para.startswith(EM_SPACE):
                para = para.lstrip()

            if not para:
                continue

            # Restore code blocks in this paragraph
            for j, code_block in enumerate(code_blocks):
                para = para.replace(f"___CODE_BLOCK_{j}___", code_block)

            # Check if we've hit the block limit
            if max_blocks and len(blocks) >= max_blocks:
                return blocks, True  # Truncated

            # Check if this is a header marker (H1/H2 headings)
            if para.startswith("__HEADER__") and para.endswith("__HEADER__"):
                # Extract header text and unescape HTML entities
                # Header blocks use plain_text, not mrkdwn, so we need to unescape
                header_text = para[10:-10].strip()  # Remove __HEADER__ markers
                header_text = (
                    header_text.replace("&amp;", "&")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                )
                blocks.append(
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": header_text},
                    }
                )
            # Add text blocks for this paragraph
            elif len(para) > max_len:
                chunks = _split_text(para, max_len)
                for chunk in chunks:
                    if max_blocks and len(blocks) >= max_blocks:
                        return blocks, True  # Truncated
                    blocks.append(
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": chunk},
                        }
                    )
            else:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": para},
                    }
                )

        # Add divider between segments (except after the last one)
        if i < len(segments) - 1:
            if max_blocks and len(blocks) >= max_blocks:
                return blocks, True  # Truncated
            blocks.append({"type": "divider"})

    # Post-process: Combine consecutive section blocks to reduce block count
    # This helps stay under Slack's 50 block limit
    blocks = _combine_section_blocks(blocks)

    return blocks, False  # Not truncated


def _combine_section_blocks(blocks: list) -> list:
    """
    Combine consecutive section blocks to reduce total block count.

    Only applies compression if we're over Slack's 50 block limit.
    This preserves semantic meaning and visual separation for normal messages.

    Strategy:
    1. Check if blocks > 50, if not, return as-is
    2. Combine small consecutive section blocks (< 600 chars combined)
    3. Keep bold subheadings with their following content
    4. Never combine across dividers (those are intentional breaks)
    5. Respect max 3000 char limit per block

    Args:
        blocks: List of Slack blocks

    Returns:
        List of combined blocks (or original if under limit)
    """
    # Only compress if we're over the 50 block limit
    if len(blocks) <= 50:
        return blocks

    combined = []
    i = 0

    while i < len(blocks):
        current = blocks[i]

        # If it's not a section block, just add it
        if current.get("type") != "section":
            combined.append(current)
            i += 1
            continue

        # Try to combine with next blocks
        combined_text = current["text"]["text"]
        j = i + 1

        # Look ahead and combine consecutive section blocks
        while j < len(blocks):
            next_block = blocks[j]

            # Stop at dividers or non-section blocks
            if next_block.get("type") != "section":
                break

            next_text = next_block["text"]["text"]
            potential_combined = combined_text + "\n\n" + next_text

            # Don't exceed Slack's 3000 char limit per text block
            if len(potential_combined) >= 3000:
                break

            # Combine if:
            # 1. Current block is a bold subheading (heading followed by content)
            #    Pattern: starts with * and is short (< 100 chars)
            # 2. OR both blocks are small (< 600 chars combined)
            current_strip = combined_text.strip()
            is_subheading = (
                current_strip.startswith("*")
                and len(combined_text) < 100
                and (current_strip.endswith("*:") or current_strip.endswith("*"))
            )
            is_small_combined = len(potential_combined) < 600

            if is_subheading or is_small_combined:
                combined_text = potential_combined
                j += 1
            else:
                break

        # Add the combined block
        combined.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": combined_text}}
        )

        i = j

    return combined


def _create_feedback_blocks() -> list:
    """Create feedback buttons."""
    return [
        {
            "type": "context_actions",
            "elements": [
                {
                    "type": "feedback_buttons",
                    "action_id": "feedback",
                    "positive_button": {
                        "text": {"type": "plain_text", "text": "Good Response"},
                        "accessibility_label": "Submit positive feedback",
                        "value": "positive",
                    },
                    "negative_button": {
                        "text": {"type": "plain_text", "text": "Bad Response"},
                        "accessibility_label": "Submit negative feedback",
                        "value": "negative",
                    },
                }
            ],
        }
    ]


def _split_text(text: str, max_len: int) -> list:
    """Split text into chunks, trying to break at newlines."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""

    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line

    if current:
        chunks.append(current)

    return chunks


def _extract_clean_result(result_text: str, thoughts: list) -> str:
    """
    Extract clean final result by stripping out all previous thoughts.

    The agent often concatenates all thoughts into the result text.
    We want to show only the LAST thought + any final content that comes after.
    """
    if not result_text:
        # No result - use last thought if available
        if thoughts:
            return thoughts[-1].text.strip()
        return ""

    result = result_text.strip()

    if not thoughts:
        return result

    # Try to find where the last thought starts in the result
    last_thought_text = thoughts[-1].text.strip()

    # Find the position of the last thought in result
    pos = result.find(last_thought_text)

    if pos != -1:
        # Found! Return from that point onwards
        return result[pos:].strip()

    # Last thought not found verbatim - try first 50 chars as a fuzzy match
    if len(last_thought_text) > 50:
        short_match = last_thought_text[:50]
        pos = result.find(short_match)
        if pos != -1:
            return result[pos:].strip()

    # Still not found - try to strip out all previous thoughts
    # by finding the longest prefix that matches concatenated thoughts
    clean_result = result
    for thought in thoughts[:-1]:  # All thoughts except the last
        thought_text = thought.text.strip()
        # Check if result starts with this thought (possibly without spaces between)
        if clean_result.startswith(thought_text):
            clean_result = clean_result[len(thought_text) :].strip()
        elif len(thought_text) > 20:
            # Try shorter match
            short = thought_text[:20]
            if clean_result.startswith(short):
                # Find where this thought likely ends
                end_pos = clean_result.find(short) + len(thought_text)
                if end_pos < len(clean_result):
                    clean_result = clean_result[end_pos:].strip()

    return clean_result if clean_result else result
