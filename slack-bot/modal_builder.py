#!/usr/bin/env python3
"""
Modal Builder - Build Slack modals for detailed investigation views
"""

import re
from typing import Any, List, Optional

from markdown_utils import slack_mrkdwn

# Em space for consistent indentation (regular spaces collapse in Slack)
EM_SPACE = "\u2003"


def _process_text_with_images(text: str, images: Optional[List[dict]] = None) -> list:
    """
    Process text that may contain markdown image references.

    Splits text on image references and returns a list of segments:
    - {"type": "text", "content": "..."} for text parts
    - {"type": "image", "file_id": "...", "alt": "..."} for image parts

    Args:
        text: Text that may contain ![alt](path) markdown
        images: List of image dicts with {path, file_id, alt, media_type}

    Returns:
        List of segments in order of appearance
    """
    import re

    # Pattern to match markdown images: ![alt](path)
    image_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"

    if not images:
        # Even without images, we need to strip image markdown to prevent
        # slack_mrkdwn() from converting it to <path|alt> link format
        cleaned_text = re.sub(image_pattern, "", text)
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

    if not path_to_image:
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
            pass

        last_end = match.end()

    # Add remaining text
    if last_end < len(text):
        remaining = text[last_end:]
        if remaining and remaining.strip():
            segments.append({"type": "text", "content": remaining})

    return segments


def _render_image_block(image_url: str, alt: str) -> dict:
    """Create a Slack image block using image_url (S3-hosted)."""
    return {
        "type": "image",
        "image_url": image_url,
        "alt_text": alt[:2000],  # Slack limit
    }


def _strip_file_links(text: str, files: Optional[List[dict]] = None) -> str:
    """
    Strip markdown file links from text.

    Files are uploaded as Slack attachments directly to the thread,
    so we don't need to render them in blocks. We just strip the markdown
    to keep the text clean.
    """
    if not text:
        return text

    # Pattern to match markdown links (not images): [text](path)
    # Uses negative lookbehind to exclude ![...](...)
    # Also exclude http/https URLs
    file_link_pattern = r"(?<!!)\[([^\]]+)\]\((?!https?://|mailto:|tel:|#)([^)]+)\)"

    # Strip file links from text
    cleaned_text = re.sub(file_link_pattern, "", text)

    # Clean up extra whitespace
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)

    return cleaned_text


