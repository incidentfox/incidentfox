"""
Agent registry and execution tracking infrastructure.

This module provides:
- In-flight run tracking for graceful shutdown
- Agent run recording to config service
- Agent factory registry with caching
"""

import asyncio
import builtins
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import httpx
from agents import Agent

from .health_server import update_heartbeat
from .logging import get_correlation_id, get_logger

logger = get_logger(__name__)

# Config service URL for recording agent runs
CONFIG_SERVICE_URL = os.getenv(
    "CONFIG_SERVICE_URL", "http://incidentfox-config-service:8080"
)

# =============================================================================
# In-Flight Run Registry
# =============================================================================
# Tracks currently executing agent runs. Used for graceful shutdown to mark
# in-flight runs as failed when the process terminates.

_in_flight_runs: set[str] = set()
_in_flight_lock = threading.Lock()
_shutdown_in_progress = False


def register_in_flight_run(run_id: str) -> None:
    """Register a run as in-flight (currently executing)."""
    with _in_flight_lock:
        if not _shutdown_in_progress:
            _in_flight_runs.add(run_id)
            logger.debug("run_registered_in_flight", run_id=run_id)


def unregister_in_flight_run(run_id: str) -> None:
    """Unregister a run from in-flight tracking."""
    with _in_flight_lock:
        _in_flight_runs.discard(run_id)
        remaining_runs = len(_in_flight_runs)
        logger.debug(
            "run_unregistered_in_flight", run_id=run_id, remaining_runs=remaining_runs
        )
    # Update heartbeat to idle if no more runs in flight
    if remaining_runs == 0:
        update_heartbeat(status="idle", operation="run_complete", run_id=run_id)


def get_in_flight_runs() -> list[str]:
    """Get list of currently in-flight run IDs."""
    with _in_flight_lock:
        return list(_in_flight_runs)


def mark_shutdown_in_progress() -> None:
    """Mark that shutdown is in progress (prevents new runs from being registered)."""
    global _shutdown_in_progress
    with _in_flight_lock:
        _shutdown_in_progress = True


def is_shutdown_in_progress() -> bool:
    """Check if shutdown is in progress."""
    return _shutdown_in_progress


def _track_background_task(coro, task_name: str):
    """
    Create a background task with error logging.

    This wrapper ensures that if a background task fails, we log the error
    instead of silently swallowing it.
    """
    task = asyncio.create_task(coro)

    def _log_exception(future):
        try:
            future.result()
        except asyncio.CancelledError:
            pass  # Task was cancelled, this is expected
        except Exception as exc:
            logger.error(
                "background_task_failed",
                task_name=task_name,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )

    task.add_done_callback(_log_exception)
    return task


async def _record_agent_run_start(
    run_id: str,
    agent_name: str,
    correlation_id: str,
    trigger_source: str = "api",
    trigger_message: str = "",
    org_id: str = "",
    team_node_id: str = "",
) -> bool:
    """Record agent run start to config service."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{CONFIG_SERVICE_URL}/api/v1/internal/agent-runs",
                json={
                    "run_id": run_id,
                    "correlation_id": correlation_id,
                    "agent_name": agent_name,
                    "trigger_source": trigger_source,
                    "trigger_message": trigger_message[:500] if trigger_message else "",
                    "org_id": org_id or os.getenv("DEFAULT_ORG_ID", ""),
                    "team_node_id": team_node_id or os.getenv("DEFAULT_TEAM_ID", ""),
                },
                headers={"X-Internal-Service": "agent"},
            )
            if resp.status_code in (200, 201):
                logger.debug("agent_run_recorded", run_id=run_id)
                return True
            else:
                logger.warning(
                    "agent_run_record_failed",
                    status=resp.status_code,
                    body=resp.text[:200],
                )
    except Exception as e:
        logger.warning("agent_run_record_error", error=str(e))
    return False


async def _record_agent_run_complete(
    run_id: str,
    status: str,
    duration_seconds: float,
    output_summary: str = "",
    error_message: str = "",
    tool_calls_count: int = 0,
) -> bool:
    """Record agent run completion to config service."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.patch(
                f"{CONFIG_SERVICE_URL}/api/v1/internal/agent-runs/{run_id}",
                json={
                    "status": status,
                    "duration_seconds": round(duration_seconds, 3),
                    "output_summary": output_summary[:1000] if output_summary else "",
                    "error_message": error_message[:500] if error_message else "",
                    "tool_calls_count": tool_calls_count,
                },
                headers={"X-Internal-Service": "agent"},
            )
            if resp.status_code == 200:
                logger.debug(
                    "agent_run_completed_recorded", run_id=run_id, status=status
                )
                return True
            else:
                logger.warning("agent_run_complete_failed", status=resp.status_code)
    except Exception as e:
        logger.warning("agent_run_complete_error", error=str(e))
    return False


