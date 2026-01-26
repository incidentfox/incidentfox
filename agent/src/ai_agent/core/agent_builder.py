"""
Dynamic Agent Builder

Constructs agents from JSON configuration with:
- Configurable prompts, models, and parameters
- Dynamic tool selection based on config
- Sub-agent construction for agent-as-tool pattern
- Validation of agent config

This enables:
1. Org admins to set default agent behavior
2. Teams to customize agents for their needs
3. Runtime agent construction without code changes
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from typing import Any

from agents import Agent, ModelSettings, Runner, function_tool
from agents.exceptions import MaxTurnsExceeded
from pydantic import BaseModel, Field

from .execution_context import get_execution_context, propagate_context_to_thread
from .logging import get_logger
from .partial_work import summarize_partial_work

logger = get_logger(__name__)


# =============================================================================
# Model Settings Helper
# =============================================================================

# OpenAI reasoning models don't support temperature, top_p, frequency_penalty, etc.
# This includes o-series (o1, o3, o4) and gpt-5 series
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def is_reasoning_model(model_name: str) -> bool:
    """Check if a model is a reasoning model that doesn't support temperature."""
    return model_name.startswith(REASONING_MODEL_PREFIXES)


def create_model_settings(
    model_name: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    reasoning: str | None = None,
    verbosity: str | None = None,
) -> ModelSettings:
    """
    Create ModelSettings with appropriate parameters based on model type.

    For reasoning models (o1, o3, o4, gpt-5): Uses reasoning effort and verbosity.
    For standard models: Uses temperature.

    Args:
        model_name: The model name (e.g., "gpt-4o", "gpt-5", "o3-mini")
        temperature: Temperature for standard models (ignored for reasoning models)
        max_tokens: Maximum tokens for response
        reasoning: Reasoning effort for reasoning models ('none', 'low', 'medium', 'high', 'xhigh')
        verbosity: Verbosity for reasoning models ('low', 'medium', 'high')

    Returns:
        ModelSettings configured appropriately for the model type
    """
    if is_reasoning_model(model_name):
        # Reasoning models use reasoning effort and verbosity instead of temperature
        effort = reasoning or "medium"
        verb = verbosity or "medium"
        return ModelSettings(
            max_tokens=max_tokens,
            reasoning={"effort": effort},
            verbosity=verb,
        )
    else:
        # Standard models use temperature
        temp = temperature if temperature is not None else 0.4
        return ModelSettings(
            temperature=temp,
            max_tokens=max_tokens,
        )


# =============================================================================
# Output Types
# =============================================================================


class AgentResult(BaseModel):
    """Standard result from an agent."""

    summary: str = Field(description="Summary of findings")
    details: str | None = Field(default=None, description="Detailed explanation")
    confidence: int = Field(default=0, description="Confidence 0-100")
    recommendations: list[str] = Field(default_factory=list)
    requires_followup: bool = Field(default=False)


# =============================================================================
# Tool Resolution
# =============================================================================