def build_session_modal(
    thread_id: str,
    thoughts: List[Any],  # List of ThoughtSection objects
    result: Optional[str] = None,
    loading_url: Optional[str] = None,
    done_url: Optional[str] = None,
    page: int = 1,
    result_images: Optional[List[dict]] = None,
    result_files: Optional[List[dict]] = None,
) -> dict:
    """
    Build a modal showing the full investigation session.

    Uses the same formatting as the main message, but shows ALL thoughts and tools
    (no truncation), and includes tool inputs and outputs.

    Supports pagination when content exceeds Slack's 100 block limit.

    Args:
        thread_id: Investigation thread ID
        thoughts: List of ThoughtSection objects (hierarchical: thoughts with nested tools)
        result: Final result text
        loading_url: URL for loading.gif (S3-hosted)
        done_url: URL for done.png (S3-hosted)
        page: Page number (1-indexed, default 1)
        result_images: List of image dicts with {path, image_url, alt, media_type}
        result_files: List of file dicts with {path, filename, description}
    """
    import json
    import logging

    logger = logging.getLogger(__name__)

    # Use URL parameters (ignore deprecated file_id params)
    loading_icon = loading_url
    done_icon = done_url

    blocks = []

    # Debug: log what data we're receiving
    logger.info(f"Building modal for {len(thoughts)} thoughts")
    for t_idx, t in enumerate(thoughts):
        logger.info(f"  Thought {t_idx}: completed={t.completed}, tools={len(t.tools)}")
        for tool in t.tools:
            logger.info(
                f"    Tool: {tool.get('name')}, running={tool.get('running')}, success={tool.get('success')}, output_len={len(str(tool.get('output', '')))}"
            )

    # Show ALL thoughts EXCEPT the last one (which we'll combine with final result)
    # In modal we show all thoughts, not just last 3, but still exclude the last one
    display_thoughts = thoughts[:-1] if thoughts else []

    for display_idx, thought in enumerate(display_thoughts):
        # Get actual thought index in original list for button values
        thought_idx = display_idx
        is_completed = thought.completed
        thought_text = thought.text

        # Convert tables to formatted lists (modals don't support table blocks)
        thought_text = _convert_table_to_list(thought_text)

        # Format thought text with markdown
        formatted_thought = slack_mrkdwn(thought_text)

        # Build thought block with icon
        thought_elements = []
        if is_completed and done_icon:
            thought_elements.append(
                {
                    "type": "image",
                    "image_url": done_icon,
                    "alt_text": "Done",
                }
            )
        elif not is_completed and loading_icon:
            thought_elements.append(
                {
                    "type": "image",
                    "image_url": loading_icon,
                    "alt_text": "Loading",
                }
            )

        thought_elements.append({"type": "mrkdwn", "text": formatted_thought})

        blocks.append({"type": "context", "elements": thought_elements})

        # Show ALL tools for this thought, grouped by subagent
        if thought.tools:
            # Group tools by subagent (Option C: per-subagent sections)
            top_level_tools = []
            subagents = (
                {}
            )  # tool_use_id -> {"task": tool, "children": [], "task_idx": int}

            for tool_idx, tool in enumerate(thought.tools):
                tool_name = tool.get("name", "")
                parent_id = tool.get("parent_tool_use_id")
                tool_use_id = tool.get("tool_use_id")

                if tool_name == "Task" and tool_use_id:
                    # This is a subagent
                    if tool_use_id not in subagents:
                        subagents[tool_use_id] = {
                            "task": tool,
                            "children": [],
                            "task_idx": tool_idx,
                        }
                    else:
                        subagents[tool_use_id]["task"] = tool
                        subagents[tool_use_id]["task_idx"] = tool_idx
                elif parent_id and parent_id in subagents:
                    # This tool belongs to a subagent
                    subagents[parent_id]["children"].append((tool_idx, tool))
                elif parent_id:
                    # Parent not seen yet - create placeholder
                    if parent_id not in subagents:
                        subagents[parent_id] = {
                            "task": None,
                            "children": [],
                            "task_idx": None,
                        }
                    subagents[parent_id]["children"].append((tool_idx, tool))
                else:
                    # Top-level tool
                    top_level_tools.append((tool_idx, tool))

            # Helper to render a single tool
            def render_tool_block(tool_idx, tool, indent_level=1):
                tool_name = tool.get("name", "Unknown")
                tool_input = tool.get("input", {})
                tool_output = tool.get("output", "")
                tool_success = tool.get("success", True)
                is_running = tool.get("running", False)
                image_file_id = tool.get("_image_file_id")
                tool_timed_out = tool.get("timed_out", False)

                tool_blocks = []

                # Tool header: arrow + icon + description
                tool_desc = _format_tool_description(
                    tool_name,
                    tool_input,
                    tool_output,
                    is_running,
                    is_completed,
                    tool_timed_out,
                )

                # Build tool line with icon - use extra indent for subagent children
                arrow = (
                    f"{EM_SPACE}{EM_SPACE}{EM_SPACE}{EM_SPACE}{EM_SPACE}{EM_SPACE}↳"
                    if indent_level == 2
                    else f"{EM_SPACE}{EM_SPACE}{EM_SPACE}↳"
                )
                tool_elements = [{"type": "mrkdwn", "text": arrow}]

                if is_running and loading_icon:
                    tool_elements.append(
                        {
                            "type": "image",
                            "image_url": loading_icon,
                            "alt_text": "Loading",
                        }
                    )
                elif tool_success and done_icon:
                    tool_elements.append(
                        {
                            "type": "image",
                            "image_url": done_icon,
                            "alt_text": "Done",
                        }
                    )

                tool_elements.append({"type": "mrkdwn", "text": tool_desc})

                tool_blocks.append({"type": "context", "elements": tool_elements})

                # Show tool input (if available and not obvious from description)
                if tool_input and _should_show_input(tool_name, tool_input):
                    input_text = _format_tool_input_detailed(
                        tool_name, tool_input, tool_output
                    )
                    if input_text:
                        # For Task tools, show full prompt with chunking
                        if tool_name == "Task":
                            MAX_CHUNK = 2900
                            wrapped_input = f"```{input_text}```"
                            if len(wrapped_input) > MAX_CHUNK:
                                chunks = [
                                    input_text[i : i + MAX_CHUNK - 10]
                                    for i in range(0, len(input_text), MAX_CHUNK - 10)
                                ]
                                for i, chunk in enumerate(chunks[:10]):
                                    prefix = "```" if i == 0 else ""
                                    suffix = (
                                        "```" if i == len(chunks) - 1 or i == 9 else ""
                                    )
                                    tool_blocks.append(
                                        {
                                            "type": "section",
                                            "text": {
                                                "type": "mrkdwn",
                                                "text": f"{prefix}{chunk}{suffix}",
                                            },
                                        }
                                    )
                            else:
                                tool_blocks.append(
                                    {
                                        "type": "section",
                                        "text": {
                                            "type": "mrkdwn",
                                            "text": wrapped_input,
                                        },
                                    }
                                )
                        else:
                            tool_blocks.append(
                                {
                                    "type": "context",
                                    "elements": [
                                        {
                                            "type": "mrkdwn",
                                            "text": f"```{input_text[:500]}```",
                                        }
                                    ],
                                }
                            )

                # Show tool output
                if (
                    tool_output
                    or (tool_name == "Write" and tool_input)
                    or (tool_name == "AskUserQuestion" and tool_input)
                    or tool_name == "Task"
                ):
                    formatted_output = _format_tool_output_compact(
                        tool_name, tool_output, tool_input
                    )
                    if formatted_output:
                        is_truncated = _is_output_truncated(formatted_output)

                        # For Task tools, never truncate - show full output with chunking
                        if tool_name == "Task":
                            # Split into chunks if needed
                            MAX_CHUNK = 2900
                            if len(formatted_output) > MAX_CHUNK:
                                chunks = [
                                    formatted_output[i : i + MAX_CHUNK]
                                    for i in range(0, len(formatted_output), MAX_CHUNK)
                                ]
                                for chunk in chunks[:10]:  # Max 10 chunks
                                    tool_blocks.append(
                                        {
                                            "type": "section",
                                            "text": {"type": "mrkdwn", "text": chunk},
                                        }
                                    )
                                if len(chunks) > 10:
                                    tool_blocks.append(
                                        {
                                            "type": "context",
                                            "elements": [
                                                {
                                                    "type": "mrkdwn",
                                                    "text": f"_... {len(chunks) - 10} more chunks_",
                                                }
                                            ],
                                        }
                                    )
                            else:
                                tool_blocks.append(
                                    {
                                        "type": "section",
                                        "text": {
                                            "type": "mrkdwn",
                                            "text": formatted_output,
                                        },
                                    }
                                )
                        elif is_truncated:
                            clean_output = formatted_output.lstrip("\u2003")
                            tool_blocks.append(
                                {
                                    "type": "section",
                                    "text": {"type": "mrkdwn", "text": clean_output},
                                    "accessory": {
                                        "type": "button",
                                        "text": {
                                            "type": "plain_text",
                                            "text": "📄 View Full",
                                        },
                                        "action_id": "view_full_output",
                                        "value": f"{thread_id}|{thought_idx}|{tool_idx}",
                                    },
                                }
                            )
                        else:
                            tool_blocks.append(
                                {
                                    "type": "context",
                                    "elements": [
                                        {"type": "mrkdwn", "text": formatted_output}
                                    ],
                                }
                            )

                # Show image block for image outputs
                if image_file_id and not is_running:
                    tool_blocks.append(
                        {
                            "type": "image",
                            "slack_file": {"id": image_file_id},
                            "alt_text": f"Image from {tool_name}",
                        }
                    )

                return tool_blocks

            # Render top-level tools first
            for tool_idx, tool in top_level_tools:
                blocks.extend(render_tool_block(tool_idx, tool, indent_level=1))

            # Render each subagent section - clean combined layout
            for sa_id, sa_data in subagents.items():
                task_tool = sa_data["task"]
                children = sa_data["children"]
                task_idx = sa_data["task_idx"]

                # Add a subtle divider before subagent section (if there were top-level tools)
                if top_level_tools and task_tool:
                    blocks.append({"type": "divider"})

                if task_tool and task_idx is not None:
                    task_input = task_tool.get("input", {})
                    task_output = task_tool.get("output", "")
                    task_success = task_tool.get("success", True)
                    is_running = task_tool.get("running", False)

                    # Parse output to get stats
                    import ast
                    import json

                    data = None
                    if isinstance(task_output, dict):
                        data = task_output
                    elif (
                        task_output
                        and isinstance(task_output, str)
                        and task_output.startswith("{")
                    ):
                        try:
                            data = json.loads(task_output)
                        except (ValueError, json.JSONDecodeError):
                            try:
                                data = ast.literal_eval(task_output)
                            except (ValueError, SyntaxError):
                                pass

                    # Extract stats for header
                    description = task_input.get("description", "Subagent")
                    stats_parts = []
                    if data:
                        duration_ms = data.get("totalDurationMs")
                        if duration_ms:
                            stats_parts.append(f"{duration_ms/1000:.1f}s")
                        tool_count = data.get("totalToolUseCount")
                        if tool_count:
                            stats_parts.append(f"{tool_count} tools")

                    # Build header as context block with done image
                    arrow = f"{EM_SPACE}{EM_SPACE}{EM_SPACE}↳"
                    header_elements = [{"type": "mrkdwn", "text": arrow}]

                    # Add status image
                    if is_running and loading_icon:
                        header_elements.append(
                            {
                                "type": "image",
                                "image_url": loading_icon,
                                "alt_text": "Running",
                            }
                        )
                    elif task_success and done_icon:
                        header_elements.append(
                            {
                                "type": "image",
                                "image_url": done_icon,
                                "alt_text": "Done",
                            }
                        )
                    elif not task_success:
                        header_elements.append({"type": "mrkdwn", "text": "❌"})

                    # Add description and stats
                    header_text = f"*{description}*"
                    if stats_parts:
                        header_text += f" • {' • '.join(stats_parts)}"
                    header_elements.append({"type": "mrkdwn", "text": header_text})

                    blocks.append({"type": "context", "elements": header_elements})

                    # Combined prompt + result block
                    # Get prompt (from output if available, otherwise input)
                    prompt = None
                    if data:
                        prompt = data.get("prompt")
                    if not prompt:
                        prompt = task_input.get("prompt", "")

                    # Truncate prompt
                    MAX_PROMPT_LEN = 200
                    if len(prompt) > MAX_PROMPT_LEN:
                        prompt = prompt[:MAX_PROMPT_LEN] + "..."

                    # Get result text (without the redundant header/stats)
                    result_text = ""
                    if data:
                        content = data.get("content", [])
                        if content and isinstance(content, list):
                            for block in content:
                                if (
                                    isinstance(block, dict)
                                    and block.get("type") == "text"
                                ):
                                    result_text = block.get("text", "")
                                    break

                    # Truncate result
                    MAX_RESULT_LEN = 300
                    if len(result_text) > MAX_RESULT_LEN:
                        result_text = result_text[:MAX_RESULT_LEN] + "..."

                    # Build combined block with clear labels and spacing
                    combined_text = f"```📝 Prompt:\n\n{prompt}\n\n────────────────────\n💬 Result:\n\n{result_text}```"

                    combined_block = {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": combined_text},
                    }

                    # Add button to view tool calls as accessory
                    if children:
                        child_count = len(children)
                        combined_block["accessory"] = {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": f"🔍 {child_count} tools",
                            },
                            "action_id": "view_subagent_details",
                            "value": f"{thread_id}|{thought_idx}|{task_idx}|{sa_id}",
                        }

                    blocks.append(combined_block)

        # Add spacing between thoughts (except after last)
        if thought_idx < len(thoughts) - 1:
            blocks.append({"type": "divider"})

    # Final result - extract clean final text (last thought + ending message only)
    if result:
        if thoughts:  # Add divider only if there was thought content
            blocks.append({"type": "divider"})

        # Extract clean final result by stripping out all previous thoughts
        clean_result = _extract_clean_result(result, thoughts)

        # Strip file links (files are uploaded as Slack attachments separately)
        clean_result = _strip_file_links(clean_result, result_files)

        # Process text for embedded images
        content_segments = _process_text_with_images(clean_result, result_images)

        for content_seg in content_segments:
            if content_seg["type"] == "image":
                # Render image block
                blocks.append(
                    _render_image_block(content_seg["file_id"], content_seg["alt"])
                )
            else:
                # Text segment - process normally
                text_content = content_seg["content"]

                # Convert tables to formatted lists (modals don't support table blocks)
                text_content = _convert_table_to_list(text_content)

                # Format result text with proper markdown and split on --- / paragraphs
                result_blocks = _process_text_to_blocks(text_content)
                blocks.extend(result_blocks)

    # Slack modals have 100 block limit and 3000 char per block limit
    MAX_MODAL_BLOCKS = 100
    BLOCKS_PER_PAGE = 95  # Leave room for pagination controls

    # Step 1: Ensure all text blocks respect 3000 char limit
    blocks = _ensure_text_block_limits(blocks)

    # Step 2: Try to compress blocks if over limit
    if len(blocks) > MAX_MODAL_BLOCKS:
        original_count = len(blocks)
        blocks = _combine_section_blocks(blocks, MAX_MODAL_BLOCKS)
        logger.info(f"Compressed modal blocks: {original_count} -> {len(blocks)}")

    # Step 3: Paginate if still over limit
    total_blocks = len(blocks)
    total_pages = (
        total_blocks + BLOCKS_PER_PAGE - 1
    ) // BLOCKS_PER_PAGE  # Ceiling division

    if total_pages > 1:
        # Ensure page is within bounds
        page = max(1, min(page, total_pages))

        # Calculate slice for current page
        start_idx = (page - 1) * BLOCKS_PER_PAGE
        end_idx = min(start_idx + BLOCKS_PER_PAGE, total_blocks)

        blocks = blocks[start_idx:end_idx]

        # Add pagination controls
        blocks.append({"type": "divider"})

        # Page indicator (small text)
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Page {page} of {total_pages}"}
                ],
            }
        )

        # Navigation buttons (only show buttons that are needed)
        pagination_elements = []

        if page > 1:
            pagination_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "← Previous"},
                    "action_id": "modal_page_prev",
                    "value": json.dumps({"thread_id": thread_id, "page": page - 1}),
                }
            )

        if page < total_pages:
            pagination_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Next →"},
                    "action_id": "modal_page_next",
                    "value": json.dumps({"thread_id": thread_id, "page": page + 1}),
                }
            )

        if pagination_elements:
            blocks.append({"type": "actions", "elements": pagination_elements})

    # Store pagination metadata
    metadata = json.dumps(
        {
            "thread_id": thread_id,
            "page": page,
            "total_pages": total_pages if total_pages > 1 else 1,
        }
    )

    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Investigation"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
        "private_metadata": metadata,
    }


