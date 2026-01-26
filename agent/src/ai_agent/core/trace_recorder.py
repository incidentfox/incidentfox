"""
Trace Recorder - Captures tool calls and agent activity for persistent tracing.

This module provides RunHooks that capture detailed trace data during agent runs,
which is then persisted to the config service for later viewing in the UI.

Architecture:
    Agent Run
         │
         ├── TraceRecorderHooks (captures tool calls)
         │      ├── on_tool_start → records start time
         │      ├── on_tool_end → records tool call with input/output
         │      └── on_handoff → records agent transitions
         │
         └── After run completes → POST to config service

Usage:
    from ai_agent.core.trace_recorder import TraceRecorderHooks, record_trace

    hooks = TraceRecorderHooks(run_id=run_id, agent_name="planner")

    result = await Runner.run(agent, message, hooks=hooks)

    # Record trace to config service
    await record_trace(run_id, hooks.get_trace_data())
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from agents import Agent, RunHooks
from agents.run_context import RunContextWrapper
from agents.tool import Tool

from .logging import get_logger

logger = get_logger(__name__)

# Config service URL from environment
import os

CONFIG_SERVICE_URL = os.getenv("CONFIG_SERVICE_URL", "http://localhost:8080")


@dataclass
class ToolCallRecord:
    """Record of a single tool call."""

    id: str
    tool_name: str
    agent_name: str
    parent_agent: str | None
    tool_input: dict | None
    tool_output: str | None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None
    status: str = "running"
    error_message: str | None = None
    sequence_number: int = 0

    def to_dict(self) -> dict:
        """Convert to dict for API submission."""
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "agent_name": self.agent_name,
            "parent_agent": self.parent_agent,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_message": self.error_message,
            "sequence_number": self.sequence_number,
        }


@dataclass
class AgentSpan:
    """Record of an agent's execution span."""

    agent_name: str
    parent_agent: str | None
    started_at: datetime
    ended_at: datetime | None = None
    status: str = "running"
    tool_count: int = 0


@dataclass
class TraceData:
    """Complete trace data for a run."""

    run_id: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    agent_spans: list[AgentSpan] = field(default_factory=list)
    agent_stack: list[str] = field(default_factory=list)
    sequence_counter: int = 0

    def to_api_format(self) -> dict:
        """Convert to format expected by config service API."""
        return {
            "run_id": self.run_id,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
        }


