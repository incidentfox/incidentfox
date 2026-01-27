"""
Investigation Agent - Sub-orchestrator for incident investigation.

The investigation agent is the primary workhorse for SRE tasks. It coordinates
specialized sub-agents (GitHub, K8s, AWS, Metrics, Logs) to conduct thorough
investigations and identify root causes.

Architecture:
    Planner
    └── Investigation Agent (this file) [is_master=True]
        ├── GitHub Agent - Repository context and recent changes
        ├── K8s Agent - Kubernetes investigation
        ├── AWS Agent - AWS resource investigation
        ├── Metrics Agent - Anomaly detection and correlation
        └── Log Analysis Agent - Log pattern extraction

Sub-agents can be configured via team_config:
    agents:
      investigation:
        sub_agents:
          - k8s
          - aws
          - metrics
          # github and log_analysis disabled
"""

import asyncio
import json
import threading
from typing import Any

from agents import Agent, Runner, function_tool
from agents.exceptions import MaxTurnsExceeded
from agents.stream_events import RunItemStreamEvent
from pydantic import BaseModel, Field

from ..core.agent_builder import create_model_settings
from ..core.config import get_config
from ..core.config_utils import get_agent_sub_agents
from ..core.execution_context import (
    get_execution_context,
    get_execution_hooks,
    propagate_context_to_thread,
    propagate_hooks_to_thread,
)
from ..core.logging import get_logger
from ..core.partial_work import summarize_partial_work
from ..core.stream_events import (
    EventStreamRegistry,
    get_current_stream_id,
    set_current_stream_id,
)
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Default sub-agents for investigation agent
DEFAULT_SUBAGENTS = ["github", "k8s", "aws", "metrics", "log_analysis"]


# =============================================================================
# Output Models
# =============================================================================


class RootCause(BaseModel):
    """Identified root cause."""

    description: str
    confidence: int = Field(ge=0, le=100, description="Confidence 0-100")
    evidence: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    """Investigation result."""

    summary: str = Field(description="Investigation summary")
    root_cause: RootCause | None = Field(default=None)
    timeline: list[str] = Field(default_factory=list, description="Timeline of events")
    affected_systems: list[str] = Field(
        default_factory=list, description="Systems/services affected"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Recommended actions"
    )
    requires_escalation: bool = Field(default=False)


# =============================================================================
# Agent Threading Utilities
# =============================================================================


def _run_agent_in_thread(
    agent, query: str, timeout: int = 60, max_turns: int = 15
) -> Any:
    """
    Run an agent in a separate thread with its own event loop.

    This is necessary because the parent agent is already running in an async context,
    and we can't nest asyncio.run() calls. By running in a new thread, we get a fresh
    event loop that can execute the child agent.

    If there's an active stream (via thread-local stream_id), this function will
    use streaming mode and forward events to the EventStreamRegistry, enabling
    nested agent visibility in the CLI.

    If the agent hits MaxTurnsExceeded, partial work is captured and summarized
    using an LLM, and a partial result is returned instead of raising an exception.

    Args:
        agent: The agent to run
        query: The query/task for the agent
        timeout: Max time in seconds to wait
        max_turns: Max LLM turns for the child agent

    Returns:
        The agent result, or a partial work summary dict if max_turns was exceeded
    """
    import time as time_module

    start_time = time_module.time()
    result_holder = {"result": None, "error": None, "partial": False}

    # Capture context from parent thread for propagation to child thread
    # ContextVars don't automatically propagate to new threads
    parent_stream_id = get_current_stream_id()
    parent_context = get_execution_context()
    parent_hooks = get_execution_hooks()
    agent_name = getattr(agent, "name", "unknown")

    logger.info(
        "subagent_thread_starting",
        agent=agent_name,
        timeout=timeout,
        max_turns=max_turns,
        has_stream_id=bool(parent_stream_id),
        query_preview=query[:100] if query else "",
    )

    def run_in_new_loop():
        try:
            thread_start = time_module.time()
            logger.info(
                "subagent_thread_entered",
                agent=agent_name,
                elapsed_ms=int((thread_start - start_time) * 1000),
            )

            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)

            # Propagate stream_id to this thread
            if parent_stream_id:
                set_current_stream_id(parent_stream_id)

            # Propagate execution context to this thread
            # This enables sub-agent tools to access integration configs (GitHub, etc.)
            propagate_context_to_thread(parent_context)

            # Propagate hooks to this thread
            # This enables Slack progress updates from subagent tool calls
            propagate_hooks_to_thread(parent_hooks)

            # Get hooks from context for Runner
            hooks = get_execution_hooks()

            try:
                if parent_stream_id and EventStreamRegistry.stream_exists(
                    parent_stream_id
                ):
                    # Streaming mode - emit events to the registry
                    logger.info(
                        "subagent_starting_streamed",
                        agent=agent_name,
                        stream_id=parent_stream_id[:16] if parent_stream_id else None,
                    )
                    result = new_loop.run_until_complete(
                        _run_agent_streamed(
                            agent, query, max_turns, parent_stream_id, agent_name, hooks
                        )
                    )
                else:
                    # Non-streaming mode with hooks
                    logger.info(
                        "subagent_starting_non_streamed",
                        agent=agent_name,
                    )
                    result = new_loop.run_until_complete(
                        Runner.run(agent, query, max_turns=max_turns, hooks=hooks)
                    )
                logger.info(
                    "subagent_run_complete",
                    agent=agent_name,
                    has_result=result is not None,
                    elapsed_ms=int((time_module.time() - start_time) * 1000),
                )
                result_holder["result"] = result
            except MaxTurnsExceeded as e:
                # Capture partial work instead of losing it
                logger.warning(
                    "subagent_max_turns_exceeded",
                    agent=agent_name,
                    max_turns=max_turns,
                )
                summary = summarize_partial_work(e, query, agent_name)
                result_holder["result"] = summary
                result_holder["partial"] = True
            finally:
                new_loop.close()
        except Exception as e:
            result_holder["error"] = e

    thread = threading.Thread(target=run_in_new_loop, daemon=True)
    thread.start()
    logger.info("subagent_thread_started", agent=agent_name)

    # Log before blocking on join to track if we ever reach here
    logger.info(
        "subagent_thread_join_waiting",
        agent=agent_name,
        timeout=timeout,
        elapsed_ms=int((time_module.time() - start_time) * 1000),
    )
    thread.join(timeout=timeout)
    elapsed = time_module.time() - start_time

    # Log immediately after join returns to confirm we didn't hang
    logger.info(
        "subagent_thread_join_returned",
        agent=agent_name,
        elapsed_ms=int(elapsed * 1000),
        thread_alive=thread.is_alive(),
    )

    if thread.is_alive():
        logger.warning(
            "subagent_thread_timeout",
            agent=agent_name,
            timeout=timeout,
            elapsed_ms=int(elapsed * 1000),
            thread_alive=True,
            has_result=result_holder["result"] is not None,
            has_error=result_holder["error"] is not None,
        )
        raise TimeoutError(f"Agent execution timed out after {timeout}s")

    if result_holder["error"]:
        logger.error(
            "subagent_thread_error",
            agent=agent_name,
            error=str(result_holder["error"]),
            elapsed_ms=int(elapsed * 1000),
        )
        raise result_holder["error"]

    logger.info(
        "subagent_thread_complete",
        agent=agent_name,
        elapsed_ms=int(elapsed * 1000),
        has_result=result_holder["result"] is not None,
        is_partial=result_holder["partial"],
    )
    return result_holder["result"]