def _format_tool_description(
    tool_name: str,
    tool_input: dict,
    output: str = "",
    is_running: bool = False,
    thought_completed: bool = False,
    timed_out: bool = False,
) -> str:
    """Format a tool with its description for display (matches main message formatting).

    Args:
        tool_name: Name of the tool
        tool_input: Tool input parameters
        output: Tool output
        is_running: Whether the tool is still running
        thought_completed: Whether the containing thought is completed
        timed_out: Whether the tool timed out waiting for user input
    """
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")[:60]
        return f"Bash | `{cmd}`"
    elif tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        return f"Read | `{file_path}`"
    elif tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        return f"Write | `{file_path}`"
    elif tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        return f"Update | `{file_path}`"
    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        parts = [f"pattern: `{pattern}`"]
        if path:
            parts.append(f"path: `{path}`")
        return f"Search | {', '.join(parts)}"
    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        parts = [f"pattern: `{pattern}`"]
        if tool_input.get("type"):
            parts.append(f'type: `{tool_input["type"]}`')
        if tool_input.get("path"):
            parts.append(f'path: `{tool_input["path"]}`')
        if tool_input.get("output_mode"):
            parts.append(f'mode: `{tool_input["output_mode"]}`')
        if tool_input.get("-i"):
            parts.append("-i")
        if tool_input.get("head_limit"):
            parts.append(f'head_limit: {tool_input["head_limit"]}')
        return f"Search | {', '.join(parts)}"
    elif tool_name == "WebFetch":
        url = tool_input.get("url", "")[:100]
        return f"Fetch | `{url}`"
    elif tool_name == "Task":
        desc = tool_input.get("description", "subtask")
        if len(desc) > 40:
            desc = desc[:37] + "..."
        return f"Task | {desc}"
    elif tool_name == "TodoWrite":
        # Show number of tasks if available
        todos = tool_input.get("todos", [])
        if todos:
            return f"Tasks | {len(todos)} item{'s' if len(todos) != 1 else ''}"
        return "Tasks"
    elif tool_name == "AskUserQuestion":
        questions = tool_input.get("questions", [])
        num_questions = len(questions)
        q_word = "question" if num_questions == 1 else "questions"
        # Check if output contains answers
        if output and "answers" in str(output):
            return f"AskUserQuestion | {num_questions} {q_word} → answered"
        elif timed_out or (thought_completed and not output):
            # Explicitly timed out or thought completed without output
            return f"AskUserQuestion | {num_questions} {q_word} (timed out)"
        elif is_running:
            # Still waiting for user response
            return f"AskUserQuestion | {num_questions} {q_word} (waiting...)"
        return f"AskUserQuestion | {num_questions} {q_word}"

    # Handle MCP tools: mcp__server__toolname format
    # Extract server and tool name for cleaner display
    if tool_name.startswith("mcp__"):
        parts = tool_name.split(
            "__", 2
        )  # Split into max 3 parts: "mcp", "server", "toolname"
        if len(parts) == 3:
            server = parts[1]
            tool = parts[2]

            # Format server name nicely (capitalize, remove underscores)
            server_display = server.replace("_", " ").title()

            # Format tool name nicely (remove underscores, keep original casing for acronyms)
            tool_display = tool.replace("_", " ")

            # Try to extract key parameters for context
            params_display = ""
            if tool_input:
                # Common useful parameters to show
                if "service" in tool_input:
                    params_display = f" | `{tool_input['service']}`"
                elif "query" in tool_input and len(str(tool_input["query"])) < 50:
                    params_display = f" | `{tool_input['query']}`"
                elif "endpoint" in tool_input:
                    params_display = f" | `{tool_input['endpoint']}`"
                elif "pod_name" in tool_input:
                    params_display = f" | `{tool_input['pod_name']}`"
                elif "namespace" in tool_input:
                    params_display = f" | `{tool_input['namespace']}`"

            return f"{server_display} | {tool_display}{params_display}"

    # Fallback for unknown tools
    return tool_name


def _should_show_input(tool_name: str, tool_input: dict) -> bool:
    """Determine if we should show detailed input for this tool."""
    # Don't show input if it's already obvious from the description
    # Show input for tools with complex parameters
    if tool_name == "Write":
        # Write has interesting content to show in input
        return True
    elif tool_name == "Edit":
        # Edit output (structured diff) is better than input, so skip input
        return False
    elif tool_name == "Task":
        return True
    # For simple tools (Bash, Read, Grep), the command/path is already in description
    return False


def _format_tool_input_detailed(
    tool_name: str, tool_input: dict, tool_output: str = None
) -> str:
    """Format detailed tool input for display in modal."""
    # Handle MCP tools - show input as JSON for most, but extract query for search tools
    if tool_name.startswith("mcp__"):
        import json

        # For log/metric search tools, show query prominently
        if "search" in tool_name.lower() or "query" in tool_name.lower():
            if "query" in tool_input:
                query = tool_input["query"]
                if len(query) < 300:
                    return query
                return query[:300] + "..."
        # For other MCP tools, show compact JSON (skip showing input, it's usually in description)
        return ""

    if tool_name == "Write":
        return tool_input.get("contents", "")[:800]
    elif tool_name == "Edit":
        old_string = tool_input.get("old_string", "")[:400]
        new_string = tool_input.get("new_string", "")[:400]
        return f"Old:\n{old_string}\n\nNew:\n{new_string}"
    elif tool_name == "Task":
        # Try to get full prompt from output (input may be truncated)
        prompt = None
        if tool_output:
            # Parse output to get full prompt
            import ast
            import json

            data = None
            if isinstance(tool_output, dict):
                data = tool_output
            elif (
                tool_output
                and isinstance(tool_output, str)
                and (tool_output.startswith("{") or tool_output.startswith("["))
            ):
                try:
                    data = json.loads(tool_output)
                except (json.JSONDecodeError, TypeError):
                    try:
                        data = ast.literal_eval(tool_output)
                    except (ValueError, SyntaxError):
                        pass
            if data:
                prompt = data.get("prompt")

        if not prompt:
            prompt = tool_input.get("prompt", "")

        return f"Prompt: {prompt}"
    else:
        # Generic: show all input as JSON-like format
        lines = []
        for k, v in tool_input.items():
            value_str = str(v)[:200]
            lines.append(f"{k}: {value_str}")
        return "\n".join(lines[:5])  # Max 5 fields


def _format_tool_output(tool_name: str, tool_output: str) -> str:
    """
    Format tool output like Claude Code web UI:
    - Read: file content with line numbers (1→, 2→, ...)
    - Bash: clean output with ... +N lines truncation
    - Others: code block with clean truncation
    """
    import ast
    import json
    import logging

    logger = logging.getLogger(__name__)

    # Max lines to show (like Claude Code's preview)
    MAX_LINES = 15

    # Debug: log raw output type and preview
    output_preview = str(tool_output)[:200] if tool_output else "(empty)"
    logger.debug(
        f"_format_tool_output: tool={tool_name}, type={type(tool_output).__name__}, preview={output_preview}"
    )

    # Special formatting for WebSearch
    if tool_name == "WebSearch":
        return _format_websearch_output(tool_output, logger)

    # If tool_output is already a dict (not a string), use it directly
    if isinstance(tool_output, dict):
        data = tool_output
        logger.debug(f"  -> Already a dict with keys: {list(data.keys())}")
    else:
        # Try to parse - could be JSON or Python dict repr
        data = None
        if tool_output and (tool_output.startswith("{") or tool_output.startswith("[")):
            # Try JSON first
            try:
                data = json.loads(tool_output)
                logger.debug(
                    f"  -> Parsed as JSON with keys: {list(data.keys()) if isinstance(data, dict) else 'list'}"
                )
            except (json.JSONDecodeError, TypeError):
                pass

            # Try Python literal (handles single quotes)
            if data is None:
                try:
                    data = ast.literal_eval(tool_output)
                    logger.debug(
                        f"  -> Parsed as Python literal with keys: {list(data.keys()) if isinstance(data, dict) else 'list'}"
                    )
                except (ValueError, SyntaxError):
                    logger.debug("  -> Failed to parse as JSON or Python literal")

    # Extract content based on tool type
    if tool_name == "Read":
        content = _extract_read_content(tool_output, data)
        if content:
            return _format_with_line_numbers(content, MAX_LINES)

    elif tool_name == "Bash":
        content = _extract_bash_output(tool_output, data)
        if content:
            return _format_plain_output(content, MAX_LINES)

    elif tool_name == "Glob":
        content = _extract_glob_output(tool_output, data)
        if content:
            return _format_plain_output(content, MAX_LINES)

    elif tool_name == "Grep":
        content = _extract_grep_output(tool_output, data)
        if content:
            return _format_plain_output(content, MAX_LINES)

    # Default: try to show something readable
    if data and isinstance(data, dict):
        # Try common content keys in priority order
        for key in ["content", "stdout", "output", "result", "text", "message"]:
            if key in data and data[key]:
                content = data[key]
                if isinstance(content, str):
                    return _format_plain_output(content, MAX_LINES)

        # Check nested 'file' structure
        if "file" in data and isinstance(data["file"], dict):
            file_content = data["file"].get("content", "")
            if file_content:
                return _format_with_line_numbers(file_content, MAX_LINES)

    # Fallback: if it's a plain string (not JSON-like), show it
    if (
        isinstance(tool_output, str)
        and not tool_output.startswith("{")
        and not tool_output.startswith("[")
    ):
        return _format_plain_output(tool_output, MAX_LINES)

    # Last resort: show nothing rather than raw JSON dump
    return ""