class TraceRecorderHooks(RunHooks):
    """
    RunHooks implementation that records tool calls for persistent tracing.

    Captures:
    - Tool name, input arguments, output result
    - Duration of each tool call
    - Which agent made the call
    - Success/error status
    """

    def __init__(
        self,
        run_id: str,
        agent_name: str,
        parent_agent: str | None = None,
    ):
        """
        Initialize trace recorder.

        Args:
            run_id: Unique ID for the agent run
            agent_name: Name of the primary agent
            parent_agent: Parent agent name if this is a sub-agent
        """
        self.trace = TraceData(run_id=run_id)
        self.trace.agent_stack.append(agent_name)

        # Track in-progress tool calls by a composite key
        self._pending_calls: dict[str, ToolCallRecord] = {}

        # Create initial agent span
        self.trace.agent_spans.append(
            AgentSpan(
                agent_name=agent_name,
                parent_agent=parent_agent,
                started_at=datetime.now(UTC),
            )
        )

    @property
    def current_agent(self) -> str:
        """Get the current agent name from the stack."""
        return self.trace.agent_stack[-1] if self.trace.agent_stack else "unknown"

    @property
    def parent_agent(self) -> str | None:
        """Get the parent agent name from the stack."""
        if len(self.trace.agent_stack) >= 2:
            return self.trace.agent_stack[-2]
        return None

    async def on_tool_start(
        self,
        context: RunContextWrapper,
        agent: Agent,
        tool: Tool,
    ) -> None:
        """Called when a tool is about to run."""
        try:
            tool_name = getattr(tool, "name", str(tool))
            call_id = str(uuid.uuid4())

            self.trace.sequence_counter += 1

            # Try to get tool input from the context
            tool_input = None
            # The tool input is typically in context.tool_input or similar
            if hasattr(context, "tool_input"):
                tool_input = context.tool_input
            elif hasattr(context, "arguments"):
                tool_input = context.arguments

            record = ToolCallRecord(
                id=call_id,
                tool_name=tool_name,
                agent_name=self.current_agent,
                parent_agent=self.parent_agent,
                tool_input=tool_input,
                tool_output=None,
                started_at=datetime.now(UTC),
                sequence_number=self.trace.sequence_counter,
                status="running",
            )

            # Store pending call - use tool_name as key since we process sequentially
            self._pending_calls[tool_name] = record

            logger.debug(
                "trace_tool_start",
                run_id=self.trace.run_id,
                tool=tool_name,
                agent=self.current_agent,
                sequence=self.trace.sequence_counter,
            )

        except Exception as e:
            logger.warning("trace_recorder_error", hook="on_tool_start", error=str(e))

    async def on_tool_end(
        self,
        context: RunContextWrapper,
        agent: Agent,
        tool: Tool,
        result: str,
    ) -> None:
        """Called when a tool finishes."""
        try:
            tool_name = getattr(tool, "name", str(tool))

            # Find the pending call
            record = self._pending_calls.pop(tool_name, None)

            if record:
                record.ended_at = datetime.now(UTC)
                record.tool_output = str(result)[:5000] if result else None
                record.status = "success"

                # Calculate duration
                if record.started_at:
                    delta = record.ended_at - record.started_at
                    record.duration_ms = int(delta.total_seconds() * 1000)

                self.trace.tool_calls.append(record)

                # Update agent span tool count
                for span in reversed(self.trace.agent_spans):
                    if span.agent_name == self.current_agent:
                        span.tool_count += 1
                        break

                logger.debug(
                    "trace_tool_end",
                    run_id=self.trace.run_id,
                    tool=tool_name,
                    agent=self.current_agent,
                    duration_ms=record.duration_ms,
                )
            else:
                # Tool end without matching start - create record anyway
                self.trace.sequence_counter += 1
                record = ToolCallRecord(
                    id=str(uuid.uuid4()),
                    tool_name=tool_name,
                    agent_name=self.current_agent,
                    parent_agent=self.parent_agent,
                    tool_input=None,
                    tool_output=str(result)[:5000] if result else None,
                    started_at=datetime.now(UTC),
                    duration_ms=0,
                    status="success",
                    sequence_number=self.trace.sequence_counter,
                )
                self.trace.tool_calls.append(record)

        except Exception as e:
            logger.warning("trace_recorder_error", hook="on_tool_end", error=str(e))

    async def on_handoff(
        self,
        context: RunContextWrapper,
        from_agent: Agent,
        to_agent: Agent,
    ) -> None:
        """Called when one agent hands off to another."""
        try:
            from_name = getattr(from_agent, "name", str(from_agent))
            to_name = getattr(to_agent, "name", str(to_agent))

            # Close the current agent span
            for span in reversed(self.trace.agent_spans):
                if span.agent_name == from_name and span.ended_at is None:
                    span.ended_at = datetime.now(UTC)
                    span.status = "completed"
                    break

            # Push new agent onto stack
            self.trace.agent_stack.append(to_name)

            # Create new agent span
            self.trace.agent_spans.append(
                AgentSpan(
                    agent_name=to_name,
                    parent_agent=from_name,
                    started_at=datetime.now(UTC),
                )
            )

            logger.debug(
                "trace_handoff",
                run_id=self.trace.run_id,
                from_agent=from_name,
                to_agent=to_name,
            )

        except Exception as e:
            logger.warning("trace_recorder_error", hook="on_handoff", error=str(e))

    def get_trace_data(self) -> TraceData:
        """Get the complete trace data."""
        # Close any pending tool calls
        for tool_name, record in self._pending_calls.items():
            record.ended_at = datetime.now(UTC)
            record.status = "incomplete"
            if record.started_at:
                delta = record.ended_at - record.started_at
                record.duration_ms = int(delta.total_seconds() * 1000)
            self.trace.tool_calls.append(record)
        self._pending_calls.clear()

        # Close any open agent spans
        for span in self.trace.agent_spans:
            if span.ended_at is None:
                span.ended_at = datetime.now(UTC)
                span.status = "completed"

        return self.trace


async def record_trace(run_id: str, trace_data: TraceData) -> bool:
    """
    Record trace data to config service.

    Args:
        run_id: The agent run ID
        trace_data: Complete trace data to record

    Returns:
        True if successful, False otherwise
    """
    if not trace_data.tool_calls:
        logger.debug("no_tool_calls_to_record", run_id=run_id)
        return True

    try:
        payload = trace_data.to_api_format()

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{CONFIG_SERVICE_URL}/api/v1/internal/agent-runs/{run_id}/tool-calls",
                json=payload,
                headers={"X-Internal-Service": "agent"},
            )

            if resp.status_code in (200, 201):
                logger.info(
                    "trace_recorded",
                    run_id=run_id,
                    tool_calls=len(trace_data.tool_calls),
                )
                return True
            else:
                logger.warning(
                    "trace_record_failed",
                    run_id=run_id,
                    status=resp.status_code,
                    body=resp.text[:200],
                )
                return False

    except Exception as e:
        logger.warning("trace_record_error", run_id=run_id, error=str(e))
        return False


def create_composite_hooks(
    run_id: str,
    agent_name: str,
    *other_hooks: RunHooks,
) -> tuple[TraceRecorderHooks, RunHooks | None]:
    """
    Create trace recorder hooks that can be composed with other hooks.

    Args:
        run_id: Unique ID for the agent run
        agent_name: Name of the primary agent
        other_hooks: Additional hooks to compose with

    Returns:
        Tuple of (trace_hooks, composite_hooks or None)
    """
    trace_hooks = TraceRecorderHooks(run_id=run_id, agent_name=agent_name)

    if not other_hooks:
        return trace_hooks, None

    # For now, return both - the runner may need to call them separately
    # or we could implement a CompositeHooks class
    return trace_hooks, other_hooks[0] if other_hooks else None
