"""
Platform-agnostic SSE event processor.

Processes events from sre-agent's SSE stream and updates InvestigationState.
Mirrors the event handling logic in slack-bot/stream_handler.py but without
any Slack-specific code.

SSE event types (from sre-agent/events.py):
  thought, tool_start, tool_end, result, error, question, question_timeout
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from incidentfox_orchestrator.message_state import (
    InvestigationState,
    SubagentInfo,
    ThoughtSection,
    ToolInfo,
)


def parse_sse_event(line: str) -> Optional[Dict[str, Any]]:
    """Parse an SSE data line into a dict. Returns None if not a data line."""
    if not line or not line.startswith("data: "):
        return None
    try:
        return json.loads(line[6:])
    except (json.JSONDecodeError, ValueError):
        return None


def handle_event(state: InvestigationState, event: Dict[str, Any]) -> bool:
    """
    Process a single SSE event and update the investigation state.

    Returns True if the state changed in a way that warrants a UI update.
    """
    event_type = event.get("type", "")
    data = event.get("data", {})

    if event_type == "thought":
        return _handle_thought(state, data)
    elif event_type == "tool_start":
        return _handle_tool_start(state, data)
    elif event_type == "tool_end":
        return _handle_tool_end(state, data)
    elif event_type == "result":
        return _handle_result(state, data)
    elif event_type == "error":
        return _handle_error(state, data)
    elif event_type == "question":
        return _handle_question(state, data)
    elif event_type == "question_timeout":
        return _handle_question_timeout(state)
    return False


def _handle_thought(state: InvestigationState, data: Dict[str, Any]) -> bool:
    """New thought from the agent."""
    text = data.get("text", "")
    parent_tool_use_id = data.get("parent_tool_use_id")

    # If this thought belongs to a subagent, track it there
    if parent_tool_use_id and parent_tool_use_id in state.subagents:
        # Subagent thoughts don't create top-level ThoughtSections
        return False

    # Mark the previous thought as completed
    if state.thoughts:
        state.thoughts[-1].completed = True

    state.thoughts.append(ThoughtSection(text=text))
    return True


def _handle_tool_start(state: InvestigationState, data: Dict[str, Any]) -> bool:
    """Tool execution starting."""
    name = data.get("name", "")
    tool_use_id = data.get("tool_use_id", "")
    parent_tool_use_id = data.get("parent_tool_use_id", "")

    tool = ToolInfo(
        name=name,
        tool_use_id=tool_use_id,
        parent_tool_use_id=parent_tool_use_id,
        input=data.get("input", {}),
        command=data.get("command", ""),
        file_path=data.get("file_path", ""),
        pattern=data.get("pattern", ""),
        description=data.get("description", ""),
        running=True,
    )

    # Track subagent (Task tool) invocations
    if name == "Task" and tool_use_id:
        state.subagents[tool_use_id] = SubagentInfo(
            description=data.get("description", ""),
            subagent_type=data.get("subagent_type", ""),
        )

    # If this tool belongs to a subagent, add to subagent's tools
    if parent_tool_use_id and parent_tool_use_id in state.subagents:
        state.subagents[parent_tool_use_id].tools.append(tool)
    else:
        # Add to the current thought section
        if not state.thoughts:
            state.thoughts.append(ThoughtSection(text=""))
        state.thoughts[-1].tools.append(tool)

    state.current_tool = tool
    return True


def _handle_tool_end(state: InvestigationState, data: Dict[str, Any]) -> bool:
    """Tool execution completed."""
    tool_use_id = data.get("tool_use_id", "")
    name = data.get("name", "")
    parent_tool_use_id = data.get("parent_tool_use_id", "")

    # Find the matching tool
    tool = _find_tool(state, tool_use_id, parent_tool_use_id)
    if tool:
        tool.running = False
        tool.success = data.get("success", True)
        tool.summary = data.get("summary", "")
        tool.output = data.get("output", "")

    # If this is a Task tool completing, mark the subagent done
    if name == "Task" and tool_use_id in state.subagents:
        state.subagents[tool_use_id].completed = True

    # Clear current tool if it matches
    if state.current_tool and state.current_tool.tool_use_id == tool_use_id:
        state.current_tool = None

    return True


def _handle_result(state: InvestigationState, data: Dict[str, Any]) -> bool:
    """Final result from the agent."""
    state.final_result = data.get("text", "")
    state.result_success = data.get("success", False)
    state.result_images = data.get("images")
    state.result_files = data.get("files")

    # Mark the last thought as completed
    if state.thoughts:
        state.thoughts[-1].completed = True

    return True


def _handle_error(state: InvestigationState, data: Dict[str, Any]) -> bool:
    """Error from the agent."""
    state.error = data.get("message", "Unknown error")

    # Mark the last thought as completed
    if state.thoughts:
        state.thoughts[-1].completed = True

    return True


def _handle_question(state: InvestigationState, data: Dict[str, Any]) -> bool:
    """Agent asking clarifying questions (AskUserQuestion tool)."""
    state.pending_questions = data.get("questions", [])
    return True


def _handle_question_timeout(state: InvestigationState) -> bool:
    """User didn't respond to a question in time."""
    state.pending_questions = None

    # Mark any AskUserQuestion tools as timed out
    for thought in state.thoughts:
        for tool in thought.tools:
            if tool.name == "AskUserQuestion" and tool.running:
                tool.timed_out = True
                tool.running = False

    return True


def _find_tool(
    state: InvestigationState,
    tool_use_id: str,
    parent_tool_use_id: str = "",
) -> Optional[ToolInfo]:
    """Find a tool by its use ID, checking subagents first."""
    if not tool_use_id:
        return None

    # Check subagent tools first
    if parent_tool_use_id and parent_tool_use_id in state.subagents:
        for tool in state.subagents[parent_tool_use_id].tools:
            if tool.tool_use_id == tool_use_id:
                return tool

    # Check all thought tools
    for thought in state.thoughts:
        for tool in thought.tools:
            if tool.tool_use_id == tool_use_id:
                return tool

    return None