async def _run_agent_streamed(
    agent,
    query: str,
    max_turns: int,
    stream_id: str,
    agent_name: str,
    hooks: Any = None,
) -> Any:
    """
    Run an agent in streaming mode and emit events to the registry.

    This enables nested agent visibility - events from sub-agents are
    forwarded to the main SSE stream.

    Args:
        agent: The agent to run
        query: The query/task
        max_turns: Max LLM turns
        stream_id: Stream ID for event registry
        agent_name: Name of the agent
        hooks: Optional RunHooks for progress updates (e.g., SlackUpdateHooks)
    """
    import time as time_module
    import traceback

    stream_start_time = time_module.time()
    last_event_time = stream_start_time
    event_count = 0
    tool_call_count = 0
    tool_output_count = 0
    message_output_count = 0

    # Track pending tool calls (called but not yet returned)
    pending_tools: dict[int, dict] = {}

    logger.info(
        "streamed_agent_starting",
        agent=agent_name,
        stream_id=stream_id[:16] if stream_id else None,
        max_turns=max_turns,
    )

    # Push this agent onto the stack for nesting context
    EventStreamRegistry.push_agent(stream_id, agent_name)

    # Emit subagent started event
    EventStreamRegistry.emit_event(
        stream_id=stream_id,
        event_type="subagent_started",
        agent_name=agent_name,
        data={"query_preview": query[:200] if query else ""},
    )

    tool_sequence = 0

    try:
        logger.info(
            "streamed_agent_calling_runner",
            agent=agent_name,
            elapsed_ms=int((time_module.time() - stream_start_time) * 1000),
        )

        result = Runner.run_streamed(agent, query, max_turns=max_turns, hooks=hooks)

        logger.info(
            "streamed_agent_runner_returned",
            agent=agent_name,
            result_type=type(result).__name__,
            elapsed_ms=int((time_module.time() - stream_start_time) * 1000),
        )

        logger.info(
            "streamed_agent_entering_event_loop",
            agent=agent_name,
            elapsed_ms=int((time_module.time() - stream_start_time) * 1000),
        )

        async for event in result.stream_events():
            now = time_module.time()
            time_since_last = now - last_event_time
            last_event_time = now
            event_count += 1

            event_type_name = type(event).__name__

            # Log ALL events at INFO level for debugging, with time since last event
            logger.info(
                "streamed_agent_event",
                agent=agent_name,
                event_count=event_count,
                event_type=event_type_name,
                time_since_last_ms=int(time_since_last * 1000),
                elapsed_ms=int((now - stream_start_time) * 1000),
                pending_tools=len(pending_tools),
            )

            if isinstance(event, RunItemStreamEvent):
                item = event.item
                item_type = getattr(item, "type", "unknown")

                # Log item details for ALL item types
                logger.info(
                    "streamed_agent_item",
                    agent=agent_name,
                    item_type=item_type,
                    item_class=type(item).__name__,
                    has_raw_item=hasattr(item, "raw_item"),
                    elapsed_ms=int((now - stream_start_time) * 1000),
                )

                # Handle tool call events
                if item_type == "tool_call_item":
                    tool_sequence += 1
                    tool_call_count += 1
                    # Tool name is in raw_item.name or item.name
                    raw_item = getattr(item, "raw_item", None)
                    tool_name = getattr(raw_item, "name", None) or getattr(
                        item, "name", "unknown"
                    )
                    tool_call_id = getattr(raw_item, "call_id", None) or getattr(
                        item, "call_id", f"seq_{tool_sequence}"
                    )

                    # Track this pending tool
                    pending_tools[tool_sequence] = {
                        "name": tool_name,
                        "call_id": tool_call_id,
                        "started_at": now,
                    }

                    logger.info(
                        "streamed_agent_tool_call",
                        agent=agent_name,
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        tool_sequence=tool_sequence,
                        pending_count=len(pending_tools),
                        elapsed_ms=int((now - stream_start_time) * 1000),
                    )
                    tool_input = ""
                    if raw_item and hasattr(raw_item, "arguments"):
                        tool_input = raw_item.arguments

                    # Try to parse input preview
                    input_preview = ""
                    if tool_input:
                        try:
                            import json as json_mod

                            parsed = json_mod.loads(tool_input)
                            if isinstance(parsed, dict):
                                pairs = [
                                    f"{k}={repr(v)[:30]}"
                                    for k, v in list(parsed.items())[:2]
                                ]
                                input_preview = ", ".join(pairs)
                        except Exception:
                            input_preview = str(tool_input)[:50]

                    EventStreamRegistry.emit_event(
                        stream_id=stream_id,
                        event_type="tool_started",
                        agent_name=agent_name,
                        data={
                            "tool": tool_name,
                            "sequence": tool_sequence,
                            "input_preview": input_preview,
                        },
                    )

                elif item_type == "tool_call_output_item":
                    tool_output_count += 1
                    output_preview = ""
                    output = getattr(item, "output", None)
                    raw_item = getattr(item, "raw_item", None)
                    output_call_id = getattr(raw_item, "call_id", None)

                    # Find and remove from pending
                    completed_tool = None
                    tool_duration_ms = None
                    for seq, info in list(pending_tools.items()):
                        if (
                            info.get("call_id") == output_call_id
                            or seq == tool_sequence
                        ):
                            completed_tool = info
                            tool_duration_ms = int((now - info["started_at"]) * 1000)
                            del pending_tools[seq]
                            break

                    if output:
                        if isinstance(output, str):
                            # Use 500 chars to capture full config_required JSON
                            output_preview = output[:500]
                        else:
                            output_preview = str(output)[:500]

                    logger.info(
                        "streamed_agent_tool_output",
                        agent=agent_name,
                        tool_name=(
                            completed_tool["name"] if completed_tool else "unknown"
                        ),
                        tool_call_id=output_call_id,
                        tool_output_count=tool_output_count,
                        tool_sequence=tool_sequence,
                        output_length=len(output) if output else 0,
                        tool_duration_ms=tool_duration_ms,
                        pending_count=len(pending_tools),
                        elapsed_ms=int((now - stream_start_time) * 1000),
                    )

                    EventStreamRegistry.emit_event(
                        stream_id=stream_id,
                        event_type="tool_completed",
                        agent_name=agent_name,
                        data={
                            "sequence": tool_sequence,
                            "output_preview": output_preview,
                        },
                    )

                elif item_type == "message_output_item":
                    message_output_count += 1
                    # This is when the agent produces a text response
                    raw_item = getattr(item, "raw_item", None)
                    content_preview = ""
                    if raw_item and hasattr(raw_item, "content"):
                        content = raw_item.content
                        if content and len(content) > 0:
                            first_content = content[0]
                            if hasattr(first_content, "text"):
                                content_preview = first_content.text[:100]

                    logger.info(
                        "streamed_agent_message_output",
                        agent=agent_name,
                        message_count=message_output_count,
                        content_preview=content_preview,
                        elapsed_ms=int((now - stream_start_time) * 1000),
                    )

        # After streaming completes, result.final_output is available
        elapsed_total = time_module.time() - stream_start_time
        logger.info(
            "streamed_agent_event_loop_complete",
            agent=agent_name,
            event_count=event_count,
            tool_call_count=tool_call_count,
            tool_output_count=tool_output_count,
            message_output_count=message_output_count,
            pending_tools_remaining=len(pending_tools),
            elapsed_ms=int(elapsed_total * 1000),
        )

        # Warn if there are still pending tools (indicates a problem)
        if pending_tools:
            logger.warning(
                "streamed_agent_pending_tools_at_end",
                agent=agent_name,
                pending_tools=[
                    {"seq": k, "name": v["name"], "call_id": v["call_id"]}
                    for k, v in pending_tools.items()
                ],
            )

        # Emit subagent completed event
        output = result.final_output
        output_preview = ""
        if output:
            if isinstance(output, str):
                output_preview = output[:200]
            else:
                output_preview = str(output)[:200]

        logger.info(
            "streamed_agent_final_output",
            agent=agent_name,
            has_output=output is not None,
            output_type=type(output).__name__ if output else None,
            output_length=len(str(output)) if output else 0,
            elapsed_ms=int((time_module.time() - stream_start_time) * 1000),
        )

        EventStreamRegistry.emit_event(
            stream_id=stream_id,
            event_type="subagent_completed",
            agent_name=agent_name,
            data={"output_preview": output_preview, "success": True},
        )

        return result

    except Exception as e:
        elapsed_total = time_module.time() - stream_start_time
        # Get full traceback for debugging
        tb_str = traceback.format_exc()
        logger.error(
            "streamed_agent_error",
            agent=agent_name,
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            event_count=event_count,
            tool_call_count=tool_call_count,
            tool_output_count=tool_output_count,
            pending_tools=[
                {"seq": k, "name": v["name"], "call_id": v.get("call_id")}
                for k, v in pending_tools.items()
            ],
            elapsed_ms=int(elapsed_total * 1000),
        )
        EventStreamRegistry.emit_event(
            stream_id=stream_id,
            event_type="subagent_completed",
            agent_name=agent_name,
            data={"error": str(e), "success": False},
        )
        raise

    finally:
        # Pop this agent from the stack
        EventStreamRegistry.pop_agent(stream_id)