def _format_websearch_output(tool_output, logger) -> str:
    """
    Format WebSearch output to show search results and summary.

    WebSearch output format:
    {'query': str, 'results': [{'tool_use_id': str, 'content': [list of search results], summary: str}], 'durationSeconds': float}
    """
    import ast
    import json

    # Parse the output
    data = None
    if isinstance(tool_output, dict):
        data = tool_output
    elif isinstance(tool_output, str):
        try:
            data = json.loads(tool_output)
        except json.JSONDecodeError:
            try:
                data = ast.literal_eval(tool_output)
            except (ValueError, SyntaxError):
                return str(tool_output)[:500]

    if not data or not isinstance(data, dict):
        return str(tool_output)[:500]

    # Extract components
    query = data.get("query", "N/A")
    results = data.get("results", [])
    duration = data.get("durationSeconds", 0)

    output_lines = []
    output_lines.append(f"🔍 Query: {query}")
    output_lines.append(f"⏱️ Duration: {duration:.2f}s")
    output_lines.append("")

    # Show search results
    if results and len(results) > 0:
        result_data = results[0]
        content = result_data.get("content", [])

        # Content is a list where:
        # - First element is a list/dict of search results (URLs)
        # - Second element is the summary text
        if content and isinstance(content, list) and len(content) >= 2:
            urls_data = content[0]
            summary = content[1]

            # Show top search results
            if urls_data:
                output_lines.append("📋 Top Results:")

                # urls_data could be:
                # 1. A list of dicts with 'title' and 'url'
                # 2. A dict with nested structure
                url_list = []
                if isinstance(urls_data, list):
                    url_list = urls_data[:5]  # Top 5
                elif isinstance(urls_data, dict):
                    # Might have 'content' key with the list
                    if "content" in urls_data:
                        url_list = (
                            urls_data["content"][:5]
                            if isinstance(urls_data["content"], list)
                            else []
                        )
                    else:
                        url_list = [urls_data]

                for idx, item in enumerate(url_list, 1):
                    if isinstance(item, dict):
                        title = item.get("title", "No title")
                        # Truncate long titles
                        if len(title) > 80:
                            title = title[:77] + "..."
                        output_lines.append(f"{idx}. {title}")

                output_lines.append("")

            # Show summary
            if summary and isinstance(summary, str):
                output_lines.append("📝 Summary:")
                # Truncate summary if too long
                summary_lines = summary.split("\n")
                for line in summary_lines[:15]:  # Max 15 lines
                    output_lines.append(line)

    return "\n".join(output_lines)


def _extract_read_content(tool_output, data: dict = None) -> str:
    """Extract file content from Read tool output.

    Read output schema: {"type": str, "file": {"content": str, "numLines": int, ...}}
    or: {"content": str, "total_lines": int, "lines_returned": int}
    """
    # If it's structured data (official schema)
    if data and isinstance(data, dict):
        # Handle nested structure: {'type': 'text', 'file': {'content': '...', 'numLines': ...}}
        if "file" in data and isinstance(data["file"], dict):
            file_data = data["file"]
            if "content" in file_data:
                return file_data["content"]

        # Official schema: {"content": str, "total_lines": int, "lines_returned": int}
        if "content" in data:
            return data["content"]

        # Try other common keys
        for key in ["text", "body", "data", "fileContent"]:
            if key in data and data[key]:
                val = data[key]
                if isinstance(val, str):
                    return val

    # Fallback: plain string output
    if isinstance(tool_output, str) and tool_output.strip():
        if not (tool_output.startswith("{") or tool_output.startswith("[")):
            return tool_output

    return ""


def _extract_bash_output(tool_output, data: dict = None) -> str:
    """Extract output from Bash tool.

    Bash output schema: {"output": str, "exitCode": int, "killed": bool, "shellId": str}
    """
    # If it's structured data (official schema)
    if data and isinstance(data, dict):
        # Official schema: {"output": str, "exitCode": int, "killed": bool, "shellId": str}
        if "output" in data:
            return data["output"]

        # Try other common keys
        for key in ["result", "stdout", "stderr", "text", "content"]:
            if key in data and data[key]:
                val = data[key]
                if isinstance(val, str):
                    return val

        if "error" in data and data["error"]:
            return f"Error: {data['error']}"

    # Fallback: plain string output
    if isinstance(tool_output, str) and tool_output.strip():
        if not (tool_output.startswith("{") or tool_output.startswith("[")):
            return tool_output

    return ""


def _extract_glob_output(tool_output, data: dict = None) -> str:
    """Extract file list from Glob tool output.

    Actual format from Claude: {'filenames': [...], 'durationMs': ..., 'numFiles': int, 'truncated': bool}
    Official schema: {"matches": list[str], "count": int, "search_path": str}
    """
    # If it's structured data
    if data and isinstance(data, dict):
        # Try actual Claude format first
        filenames = data.get("filenames", [])
        if not filenames:
            filenames = data.get("matches", [])

        num_files = data.get("numFiles", data.get("count", len(filenames)))
        f_word = "file" if num_files == 1 else "files"

        if filenames:
            file_list = "\n".join(str(f) for f in filenames[:20])
            if len(filenames) > 20:
                return f"Found {num_files} {f_word}:\n{file_list}\n... +{len(filenames) - 20} more"
            return f"Found {num_files} {f_word}:\n{file_list}"
        elif num_files == 0:
            return "No files found"

    # Fallback: plain string output
    if isinstance(tool_output, str) and tool_output.strip():
        if not (tool_output.startswith("{") or tool_output.startswith("[")):
            return tool_output.strip()

    return ""


def _extract_grep_output(tool_output, data: dict = None) -> str:
    """Extract matches from Grep tool output.

    Actual format from Claude:
    - content mode: {'mode': 'content', 'content': 'file:line:text\n...', 'numLines': int}
    - files_with_matches mode: {'mode': 'files_with_matches', 'filenames': [...]}

    Official schema:
    - content mode: {"matches": [...], "total_matches": int}
    - files_with_matches mode: {"files": list[str], "count": int}
    """
    if data and isinstance(data, dict):
        # Content mode - has actual matching lines
        if "content" in data and data["content"]:
            content = data["content"]
            all_lines = content.strip().split("\n")
            lines = all_lines[:20]
            result = "\n".join(lines)
            if len(all_lines) > 20:
                result += f"\n... +{len(all_lines) - 20} more"
            return result

        # Files with matches mode
        filenames = data.get("filenames", data.get("files", []))
        if filenames:
            count = data.get("numFiles", data.get("count", len(filenames)))
            f_word = "file" if count == 1 else "files"
            file_list = "\n".join(str(f) for f in filenames[:20])
            if len(filenames) > 20:
                return f"Found {count} {f_word}:\n{file_list}\n... +{len(filenames) - 20} more"
            return f"Found {count} {f_word}:\n{file_list}"

        # Official schema with matches array
        if "matches" in data:
            matches = data["matches"]
            if isinstance(matches, list) and matches:
                formatted = []
                for m in matches[:20]:
                    if isinstance(m, dict):
                        file = m.get("file", "")
                        line_num = m.get("line_number", "")
                        line = m.get("line", "")
                        if line_num:
                            formatted.append(f"{file}:{line_num}:{line}")
                        else:
                            formatted.append(f"{file}:{line}")
                    else:
                        formatted.append(str(m))
                return "\n".join(formatted)

        # No matches found
        if data.get("numFiles", 0) == 0 and data.get("numLines", 0) == 0:
            return "No matches found"

    # Fallback: plain string output
    if isinstance(tool_output, str) and tool_output.strip():
        if not (tool_output.startswith("{") or tool_output.startswith("[")):
            return tool_output.strip()

    return ""


def _extract_edit_output(tool_input, data: dict = None) -> str:
    """Extract edit diff from Edit tool output - Claude Code diff style with actual line numbers.

    Edit output schema: {
        "structuredPatch": [{
            "oldStart": int, "oldLines": int, "newStart": int, "newLines": int,
            "lines": [" context", "-removed", "+added", ...]
        }],
        "filePath": str, "oldString": str, "newString": str, ...
    }
    """
    # Use structuredPatch from output if available (has actual line numbers!)
    if data and isinstance(data, dict) and "structuredPatch" in data:
        patches = data["structuredPatch"]
        if patches and len(patches) > 0:
            patch = patches[0]  # Use first patch
            old_start = patch.get("oldStart", 1)
            new_start = patch.get("newStart", 1)
            diff_lines = patch.get("lines", [])

            if not diff_lines:
                return ""

            # Count added/removed lines
            added_count = sum(1 for line in diff_lines if line.startswith("+"))
            removed_count = sum(1 for line in diff_lines if line.startswith("-"))

            output_lines = []

            # Summary like Claude Code
            summary_parts = []
            if added_count > 0:
                summary_parts.append(
                    f"Added {added_count} line{'s' if added_count != 1 else ''}"
                )
            if removed_count > 0:
                summary_parts.append(
                    f"removed {removed_count} line{'s' if removed_count != 1 else ''}"
                )
            if summary_parts:
                output_lines.append(", ".join(summary_parts))
                output_lines.append("")  # Blank line

            # Format diff with actual line numbers
            old_line_num = old_start
            new_line_num = new_start
            max_display_lines = 15
            lines_shown = 0

            for diff_line in diff_lines:
                if lines_shown >= max_display_lines:
                    remaining = len(diff_lines) - lines_shown
                    output_lines.append(
                        f"... +{remaining} more {'line' if remaining == 1 else 'lines'}"
                    )
                    break

                # Truncate very long lines
                content = diff_line[1:] if diff_line else ""  # Remove prefix
                if len(content) > 80:
                    content = content[:77] + "..."

                if diff_line.startswith("-"):
                    # Removed line - show old line number with red emoji
                    output_lines.append(f"{old_line_num} 🔴 -{content}")
                    old_line_num += 1
                elif diff_line.startswith("+"):
                    # Added line - show new line number with green emoji
                    output_lines.append(f"{new_line_num} 🟢 +{content}")
                    new_line_num += 1
                else:
                    # Context line - show both line numbers advancing
                    output_lines.append(f"{old_line_num}    {content}")
                    old_line_num += 1
                    new_line_num += 1

                lines_shown += 1

            return "\n".join(output_lines)

    return ""