def get_all_available_tools() -> dict[str, Callable]:
    """
    Get all available tools as a name → function mapping.

    This is the master registry of tools that can be enabled/disabled.
    """
    tools = {}

    # Meta tools
    try:
        from ..tools.agent_tools import llm_call, web_search
        from ..tools.thinking import think

        tools["think"] = think
        tools["llm_call"] = llm_call
        tools["web_search"] = web_search
    except Exception as e:
        logger.warning("meta_tools_load_failed", error=str(e))

    # Kubernetes tools
    try:
        from ..tools.kubernetes import (
            describe_deployment,
            describe_pod,
            describe_service,
            get_deployment_history,
            get_pod_events,
            get_pod_logs,
            get_pod_resource_usage,
            list_pods,
        )

        tools.update(
            {
                "list_pods": list_pods,
                "describe_pod": describe_pod,
                "get_pod_logs": get_pod_logs,
                "get_pod_events": get_pod_events,
                "describe_deployment": describe_deployment,
                "get_deployment_history": get_deployment_history,
                "describe_service": describe_service,
                "get_pod_resource_usage": get_pod_resource_usage,
            }
        )
    except Exception as e:
        logger.warning("k8s_tools_load_failed", error=str(e))

    # AWS tools
    try:
        from ..tools.aws_tools import (
            describe_ec2_instance,
            describe_lambda_function,
            get_cloudwatch_logs,
            get_cloudwatch_metrics,
            get_rds_instance_status,
            list_ecs_tasks,
            query_cloudwatch_insights,
        )

        tools.update(
            {
                "describe_ec2_instance": describe_ec2_instance,
                "get_cloudwatch_logs": get_cloudwatch_logs,
                "describe_lambda_function": describe_lambda_function,
                "get_rds_instance_status": get_rds_instance_status,
                "query_cloudwatch_insights": query_cloudwatch_insights,
                "get_cloudwatch_metrics": get_cloudwatch_metrics,
                "list_ecs_tasks": list_ecs_tasks,
            }
        )
    except Exception as e:
        logger.warning("aws_tools_load_failed", error=str(e))

    # Anomaly detection tools
    try:
        from ..tools.anomaly_tools import (
            analyze_metric_distribution,
            correlate_metrics,
            detect_anomalies,
            find_change_point,
            forecast_metric,
        )

        tools.update(
            {
                "detect_anomalies": detect_anomalies,
                "correlate_metrics": correlate_metrics,
                "find_change_point": find_change_point,
                "forecast_metric": forecast_metric,
                "analyze_metric_distribution": analyze_metric_distribution,
            }
        )
    except Exception as e:
        logger.warning("anomaly_tools_load_failed", error=str(e))

    # Grafana tools
    try:
        from ..tools.grafana_tools import (
            grafana_get_alerts,
            grafana_get_annotations,
            grafana_get_dashboard,
            grafana_list_dashboards,
            grafana_list_datasources,
            grafana_query_prometheus,
        )

        tools.update(
            {
                "grafana_list_dashboards": grafana_list_dashboards,
                "grafana_get_dashboard": grafana_get_dashboard,
                "grafana_query_prometheus": grafana_query_prometheus,
                "grafana_list_datasources": grafana_list_datasources,
                "grafana_get_annotations": grafana_get_annotations,
                "grafana_get_alerts": grafana_get_alerts,
            }
        )
    except Exception as e:
        logger.warning("grafana_tools_load_failed", error=str(e))

    # Docker tools
    try:
        from ..tools.docker_tools import (
            docker_exec,
            docker_images,
            docker_inspect,
            docker_logs,
            docker_ps,
            docker_stats,
        )

        tools.update(
            {
                "docker_ps": docker_ps,
                "docker_logs": docker_logs,
                "docker_inspect": docker_inspect,
                "docker_exec": docker_exec,
                "docker_images": docker_images,
                "docker_stats": docker_stats,
            }
        )
    except Exception as e:
        logger.warning("docker_tools_load_failed", error=str(e))

    # Git tools
    try:
        from ..tools.git_tools import (
            git_blame,
            git_branch_list,
            git_diff,
            git_log,
            git_show,
            git_status,
        )

        tools.update(
            {
                "git_status": git_status,
                "git_diff": git_diff,
                "git_log": git_log,
                "git_blame": git_blame,
                "git_show": git_show,
                "git_branch_list": git_branch_list,
            }
        )
    except Exception as e:
        logger.warning("git_tools_load_failed", error=str(e))

    # Coding tools
    try:
        from ..tools.coding_tools import (
            list_directory,
            pytest_run,
            python_run_tests,
            read_file,
            repo_search_text,
            run_linter,
            write_file,
        )

        tools.update(
            {
                "repo_search_text": repo_search_text,
                "read_file": read_file,
                "write_file": write_file,
                "list_directory": list_directory,
                "python_run_tests": python_run_tests,
                "pytest_run": pytest_run,
                "run_linter": run_linter,
            }
        )
    except Exception as e:
        logger.warning("coding_tools_load_failed", error=str(e))

    # GitHub tools
    try:
        from ..tools.github_tools import (
            list_issues,
            list_pull_requests,
            read_github_file,
            search_github_code,
        )

        tools.update(
            {
                "search_github_code": search_github_code,
                "read_github_file": read_github_file,
                "list_pull_requests": list_pull_requests,
                "list_issues": list_issues,
            }
        )
    except Exception as e:
        logger.warning("github_tools_load_failed", error=str(e))

    # Knowledge base tools
    try:
        from ..tools.knowledge_base_tools import (
            ask_knowledge_base,
            get_knowledge_context,
            list_knowledge_trees,
            search_knowledge_base,
        )

        tools.update(
            {
                "search_knowledge_base": search_knowledge_base,
                "ask_knowledge_base": ask_knowledge_base,
                "get_knowledge_context": get_knowledge_context,
                "list_knowledge_trees": list_knowledge_trees,
            }
        )
    except Exception as e:
        logger.warning("kb_tools_load_failed", error=str(e))

    # Remediation tools
    try:
        from ..tools.remediation_tools import (
            get_current_replicas,
            get_remediation_status,
            list_pending_remediations,
            propose_deployment_restart,
            propose_deployment_rollback,
            propose_emergency_action,
            propose_pod_restart,
            propose_remediation,
            propose_scale_deployment,
        )

        tools.update(
            {
                "propose_remediation": propose_remediation,
                "propose_pod_restart": propose_pod_restart,
                "propose_deployment_restart": propose_deployment_restart,
                "propose_scale_deployment": propose_scale_deployment,
                "propose_deployment_rollback": propose_deployment_rollback,
                "propose_emergency_action": propose_emergency_action,
                "get_current_replicas": get_current_replicas,
                "list_pending_remediations": list_pending_remediations,
                "get_remediation_status": get_remediation_status,
            }
        )
    except Exception as e:
        logger.warning("remediation_tools_load_failed", error=str(e))

    logger.debug("all_tools_registered", count=len(tools))
    return tools