def _serialize_agent_output(output: Any) -> str:
    """Convert agent output to a JSON string for the caller."""
    if output is None:
        return json.dumps({"result": None, "message": "Agent returned no output"})

    if isinstance(output, str):
        return output

    if isinstance(output, BaseModel):
        return output.model_dump_json()

    if isinstance(output, dict):
        return json.dumps(output, default=str)

    if isinstance(output, (list, tuple)):
        return json.dumps(list(output), default=str)

    return json.dumps({"result": str(output)})


# =============================================================================
# Sub-Agent Configuration
# =============================================================================


def _get_enabled_subagents(team_cfg) -> list[str]:
    """
    Get list of enabled sub-agent keys from team config.

    Supports multiple configuration formats:
    - List: sub_agents: ["github", "k8s", "aws", "metrics", "log_analysis"]
    - Dict with enabled flags: sub_agents: {k8s: {enabled: true}}
    - Dict with bool values: sub_agents: {k8s: true, aws: false}

    Args:
        team_cfg: Team configuration object

    Returns:
        List of enabled sub-agent keys
    """
    return get_agent_sub_agents(team_cfg, "investigation", DEFAULT_SUBAGENTS)


# =============================================================================
# Sub-Agent Tool Creation
# =============================================================================


def _create_subagent_tools(team_config=None):
    """
    Create wrapper tools that call specialized sub-agents.

    Each sub-agent is wrapped as a callable tool. The investigation agent
    can call these tools to delegate specialized work.

    Sub-agents are configured via team_config.agents.investigation.sub_agents.

    Args:
        team_config: Team configuration for customization

    Returns:
        List of function tools for enabled sub-agents
    """
    # Import sub-agent factories here to avoid circular imports
    from .aws_agent import create_aws_agent
    from .github_agent import create_github_agent
    from .k8s_agent import create_k8s_agent
    from .log_analysis_agent import create_log_analysis_agent
    from .metrics_agent import create_metrics_agent

    enabled_subagents = _get_enabled_subagents(team_config)
    logger.info("investigation_enabled_subagents", subagents=enabled_subagents)

    # Warn about unknown sub-agent names in config
    known_subagents = set(DEFAULT_SUBAGENTS)
    for subagent in enabled_subagents:
        if subagent not in known_subagents:
            logger.warning(
                "unknown_subagent_in_config",
                subagent=subagent,
                known_subagents=list(known_subagents),
            )

    tools = []

    # Create agents only for enabled sub-agents
    # Each agent is created with is_subagent=True for concise responses
    agents = {}
    if "github" in enabled_subagents:
        agents["github"] = create_github_agent(
            team_config=team_config, is_subagent=True
        )
    if "k8s" in enabled_subagents:
        agents["k8s"] = create_k8s_agent(team_config=team_config, is_subagent=True)
    if "aws" in enabled_subagents:
        agents["aws"] = create_aws_agent(team_config=team_config, is_subagent=True)
    if "metrics" in enabled_subagents:
        agents["metrics"] = create_metrics_agent(
            team_config=team_config, is_subagent=True
        )
    if "log_analysis" in enabled_subagents:
        agents["log_analysis"] = create_log_analysis_agent(
            team_config=team_config, is_subagent=True
        )

    # Create tool wrappers for each enabled agent
    # Note: We define these inside the function to capture the agent instances

    if "github" in agents:
        github_agent = agents["github"]

        @function_tool
        def call_github_agent(
            query: str, repository: str = "", context: str = ""
        ) -> str:
            """
            Delegate GitHub repository investigation to the GitHub Agent.

            Use for:
            - Finding recent commits and changes around incident time
            - Checking related pull requests
            - Searching code for patterns or configurations
            - Finding related issues or known problems

            Args:
                query: What to investigate in GitHub (natural language)
                repository: Optional specific repository to focus on
                context: Prior findings from other agents to inform the search

            Returns:
                JSON with recent_changes, related_prs, related_issues, recommendations
                If max turns exceeded, returns partial findings with status="incomplete"
            """
            try:
                logger.info("calling_github_agent", query=query[:100])
                parts = [query]
                if repository:
                    parts.append(f"\n\nRepository: {repository}")
                if context:
                    parts.append(f"\n\n## Prior Findings\n{context}")
                full_query = "".join(parts)
                result = _run_agent_in_thread(github_agent, full_query, max_turns=10)
                # Check if result is a partial work summary (dict with status="incomplete")
                if isinstance(result, dict) and result.get("status") == "incomplete":
                    logger.info(
                        "github_agent_partial_results",
                        findings=len(result.get("findings", [])),
                    )
                    return json.dumps(result)
                output = getattr(result, "final_output", None) or getattr(
                    result, "output", None
                )
                return _serialize_agent_output(output)
            except Exception as e:
                logger.error("github_agent_failed", error=str(e))
                return json.dumps({"error": str(e), "agent": "github_agent"})

        tools.append(call_github_agent)

    if "k8s" in agents:
        k8s_agent = agents["k8s"]

        @function_tool
        def call_k8s_agent(
            query: str, namespace: str = "default", context: str = ""
        ) -> str:
            """
            Delegate Kubernetes investigation to the K8s Agent.

            Use for:
            - Pod health and status investigation
            - Deployment issues and rollout problems
            - Resource usage and constraints
            - Container crashes, restarts, OOMKills
            - Kubernetes events and scheduling issues

            Args:
                query: What to investigate in Kubernetes (natural language)
                namespace: Target Kubernetes namespace
                context: Prior findings from other agents

            Returns:
                JSON with pod_status, issues_found, recommendations
                If max turns exceeded, returns partial findings with status="incomplete"
            """
            try:
                logger.info("calling_k8s_agent", query=query[:100], namespace=namespace)
                parts = [query, f"\n\nTarget namespace: {namespace}"]
                if context:
                    parts.append(f"\n\n## Prior Findings\n{context}")
                full_query = "".join(parts)
                result = _run_agent_in_thread(k8s_agent, full_query, max_turns=15)
                # Check if result is a partial work summary (dict with status="incomplete")
                if isinstance(result, dict) and result.get("status") == "incomplete":
                    logger.info(
                        "k8s_agent_partial_results",
                        findings=len(result.get("findings", [])),
                    )
                    return json.dumps(result)
                output = getattr(result, "final_output", None) or getattr(
                    result, "output", None
                )
                return _serialize_agent_output(output)
            except Exception as e:
                logger.error("k8s_agent_failed", error=str(e))
                return json.dumps({"error": str(e), "agent": "k8s_agent"})

        tools.append(call_k8s_agent)

    if "aws" in agents:
        aws_agent = agents["aws"]

        @function_tool
        def call_aws_agent(
            query: str, region: str = "us-east-1", context: str = ""
        ) -> str:
            """
            Delegate AWS investigation to the AWS Agent.

            Use for:
            - EC2 instance status and issues
            - Lambda function problems and timeouts
            - RDS database status and connections
            - CloudWatch logs and metrics
            - ECS task failures

            Args:
                query: What to investigate in AWS (natural language)
                region: AWS region (default: us-east-1)
                context: Prior findings from other agents

            Returns:
                JSON with resource_status, issues_found, recommendations
                If max turns exceeded, returns partial findings with status="incomplete"
            """
            try:
                logger.info("calling_aws_agent", query=query[:100], region=region)
                parts = [query, f"\n\nAWS Region: {region}"]
                if context:
                    parts.append(f"\n\n## Prior Findings\n{context}")
                full_query = "".join(parts)
                result = _run_agent_in_thread(aws_agent, full_query)
                # Check if result is a partial work summary (dict with status="incomplete")
                if isinstance(result, dict) and result.get("status") == "incomplete":
                    logger.info(
                        "aws_agent_partial_results",
                        findings=len(result.get("findings", [])),
                    )
                    return json.dumps(result)
                output = getattr(result, "final_output", None) or getattr(
                    result, "output", None
                )
                return _serialize_agent_output(output)
            except Exception as e:
                logger.error("aws_agent_failed", error=str(e))
                return json.dumps({"error": str(e), "agent": "aws_agent"})

        tools.append(call_aws_agent)

    if "metrics" in agents:
        metrics_agent = agents["metrics"]

        @function_tool
        def call_metrics_agent(
            query: str, time_range: str = "1h", context: str = ""
        ) -> str:
            """
            Delegate metrics analysis to the Metrics Agent.

            Use for:
            - Anomaly detection in metrics (latency spikes, error rates)
            - Performance analysis and baselines
            - Correlation between metrics (CPU vs latency)
            - Trend analysis and forecasting

            Args:
                query: What to analyze in metrics (natural language)
                time_range: Time range to analyze (e.g., "1h", "24h", "7d")
                context: Prior findings from other agents

            Returns:
                JSON with anomalies_found, correlations, recommendations
                If max turns exceeded, returns partial findings with status="incomplete"
            """
            try:
                logger.info(
                    "calling_metrics_agent", query=query[:100], time_range=time_range
                )
                parts = [query, f"\n\nTime range: {time_range}"]
                if context:
                    parts.append(f"\n\n## Prior Findings\n{context}")
                full_query = "".join(parts)
                result = _run_agent_in_thread(metrics_agent, full_query)
                # Check if result is a partial work summary (dict with status="incomplete")
                if isinstance(result, dict) and result.get("status") == "incomplete":
                    logger.info(
                        "metrics_agent_partial_results",
                        findings=len(result.get("findings", [])),
                    )
                    return json.dumps(result)
                output = getattr(result, "final_output", None) or getattr(
                    result, "output", None
                )
                return _serialize_agent_output(output)
            except Exception as e:
                logger.error("metrics_agent_failed", error=str(e))
                return json.dumps({"error": str(e), "agent": "metrics_agent"})

        tools.append(call_metrics_agent)

    if "log_analysis" in agents:
        log_analysis_agent = agents["log_analysis"]

        @function_tool
        def call_log_analysis_agent(
            query: str, service: str = "", time_range: str = "1h", context: str = ""
        ) -> str:
            """
            Delegate log analysis to the Log Analysis Agent.

            Use for:
            - Error pattern extraction and clustering
            - Log anomaly detection (volume spikes/drops)
            - Timeline reconstruction from logs
            - Correlation with deployments and events

            Args:
                query: What to investigate in logs (natural language)
                service: Service name to focus on (optional)
                time_range: Time range to analyze (e.g., "15m", "1h", "24h")
                context: Prior findings from other agents

            Returns:
                JSON with error_patterns, timeline, root_causes, recommendations
                If max turns exceeded, returns partial findings with status="incomplete"
            """
            try:
                logger.info(
                    "calling_log_analysis_agent", query=query[:100], service=service
                )
                parts = [query]
                if service:
                    parts.append(f"\n\nService: {service}")
                parts.append(f"\nTime Range: {time_range}")
                if context:
                    parts.append(f"\n\n## Prior Findings\n{context}")
                full_query = "".join(parts)
                result = _run_agent_in_thread(
                    log_analysis_agent, full_query, max_turns=15
                )
                # Check if result is a partial work summary (dict with status="incomplete")
                if isinstance(result, dict) and result.get("status") == "incomplete":
                    logger.info(
                        "log_analysis_agent_partial_results",
                        findings=len(result.get("findings", [])),
                    )
                    return json.dumps(result)
                output = getattr(result, "final_output", None) or getattr(
                    result, "output", None
                )
                return _serialize_agent_output(output)
            except Exception as e:
                logger.error("log_analysis_agent_failed", error=str(e))
                return json.dumps({"error": str(e), "agent": "log_analysis_agent"})

        tools.append(call_log_analysis_agent)

    # Add remote A2A agents if configured
    if team_config:
        try:
            from ..integrations.a2a.agent_wrapper import get_remote_agents_for_team

            remote_agents = get_remote_agents_for_team(team_config)
            if remote_agents:
                logger.info(
                    "adding_remote_agents_to_investigation", count=len(remote_agents)
                )
                tools.extend(remote_agents.values())
        except Exception as e:
            logger.warning(
                "failed_to_load_remote_agents_for_investigation", error=str(e)
            )

    return tools