def _extract_write_output(tool_output, data: dict = None) -> str:
    """Extract file content from Write tool output.

    Write output schema: {"type": "create", "filePath": str, "content": str, ...}
    """
    # If it's structured data
    if data and isinstance(data, dict):
        # Check for 'content' key (full file content)
        if "content" in data:
            return data["content"]

        # Try other common keys
        for key in ["text", "body", "data", "fileContent"]:
            if key in data and data[key]:
                val = data[key]
                if isinstance(val, str):
                    return val

    # Fallback: plain string output
    if isinstance(tool_output, str) and tool_output.strip():
        if not (tool_output.startswith("{") or tool_output.startswith("[")):
            return tool_output

    return ""


def _format_with_line_numbers(content: str, max_lines: int) -> str:
    """
    Format content with line numbers like Claude Code:
    1→from dataclasses import dataclass
    2→import datetime
    ...
    ... +N lines
    """
    # Slack section blocks have 3000 char limit - keep output under 2500 to be safe
    MAX_CHARS = 2500

    lines = content.split("\n")
    total_lines = len(lines)

    # Show first max_lines (or fewer if we hit char limit)
    formatted_lines = []
    char_count = 0
    lines_shown = 0

    for i, line in enumerate(lines[:max_lines], 1):
        # Truncate individual long lines
        if len(line) > 100:
            line = line[:100] + "..."
        formatted_line = f"{i}→{line}"

        if char_count + len(formatted_line) + 1 > MAX_CHARS:
            break

        formatted_lines.append(formatted_line)
        char_count += len(formatted_line) + 1  # +1 for newline
        lines_shown = i

    result = "\n".join(formatted_lines)

    # Add truncation indicator if needed
    remaining = total_lines - lines_shown
    if remaining > 0:
        result += f"\n   ... +{remaining} {'line' if remaining == 1 else 'lines'}"

    # Wrap in indented code block
    return f"{EM_SPACE}{EM_SPACE}```\n{result}\n```"


def _format_plain_output(content: str, max_lines: int) -> str:
    """
    Format plain output with ... +N lines truncation.
    """
    # Slack section blocks have 3000 char limit - keep output under 2500 to be safe
    MAX_CHARS = 2500

    lines = content.split("\n")
    total_lines = len(lines)

    # Show first max_lines (or fewer if we hit char limit)
    output_lines = []
    char_count = 0
    lines_shown = 0

    for i, line in enumerate(lines[:max_lines]):
        # Truncate individual long lines
        if len(line) > 120:
            line = line[:120] + "..."

        if char_count + len(line) + 1 > MAX_CHARS:
            break

        output_lines.append(line)
        char_count += len(line) + 1  # +1 for newline
        lines_shown = i + 1

    result = "\n".join(output_lines)

    # Add truncation indicator if needed
    remaining = total_lines - lines_shown
    if remaining > 0:
        result += f"\n   ... +{remaining} {'line' if remaining == 1 else 'lines'}"

    # Wrap in indented code block
    return f"{EM_SPACE}{EM_SPACE}```\n{result}\n```"


def _format_todowrite_output(tool_output, data: dict = None) -> str:
    """Format TodoWrite output as a nice task list."""
    if not data or not isinstance(data, dict):
        return ""

    new_todos = data.get("newTodos", [])
    if not new_todos:
        return ""

    lines = ["```"]
    lines.append("📝 Task List:")
    lines.append("")

    for i, todo in enumerate(new_todos[:10], 1):  # Limit to 10 tasks
        content = todo.get("content", "Unknown task")
        status = todo.get("status", "pending")

        # Status icons
        if status == "completed":
            icon = "✅"
        elif status == "in_progress":
            icon = "🔄"
        else:
            icon = "⏸️"

        lines.append(f"{i}. {icon} {content}")

    if len(new_todos) > 10:
        lines.append(f"   ... +{len(new_todos) - 10} more tasks")

    lines.append("```")
    return "\n".join(lines)


def _format_killshell_output(tool_output, data: dict = None) -> str:
    """Format KillShell output message."""
    if not data or not isinstance(data, dict):
        return ""

    message = data.get("message", "")
    shell_id = data.get("shell_id", "")

    if not message:
        return ""

    # Extract command from message if possible
    # Format: "Successfully killed shell: ID (command)"
    lines = ["```"]
    lines.append("✅ Process terminated")
    if shell_id:
        lines.append(f"📌 Process ID: {shell_id}")

    # Try to extract command
    if "(" in message and ")" in message:
        start = message.find("(")
        end = message.rfind(")")
        command = message[start + 1 : end]
        lines.append(f"💻 Command: {command}")

    lines.append("```")
    return "\n".join(lines)


def _format_websearch_output_compact(
    tool_output, data: dict = None, logger=None
) -> str:
    """
    Format WebSearch output for modal display.
    Shows query, ALL URLs, and FULL summary (no truncation).
    Progressive disclosure will kick in if output is too long.
    """
    import ast
    import json

    # Parse the output
    if data is None:
        if isinstance(tool_output, dict):
            data = tool_output
        elif isinstance(tool_output, str):
            try:
                data = json.loads(tool_output)
            except json.JSONDecodeError:
                try:
                    data = ast.literal_eval(tool_output)
                except (ValueError, SyntaxError):
                    return f"```\n{str(tool_output)[:300]}\n```"

    if not data or not isinstance(data, dict):
        return f"```\n{str(tool_output)[:300]}\n```"

    # Extract components
    query = data.get("query", "N/A")
    results = data.get("results", [])
    duration = data.get("durationSeconds", 0)

    output_lines = []
    output_lines.append(f"🔍 Query: {query}")
    output_lines.append(f"⏱️ Duration: {duration:.2f}s")
    output_lines.append("")

    # Show search results
    if results and len(results) > 0:
        # results[0] contains {tool_use_id, content: [list of URL dicts]}
        # results[1] is the summary string (if present)
        result_data = results[0]
        content = result_data.get("content", [])
        summary = (
            results[1] if len(results) > 1 and isinstance(results[1], str) else None
        )

        # Show ALL search results (no truncation)
        if content and isinstance(content, list):
            output_lines.append("📋 Search Results:")

            for idx, item in enumerate(content, 1):  # Show ALL results
                if isinstance(item, dict):
                    title = item.get("title", "No title")
                    url = item.get("url", "")
                    # Show full title and URL
                    output_lines.append(f"{idx}. {title}")
                    if url:
                        output_lines.append(f"   {url}")

            output_lines.append("")

        # Show FULL summary (no truncation)
        if summary:
            output_lines.append("📝 Summary:")
            # Show complete summary, no line limit
            summary_lines = summary.split("\n")
            for line in summary_lines:
                output_lines.append(line)

    return "```\n" + "\n".join(output_lines) + "\n```"


def _format_webfetch_output_compact(tool_output, data: dict = None, logger=None) -> str:
    """
    Format WebFetch output for modal display.
    Shows URL, status code, and the full result content.
    """
    import ast
    import json

    # Parse the output
    if data is None:
        if isinstance(tool_output, dict):
            data = tool_output
        elif isinstance(tool_output, str):
            try:
                data = json.loads(tool_output)
            except json.JSONDecodeError:
                try:
                    data = ast.literal_eval(tool_output)
                except (ValueError, SyntaxError):
                    return f"```\n{str(tool_output)[:300]}\n```"

    if not data or not isinstance(data, dict):
        return f"```\n{str(tool_output)[:300]}\n```"

    # Extract components
    url = data.get("url", "N/A")
    code = data.get("code", 0)
    code_text = data.get("codeText", "")
    result = data.get("result", "")
    duration_ms = data.get("durationMs", 0)
    bytes_count = data.get("bytes", 0)

    output_lines = []
    output_lines.append(f"🌐 URL: {url}")
    output_lines.append(f"📊 Status: {code} {code_text}")
    output_lines.append(f"⏱️ Duration: {duration_ms/1000:.2f}s")
    output_lines.append(f"📦 Size: {bytes_count:,} bytes")
    output_lines.append("")
    output_lines.append("📄 Content:")
    output_lines.append("")

    # Show the full result content (no truncation)
    if result:
        # The result might be markdown formatted, so preserve it
        result_lines = result.split("\n")
        for line in result_lines:
            output_lines.append(line)
    else:
        output_lines.append("(No content)")

    return "```\n" + "\n".join(output_lines) + "\n```"


def _format_task_output(tool_output, data: dict = None, tool_input: dict = None) -> str:
    """Format subagent Task output nicely - extract the actual result text."""
    if not data or not isinstance(data, dict):
        return ""

    lines = []

    # Get description from input
    description = ""
    if tool_input:
        description = tool_input.get("description", "")

    # Extract status
    status = data.get("status", "unknown")
    status_icon = (
        "✅" if status == "completed" else "🔄" if status == "running" else "❌"
    )

    # Header with description
    if description:
        lines.append(f"```\n{status_icon} Subagent: {description}")
    else:
        lines.append(f"```\n{status_icon} Subagent task {status}")

    # Show stats if available
    duration_ms = data.get("totalDurationMs")
    tokens = data.get("totalTokens")
    tool_count = data.get("totalToolUseCount")

    stats = []
    if duration_ms:
        duration_s = duration_ms / 1000
        stats.append(f"{duration_s:.1f}s")
    if tool_count:
        stats.append(f"{tool_count} tools")
    if tokens:
        stats.append(f"{tokens} tokens")

    if stats:
        lines.append(f"📊 {' | '.join(stats)}")

    lines.append("")

    # Extract the actual text content from the response
    content = data.get("content", [])
    if content and isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                # Show full text (no truncation)
                lines.append(text)
                break

    lines.append("```")
    return "\n".join(lines)


