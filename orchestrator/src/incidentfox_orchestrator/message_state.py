"""
Platform-agnostic investigation state for Teams and Google Chat.

Mirrors slack-bot/state.py but without Slack-specific fields (channel_id,
message_ts, thread_ts). Used by stream_handler.py and message_builder/ to
track investigation progress and build rich cards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolInfo:
    """A tool execution within a thought section."""

    name: str
    tool_use_id: str = ""
    parent_tool_use_id: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    # Quick-access fields extracted from input
    command: str = ""
    file_path: str = ""
    pattern: str = ""
    description: str = ""
    # Execution state
    running: bool = True
    success: Optional[bool] = None
    summary: str = ""
    output: str = ""
    timed_out: bool = False


@dataclass
class ThoughtSection:
    """A thought with its associated tool executions."""

    text: str
    tools: List[ToolInfo] = field(default_factory=list)
    completed: bool = False


@dataclass
class SubagentInfo:
    """Tracks a subagent (Task tool) invocation."""

    description: str = ""
    subagent_type: str = ""
    completed: bool = False
    tools: List[ToolInfo] = field(default_factory=list)


@dataclass
class InvestigationState:
    """
    Platform-agnostic state for a running investigation.

    Tracks thoughts, tool executions, subagents, and the final result.
    Consumed by message_builder to produce progress/final cards.
    """

    session_id: str
    run_id: str
    correlation_id: str

    # Hierarchical thought → tool structure
    thoughts: List[ThoughtSection] = field(default_factory=list)
    current_tool: Optional[ToolInfo] = None

    # Subagent tracking (key: tool_use_id of Task tool)
    subagents: Dict[str, SubagentInfo] = field(default_factory=dict)

    # Final state
    final_result: Optional[str] = None
    result_success: bool = False
    result_images: Optional[List[Dict[str, Any]]] = None
    result_files: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None

    # Pending questions from AskUserQuestion
    pending_questions: Optional[List[Dict[str, Any]]] = None

    # Update throttling
    last_update_time: float = 0.0

    @property
    def current_thought_section(self) -> Optional[ThoughtSection]:
        """Get the most recent thought section."""
        return self.thoughts[-1] if self.thoughts else None

    @property
    def is_complete(self) -> bool:
        """Whether the investigation has finished (result or error)."""
        return self.final_result is not None or self.error is not None

    @property
    def thought_count(self) -> int:
        """Number of completed thoughts."""
        return sum(1 for t in self.thoughts if t.completed)

    @property
    def tool_count(self) -> int:
        """Total number of tools executed across all thoughts."""
        return sum(len(t.tools) for t in self.thoughts)