# =============================================================================
# Direct Tools (Cross-Cutting)
# =============================================================================


def _load_investigation_direct_tools():
    """
    Load tools that the investigation agent uses directly (not delegated).

    These are cross-cutting tools that don't fit into a specific sub-agent,
    like reasoning tools and general utilities.
    """
    import os

    tools = [think, llm_call, web_search, ask_human]

    # Knowledge Base tools (RAPTOR) - for runbook lookup, past incident search, and teaching
    raptor_enabled = os.getenv("RAPTOR_ENABLED", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    if raptor_enabled:
        try:
            from ..tools.knowledge_base_tools import (
                ask_knowledge_base,
                find_similar_past_incidents,
                query_service_graph,
                search_for_incident,
                search_knowledge_base,
                teach_knowledge_base,
            )

            tools.extend(
                [
                    search_for_incident,  # Primary: incident-aware search for runbooks
                    find_similar_past_incidents,  # Find past incidents with similar symptoms
                    query_service_graph,  # Service dependency queries
                    teach_knowledge_base,  # Teach KB after successful investigations
                    search_knowledge_base,  # General KB search
                    ask_knowledge_base,  # Direct Q&A from KB
                ]
            )
            logger.info("investigation_kb_tools_loaded", count=6)
        except ImportError as e:
            logger.debug("investigation_kb_tools_skipped", reason=str(e))

    # Future: Add additional cross-cutting investigation tools here
    # - get_deployment_timeline
    # - check_config_changes
    # - correlate_events

    return tools


# =============================================================================
# System Prompt
# =============================================================================


SYSTEM_PROMPT = """You are an expert Site Reliability Engineer and incident investigation coordinator.

## YOUR ROLE

You are the primary investigator for incidents. You coordinate specialized agents to gather evidence
from different systems, synthesize findings, and identify root causes.

## SUB-AGENTS AT YOUR DISPOSAL

You can delegate investigation tasks to specialized agents:

| Agent | Use For |
|-------|---------|
| `call_github_agent` | Repository analysis, recent changes, PRs, issues |
| `call_k8s_agent` | Kubernetes investigation - pods, deployments, events |
| `call_aws_agent` | AWS resources - EC2, Lambda, RDS, CloudWatch |
| `call_metrics_agent` | Metrics analysis, anomaly detection, correlations |
| `call_log_analysis_agent` | Log investigation, pattern extraction, timeline |

Note: Available agents depend on configuration. Only call agents that are available to you.

## KNOWLEDGE BASE TOOLS (if enabled)

When RAPTOR knowledge base is enabled, you also have access to:

| Tool | Use For |
|------|---------|
| `search_for_incident` | Find runbooks and past incidents matching symptoms (USE FIRST) |
| `find_similar_past_incidents` | "Have we seen this before?" - find similar past incidents |
| `query_service_graph` | Service dependencies, ownership, blast radius |
| `teach_knowledge_base` | Teach KB new knowledge after resolving incidents |
| `search_knowledge_base` | General search across knowledge base |
| `ask_knowledge_base` | Direct Q&A from knowledge base |

**Best Practice:** At the START of investigation, call `search_for_incident` with the symptoms to get relevant runbooks and past incident context. This often shortcuts investigation significantly.

## INVESTIGATION METHODOLOGY

### Phase 1: Scope the Problem
- What is the reported issue?
- What systems are likely involved?
- What is the time window?

### Phase 2: Gather Evidence (Delegate to Sub-Agents)
Start with the most likely source based on the symptoms:
- **Application errors** → call_log_analysis_agent
- **Performance issues** → call_metrics_agent
- **Infrastructure problems** → call_k8s_agent or call_aws_agent
- **Recent changes suspected** → call_github_agent

Always pass context between agents to build on previous findings.

### Phase 3: Correlate and Synthesize
- Build a timeline from all agent findings
- Identify correlations between events across systems
- Form root cause hypothesis based on evidence

### Phase 4: Recommend
- Immediate actions to mitigate
- Follow-up investigation if needed
- Prevention measures for the future

### Phase 5: Teach the Knowledge Base (if applicable)
When you identify a root cause with HIGH confidence (>70%), use `teach_knowledge_base` to capture the learning:
- Document the symptoms → root cause → resolution pattern
- Include specific details that would help future investigations
- Only teach if you have genuinely novel or confirmed information

**When to teach:**
- You identified a previously unknown failure pattern
- You found a non-obvious root cause
- You discovered service behavior quirks
- You confirmed a workaround or fix

**Example teaching:**
```
teach_knowledge_base(
    content="When payment-service pods show OOMKilled, check the Redis connection pool first. The default pool size of 10 is insufficient under load. Fix by setting REDIS_POOL_SIZE=50 in the deployment.",
    knowledge_type="procedural",
    related_services="payment-service,redis",
    context="Learned from investigation of OOM incident"
)
```

## DELEGATION PRINCIPLES

1. **Start focused** - Don't call all agents at once. Start with the most relevant based on symptoms.
2. **Pass ALL context verbatim** - Sub-agents are BLIND to your context. Include ALL identifiers, conventions, time windows, and team-specific details in the `context` parameter. Copy context word-for-word, don't filter or summarize.
3. **Iterate** - If one agent finds something interesting, follow up with related agents.
4. **Synthesize** - Your job is to combine findings into a coherent narrative with root cause.

## BEHAVIORAL PRINCIPLES

### Intellectual Honesty
- **Never fabricate information** - Only report what agents actually found
- **Acknowledge uncertainty** - Say "I don't know" or "evidence is inconclusive"
- **Distinguish facts from hypotheses** - "K8s agent found OOMKilled (fact). This suggests memory limit is too low (hypothesis)."

### Thoroughness
- **Don't stop at symptoms** - Dig until you find actionable root cause
- **Cross-correlate** - Look for connections between different system findings
- **Check for recent changes** - They often explain sudden issues

### Evidence Presentation
- **Quote agent findings** - Include specific data from sub-agents
- **Build timeline** - Show chronological sequence of events
- **Show reasoning** - Explain why you think X caused Y

## COMMON INVESTIGATION PATTERNS

| Symptom | First Check | Then Check |
|---------|-------------|------------|
| High latency | call_metrics_agent | call_k8s_agent (resources) |
| 5xx errors | call_log_analysis_agent | call_k8s_agent (pod health) |
| Service down | call_k8s_agent | call_aws_agent (infra) |
| Sudden change | call_github_agent | related system agents |
| Database issues | call_aws_agent (RDS) | call_log_analysis_agent |

## TOOL CALL LIMITS

- Maximum 10 tool calls per investigation
- After 6 calls, you MUST start forming conclusions
- Don't call the same agent twice with the same query

## ANTI-PATTERNS (DON'T DO THESE)

❌ Call all 5 agents immediately without a plan
❌ Ignore context from previous agent calls
❌ Stop after one agent call without synthesis
❌ Make claims without evidence from agents
❌ Repeat the same query to the same agent

## OUTPUT FORMAT

### Summary
Brief overview of what you found (2-3 sentences).

### Root Cause
- **Description**: What is causing the issue?
- **Confidence**: 0-100% based on evidence quality
- **Evidence**: Specific findings that support this conclusion

### Timeline
Chronological sequence of events with timestamps.

### Affected Systems
List of impacted services/resources.

### Recommendations
1. **Immediate**: Actions to take now
2. **Follow-up**: Additional investigation needed
3. **Prevention**: How to prevent recurrence"""


# =============================================================================
# Agent Factory
# =============================================================================


def create_investigation_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create investigation agent (sub-orchestrator).

    The investigation agent orchestrates specialized agents (K8s, AWS, metrics,
    logs, GitHub) to conduct thorough incident investigations. It can also use
    direct tools for cross-cutting concerns.

    The agent's role can be configured dynamically:
    - As entrance agent: default (no special guidance)
    - As sub-agent: is_subagent=True (adds response guidance for concise output)
    - As master agent: is_master=True (adds delegation guidance) - default True

    Sub-agents can be configured via team_config:
        agents:
          investigation:
            subagents:
              - k8s
              - aws
              - metrics
              # github and log_analysis disabled

    Args:
        team_config: Team configuration for customization
        is_subagent: If True, agent is being called by another agent.
                     This adds guidance for concise, caller-focused responses.
        is_master: If True, agent can delegate to other agents.
                   Defaults to True since investigation is a sub-orchestrator.
                   Can be set via team config: agents.investigation.is_master: false
    """
    from ..prompts.layers import apply_role_based_prompt, build_agent_prompt_sections

    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Investigation agent is always a master (it delegates to sub-agents)
    # unless explicitly disabled in config
    effective_is_master = True if is_master else True  # Default to True
    if team_cfg:
        try:
            agent_cfg = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_cfg = team_cfg.get_agent_config("investigation")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_cfg = agents.get("investigation", {})

            if agent_cfg:
                # Allow explicit disable of master mode
                if hasattr(agent_cfg, "is_master"):
                    if agent_cfg.is_master is False:  # Explicit False
                        effective_is_master = False
                elif isinstance(agent_cfg, dict):
                    if agent_cfg.get("is_master") is False:  # Explicit False
                        effective_is_master = False
        except Exception:
            pass

    # Check if team has custom prompt
    custom_prompt = None
    if team_cfg:
        try:
            agent_cfg = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_cfg = team_cfg.get_agent_config("investigation")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_cfg = agents.get("investigation")

            if agent_cfg:
                if hasattr(agent_cfg, "get_system_prompt"):
                    custom_prompt = agent_cfg.get_system_prompt()
                elif hasattr(agent_cfg, "prompt") and agent_cfg.prompt:
                    custom_prompt = agent_cfg.prompt
                elif isinstance(agent_cfg, dict):
                    prompt_config = agent_cfg.get("prompt", {})
                    if isinstance(prompt_config, str):
                        custom_prompt = prompt_config
                    elif isinstance(prompt_config, dict):
                        custom_prompt = prompt_config.get("system")

                if custom_prompt:
                    logger.info(
                        "using_custom_investigation_prompt",
                        prompt_length=len(custom_prompt),
                    )
        except Exception:
            pass

    base_prompt = custom_prompt or SYSTEM_PROMPT

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="investigation",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=effective_is_master,
    )

    # Add shared sections (error handling, tool limits, evidence format)
    # NOTE: Contextual information (service_info, namespaces, regions, etc.) is now
    # passed in the user message, not the system prompt. This allows context to flow
    # naturally from the planner through to sub-agents when delegating.
    shared_sections = build_agent_prompt_sections(
        integration_name="investigation",
        is_subagent=is_subagent,
        include_error_handling=True,
        include_tool_limits=True,
        include_evidence_format=True,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Load direct tools and sub-agent tools
    direct_tools = _load_investigation_direct_tools()
    subagent_tools = _create_subagent_tools(team_config=team_cfg)
    tools = direct_tools + subagent_tools

    logger.info(
        "investigation_agent_tools_loaded",
        direct_count=len(direct_tools),
        subagent_count=len(subagent_tools),
        total=len(tools),
    )

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.2
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

    if team_cfg:
        try:
            agent_cfg = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_cfg = team_cfg.get_agent_config("investigation")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_cfg = agents.get("investigation")

            if agent_cfg:
                model_cfg = None
                if hasattr(agent_cfg, "model"):
                    model_cfg = agent_cfg.model
                elif isinstance(agent_cfg, dict):
                    model_cfg = agent_cfg.get("model")

                if model_cfg:
                    if hasattr(model_cfg, "name"):
                        model_name = model_cfg.name
                        temperature = model_cfg.temperature
                        max_tokens = model_cfg.max_tokens
                        reasoning = getattr(model_cfg, "reasoning", None)
                        verbosity = getattr(model_cfg, "verbosity", None)
                    elif isinstance(model_cfg, dict):
                        model_name = model_cfg.get("name", model_name)
                        temperature = model_cfg.get("temperature", temperature)
                        max_tokens = model_cfg.get("max_tokens", max_tokens)
                        reasoning = model_cfg.get("reasoning")
                        verbosity = model_cfg.get("verbosity")
                    logger.info(
                        "using_team_model_config",
                        agent="investigation",
                        model=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        reasoning=reasoning,
                        verbosity=verbosity,
                    )
        except Exception:
            pass

    return Agent[TaskContext](
        name="InvestigationAgent",
        instructions=system_prompt,
        model=model_name,
        model_settings=create_model_settings(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            verbosity=verbosity,
        ),
        tools=tools,
        # Removed output_type=InvestigationResult to allow flexible XML-based output format
        # defined in system prompt. This enables hot-reloadable output schema via config.
    )