async def _record_agent_run_complete_sync(
    run_id: str,
    status: str,
    duration_seconds: float = 0,
    output_summary: str = "",
    error_message: str = "",
    tool_calls_count: int = 0,
) -> bool:
    """
    Record agent run completion SYNCHRONOUSLY with timeout.

    This is the reliable version that ensures completion is recorded before
    returning. It wraps _record_agent_run_complete with a timeout to prevent
    blocking indefinitely if config service is slow/down.

    If recording fails, the cleanup job will catch it later.
    """
    try:
        # Use a 5 second timeout - enough for normal operation,
        # but won't block too long if config service is having issues
        success = await asyncio.wait_for(
            _record_agent_run_complete(
                run_id=run_id,
                status=status,
                duration_seconds=duration_seconds,
                output_summary=output_summary,
                error_message=error_message,
                tool_calls_count=tool_calls_count,
            ),
            timeout=5.0,
        )
        if success:
            logger.info(
                "agent_run_completion_recorded_sync",
                run_id=run_id,
                status=status,
            )
        return success
    except builtins.TimeoutError:
        logger.warning(
            "agent_run_completion_recording_timeout",
            run_id=run_id,
            status=status,
            message="Config service slow, cleanup job will catch this",
        )
        return False
    except Exception as e:
        logger.warning(
            "agent_run_completion_recording_failed",
            run_id=run_id,
            status=status,
            error=str(e),
            message="Cleanup job will catch this",
        )
        return False


async def _record_detailed_tool_calls(
    run_id: str,
    run_result: Any,
) -> bool:
    """
    Extract and record detailed tool calls from run result.

    Supports various OpenAI Agents SDK result structures to extract:
    - Tool name
    - Input arguments
    - Output/result
    - Timing information
    """
    try:
        # Extract tool calls from run result
        # The SDK may expose this in different ways
        tool_calls_raw = getattr(run_result, "tool_calls", None) or []
        new_items = getattr(run_result, "new_items", None) or []

        # Combine sources
        all_calls = []

        # Process tool_calls attribute if available
        for i, tc in enumerate(tool_calls_raw):
            call_data = _extract_tool_call_data(tc, i, run_id)
            if call_data:
                all_calls.append(call_data)

        # Process new_items if they contain tool calls
        for i, item in enumerate(new_items):
            item_type = getattr(item, "type", None) or type(item).__name__
            if "tool" in str(item_type).lower() or "function" in str(item_type).lower():
                call_data = _extract_tool_call_data(item, len(all_calls), run_id)
                if call_data:
                    all_calls.append(call_data)

        if not all_calls:
            logger.debug("no_tool_calls_to_record", run_id=run_id)
            return True

        # Send to config service
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{CONFIG_SERVICE_URL}/api/v1/internal/agent-runs/{run_id}/tool-calls",
                json={
                    "run_id": run_id,
                    "tool_calls": all_calls,
                },
                headers={"X-Internal-Service": "agent"},
            )
            if resp.status_code in (200, 201):
                logger.debug(
                    "tool_calls_recorded",
                    run_id=run_id,
                    count=len(all_calls),
                )
                return True
            else:
                logger.warning(
                    "tool_calls_record_failed",
                    status=resp.status_code,
                    body=resp.text[:200],
                )
    except Exception as e:
        logger.warning("tool_calls_record_error", run_id=run_id, error=str(e))
    return False


