"""
Agent execution framework with retry logic, timeouts, and error handling.

This module provides the core agent execution infrastructure.
"""

import asyncio
import builtins
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

# Tracing disabled - using OpenAI's native tracing UI
import httpx
from agents import Agent, Runner, RunResult
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import get_config
from .errors import TimeoutError
from .logging import get_correlation_id, get_logger, set_correlation_id
from .metrics import get_metrics_collector
from .trace_recorder import (
    TraceRecorderHooks,
    record_trace,
)

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
        logger.debug("run_unregistered_in_flight", run_id=run_id)


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


class AgentRunner(Generic[T]):
    """
    Production-ready agent runner with retry logic and error handling.

    Features:
    - Automatic retries with exponential backoff
    - Timeout handling
    - Metrics collection
    - Structured logging
    - Error recovery
    """

    def __init__(
        self,
        agent: Agent[T],
        max_retries: int = 3,
        timeout: int | None = None,
    ):
        """
        Initialize agent runner.

        Args:
            agent: The OpenAI agent to run
            max_retries: Maximum number of retry attempts
            timeout: Execution timeout in seconds
        """
        self.agent = agent
        self.max_retries = max_retries
        self.timeout = timeout or get_config().agent_timeout
        self.runner = Runner()  # Runner doesn't take arguments
        self.metrics = get_metrics_collector()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    async def run(
        self,
        context: T,
        user_message: str,
        execution_context: ExecutionContext | None = None,
    ) -> AgentResult[Any]:
        """
        Run the agent with proper error handling and metrics.

        Args:
            context: Agent context
            user_message: User message or task
            execution_context: Optional execution context

        Returns:
            AgentResult with execution details
        """
        exec_ctx = execution_context or ExecutionContext()
        set_correlation_id(exec_ctx.correlation_id)

        agent_name = self.agent.name or "unknown"
        start_time = datetime.utcnow()

        # Generate unique run ID for tracking
        import uuid

        run_id = exec_ctx.metadata.get("run_id") or str(uuid.uuid4())[:8]
        trigger_source = exec_ctx.metadata.get("trigger_source", "api")
        trigger_message = user_message[:500] if user_message else ""

        logger.info(
            "agent_execution_started",
            agent_name=agent_name,
            message_preview=user_message[:100],
            correlation_id=exec_ctx.correlation_id,
            run_id=run_id,
        )

        # Register run as in-flight for graceful shutdown tracking
        register_in_flight_run(run_id)

        # Record run start (fire and forget - OK if this fails, run just won't be tracked)
        _track_background_task(
            _record_agent_run_start(
                run_id=run_id,
                agent_name=agent_name,
                correlation_id=exec_ctx.correlation_id,
                trigger_source=trigger_source,
                trigger_message=trigger_message,
                org_id=exec_ctx.metadata.get("org_id", ""),
                team_node_id=exec_ctx.metadata.get("team_node_id", ""),
            ),
            task_name="record_agent_run_start",
        )

        # Create trace recorder hooks to capture tool calls
        trace_hooks = TraceRecorderHooks(
            run_id=run_id,
            agent_name=agent_name,
        )

        try:
            # Execute with timeout
            run_result = await asyncio.wait_for(
                # OpenAI Agents SDK Runner expects (agent, input, context=...).
                # Use positional args for maximum compatibility across Runner versions.
                self.runner.run(
                    self.agent,
                    user_message,
                    context=context,
                    max_turns=(exec_ctx.max_turns or 200),
                    hooks=trace_hooks,
                ),
                timeout=exec_ctx.timeout or self.timeout,
            )

            duration = (datetime.utcnow() - start_time).total_seconds()

            # Extract token usage if available
            token_usage = self._extract_token_usage(run_result)

            # Record metrics
            self.metrics.record_agent_request(
                agent_name=agent_name,
                duration=duration,
                status="success",
                token_usage=token_usage,
            )

            logger.info(
                "agent_execution_completed",
                agent_name=agent_name,
                duration_seconds=round(duration, 3),
                runner_status=getattr(run_result, "status", None),
                correlation_id=exec_ctx.correlation_id,
            )

            output = getattr(run_result, "output", None)
            if output is None:
                output = getattr(run_result, "final_output", None)

            # Get trace data for tool calls count
            trace_data = trace_hooks.get_trace_data()

            # Record run completion SYNCHRONOUSLY to ensure it's recorded
            # before returning (prevents orphaned "running" status)
            await _record_agent_run_complete_sync(
                run_id=run_id,
                status="completed",
                duration_seconds=duration,
                output_summary=str(output)[:1000] if output else "",
                tool_calls_count=len(trace_data.tool_calls),
            )

            # Record detailed tool calls (can be async - not critical for status)
            _track_background_task(
                record_trace(run_id, trace_data),
                task_name="record_trace",
            )

            # Unregister from in-flight tracking
            unregister_in_flight_run(run_id)

            return AgentResult(
                success=True,
                output=output,
                error=None,
                duration_seconds=duration,
                token_usage=token_usage,
                correlation_id=exec_ctx.correlation_id,
                metadata=exec_ctx.metadata,
            )

        except builtins.TimeoutError:
            duration = (datetime.utcnow() - start_time).total_seconds()

            self.metrics.record_agent_request(
                agent_name=agent_name,
                duration=duration,
                status="timeout",
            )
            self.metrics.record_error("TimeoutError", agent_name)

            error_msg = f"Agent execution timed out after {self.timeout}s"
            logger.error(
                "agent_execution_timeout",
                agent_name=agent_name,
                timeout_seconds=self.timeout,
                duration_seconds=round(duration, 3),
                correlation_id=exec_ctx.correlation_id,
                run_id=run_id,
            )

            # Record timeout SYNCHRONOUSLY
            await _record_agent_run_complete_sync(
                run_id=run_id,
                status="timeout",
                duration_seconds=duration,
                error_message=error_msg,
            )

            # Unregister from in-flight tracking
            unregister_in_flight_run(run_id)

            return AgentResult(
                success=False,
                output=None,
                error=error_msg,
                duration_seconds=duration,
                token_usage=None,
                correlation_id=exec_ctx.correlation_id,
                metadata=exec_ctx.metadata,
            )

        except RetryError as e:
            duration = (datetime.utcnow() - start_time).total_seconds()

            self.metrics.record_agent_request(
                agent_name=agent_name,
                duration=duration,
                status="retry_exhausted",
            )
            self.metrics.record_error("RetryError", agent_name)

            error_msg = (
                f"Agent execution failed after {self.max_retries} retries: {str(e)}"
            )
            logger.error(
                "agent_execution_retry_exhausted",
                agent_name=agent_name,
                error=str(e),
                duration_seconds=round(duration, 3),
                correlation_id=exec_ctx.correlation_id,
                run_id=run_id,
                exc_info=True,
            )

            # Record failure SYNCHRONOUSLY
            await _record_agent_run_complete_sync(
                run_id=run_id,
                status="failed",
                duration_seconds=duration,
                error_message=error_msg[:500],
            )

            # Unregister from in-flight tracking
            unregister_in_flight_run(run_id)

            return AgentResult(
                success=False,
                output=None,
                error=error_msg,
                duration_seconds=duration,
                token_usage=None,
                correlation_id=exec_ctx.correlation_id,
                metadata=exec_ctx.metadata,
            )

        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()

            self.metrics.record_agent_request(
                agent_name=agent_name,
                duration=duration,
                status="error",
            )
            self.metrics.record_error(type(e).__name__, agent_name)

            error_msg = str(e)
            logger.error(
                "agent_execution_failed",
                agent_name=agent_name,
                error=error_msg,
                error_type=type(e).__name__,
                duration_seconds=round(duration, 3),
                correlation_id=exec_ctx.correlation_id,
                run_id=run_id,
                exc_info=True,
            )

            # Record failure SYNCHRONOUSLY
            await _record_agent_run_complete_sync(
                run_id=run_id,
                status="failed",
                duration_seconds=duration,
                error_message=error_msg[:500],
            )

            # Unregister from in-flight tracking
            unregister_in_flight_run(run_id)

            return AgentResult(
                success=False,
                output=None,
                error=error_msg,
                duration_seconds=duration,
                token_usage=None,
                correlation_id=exec_ctx.correlation_id,
                metadata=exec_ctx.metadata,
            )

    def _extract_token_usage(self, run_result: RunResult) -> dict | None:
        """Extract token usage from run result."""
        # This depends on the OpenAI Agents SDK implementation
        # Adapt based on actual response structure
        if hasattr(run_result, "usage"):
            return {
                "model": getattr(run_result, "model", "unknown"),
                "prompt_tokens": getattr(run_result.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(run_result.usage, "completion_tokens", 0),
                "total_tokens": getattr(run_result.usage, "total_tokens", 0),
            }
        return None


class AgentRegistry:
    """Registry for managing agent factories and per-team runners."""

    def __init__(self):
        self._factories: dict[str, tuple[Callable[..., Agent], int]] = {}
        self._default_runners: dict[str, AgentRunner] = {}
        # Cache runners by (agent_name + team_config hash). Keep bounded to avoid unbounded growth.
        self._team_runners: OrderedDict[str, AgentRunner] = OrderedDict()
        self._team_runner_cache_max = 128

    def register_factory(
        self, name: str, factory: Callable[..., Agent], max_retries: int = 3
    ) -> None:
        """Register an agent factory."""
        self._factories[name] = (factory, max_retries)
        # Warm a default runner (no team overrides) for health/readiness.
        try:
            agent = factory(None)  # type: ignore[arg-type]
        except TypeError:
            agent = factory()
        self._default_runners[name] = AgentRunner(agent, max_retries=max_retries)
        logger.info("agent_factory_registered", agent_name=name)

    def get_agent(self, name: str) -> Agent | None:
        """Get an agent by name."""
        runner = self._default_runners.get(name)
        return runner.agent if runner else None

    def get_runner(
        self,
        name: str,
        *,
        team_config_hash: str | None = None,
        factory_kwargs: dict | None = None,
    ) -> AgentRunner | None:
        """
        Get an agent runner.

        - If no team_config_hash is provided, returns the default runner.
        - If team_config_hash is provided, returns a cached runner for that team, creating it if needed.
        """
        if name not in self._factories:
            return None

        if not team_config_hash:
            return self._default_runners.get(name)

        cache_key = f"{name}:{team_config_hash}"
        existing = self._team_runners.get(cache_key)
        if existing:
            self._team_runners.move_to_end(cache_key)
            return existing

        factory, max_retries = self._factories[name]
        kwargs = factory_kwargs or {}
        agent = factory(**kwargs)
        runner = AgentRunner(agent, max_retries=max_retries)

        self._team_runners[cache_key] = runner
        self._team_runners.move_to_end(cache_key)
        while len(self._team_runners) > self._team_runner_cache_max:
            self._team_runners.popitem(last=False)

        return runner

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._factories.keys())


# Global registry
_agent_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry."""
    return _agent_registry
