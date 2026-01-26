"""
Planner Agent - Meta-agent that orchestrates complex tasks.

The planner is the main entry point for complex requests. It routes to:
1. Investigation Agent - For incident investigation (the main workhorse)
2. Coding Agent - For code analysis and fixes (explicit requests only)
3. Writeup Agent - For postmortems and documentation (explicit requests only)

Architecture (Starship Topology):
    Planner (this file)
    ├── Investigation Agent [is_master=True, is_subagent=True]
    │   ├── GitHub Agent
    │   ├── K8s Agent
    │   ├── AWS Agent
    │   ├── Metrics Agent
    │   └── Log Analysis Agent
    ├── Coding Agent [is_subagent=True]
    └── Writeup Agent [is_subagent=True]

Uses Agent-as-Tool pattern for true multi-agent orchestration with control retention.

System Prompt Architecture (Standard Pattern):
    base_prompt = custom_prompt or PLANNER_SYSTEM_PROMPT
    system_prompt = base_prompt + capabilities
    system_prompt = apply_role_based_prompt(...)  # Role sections
    system_prompt += shared_sections              # Error handling, tool limits, etc.

Context (runtime metadata, team config) is passed in the USER MESSAGE, not the
system prompt. This allows context to flow naturally to sub-agents when delegating.

To include context, callers should use:
    from ai_agent.prompts.layers import build_user_context
    context = build_user_context(timestamp=..., team_config=...)
    full_query = f"{context}\\n\\n## Task\\n{user_query}"
"""

import asyncio
import json
import threading
from typing import Any

from agents import Agent, Runner, function_tool

from ..core.agent_builder import create_model_settings
from agents.exceptions import MaxTurnsExceeded
from agents.stream_events import RunItemStreamEvent
from pydantic import BaseModel, Field

from ..core.config import get_config
from ..core.config_utils import get_agent_sub_agents
from ..core.execution_context import (
    create_mcp_servers_for_subagent,
    get_execution_context,
    propagate_context_to_thread,
)
from ..core.logging import get_logger
from ..core.partial_work import summarize_partial_work
from ..core.stream_events import (
    EventStreamRegistry,
    get_current_stream_id,
    set_current_stream_id,
)
from ..prompts.agent_capabilities import AGENT_CAPABILITIES
from ..prompts.planner_prompt import build_planner_system_prompt

# Import meta-agent tools
from ..tools.agent_tools import get_agent_tools
from .base import TaskContext

# Import agent factories for the 3 top-level agents
from .coding_agent import create_coding_agent
from .investigation_agent import create_investigation_agent
from .writeup_agent import create_writeup_agent

logger = get_logger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Default agents available to planner (Starship topology)
DEFAULT_PLANNER_AGENTS = ["investigation", "coding", "writeup"]


# =============================================================================
# Agent Threading Utilities
# =============================================================================