def _format_taskoutput_output(tool_output, data: dict = None) -> str:
    """Format TaskOutput output showing task results."""
    if not data or not isinstance(data, dict):
        return ""

    retrieval_status = data.get("retrieval_status", "")
    task_data = data.get("task", {})

    if not task_data:
        return ""

    lines = ["```"]

    # Show retrieval status
    if retrieval_status == "success":
        lines.append("✅ Task completed")
    else:
        lines.append(f"Status: {retrieval_status}")

    # Task ID
    task_id = task_data.get("task_id", "")
    if task_id:
        lines.append(f"📌 Task ID: {task_id}")

    # Task status and exit code
    exit_code = task_data.get("exitCode")
    if exit_code is not None:
        lines.append(f"🔢 Exit code: {exit_code}")

    # Task output (truncated)
    output = task_data.get("output", "")
    if output:
        lines.append("")
        lines.append("📄 Output:")
        # Show first few lines
        output_lines = output.strip().split("\n")
        for line in output_lines[:5]:  # Show first 5 lines
            if len(line) > 70:
                line = line[:67] + "..."
            lines.append(f"  {line}")

        if len(output_lines) > 5:
            lines.append(f"  ... +{len(output_lines) - 5} more lines")

    lines.append("```")
    return "\n".join(lines)


def _format_askuserquestion_output(
    tool_output, data: dict = None, tool_input: dict = None, logger=None
) -> str:
    """
    Format AskUserQuestion output showing the questions asked and user's answers.
    Shows a clean Q&A summary without all the options.
    """
    import ast
    import json

    # Parse the output to get answers
    if data is None:
        if isinstance(tool_output, dict):
            data = tool_output
        elif isinstance(tool_output, str):
            try:
                data = json.loads(tool_output)
            except json.JSONDecodeError:
                try:
                    data = ast.literal_eval(tool_output)
                except (ValueError, SyntaxError):
                    pass

    # Get questions from input (has the full question text)
    questions = []
    if tool_input and isinstance(tool_input, dict):
        questions = tool_input.get("questions", [])

    # Get answers from output
    answers = {}
    if data and isinstance(data, dict):
        answers = data.get("answers", {})

    if not questions:
        return "```\n❓ Questions asked (no details available)\n```"

    # Check if this was a timeout (no answers at all)
    has_any_answers = bool(answers)

    lines = []
    if has_any_answers:
        lines.append("📝 *Questions & Answers*")
    else:
        lines.append("⏱️ *Questions Asked (timed out)*")
        lines.append(
            "_Agent did not receive a response within 60 seconds and continued._"
        )
    lines.append("")

    for i, q in enumerate(questions):
        header = q.get("header", f"Question {i+1}")
        question_text = q.get("question", "")
        # Get the user's answer for this question
        answer_key = f"question_{i}"
        user_answer = answers.get(answer_key, "")

        # Format Q&A
        lines.append(f"*{header}*")
        lines.append(f"Q: {question_text}")

        if user_answer:
            # Check if answer contains both selection and comment (format: "Selection // comment")
            if " // " in user_answer:
                parts = user_answer.split(" // ", 1)
                selection = parts[0]
                comment = parts[1]
                lines.append(f"A: `{selection}`")
                lines.append(f"_Comment: {comment}_")
            else:
                lines.append(f"A: `{user_answer}`")
        else:
            lines.append("A: _(no answer)_")

        lines.append("")  # Blank line between questions

    return "\n".join(lines)


def _format_tool_output_compact(
    tool_name: str, tool_output: str, tool_input: dict = None
) -> str:
    """
    Format tool output compactly for context blocks (less whitespace).
    Returns output wrapped in code block without extra indentation.
    """
    import ast
    import json

    MAX_LINES = 12  # Slightly fewer lines for compact view
    MAX_CHARS = 800  # Context blocks are smaller

    # Handle MCP tools - parse the content array and extract text
    if tool_name.startswith("mcp__"):
        try:
            if isinstance(tool_output, str):
                data = (
                    ast.literal_eval(tool_output)
                    if tool_output.startswith("[")
                    else json.loads(tool_output)
                )
            else:
                data = tool_output

            # MCP tools return: [{"type": "text", "text": "..."}] format
            if isinstance(data, list) and len(data) > 0:
                first_item = data[0]
                if isinstance(first_item, dict) and first_item.get("type") == "text":
                    text_content = first_item.get("text", "")
                    # Try to parse if it's JSON
                    try:
                        parsed = json.loads(text_content)
                        # If it's a dict with success/error keys, format nicely
                        if isinstance(parsed, dict):
                            if parsed.get("success") is False:
                                return f"```Error: {parsed.get('error', 'Unknown error')}```"
                            # Otherwise format as compact JSON
                            formatted = json.dumps(parsed, indent=2)
                            lines = formatted.split("\n")
                            if len(lines) > MAX_LINES:
                                return (
                                    "```"
                                    + "\n".join(lines[:MAX_LINES])
                                    + f"\n... +{len(lines) - MAX_LINES} lines```"
                                )
                            return f"```{formatted}```"
                    except (ValueError, json.JSONDecodeError):
                        # Not JSON, show as plain text
                        if len(text_content) > MAX_CHARS:
                            lines = text_content.split("\n")
                            if len(lines) > MAX_LINES:
                                return (
                                    "```"
                                    + "\n".join(lines[:MAX_LINES])
                                    + f"\n... +{len(lines) - MAX_LINES} lines```"
                                )
                            return f"```{text_content[:MAX_CHARS]}...\n... +{len(text_content) - MAX_CHARS} chars```"
                        return f"```{text_content}```"
        except Exception:
            pass  # Fall through to default handling

    # Parse if needed
    data = None
    if isinstance(tool_output, dict):
        data = tool_output
    elif (
        tool_output
        and isinstance(tool_output, str)
        and (tool_output.startswith("{") or tool_output.startswith("["))
    ):
        try:
            data = json.loads(tool_output)
        except (json.JSONDecodeError, TypeError):
            try:
                data = ast.literal_eval(tool_output)
            except (ValueError, SyntaxError):
                pass

    # Extract content based on tool type
    import logging

    logger = logging.getLogger(__name__)

    content = ""
    if tool_name == "Read":
        content = _extract_read_content(tool_output, data)
    elif tool_name == "Bash":
        content = _extract_bash_output(tool_output, data)
        # Check if this is a background task
        if data and isinstance(data, dict) and "backgroundTaskId" in data:
            task_id = data["backgroundTaskId"]
            return (
                f"```\n🔄 Process started in background\n📌 Process ID: {task_id}\n```"
            )
    elif tool_name == "Glob":
        content = _extract_glob_output(tool_output, data)
    elif tool_name == "Grep":
        content = _extract_grep_output(tool_output, data)
    elif tool_name == "Write":
        # For Write, show the actual content written (from output, not input)
        # Write output schema: {"type": "create", "filePath": str, "content": str, ...}
        # Use output instead of input because input.content may be truncated in logs
        content = _extract_write_output(tool_output, data)
        if content:
            # Use the same formatting as Read tool for consistency
            return _format_with_line_numbers(content, MAX_LINES)
    elif tool_name == "Edit":
        # For Edit, use structuredPatch from output (has actual line numbers!)
        # Output schema: {"structuredPatch": [...], "filePath": str, ...}
        content = _extract_edit_output(tool_output, data)
    elif tool_name == "TodoWrite":
        # Format todo list nicely
        return _format_todowrite_output(tool_output, data)
    elif tool_name == "KillShell":
        # Format kill message nicely
        return _format_killshell_output(tool_output, data)
    elif tool_name == "Task":
        # Format subagent Task output nicely
        return _format_task_output(tool_output, data, tool_input)
    elif tool_name == "TaskOutput":
        # Format task output nicely
        return _format_taskoutput_output(tool_output, data)
    elif tool_name == "WebSearch":
        # Format web search results nicely
        return _format_websearch_output_compact(tool_output, data, logger)
    elif tool_name == "WebFetch":
        # Format web fetch results nicely
        return _format_webfetch_output_compact(tool_output, data, logger)
    elif tool_name == "AskUserQuestion":
        # Format Q&A nicely - show questions and user's answers
        return _format_askuserquestion_output(tool_output, data, tool_input, logger)
    else:
        # Try common keys
        if data and isinstance(data, dict):
            for key in ["content", "stdout", "output", "result", "text", "message"]:
                if key in data and data[key]:
                    content = str(data[key])
                    break
        elif isinstance(tool_output, str) and not tool_output.startswith("{"):
            content = tool_output

    # Fallback: if we still have no content but have raw output, try to show something
    if not content and tool_output:
        # If it's a plain string, show it
        if (
            isinstance(tool_output, str)
            and not tool_output.startswith("{")
            and not tool_output.startswith("[")
        ):
            content = tool_output
        # If we parsed data but didn't extract, try to stringify it reasonably
        elif data and isinstance(data, dict):
            # Just show the first non-empty value
            for v in data.values():
                if v and isinstance(v, str) and len(v) > 5:
                    content = v[:500]
                    break

    if not content:
        return ""

    # Format with line numbers for Read, plain for others
    if tool_name == "Read":
        lines = content.split("\n")
        formatted_lines = []
        char_count = 0

        for i, line in enumerate(lines[:MAX_LINES], 1):
            if len(line) > 80:
                line = line[:80] + "..."
            formatted_line = f"{i}→{line}"
            if char_count + len(formatted_line) > MAX_CHARS:
                break
            formatted_lines.append(formatted_line)
            char_count += len(formatted_line) + 1

        result = "\n".join(formatted_lines)
        remaining = len(lines) - len(formatted_lines)
        if remaining > 0:
            result += f"\n... +{remaining} {'line' if remaining == 1 else 'lines'}"
    else:
        lines = content.split("\n")
        output_lines = []
        char_count = 0

        for line in lines[:MAX_LINES]:
            if len(line) > 100:
                line = line[:100] + "..."
            if char_count + len(line) > MAX_CHARS:
                break
            output_lines.append(line)
            char_count += len(line) + 1

        result = "\n".join(output_lines)
        remaining = len(lines) - len(output_lines)
        if remaining > 0:
            result += f"\n... +{remaining} {'line' if remaining == 1 else 'lines'}"

    return f"```\n{result}\n```"