def resolve_tools(
    enabled: list[str],
    disabled: list[str],
    tool_configs: dict[str, dict[str, Any]] | None = None,
) -> list[Callable]:
    """
    Resolve the list of tools to use based on config.

    Args:
        enabled: List of tool names to enable ("*" = all)
        disabled: List of tool names to disable
        tool_configs: Optional config values to inject into tools

    Returns:
        List of tool functions
    """
    all_tools = get_all_available_tools()

    # Determine which tools to include
    if "*" in enabled:
        result_tools = list(all_tools.values())
        result_names = set(all_tools.keys())
    else:
        result_tools = []
        result_names = set()
        for name in enabled:
            if name in all_tools:
                result_tools.append(all_tools[name])
                result_names.add(name)

    # Remove disabled tools
    if disabled:
        disabled_set = set(disabled)
        result_tools = [
            t for t, n in zip(result_tools, result_names) if n not in disabled_set
        ]

    # TODO: Inject tool configs (for tools that need configuration)
    # This would require wrapping tools with partial application

    logger.debug("tools_resolved", enabled=len(result_tools), disabled=len(disabled))
    return result_tools


# =============================================================================
# Agent Builder
# =============================================================================


def get_default_prompt(agent_id: str) -> str:
    """Get the default system prompt for an agent."""
    # Import here to avoid circular dependency
    prompts = {
        "planner": """You are an expert incident coordinator...
(Default planner prompt - will be replaced by actual prompt from agent files)""",
        "investigation": """You are an expert SRE with deep expertise in incident investigation...""",
        "k8s": """You are a Kubernetes expert specializing in troubleshooting...""",
        "aws": """You are an AWS expert specializing in resource management...""",
        "metrics": """You are a metrics analysis expert specializing in anomaly detection...""",
        "coding": """You are an expert software engineer specializing in code analysis...""",
    }
    return prompts.get(agent_id, "You are an AI assistant.")


