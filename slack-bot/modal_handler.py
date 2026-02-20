"""
Modal view handlers, question/answer flow, and feedback collection.

Handles investigation session modals, tool output display, pagination,
question answering (checkbox/toggle/submit), and user feedback.
"""

import logging
import os
import re

import requests
from state import (
    _button_selections,
    _investigation_cache,
    _load_session_from_db,
    _pending_questions,
    _question_messages,
)

logger = logging.getLogger(__name__)

SRE_AGENT_URL = os.environ.get("SRE_AGENT_URL", "http://localhost:8000")


def get_config_client():
    from config_client import get_config_client as _get_config_client

    return _get_config_client()


def handle_positive_feedback(ack, body):
    """Handle positive feedback."""
    ack()
    logger.info(f"Positive feedback: {body.get('message', {}).get('ts')}")


def handle_negative_feedback(ack, body):
    """Handle negative feedback."""
    ack()
    logger.info(f"Negative feedback: {body.get('message', {}).get('ts')}")


def handle_view_session(ack, body, client):
    """Handle "View Session" button - open modal with chronological timeline."""
    ack()

    # Get message_ts from button value (unique per message, unlike thread_id)
    message_ts = body["actions"][0].get("value", "unknown")

    # Lookup investigation state: try in-memory cache first, then DB
    logger.info(f"View Session clicked: message_ts={message_ts}")
    state = _investigation_cache.get(message_ts)
    if not state:
        logger.info(f"Cache miss for message_ts={message_ts}, trying DB...")
        state = _load_session_from_db(message_ts)
    if not state:
        logger.warning(f"No cached or persisted state for message_ts: {message_ts}")
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

    # Get S3-hosted asset URLs for modal
    from assets_config import get_asset_url

    loading_url = get_asset_url("loading")
    done_url = get_asset_url("done")

    # Build modal with hierarchical thoughts (same formatting as main message)
    from modal_builder import build_session_modal

    modal = build_session_modal(
        thread_id=message_ts,  # Pass message_ts as cache key (named thread_id for modal builder compat)
        thoughts=state.thoughts,
        result=state.final_result,
        loading_url=loading_url,
        done_url=done_url,
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

    # Lookup investigation state: try in-memory cache, then DB
    state = _investigation_cache.get(thread_id)
    if not state:
        state = _load_session_from_db(thread_id)
    if not state:
        logger.warning(f"No cached state for pagination: {thread_id}")
        return

    # Get S3-hosted asset URLs for modal
    from assets_config import get_asset_url

    loading_url = get_asset_url("loading")
    done_url = get_asset_url("done")

    # Build modal for requested page
    from modal_builder import build_session_modal

    modal = build_session_modal(
        thread_id=thread_id,
        thoughts=state.thoughts,
        result=state.final_result,
        loading_url=loading_url,
        done_url=done_url,
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


def handle_modal_page_info(ack):
    """Handle click on page info button (no-op, just acknowledge)."""
    ack()


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

    # Lookup investigation state: try in-memory cache, then DB
    state = _investigation_cache.get(thread_id)
    if not state:
        state = _load_session_from_db(thread_id)
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


def handle_view_full_output(ack, body, client):
    """Handle "View Full" button - show complete untruncated file content."""
    ack()

    # Parse button value: thread_id|thought_idx|tool_idx
    button_value = body["actions"][0].get("value", "")
    try:
        thread_id, thought_idx, tool_idx = button_value.split("|")
        thought_idx = int(thought_idx)
        tool_idx = int(tool_idx)
    except (ValueError, AttributeError):
        logger.warning(f"Invalid button value: {button_value}")
        return

    # Lookup investigation state: try in-memory cache, then DB
    state = _investigation_cache.get(thread_id)
    if not state:
        state = _load_session_from_db(thread_id)
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


def handle_view_subagent_details(ack, body, client):
    """Handle "View Details" button for subagent - show all child tool calls."""
    ack()

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

    # Lookup investigation state: try in-memory cache, then DB
    state = _investigation_cache.get(thread_id)
    if not state:
        state = _load_session_from_db(thread_id)
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

    # Lookup investigation state: try in-memory cache, then DB
    state = _investigation_cache.get(thread_id)
    if not state:
        state = _load_session_from_db(thread_id)
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


def handle_checkbox_action(ack, body, client):
    """Handle checkbox selections - just acknowledge, state is read on submit."""
    ack()
    # No action needed - checkbox state is captured in body["state"]["values"] on submit


def _unescape_html(text: str) -> str:
    """Unescape HTML entities that Slack may have added to block text."""
    import html

    return html.unescape(text)


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
        from investigation_handler import _sre_agent_headers

        response = requests.post(
            f"{SRE_AGENT_URL}/answer",
            json={"thread_id": thread_id, "answers": answers},
            headers=_sre_agent_headers(),
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
        except Exception:
            pass


def _build_submitted_answer_blocks(
    questions: list, answers: dict, client, body, user_id: str = None
) -> list:
    """Build blocks showing the submitted Q&A summary with checkmark image and user mention."""
    from assets_config import get_asset_url

    # Get S3-hosted checkmark image URL
    done_url = get_asset_url("done")

    blocks = []

    # Header with checkmark and user mention
    if user_id:
        header_text = f"*Answer submitted by <@{user_id}>!* Processing your response..."
    else:
        header_text = "*Answer submitted!* Processing your response..."

    header_elements = []
    if done_url:
        header_elements.append(
            {"type": "image", "image_url": done_url, "alt_text": "Done"}
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


def handle_feedback(ack, body, client):
    """Handle feedback button clicks."""
    ack()
    action = body.get("actions", [{}])[0]
    value = action.get("value", "")
    message_ts = body.get("message", {}).get("ts")

    if value == "positive":
        logger.info(f"Positive feedback for message {message_ts}")
    else:
        logger.info(f"Negative feedback for message {message_ts}")

    # Optionally update the message to show feedback was received
    # For now, just acknowledge


# Keep simple examples for testing
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


def action_button_click(body, ack, say):
    """Handle button click action."""
    ack()
    say(f"<@{body['user']['id']}> clicked the button")


def handle_github_app_install_button(ack, body):
    """
    Handle GitHub App install button click.

    The button has a URL that opens in a new tab, so we just need to ack.
    The user will complete the GitHub App installation flow externally,
    then return to the Slack modal to enter their org name.
    """
    ack()
    logger.info(
        "GitHub App install button clicked",
        user_id=body.get("user", {}).get("id"),
        team_id=body.get("team", {}).get("id"),
    )