def _convert_table_to_list(text: str) -> str:
    """
    Convert markdown tables to formatted lists for modal display.

    Example:
    | Tool | Status |          →    ‣ Tool A
    |------|--------|                    Status: SUCCESS
    | A    | SUCCESS|
    | B    | FAILED |                ‣ Tool B
                                        Status: FAILED
    """
    import re

    # Find all markdown tables
    table_pattern = r"\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)+"

    def replace_table(match):
        table_text = match.group(0)
        lines = [line.strip() for line in table_text.split("\n") if line.strip()]

        if len(lines) < 3:  # Need at least header, separator, and one data row
            return table_text

        # Parse header
        header_line = lines[0]
        headers = [
            h.strip() for h in header_line.split("|")[1:-1]
        ]  # Remove first/last empty

        # Skip separator line (lines[1])

        # Parse data rows
        data_rows = []
        for line in lines[2:]:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if cells:  # Non-empty row
                data_rows.append(cells)

        if not data_rows or not headers:
            return table_text

        # Convert to formatted list with better spacing
        result = []
        for idx, row in enumerate(data_rows):
            # First column becomes the bullet point
            if len(row) > 0:
                result.append(f"‣ {row[0]}")

                # Remaining columns become indented key-value pairs
                for i in range(1, len(row)):
                    if i < len(headers):
                        # Use visible indentation that won't get stripped by markdown processing
                        result.append(f"   ↳ {headers[i]}: {row[i]}")

                # Add blank line between items (except after last)
                if idx < len(data_rows) - 1:
                    result.append("")

        return "\n".join(result)

    # Replace all tables
    converted = re.sub(table_pattern, replace_table, text)
    return converted


def _is_output_truncated(formatted_output: str) -> bool:
    """Check if tool output was truncated (has '... +X lines' indicator)."""
    return "... +" in formatted_output and " lines" in formatted_output


def build_full_output_modal(
    tool_name: str, file_path: str, full_content: str, add_line_numbers: bool = True
) -> dict:
    """
    Build a modal showing the full, untruncated output of a tool.

    Args:
        tool_name: Name of the tool (Read, Write, WebSearch, etc.)
        file_path: Path to the file (or query for search tools)
        full_content: Full content to display
        add_line_numbers: Whether to add line numbers (default True for files, False for search)

    Returns:
        Modal view dict
    """
    blocks = []

    # Split content into chunks (Slack limit: 3000 chars per text block)
    MAX_CHUNK_SIZE = 2900  # Leave buffer for code block markers
    MAX_BLOCKS = 99  # Leave 1 for truncation note if needed

    lines = full_content.split("\n")

    # Format with line numbers if requested
    if add_line_numbers:
        formatted_lines = [f"{i}→{line}" for i, line in enumerate(lines, 1)]
    else:
        formatted_lines = lines
    # Split into chunks
    chunks = []
    current_chunk = ""

    for line in formatted_lines:
        if len(current_chunk) + len(line) + 1 > MAX_CHUNK_SIZE:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)

    # Add chunks as code blocks
    for i, chunk in enumerate(chunks[:MAX_BLOCKS]):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```\n{chunk}\n```"},
            }
        )

    # Add truncation note if exceeded block limit
    if len(chunks) > MAX_BLOCKS:
        # Calculate how many lines were shown vs total
        lines_shown = sum(chunk.count("\n") + 1 for chunk in chunks[:MAX_BLOCKS])
        remaining_lines = len(lines) - lines_shown
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_... truncated {remaining_lines} more {'line' if remaining_lines == 1 else 'lines'} ({len(lines)} total)_",
                    }
                ],
            }
        )

    # Truncate file path if too long for title
    title_text = f"{tool_name}: {file_path}"
    if len(title_text) > 24:  # Slack title limit
        # Show just filename
        import os

        filename = os.path.basename(file_path)
        title_text = f"{tool_name}: {filename}"
        if len(title_text) > 24:
            title_text = f"{tool_name} Output"

    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": title_text},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
    }


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

    # Still not found - just return the full result
    # This handles cases where the thought was modified in the result
    return result


# =============================================================================
# Block Limit Helpers - Handle Slack's 100 block and 3000 char limits
# =============================================================================


def _process_text_to_blocks(text: str) -> list:
    """
    Process text into Slack blocks, splitting on horizontal rules and paragraphs.

    This matches the logic in message_builder.py to ensure consistent rendering
    between main messages and modals.

    Strategy:
    1. Split on horizontal rules (---) → divider blocks
    2. Split on double newlines (\n\n) → separate section blocks
    3. Split long blocks (>2900 chars) → multiple section blocks

    Args:
        text: Text to process

    Returns:
        List of Slack blocks (section, divider)
    """
    import re

    from markdown_utils import slack_mrkdwn

    blocks = []

    # Protect code blocks from being split
    code_blocks = []

    def save_code_block(match):
        code_blocks.append(match.group(0))
        return f"___CODE_BLOCK_{len(code_blocks)-1}___"

    text = re.sub(r"```[\s\S]*?```", save_code_block, text)

    # Split on horizontal rules (--- on its own line, not in tables)
    segments = re.split(r"\n+(?!.*\|)---+(?!.*\|)\n+", text)

    for i, segment in enumerate(segments):
        segment = segment.strip()
        if not segment:
            continue

        # Split segment on double newlines to create separate blocks per paragraph
        paragraphs = segment.split("\n\n")

        for para in paragraphs:
            para = para.rstrip()
            if not para.lstrip():
                continue

            # Restore code blocks
            for j, code_block in enumerate(code_blocks):
                para = para.replace(f"___CODE_BLOCK_{j}___", code_block)

            # Format with markdown
            formatted = slack_mrkdwn(para)

            # Split if exceeds char limit
            if len(formatted) > 2900:
                chunks = _split_text_for_blocks(formatted, 2900)
                for chunk in chunks:
                    blocks.append(
                        {"type": "section", "text": {"type": "mrkdwn", "text": chunk}}
                    )
            else:
                blocks.append(
                    {"type": "section", "text": {"type": "mrkdwn", "text": formatted}}
                )

        # Add divider between segments (except after the last one)
        if i < len(segments) - 1:
            blocks.append({"type": "divider"})

    return blocks


def _split_text_for_blocks(text: str, max_len: int = 2900) -> list:
    """
    Split text into chunks that fit within Slack's 3000 char limit.

    Tries to break at natural boundaries (newlines, sentences) to preserve readability.
    No information is lost - all content is preserved across multiple chunks.

    Args:
        text: Text to split
        max_len: Maximum length per chunk (default 2900 for safety margin)

    Returns:
        List of text chunks
    """
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""

    for line in text.split("\n"):
        # If adding this line would exceed the limit
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current)
            # If a single line is too long, split it at word boundaries
            if len(line) > max_len:
                words = line.split(" ")
                current = ""
                for word in words:
                    if len(current) + len(word) + 1 > max_len:
                        if current:
                            chunks.append(current)
                        current = word
                    else:
                        current = current + " " + word if current else word
            else:
                current = line
        else:
            current = current + "\n" + line if current else line

    if current:
        chunks.append(current)

    return chunks


def _combine_section_blocks(blocks: list, max_blocks: int = 100) -> list:
    """
    Combine consecutive section blocks to reduce total block count.

    Only applies compression if we're over Slack's block limit.
    This preserves semantic meaning and visual separation for normal modals.

    Strategy:
    1. Check if blocks > max_blocks, if not, return as-is
    2. Combine small consecutive section blocks (< 600 chars combined)
    3. Keep bold subheadings with their following content
    4. Never combine across dividers (those are intentional breaks)
    5. Respect max 3000 char limit per block

    Args:
        blocks: List of Slack blocks
        max_blocks: Maximum allowed blocks (default 100 for modals)

    Returns:
        List of combined blocks (or original if under limit)
    """
    # Only compress if we're over the block limit
    if len(blocks) <= max_blocks:
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

        # Skip blocks with accessories (buttons, etc.)
        if current.get("accessory"):
            combined.append(current)
            i += 1
            continue

        # Try to combine with next blocks
        combined_text = current.get("text", {}).get("text", "")
        j = i + 1

        # Look ahead and combine consecutive section blocks
        while j < len(blocks):
            next_block = blocks[j]

            # Stop at dividers or non-section blocks
            if next_block.get("type") != "section":
                break

            # Stop at blocks with accessories
            if next_block.get("accessory"):
                break

            next_text = next_block.get("text", {}).get("text", "")
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


