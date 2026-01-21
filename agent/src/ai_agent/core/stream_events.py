"""
Stream event infrastructure for sub-agent event propagation.

This module enables nested agent streaming - when the planner calls a sub-agent
like investigation_agent, events from the sub-agent are propagated back to the
main stream so users can see what's happening inside sub-agents.

Architecture:
    Main Stream (SSE)
         │
         ├── Planner events (direct from Runner.run_streamed)
         │
         └── Sub-agent events (via EventStreamRegistry)
              │
              ├── investigation_agent events
              │    ├── k8s_agent events
              │    ├── aws_agent events
              │    └── ...
              │
              └── coding_agent events

Usage:
    # In streaming endpoint:
    stream_id = str(uuid.uuid4())
    event_queue = EventStreamRegistry.create_stream(stream_id)

    try:
        async for event in stream_with_subagents(agent, message, stream_id):
            yield event
    finally:
        EventStreamRegistry.close_stream(stream_id)

    # In _run_agent_in_thread:
    queue = EventStreamRegistry.get_queue(stream_id)
    if queue:
        # Use streaming mode and forward events
"""

import queue
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class SubAgentEvent:
    """Event from a sub-agent execution."""

    event_type: (
        str  # subagent_started, tool_started, tool_completed, subagent_completed
    )
    agent_name: str
    data: dict = field(default_factory=dict)
    parent_agent: str | None = None
    depth: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sequence: int = 0


class EventStreamRegistry:
    """
    Global registry for active event streams.

    Thread-safe registry that allows sub-agents running in separate threads
    to find and emit events to the correct stream.
    """

    _lock = threading.Lock()
    _streams: dict[str, queue.Queue] = {}
    _metadata: dict[str, dict[str, Any]] = {}

    @classmethod
    def create_stream(cls, stream_id: str) -> queue.Queue:
        """
        Create a new event stream.

        Args:
            stream_id: Unique identifier for this stream (e.g., correlation_id)

        Returns:
            Queue for receiving sub-agent events
        """
        with cls._lock:
            q: queue.Queue = queue.Queue()
            cls._streams[stream_id] = q
            cls._metadata[stream_id] = {
                "created_at": datetime.now(UTC).isoformat(),
                "agent_stack": [],
                "sequence": 0,
            }
            return q

    @classmethod
    def get_queue(cls, stream_id: str) -> queue.Queue | None:
        """
        Get the event queue for a stream.

        Args:
            stream_id: Stream identifier

        Returns:
            Queue if stream exists, None otherwise
        """
        with cls._lock:
            return cls._streams.get(stream_id)

    @classmethod
    def close_stream(cls, stream_id: str) -> None:
        """
        Close and remove a stream.

        Args:
            stream_id: Stream identifier to close
        """
        with cls._lock:
            cls._streams.pop(stream_id, None)
            cls._metadata.pop(stream_id, None)

    @classmethod
    def emit_event(
        cls,
        stream_id: str,
        event_type: str,
        agent_name: str,
        data: dict | None = None,
        parent_agent: str | None = None,
    ) -> bool:
        """
        Emit an event to a stream.

        Thread-safe method that can be called from any thread.

        Args:
            stream_id: Target stream
            event_type: Type of event
            agent_name: Name of the agent emitting
            data: Event data
            parent_agent: Parent agent name if nested (auto-computed if not provided)

        Returns:
            True if event was emitted, False if stream doesn't exist
        """
        with cls._lock:
            q = cls._streams.get(stream_id)
            if q is None:
                return False

            meta = cls._metadata.get(stream_id, {})
            seq = meta.get("sequence", 0) + 1
            meta["sequence"] = seq

            stack = meta.get("agent_stack", [])
            depth = len(stack)

            # Auto-compute parent_agent if not provided
            effective_parent = parent_agent
            if effective_parent is None and len(stack) >= 2:
                effective_parent = stack[-2]

            event = SubAgentEvent(
                event_type=event_type,
                agent_name=agent_name,
                data=data or {},
                parent_agent=effective_parent,
                depth=depth,
                sequence=seq,
            )
            q.put_nowait(event)
            return True

    @classmethod
    def push_agent(cls, stream_id: str, agent_name: str) -> None:
        """Push an agent onto the call stack."""
        with cls._lock:
            meta = cls._metadata.get(stream_id)
            if meta:
                meta.setdefault("agent_stack", []).append(agent_name)

    @classmethod
    def pop_agent(cls, stream_id: str) -> str | None:
        """Pop an agent from the call stack."""
        with cls._lock:
            meta = cls._metadata.get(stream_id)
            if meta and meta.get("agent_stack"):
                return meta["agent_stack"].pop()
            return None

    @classmethod
    def get_parent_agent(cls, stream_id: str) -> str | None:
        """Get the parent of the current agent from the stack.

        Returns the second-to-last item (the parent of the current agent),
        not the current agent itself.
        """
        with cls._lock:
            meta = cls._metadata.get(stream_id)
            if meta and meta.get("agent_stack"):
                stack = meta["agent_stack"]
                # Return the parent (second-to-last) not the current agent (last)
                if len(stack) >= 2:
                    return stack[-2]
            return None

    @classmethod
    def stream_exists(cls, stream_id: str) -> bool:
        """Check if a stream exists."""
        with cls._lock:
            return stream_id in cls._streams


# Thread-local storage for the current stream_id
_thread_local = threading.local()


def set_current_stream_id(stream_id: str | None) -> None:
    """Set the stream ID for the current thread."""
    _thread_local.stream_id = stream_id


def get_current_stream_id() -> str | None:
    """Get the stream ID for the current thread."""
    return getattr(_thread_local, "stream_id", None)


def emit_to_current_stream(
    event_type: str,
    agent_name: str,
    data: dict | None = None,
) -> bool:
    """
    Emit an event to the current thread's stream.

    Convenience function for use in _run_agent_in_thread.

    Args:
        event_type: Type of event
        agent_name: Name of the agent
        data: Event data

    Returns:
        True if emitted, False if no stream
    """
    stream_id = get_current_stream_id()
    if not stream_id:
        return False

    parent = EventStreamRegistry.get_parent_agent(stream_id)
    return EventStreamRegistry.emit_event(
        stream_id=stream_id,
        event_type=event_type,
        agent_name=agent_name,
        data=data,
        parent_agent=parent,
    )


def emit_raw_event_to_current_stream(event_data: dict) -> bool:
    """
    Emit a raw event dict to the current thread's stream.

    This is used for special events like human_input_required that don't
    follow the standard SubAgentEvent structure.

    Args:
        event_data: Raw event dictionary to emit

    Returns:
        True if emitted, False if no stream
    """
    stream_id = get_current_stream_id()
    if not stream_id:
        return False

    with EventStreamRegistry._lock:
        q = EventStreamRegistry._streams.get(stream_id)
        if q is None:
            return False

        # Create a special event that carries raw data
        event = SubAgentEvent(
            event_type=event_data.get("type", "raw_event"),
            agent_name="system",
            data=event_data,
            depth=0,
        )
        q.put_nowait(event)
        return True