def build_agent_from_config(
    agent_id: str,
    effective_config: dict[str, Any],
    parent_agents: dict[str, Agent] | None = None,
    remote_agents: dict[str, Callable] | None = None,
) -> Agent | None:
    """
    Build an agent from configuration.

    Args:
        agent_id: The agent identifier (e.g., 'investigation', 'k8s')
        effective_config: The effective (merged) configuration
        parent_agents: Dict of already-built agents (for sub-agent references)
        remote_agents: Dict of remote A2A agents (for sub-agent references)

    Returns:
        Constructed Agent or None if disabled
    """
    agents_config = effective_config.get("agents", {})
    agent_config = agents_config.get(agent_id, {})

    if not agent_config.get("enabled", True):
        logger.info("agent_disabled", agent_id=agent_id)
        return None

    # Get agent settings
    name = agent_config.get("name", agent_id.title())
    model_config = agent_config.get("model", {})
    prompt_config = agent_config.get("prompt", {})
    tools_config = agent_config.get("tools", {})
    max_turns = agent_config.get("max_turns", 20)

    # Build system prompt
    system_prompt = prompt_config.get("system", "") or get_default_prompt(agent_id)
    if prompt_config.get("prefix"):
        system_prompt = prompt_config["prefix"] + "\n\n" + system_prompt
    if prompt_config.get("suffix"):
        system_prompt = system_prompt + "\n\n" + prompt_config["suffix"]

    # Build model settings using shared helper
    model_name = model_config.get("name", "gpt-4o")
    model_settings = create_model_settings(
        model_name=model_name,
        temperature=model_config.get("temperature", 0.4),
        max_tokens=model_config.get("max_tokens"),
        reasoning=model_config.get("reasoning"),
        verbosity=model_config.get("verbosity"),
    )

    # Resolve tools
    # Handle both legacy format {enabled: [], disabled: []} and canonical format {tool_id: bool}
    if "enabled" in tools_config or "disabled" in tools_config:
        # Legacy format
        enabled = tools_config.get("enabled", ["*"])
        disabled = tools_config.get("disabled", [])
    else:
        # Canonical format: Dict[str, bool]
        enabled = []
        disabled = []
        for tool_id, is_enabled in tools_config.items():
            if tool_id in ("configured",):  # Skip metadata keys
                continue
            if is_enabled:
                enabled.append(tool_id)
            else:
                disabled.append(tool_id)
        # If no tools specified, enable all
        if not enabled and not disabled:
            enabled = ["*"]

    tools = resolve_tools(
        enabled=enabled,
        disabled=disabled,
        tool_configs=tools_config.get("configured"),
    )

    # Build sub-agent tools (for planner)
    # Handle both legacy format (list) and canonical format (Dict[str, bool])
    sub_agents_config = agent_config.get("sub_agents", [])
    if isinstance(sub_agents_config, dict):
        # Canonical format: Dict[str, bool]
        sub_agent_ids = [
            agent_id for agent_id, enabled in sub_agents_config.items() if enabled
        ]
        logger.debug(
            "sub_agents_resolved_canonical",
            agent_id=agent_id,
            sub_agents_config=sub_agents_config,
            final=sub_agent_ids,
        )
    elif isinstance(sub_agents_config, list):
        # Legacy format: list with disable/enable pattern
        disable_default = agent_config.get("disable_default_sub_agents", [])
        enable_extra = agent_config.get("enable_extra_sub_agents", [])

        # Start with defaults, remove disabled, add extras
        sub_agent_ids = [sid for sid in sub_agents_config if sid not in disable_default]
        sub_agent_ids.extend(enable_extra)
        # Deduplicate while preserving order
        seen = set()
        sub_agent_ids = [
            sid for sid in sub_agent_ids if not (sid in seen or seen.add(sid))
        ]

        if disable_default or enable_extra:
            logger.info(
                "sub_agents_resolved",
                agent_id=agent_id,
                default=sub_agents_config,
                disabled=disable_default,
                extra=enable_extra,
                final=sub_agent_ids,
            )
    else:
        sub_agent_ids = []

    if sub_agent_ids:
        for sub_id in sub_agent_ids:
            # Check if it's a local agent
            if parent_agents and sub_id in parent_agents:
                # Create agent-as-tool wrapper
                sub_agent = parent_agents[sub_id]
                sub_tool = _create_agent_tool(sub_id, sub_agent, max_turns)
                tools.append(sub_tool)
            # Check if it's a remote A2A agent
            elif remote_agents and sub_id in remote_agents:
                # Remote agent already wrapped as tool
                tools.append(remote_agents[sub_id])
                logger.info(
                    "remote_agent_added_as_sub_agent",
                    agent_id=agent_id,
                    remote_agent_id=sub_id,
                )
            else:
                logger.warning(
                    "sub_agent_not_found", agent_id=agent_id, sub_agent_id=sub_id
                )

    logger.info(
        "agent_built_from_config",
        agent_id=agent_id,
        model=model_name,
        tools=len(tools),
        max_turns=max_turns,
    )

    return Agent(
        name=name,
        instructions=system_prompt,
        model=model_name,
        model_settings=model_settings,
        tools=tools,
        output_type=AgentResult,
    )