def _ensure_text_block_limits(blocks: list) -> list:
    """
    Ensure all text blocks respect Slack's 3000 character limit.

    If a block exceeds the limit, split it into multiple blocks.
    This is a safety net - ideally content should be properly sized upstream.

    Args:
        blocks: List of Slack blocks

    Returns:
        List of blocks with all text within limits
    """
    MAX_TEXT_LEN = 2900  # Safety margin below 3000
    result = []

    for block in blocks:
        block_type = block.get("type")

        if block_type == "section":
            text_obj = block.get("text", {})
            text = text_obj.get("text", "")

            if len(text) > MAX_TEXT_LEN:
                # Split into multiple blocks
                chunks = _split_text_for_blocks(text, MAX_TEXT_LEN)
                for chunk in chunks:
                    result.append(
                        {
                            "type": "section",
                            "text": {
                                "type": text_obj.get("type", "mrkdwn"),
                                "text": chunk,
                            },
                        }
                    )
            else:
                result.append(block)

        elif block_type == "context":
            # Context blocks have element limit, handle carefully
            elements = block.get("elements", [])
            safe_elements = []
            for elem in elements:
                if elem.get("type") in ("mrkdwn", "plain_text"):
                    text = elem.get("text", "")
                    if len(text) > MAX_TEXT_LEN:
                        # Truncate context elements (they're meant to be short)
                        elem = {**elem, "text": text[: MAX_TEXT_LEN - 3] + "..."}
                safe_elements.append(elem)
            result.append({**block, "elements": safe_elements})

        else:
            # Other block types (divider, header, actions, etc.) - pass through
            result.append(block)

    return result


def build_subagent_detail_modal(
    thread_id: str,
    task_tool: dict,
    children: list,
    loading_url: str = None,
    done_url: str = None,
    thought_idx: int = 0,
    page: int = 1,
) -> dict:
    """
    Build a modal showing detailed view of a subagent's tool calls.

    Args:
        thread_id: Thread ID for button values
        task_tool: The Task tool dict
        children: List of (idx, tool) tuples for child tools
        loading_url: URL for loading animation (S3-hosted)
        done_url: URL for done checkmark (S3-hosted)
        thought_idx: Index of the thought containing this subagent (for button values)
        page: Page number for pagination (1-indexed)

    Returns:
        Modal view dict
    """
    import json

    # Use URL parameters (ignore deprecated file_id params)
    loading_icon = loading_url
    done_icon = done_url

    blocks = []

    task_input = task_tool.get("input", {})
    task_output = task_tool.get("output", "")
    task_success = task_tool.get("success", True)
    description = task_input.get("description", "Subagent task")

    # Parse task output JSON early to extract full prompt
    import ast
    import json

    data = None
    if isinstance(task_output, dict):
        data = task_output
    elif (
        task_output
        and isinstance(task_output, str)
        and (task_output.startswith("{") or task_output.startswith("["))
    ):
        try:
            data = json.loads(task_output)
        except (json.JSONDecodeError, TypeError):
            try:
                data = ast.literal_eval(task_output)
            except (ValueError, SyntaxError):
                pass

    # Add header with full description and status
    status_icon = "✅" if task_success else "❌"
    blocks.append(
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{status_icon} {description}"},
        }
    )

    # Show the full prompt (what the subagent was asked to do)
    # Try to get full prompt from output data first (input may be truncated)
    prompt = None
    if data:
        prompt = data.get("prompt")  # Full prompt is in the output
    if not prompt:
        prompt = task_input.get("prompt", "")  # Fallback to input

    if prompt:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "*📝 Prompt:*"}],
            }
        )
        # Prompts are usually plain instructions, just wrap in code block
        # Format with slack_mrkdwn for proper escaping
        formatted_prompt = f"```\n{prompt}\n```"
        # Split if too long
        MAX_CHUNK = 2900
        if len(formatted_prompt) > MAX_CHUNK:
            chunks = _split_text_for_blocks(formatted_prompt, MAX_CHUNK)
            for chunk in chunks[:5]:  # Max 5 chunks
                blocks.append(
                    {"type": "section", "text": {"type": "mrkdwn", "text": chunk}}
                )
        else:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": formatted_prompt},
                }
            )

    blocks.append({"type": "divider"})

    # Tool calls section
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*📋 {len(children)} Tool Calls*"}
            ],
        }
    )

    # Render each child tool
    for child_idx, tool in children:
        tool_name = tool.get("name", "Unknown")
        tool_input = tool.get("input", {})
        tool_output = tool.get("output", "")
        tool_success = tool.get("success", True)
        is_running = tool.get("running", False)

        # Tool header line
        tool_desc = _format_tool_description(
            tool_name,
            tool_input,
            tool_output,
            is_running,
            thought_completed=True,
            timed_out=False,
        )

        tool_elements = [{"type": "mrkdwn", "text": f"{EM_SPACE}{EM_SPACE}{EM_SPACE}↳"}]

        if is_running and loading_icon:
            tool_elements.append(
                {
                    "type": "image",
                    "image_url": loading_icon,
                    "alt_text": "Loading",
                }
            )
        elif tool_success and done_icon:
            tool_elements.append(
                {
                    "type": "image",
                    "image_url": done_icon,
                    "alt_text": "Done",
                }
            )

        tool_elements.append({"type": "mrkdwn", "text": tool_desc})

        blocks.append({"type": "context", "elements": tool_elements})

        # Show tool input if meaningful
        if tool_input and _should_show_input(tool_name, tool_input):
            input_text = _format_tool_input_detailed(tool_name, tool_input, tool_output)
            if input_text:
                # Chunk if very long, otherwise truncate
                if len(input_text) > 2000:
                    MAX_CHUNK = 2900
                    wrapped = f"```{input_text}```"
                    if len(wrapped) > MAX_CHUNK:
                        chunks = [
                            input_text[i : i + MAX_CHUNK - 10]
                            for i in range(0, len(input_text), MAX_CHUNK - 10)
                        ]
                        for i, chunk in enumerate(chunks[:5]):
                            prefix = "```" if i == 0 else ""
                            suffix = "```" if i == len(chunks) - 1 or i == 4 else ""
                            blocks.append(
                                {
                                    "type": "context",
                                    "elements": [
                                        {
                                            "type": "mrkdwn",
                                            "text": f"{prefix}{chunk}{suffix}",
                                        }
                                    ],
                                }
                            )
                    else:
                        blocks.append(
                            {
                                "type": "context",
                                "elements": [{"type": "mrkdwn", "text": wrapped}],
                            }
                        )
                else:
                    blocks.append(
                        {
                            "type": "context",
                            "elements": [
                                {"type": "mrkdwn", "text": f"```{input_text}```"}
                            ],
                        }
                    )

        # Show tool output (with "View full" button if truncated)
        if tool_output:
            formatted_output = _format_tool_output_compact(
                tool_name, tool_output, tool_input
            )
            if formatted_output:
                # Check if output was truncated (has '... +X lines' indicator)
                is_truncated = _is_output_truncated(formatted_output)

                if is_truncated:
                    # Show with "View full" button
                    clean_output = formatted_output.lstrip("\u2003")  # Remove indent
                    blocks.append(
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": clean_output},
                            "accessory": {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "📄 View Full"},
                                "action_id": "view_full_output",
                                "value": f"{thread_id}|{thought_idx}|{child_idx}",
                            },
                        }
                    )
                else:
                    blocks.append(
                        {
                            "type": "context",
                            "elements": [{"type": "mrkdwn", "text": formatted_output}],
                        }
                    )

    blocks.append({"type": "divider"})

    # Subagent result/summary
    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "*💬 Result:*"}]}
    )

    # Extract result text from Task output
    result_text = ""
    if data:
        content = data.get("content", [])
        if content and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    result_text = block.get("text", "")
                    break

    # If we have result text, use the same text processing as main modal
    if result_text:
        result_blocks = _process_text_to_blocks(result_text)
        blocks.extend(result_blocks)

    # Ensure text blocks respect 3000 char limit
    blocks = _ensure_text_block_limits(blocks)

    # Pagination if blocks exceed limit
    BLOCKS_PER_PAGE = 95  # Leave room for pagination controls

    # Get the subagent_id for pagination buttons
    subagent_id = task_tool.get("tool_use_id", "")

    total_pages = (len(blocks) + BLOCKS_PER_PAGE - 1) // BLOCKS_PER_PAGE

    if total_pages > 1:
        # Calculate page bounds
        start_idx = (page - 1) * BLOCKS_PER_PAGE
        end_idx = min(start_idx + BLOCKS_PER_PAGE, len(blocks))

        blocks = blocks[start_idx:end_idx]

        # Add pagination controls
        blocks.append({"type": "divider"})

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Page {page} of {total_pages}"}
                ],
            }
        )

        # Navigation buttons
        pagination_elements = []

        if page > 1:
            pagination_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "← Previous"},
                    "action_id": "subagent_modal_page_prev",
                    "value": json.dumps(
                        {
                            "thread_id": thread_id,
                            "thought_idx": thought_idx,
                            "subagent_id": subagent_id,
                            "page": page - 1,
                        }
                    ),
                }
            )

        if page < total_pages:
            pagination_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Next →"},
                    "action_id": "subagent_modal_page_next",
                    "value": json.dumps(
                        {
                            "thread_id": thread_id,
                            "thought_idx": thought_idx,
                            "subagent_id": subagent_id,
                            "page": page + 1,
                        }
                    ),
                }
            )

        if pagination_elements:
            blocks.append({"type": "actions", "elements": pagination_elements})

    # Store pagination metadata
    metadata = json.dumps(
        {
            "thread_id": thread_id,
            "thought_idx": thought_idx,
            "subagent_id": subagent_id,
            "page": page,
            "total_pages": total_pages if total_pages > 1 else 1,
        }
    )

    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Subagent Details"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
        "private_metadata": metadata,
    }