def _run_agent_in_thread(
    agent, query: str, timeout: int = 120, max_turns: int = 25
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

    MCP Support: If the agent has MCPs configured in team config (via execution context),
    this function creates MCP servers for the sub-agent and passes them to Runner.run().

    Args:
        agent: The agent to run
        query: The query/task for the agent
        timeout: Max time in seconds to wait (default 120s for investigation)
        max_turns: Max LLM turns for the child agent (default 25 for thorough investigation)

    Returns:
        The agent result, or a partial work summary dict if max_turns was exceeded
    """
    result_holder = {"result": None, "error": None, "partial": False}

    # Capture context from parent thread for propagation to child thread
    # ContextVars don't automatically propagate to new threads
    parent_stream_id = get_current_stream_id()
    parent_context = get_execution_context()
    agent_name = getattr(agent, "name", "unknown")

    def run_in_new_loop():
        try:
            # Create a completely new event loop for this thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)

            # Propagate stream_id to this thread
            if parent_stream_id:
                set_current_stream_id(parent_stream_id)

            # Propagate execution context to this thread
            # This enables sub-agent tools to access integration configs (GitHub, etc.)
            propagate_context_to_thread(parent_context)

            try:
                # Run the async agent execution with MCP support
                result = new_loop.run_until_complete(
                    _run_agent_with_mcp(
                        agent=agent,
                        query=query,
                        max_turns=max_turns,
                        agent_name=agent_name,
                        parent_stream_id=parent_stream_id,
                    )
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

    # Start thread and wait (daemon=True ensures cleanup on timeout)
    thread = threading.Thread(target=run_in_new_loop, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # Thread didn't complete in time, but daemon thread will be cleaned up
        logger.warning("agent_thread_timeout", timeout=timeout)
        raise TimeoutError(f"Agent execution timed out after {timeout}s")

    if result_holder["error"]:
        raise result_holder["error"]

    return result_holder["result"]


async def _run_agent_with_mcp(
    agent, query: str, max_turns: int, agent_name: str, parent_stream_id: str | None
) -> Any:
    """
    Run an agent with MCP server support.

    Creates MCP servers for the agent based on team config (from execution context),
    then runs the agent with those servers.

    Args:
        agent: The agent to run
        query: The query/task
        max_turns: Max LLM turns
        agent_name: Name of the agent (for MCP filtering)
        parent_stream_id: Stream ID for streaming mode (None for non-streaming)

    Returns:
        Agent result
    """
    # Try to create MCP servers for this sub-agent
    stack, mcp_servers = await create_mcp_servers_for_subagent(agent_name)

    if stack and mcp_servers:
        logger.info(
            "running_subagent_with_mcp",
            agent_name=agent_name,
            mcp_count=len(mcp_servers),
        )
        async with stack:
            # Enter each MCP server context
            entered_servers = []
            for server in mcp_servers:
                try:
                    entered = await stack.enter_async_context(server)
                    entered_servers.append(entered)
                except Exception as e:
                    logger.warning(
                        "mcp_server_enter_failed",
                        agent_name=agent_name,
                        error=str(e),
                    )

            if parent_stream_id and EventStreamRegistry.stream_exists(parent_stream_id):
                # Streaming mode with MCP
                return await _run_agent_streamed(
                    agent, query, max_turns, parent_stream_id, agent_name,
                    mcp_servers=entered_servers if entered_servers else None,
                )
            else:
                # Non-streaming mode with MCP
                return await Runner.run(
                    agent, query, max_turns=max_turns,
                    mcp_servers=entered_servers if entered_servers else None,
                )
    else:
        # No MCP servers configured for this agent
        if parent_stream_id and EventStreamRegistry.stream_exists(parent_stream_id):
            # Streaming mode - emit events to the registry
            return await _run_agent_streamed(
                agent, query, max_turns, parent_stream_id, agent_name
            )
        else:
            # Non-streaming mode - original behavior
            return await Runner.run(agent, query, max_turns=max_turns)


async def _run_agent_streamed(
    agent, query: str, max_turns: int, stream_id: str, agent_name: str,
    mcp_servers: list | None = None
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
        mcp_servers: Optional list of MCP servers for this agent
    """
    # Push this agent onto the stack for nesting context
    EventStreamRegistry.push_agent(stream_id, agent_name)

    # Emit subagent started event
    EventStreamRegistry.emit_event(
        stream_id=stream_id,
        event_type="subagent_started",
        agent_name=agent_name,
        data={
            "query_preview": query[:200] if query else "",
            "mcp_count": len(mcp_servers) if mcp_servers else 0,
        },
    )

    tool_sequence = 0

    try:
        # Pass MCP servers to Runner if available
        if mcp_servers:
            result = Runner.run_streamed(agent, query, max_turns=max_turns, mcp_servers=mcp_servers)
        else:
            result = Runner.run_streamed(agent, query, max_turns=max_turns)

        async for event in result.stream_events():
            if isinstance(event, RunItemStreamEvent):
                item = event.item

                # Handle tool call events
                if hasattr(item, "type"):
                    if item.type == "tool_call_item":
                        tool_sequence += 1
                        # Tool name is in raw_item.name or item.name
                        raw_item = getattr(item, "raw_item", None)
                        tool_name = getattr(raw_item, "name", None) or getattr(
                            item, "name", "unknown"
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

                    elif item.type == "tool_call_output_item":
                        output_preview = ""
                        output = getattr(item, "output", None)
                        if output:
                            if isinstance(output, str):
                                # Use 500 chars to capture full config_required JSON
                                output_preview = output[:500]
                            else:
                                output_preview = str(output)[:500]

                        EventStreamRegistry.emit_event(
                            stream_id=stream_id,
                            event_type="tool_completed",
                            agent_name=agent_name,
                            data={
                                "sequence": tool_sequence,
                                "output_preview": output_preview,
                            },
                        )

        # After streaming completes, result.final_output is available
        # Emit subagent completed event
        output = result.final_output
        output_preview = ""
        if output:
            if isinstance(output, str):
                output_preview = output[:200]
            else:
                output_preview = str(output)[:200]

        EventStreamRegistry.emit_event(
            stream_id=stream_id,
            event_type="subagent_completed",
            agent_name=agent_name,
            data={"output_preview": output_preview, "success": True},
        )

        return result

    except Exception as e:
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


# =============================================================================
# Output Models
# =============================================================================


class InvestigationSummary(BaseModel):
    """Summary of an investigation result."""

    summary: str = Field(description="Brief summary of findings")
    root_cause: str = Field(default="", description="Identified root cause if found")
    confidence: int = Field(
        default=0, ge=0, le=100, description="Confidence level 0-100"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Recommended actions"
    )
    needs_followup: bool = Field(
        default=False, description="Whether more investigation is needed"
    )


# =============================================================================
# Utilities
# =============================================================================


def _serialize_agent_output(output: Any) -> str:
    """Convert agent output to a JSON string for the planner."""
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

    # Fallback
    return json.dumps({"result": str(output)})


# =============================================================================
# Agent Configuration
# =============================================================================


def _get_enabled_agents_from_config(team_cfg) -> list[str]:
    """
    Get list of enabled agent keys from team config.

    Reads sub_agents from the planner agent configuration, respecting
    the enabled/disabled settings. Config is the source of truth.

    Supports multiple configuration formats:
    - List: sub_agents: ["investigation", "coding", "writeup"]
    - Dict with enabled flags: sub_agents: {investigation: {enabled: true}}
    - Dict with bool values: sub_agents: {investigation: true, coding: false}

    Args:
        team_cfg: Team configuration object

    Returns:
        List of enabled agent keys
    """
    return get_agent_sub_agents(team_cfg, "planner", DEFAULT_PLANNER_AGENTS)


# =============================================================================
# Agent Tool Creation
# =============================================================================


def create_agent_tools(team_config=None):
    """
    Create wrapper tools that call the 3 top-level agents.

    This implements the Agent-as-Tool pattern where:
    - Each agent is wrapped as a callable tool
    - The planner calls the tool, agent runs, result returns to planner
    - Planner retains control and can call multiple agents

    The 3 top-level agents (Starship topology) are:
    - Investigation Agent: Main workhorse for SRE tasks (delegates to sub-agents)
    - Coding Agent: For explicit code fix/analysis requests
    - Writeup Agent: For postmortem/documentation requests

    Remote A2A agents can be added dynamically from config.
    """
    from ..integrations.a2a.agent_wrapper import get_remote_agents_for_team

    enabled_agents = _get_enabled_agents_from_config(team_config)
    logger.info("planner_enabled_agents", agents=enabled_agents)

    # Warn about unknown agent names in config
    known_agents = set(DEFAULT_PLANNER_AGENTS)
    for agent in enabled_agents:
        if agent not in known_agents:
            logger.warning(
                "unknown_agent_in_config",
                agent=agent,
                known_agents=list(known_agents),
            )

    tools = []

    # Create the agents based on what's enabled
    # Investigation agent is created with is_subagent=True (called by planner)
    # It internally sets is_master=True because it delegates to its own sub-agents
    if "investigation" in enabled_agents:
        investigation_agent = create_investigation_agent(
            team_config=team_config, is_subagent=True
        )

        @function_tool
        def call_investigation_agent(
            query: str, context: str = "", instructions: str = ""
        ) -> str:
            """
            Delegate incident investigation to the Investigation Agent.

            The Investigation Agent is your primary tool for SRE tasks. It coordinates
            specialized sub-agents (K8s, AWS, Metrics, Logs, GitHub) to conduct
            thorough investigations and identify root causes.

            USE THIS AGENT FOR:
            - Incident investigation (any severity)
            - Root cause analysis
            - System health checks
            - Performance investigations
            - Error pattern analysis

            The agent will autonomously:
            - Decide which sub-agents to call based on symptoms
            - Gather evidence from multiple systems
            - Correlate findings across systems
            - Build timelines and identify root cause

            Args:
                query: Natural language description of what to investigate
                context: Prior findings or relevant context
                instructions: Specific guidance (focus areas, priorities)

            Returns:
                JSON with root_cause, confidence, timeline, affected_systems, recommendations
                If max turns exceeded, returns partial findings with status="incomplete"
            """
            try:
                logger.info("calling_investigation_agent", query=query[:100])
                parts = [query]
                if context:
                    parts.append(f"\n\n## Prior Context\n{context}")
                if instructions:
                    parts.append(f"\n\n## Investigation Guidance\n{instructions}")
                full_query = "".join(parts)
                result = _run_agent_in_thread(
                    investigation_agent, full_query, timeout=120, max_turns=25
                )
                # Check if result is a partial work summary (dict with status="incomplete")
                if isinstance(result, dict) and result.get("status") == "incomplete":
                    logger.info(
                        "investigation_agent_partial_results",
                        findings=len(result.get("findings", [])),
                    )
                    return json.dumps(result)
                output = getattr(result, "final_output", None) or getattr(
                    result, "output", None
                )
                return _serialize_agent_output(output)
            except Exception as e:
                logger.error("investigation_agent_failed", error=str(e))
                return json.dumps({"error": str(e), "agent": "investigation_agent"})

        tools.append(call_investigation_agent)

    if "coding" in enabled_agents:
        coding_agent = create_coding_agent(team_config=team_config, is_subagent=True)

        @function_tool
        def call_coding_agent(
            query: str,
            file_context: str = "",
            context: str = "",
            instructions: str = "",
        ) -> str:
            """
            Delegate code analysis or fix to the Coding Agent.

            USE THIS AGENT ONLY WHEN:
            - User explicitly asks for code analysis
            - User explicitly asks to fix a bug in code
            - User explicitly asks to review code
            - User explicitly asks to create a PR or code change

            DO NOT USE FOR:
            - General investigation (use investigation_agent instead)
            - Understanding what's wrong (investigate first)

            Args:
                query: What code task to perform
                file_context: Relevant file paths or code snippets
                context: Prior investigation findings
                instructions: Specific guidance for the fix

            Returns:
                JSON with code analysis, issues_found, code_changes, and recommendations
                If max turns exceeded, returns partial findings with status="incomplete"
            """
            try:
                logger.info("calling_coding_agent", query=query[:100])
                parts = [query]
                if file_context:
                    parts.append(f"\n\nFile context: {file_context}")
                if context:
                    parts.append(f"\n\n## Prior Findings\n{context}")
                if instructions:
                    parts.append(f"\n\n## Coding Guidance\n{instructions}")
                full_query = "".join(parts)
                result = _run_agent_in_thread(
                    coding_agent, full_query, timeout=60, max_turns=15
                )
                # Check if result is a partial work summary (dict with status="incomplete")
                if isinstance(result, dict) and result.get("status") == "incomplete":
                    logger.info(
                        "coding_agent_partial_results",
                        findings=len(result.get("findings", [])),
                    )
                    return json.dumps(result)
                output = getattr(result, "final_output", None) or getattr(
                    result, "output", None
                )
                return _serialize_agent_output(output)
            except Exception as e:
                logger.error("coding_agent_failed", error=str(e))
                return json.dumps({"error": str(e), "agent": "coding_agent"})

        tools.append(call_coding_agent)

    if "writeup" in enabled_agents:
        writeup_agent = create_writeup_agent(team_config=team_config, is_subagent=True)

        @function_tool
        def call_writeup_agent(
            query: str, investigation_findings: str = "", template: str = ""
        ) -> str:
            """
            Delegate postmortem or incident writeup to the Writeup Agent.

            USE THIS AGENT ONLY WHEN:
            - User explicitly asks for a postmortem
            - User explicitly asks for an incident writeup
            - User explicitly asks for documentation of findings

            DO NOT USE FOR:
            - Active investigation (use investigation_agent instead)
            - Before investigation is complete

            Args:
                query: What kind of writeup to create
                investigation_findings: Findings from investigation to include
                template: Optional template or format requirements

            Returns:
                JSON with postmortem document structure
                If max turns exceeded, returns partial findings with status="incomplete"
            """
            try:
                logger.info("calling_writeup_agent", query=query[:100])
                parts = [query]
                if investigation_findings:
                    parts.append(
                        f"\n\n## Investigation Findings\n{investigation_findings}"
                    )
                if template:
                    parts.append(f"\n\n## Template/Format\n{template}")
                full_query = "".join(parts)
                result = _run_agent_in_thread(
                    writeup_agent, full_query, timeout=60, max_turns=10
                )
                # Check if result is a partial work summary (dict with status="incomplete")
                if isinstance(result, dict) and result.get("status") == "incomplete":
                    logger.info(
                        "writeup_agent_partial_results",
                        findings=len(result.get("findings", [])),
                    )
                    return json.dumps(result)
                output = getattr(result, "final_output", None) or getattr(
                    result, "output", None
                )
                return _serialize_agent_output(output)
            except Exception as e:
                logger.error("writeup_agent_failed", error=str(e))
                return json.dumps({"error": str(e), "agent": "writeup_agent"})

        tools.append(call_writeup_agent)

    # Add remote A2A agent tools dynamically from config
    if team_config:
        try:
            remote_agents = get_remote_agents_for_team(team_config)
            if remote_agents:
                logger.info("adding_remote_agents_to_planner", count=len(remote_agents))
                # remote_agents is already a dict of tool-wrapped functions
                tools.extend(remote_agents.values())
        except Exception as e:
            logger.warning("failed_to_load_remote_agents_for_planner", error=str(e))

    return tools


# =============================================================================
# Planner Agent Factory
# =============================================================================


def create_planner_agent(
    team_config=None,
) -> Agent[TaskContext]:
    """
    Create and configure the Planner Agent with 3 top-level agents as tools.

    The planner acts as a meta-agent that can:
    - Use tools for reasoning (think, web_search, llm_call)
    - Call specialized agents as tools and get results back
    - Synthesize results from multiple agents
    - Maintain control throughout the process

    Starship Topology:
        Planner
        ├── Investigation Agent (main workhorse, has sub-agents)
        ├── Coding Agent (explicit code requests only)
        └── Writeup Agent (explicit documentation requests only)

    System prompt follows the standard pattern:
        base_prompt = custom_prompt or PLANNER_SYSTEM_PROMPT
        system_prompt = base_prompt + capabilities
        system_prompt = apply_role_based_prompt(...)  # Role sections
        system_prompt += shared_sections

    NOTE: Runtime metadata and contextual info should be passed in the USER
    MESSAGE, not the system prompt. Use build_user_context() for this:

        from ai_agent.prompts.layers import build_user_context
        context = build_user_context(timestamp=..., team_config=...)
        full_query = f"{context}\\n\\n## Task\\n{user_query}"

    Args:
        team_config: Team configuration object or dict

    Returns:
        Configured Planner Agent
    """
    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Get meta-agent tools (think, web_search, llm_call, etc.)
    meta_tools = get_agent_tools()

    # Get agent-as-tool wrappers for the 3 top-level agents
    agent_tools = create_agent_tools(team_config=team_cfg)

    # Get remote A2A agents for capabilities section
    remote_agents_config = None
    if team_cfg:
        try:
            from ..integrations.a2a.agent_wrapper import get_remote_agents_for_team

            remote_agents = get_remote_agents_for_team(team_cfg)
            if remote_agents:
                # Build config dict for prompt builder
                remote_agents_config = {}
                for agent_id, tool in remote_agents.items():
                    tool_name = getattr(tool, "__name__", agent_id)
                    tool_doc = getattr(tool, "__doc__", "") or "Remote agent"
                    # Extract description from docstring
                    doc_lines = tool_doc.strip().split("\n")
                    description = doc_lines[0] if doc_lines else "Remote agent"

                    remote_agents_config[agent_id] = {
                        "name": tool_name.replace("call_", "")
                        .replace("_agent", "")
                        .replace("_", " ")
                        .title()
                        + " Agent",
                        "tool_name": tool_name,
                        "description": description,
                    }
                logger.info("planner_remote_agents_loaded", count=len(remote_agents))
        except Exception as e:
            logger.warning("failed_to_load_remote_agents_for_prompt", error=str(e))

    # Get enabled agents from team config (respects enabled/disabled settings)
    enabled_agents = _get_enabled_agents_from_config(team_cfg)

    # Build system prompt using the standard pattern
    # (custom prompt can override base, role sections and shared sections still appended)
    system_prompt = build_planner_system_prompt(
        enabled_agents=enabled_agents,
        agent_capabilities=AGENT_CAPABILITIES,
        remote_agents=remote_agents_config,
        team_config=team_cfg if isinstance(team_cfg, dict) else None,
    )

    logger.info(
        "planner_prompt_built",
        prompt_length=len(system_prompt),
        enabled_agents=enabled_agents,
        has_remote_agents=bool(remote_agents_config),
    )

    # Combine meta-tools and agent-as-tool wrappers
    all_tools = meta_tools + agent_tools

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = config.openai.temperature
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

    if team_cfg:
        try:
            agent_config = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_config = team_cfg.get_agent_config("planner")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_config = agents.get("planner")

            if agent_config:
                model_cfg = None
                if hasattr(agent_config, "model"):
                    model_cfg = agent_config.model
                elif isinstance(agent_config, dict):
                    model_cfg = agent_config.get("model")

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
                        agent="planner",
                        model=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        reasoning=reasoning,
                        verbosity=verbosity,
                    )
        except Exception:
            pass

    # Create the planner agent (without MCP servers - those are passed per-request)
    return Agent[TaskContext](
        name="Planner",
        instructions=system_prompt,
        model=model_name,
        model_settings=create_model_settings(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning=reasoning,
            verbosity=verbosity,
        ),
        tools=all_tools,
        output_type=InvestigationSummary,
    )