def _run_agent_in_thread(agent: Agent, query: str, max_turns: int = 25) -> Any:
    """
    Run an agent in a separate thread with its own event loop.

    If the agent hits MaxTurnsExceeded, partial work is captured and summarized
    using an LLM, and a partial result is returned instead of raising an exception.

    Returns:
        The agent result, or a partial work summary dict if max_turns was exceeded
    """
    result_holder = {"result": None, "error": None, "partial": False}
    agent_name = getattr(agent, "name", "unknown")

    # Capture context from parent thread for propagation to child thread
    # ContextVars don't automatically propagate to new threads
    parent_context = get_execution_context()

    def run_in_new_loop():
        try:
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)

            # Propagate execution context to this thread
            # This enables sub-agent tools to access integration configs (GitHub, etc.)
            propagate_context_to_thread(parent_context)

            try:
                result = new_loop.run_until_complete(
                    Runner.run(agent, query, max_turns=max_turns)
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

    thread = threading.Thread(target=run_in_new_loop)
    thread.start()
    thread.join(timeout=300)  # 5 minute timeout

    if thread.is_alive():
        raise TimeoutError("Agent execution timed out")

    if result_holder["error"]:
        raise result_holder["error"]

    return result_holder["result"]


def _create_agent_tool(agent_id: str, agent: Agent, max_turns: int) -> Callable:
    """Create a function_tool wrapper for an agent."""

    @function_tool
    def call_agent(query: str) -> str:
        """
        Call a specialized agent with a natural language query.

        The agent will investigate and return structured findings.

        Args:
            query: Natural language description of what to investigate

        Returns:
            JSON with the agent's findings and recommendations
            If max turns exceeded, returns partial findings with status="incomplete"
        """
        try:
            result = _run_agent_in_thread(agent, query, max_turns)
            # Check if result is a partial work summary (dict with status="incomplete")
            if isinstance(result, dict) and result.get("status") == "incomplete":
                logger.info(
                    f"{agent_id}_agent_partial_results",
                    findings=len(result.get("findings", [])),
                )
                return json.dumps(result)
            if hasattr(result, "final_output"):
                if hasattr(result.final_output, "model_dump_json"):
                    return result.final_output.model_dump_json()
                return json.dumps({"result": str(result.final_output)})
            return json.dumps({"result": str(result)})
        except Exception as e:
            return json.dumps({"error": str(e), "agent": f"{agent_id}_agent"})

    # Rename the tool based on agent
    call_agent.__name__ = f"call_{agent_id}_agent"
    call_agent.__doc__ = f"""
    Call the {agent.name} to investigate.

    This agent specializes in: {agent_id}

    Send a natural language query describing what you need investigated.
    The agent will use its tools and return findings.

    Args:
        query: Natural language investigation request

    Returns:
        JSON with findings, recommendations, and confidence
        If max turns exceeded, returns partial findings with status="incomplete"
    """

    return call_agent


def _get_sub_agent_ids(agent_config: dict[str, Any]) -> list[str]:
    """Extract sub-agent IDs from agent config."""
    sub_agents_config = agent_config.get("sub_agents", {})
    if isinstance(sub_agents_config, dict):
        return [agent_id for agent_id, enabled in sub_agents_config.items() if enabled]
    elif isinstance(sub_agents_config, list):
        return list(sub_agents_config)
    return []


def _topological_sort_agents(agents_config: dict[str, Any]) -> list[str]:
    """
    Topologically sort agents so dependencies are built first.

    Uses Kahn's algorithm to handle nested orchestrators correctly.
    Example: github, k8s → investigation → planner

    Returns:
        List of agent_ids in build order (dependencies first)
    """
    # Build dependency graph
    # dependencies[agent_id] = set of agent_ids this agent depends on
    dependencies: dict[str, set[str]] = {}
    for agent_id, config in agents_config.items():
        sub_agent_ids = _get_sub_agent_ids(config)
        # Only include dependencies that exist in our config
        dependencies[agent_id] = {sid for sid in sub_agent_ids if sid in agents_config}

    # Kahn's algorithm for topological sort
    # Start with agents that have no dependencies (leaf agents)
    result = []
    no_deps = [aid for aid, deps in dependencies.items() if not deps]

    while no_deps:
        # Process an agent with no remaining dependencies
        agent_id = no_deps.pop(0)
        result.append(agent_id)

        # Remove this agent from others' dependencies
        for aid, deps in dependencies.items():
            if agent_id in deps:
                deps.remove(agent_id)
                if not deps and aid not in result and aid not in no_deps:
                    no_deps.append(aid)

    # Check for circular dependencies
    if len(result) != len(agents_config):
        missing = set(agents_config.keys()) - set(result)
        logger.error(
            "circular_dependency_detected",
            missing_agents=list(missing),
            built_agents=result,
        )
        # Still return what we could build
        result.extend(missing)

    return result


def build_agent_hierarchy(
    effective_config: dict[str, Any], team_config=None
) -> dict[str, Agent]:
    """
    Build all agents based on configuration.

    Uses topological sorting to handle nested orchestrators correctly.
    Example: Starship topology (planner → investigation → [k8s, aws, ...])
    Build order: k8s, aws, ... → investigation → planner

    Args:
        effective_config: The effective (merged) configuration
        team_config: Optional team config object for loading remote agents

    Returns:
        Dict of agent_id → Agent
    """
    agents_config = effective_config.get("agents", {})
    built_agents: dict[str, Agent] = {}

    # Load remote A2A agents
    remote_agents: dict[str, Callable] = {}
    if team_config:
        try:
            from ..integrations.a2a.agent_wrapper import get_remote_agents_for_team

            remote_agents = get_remote_agents_for_team(team_config)
            logger.info("remote_agents_loaded_for_hierarchy", count=len(remote_agents))
        except Exception as e:
            logger.warning("failed_to_load_remote_agents", error=str(e))

    # Topologically sort agents (dependencies first)
    build_order = _topological_sort_agents(agents_config)
    logger.info("agent_build_order", order=build_order)

    # Build agents in dependency order
    for agent_id in build_order:
        config = agents_config.get(agent_id, {})
        if not config.get("enabled", True):
            logger.debug("agent_disabled_skipping", agent_id=agent_id)
            continue

        agent = build_agent_from_config(
            agent_id,
            effective_config,
            parent_agents=built_agents,  # Contains all previously built agents
            remote_agents=remote_agents,
        )
        if agent:
            built_agents[agent_id] = agent

    logger.info(
        "agent_hierarchy_built",
        local_agents=len(built_agents),
        remote_agents=len(remote_agents),
        build_order=build_order,
    )
    return built_agents


def get_planner_agent(
    effective_config: dict[str, Any], team_config=None
) -> Agent | None:
    """
    Get the planner agent (main entry point).

    This builds the full agent hierarchy and returns the planner.

    Args:
        effective_config: The effective (merged) configuration
        team_config: Optional team config object for loading remote agents

    Returns:
        Planner Agent or None
    """
    agents = build_agent_hierarchy(effective_config, team_config=team_config)
    return agents.get("planner")


# =============================================================================
# Validation
# =============================================================================


def validate_agent_config(agent_config: dict[str, Any]) -> list[str]:
    """
    Validate an agent configuration.

    Returns list of error messages (empty if valid).
    """
    errors = []

    # Check model
    model_config = agent_config.get("model", {})
    if "name" in model_config:
        model_name = model_config["name"]
        # Valid model prefixes (allows for versioned models like gpt-5.1, gpt-5.2, etc.)
        valid_prefixes = (
            "gpt-5",  # GPT-5 series (reasoning models)
            "gpt-4o",  # GPT-4o series
            "gpt-4-turbo",
            "gpt-4.1",  # GPT-4.1 series
            "gpt-3.5-turbo",
            "o1",  # o1 reasoning models
            "o3",  # o3 reasoning models
            "o4",  # o4 reasoning models
        )
        if not model_name.startswith(valid_prefixes):
            errors.append(f"Unknown model: {model_name}")

    if "temperature" in model_config:
        temp = model_config["temperature"]
        if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
            errors.append(f"Temperature must be between 0 and 2, got {temp}")

    # Check max_turns
    if "max_turns" in agent_config:
        mt = agent_config["max_turns"]
        if not isinstance(mt, int) or mt < 1 or mt > 100:
            errors.append(f"max_turns must be between 1 and 100, got {mt}")

    # Check tools
    tools_config = agent_config.get("tools", {})
    all_tools = get_all_available_tools()

    for tool_name in tools_config.get("enabled", []):
        if tool_name != "*" and tool_name not in all_tools:
            errors.append(f"Unknown tool: {tool_name}")

    for tool_name in tools_config.get("disabled", []):
        if tool_name not in all_tools:
            errors.append(f"Unknown tool in disabled list: {tool_name}")

    return errors