def _extract_tool_call_data(tc: Any, sequence: int, run_id: str) -> dict | None:
    """
    Extract tool call data from various SDK structures.

    Handles multiple attribute patterns used by OpenAI Agents SDK.
    The SDK wraps tool calls in items with a `raw_item` attribute containing
    the actual tool call data (name, arguments, etc).
    """
    import uuid

    try:
        # The SDK wraps tool calls - check for raw_item first
        raw_item = getattr(tc, "raw_item", None)
        source = raw_item if raw_item else tc

        # Try different attribute patterns for tool name
        tool_name = (
            getattr(source, "name", None)
            or getattr(tc, "name", None)
            or getattr(tc, "tool_name", None)
            or getattr(getattr(tc, "function", None), "name", None)
            or "unknown"
        )

        # Try different patterns for input/arguments
        tool_input = None
        # Check raw_item first (SDK pattern)
        if raw_item and hasattr(raw_item, "arguments"):
            args = raw_item.arguments
            if isinstance(args, str):
                import json

                try:
                    tool_input = json.loads(args)
                except Exception:
                    tool_input = {"raw": args[:1000]}
            elif isinstance(args, dict):
                tool_input = args
        elif hasattr(tc, "arguments"):
            args = tc.arguments
            if isinstance(args, str):
                import json

                try:
                    tool_input = json.loads(args)
                except Exception:
                    tool_input = {"raw": args[:1000]}
            elif isinstance(args, dict):
                tool_input = args
        elif hasattr(tc, "tool_input"):
            tool_input = tc.tool_input
        elif hasattr(tc, "function") and hasattr(tc.function, "arguments"):
            args = tc.function.arguments
            if isinstance(args, str):
                import json

                try:
                    tool_input = json.loads(args)
                except Exception:
                    tool_input = {"raw": args[:1000]}
            elif isinstance(args, dict):
                tool_input = args

        # Try to get output/result
        tool_output = None
        if hasattr(tc, "output"):
            tool_output = str(tc.output)[:5000]
        elif hasattr(tc, "result"):
            tool_output = str(tc.result)[:5000]
        elif hasattr(tc, "content"):
            tool_output = str(tc.content)[:5000]

        # Status and error
        status = "success"
        error_message = None
        if hasattr(tc, "error"):
            error = tc.error
            if error:
                status = "error"
                error_message = str(error)[:1000]

        # Duration if available
        duration_ms = None
        if hasattr(tc, "duration_ms"):
            duration_ms = tc.duration_ms
        elif hasattr(tc, "duration"):
            duration_ms = int(tc.duration * 1000) if tc.duration else None

        return {
            "id": f"{run_id}_{sequence}_{uuid.uuid4().hex[:8]}",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
            "status": status,
            "error_message": error_message,
            "duration_ms": duration_ms,
            "sequence_number": sequence,
        }
    except Exception as e:
        logger.warning("tool_call_extract_error", error=str(e), sequence=sequence)
        return None


T = TypeVar("T")


@dataclass
class ExecutionContext:
    """Context for agent execution."""

    correlation_id: str = field(default_factory=lambda: get_correlation_id())
    metadata: dict[str, Any] = field(default_factory=dict)
    timeout: int | None = None
    max_turns: int | None = None


@dataclass
class AgentResult(Generic[T]):
    """Result from agent execution."""

    success: bool
    output: T | None
    error: str | None
    duration_seconds: float
    token_usage: dict | None
    correlation_id: str
    metadata: dict[str, Any]


class AgentRegistry:
    """Registry for managing agent factories and cached agents."""

    def __init__(self):
        self._factories: dict[str, Callable[..., Agent]] = {}
        self._default_agents: dict[str, Agent] = {}
        # Cache agents by (agent_name + team_config hash). Keep bounded to avoid unbounded growth.
        self._team_agents: OrderedDict[str, Agent] = OrderedDict()
        self._team_agent_cache_max = 128

    def register_factory(
        self, name: str, factory: Callable[..., Agent], max_retries: int = 3
    ) -> None:
        """Register an agent factory.

        Note: max_retries parameter is kept for backwards compatibility but is no longer used.
        Retry logic is now handled by _run_agent_with_retry() in api_server.py.
        """
        self._factories[name] = factory
        # Warm a default agent (no team overrides) for health/readiness.
        try:
            agent = factory(None)  # type: ignore[arg-type]
        except TypeError:
            agent = factory()
        self._default_agents[name] = agent
        logger.info("agent_factory_registered", agent_name=name)

    def get_agent(
        self,
        name: str,
        *,
        team_config_hash: str | None = None,
        factory_kwargs: dict | None = None,
    ) -> Agent | None:
        """
        Get an agent by name.

        - If no team_config_hash is provided, returns the default cached agent.
        - If team_config_hash is provided, returns a cached agent for that team, creating it if needed.
        """
        if name not in self._factories:
            return None

        if not team_config_hash:
            return self._default_agents.get(name)

        cache_key = f"{name}:{team_config_hash}"
        existing = self._team_agents.get(cache_key)
        if existing:
            self._team_agents.move_to_end(cache_key)
            return existing

        factory = self._factories[name]
        kwargs = factory_kwargs or {}
        agent = factory(**kwargs)

        self._team_agents[cache_key] = agent
        self._team_agents.move_to_end(cache_key)
        while len(self._team_agents) > self._team_agent_cache_max:
            self._team_agents.popitem(last=False)

        return agent

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._factories.keys())


# Global registry
_agent_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry."""
    return _agent_registry
