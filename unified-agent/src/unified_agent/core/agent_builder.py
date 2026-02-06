"""
Dynamic Agent Builder for Unified Agent.

Constructs agents from JSON configuration with:
- Configurable prompts, models, and parameters
- Dynamic tool selection based on config
- Sub-agent construction for agent-as-tool pattern
- Multi-model support via LiteLLM (Claude, Gemini, OpenAI)

This enables:
1. Org admins to set default agent behavior
2. Teams to customize agents for their needs
3. Runtime agent construction without code changes
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from typing import Any, Optional

from pydantic import BaseModel, Field

from .agent import Agent, ModelSettings, function_tool
from .runner import MODEL_ALIASES, MaxTurnsExceeded, Runner

logger = logging.getLogger(__name__)


# =============================================================================
# Model Settings Helper
# =============================================================================

# Reasoning models that don't support temperature (OpenAI o-series)
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4")

# LiteLLM model prefixes by provider
CLAUDE_PREFIXES = ("anthropic/", "claude-")
GEMINI_PREFIXES = ("gemini/", "google/")
OPENAI_PREFIXES = ("openai/", "gpt-", "o1", "o3", "o4")


def is_reasoning_model(model_name: str) -> bool:
    """Check if a model is a reasoning model that doesn't support temperature."""
    # Extract base model name (after provider prefix)
    base_model = model_name.split("/")[-1] if "/" in model_name else model_name
    return base_model.startswith(REASONING_MODEL_PREFIXES)


def normalize_model_name(model_name: str) -> str:
    """
    Normalize model name to LiteLLM format.

    Handles:
    - Aliases (sonnet, opus, haiku, etc.)
    - Provider-prefixed names (anthropic/claude-...)
    - Legacy names (gpt-5.2 -> openai/gpt-5.2)
    """
    # Check aliases first
    if model_name in MODEL_ALIASES:
        return MODEL_ALIASES[model_name]

    # Already has provider prefix
    if "/" in model_name:
        return model_name

    # Map common model names to LiteLLM format
    if model_name.startswith("claude-"):
        return f"anthropic/{model_name}"
    elif model_name.startswith(("gpt-", "o1", "o3", "o4")):
        return f"openai/{model_name}"
    elif model_name.startswith("gemini-"):
        return f"gemini/{model_name}"

    # Default to using as-is (let LiteLLM handle it)
    return model_name


def create_model_settings(
    model_name: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    reasoning: str | None = None,
    verbosity: str | None = None,
) -> ModelSettings:
    """
    Create ModelSettings with appropriate parameters based on model type.

    For reasoning models (o1, o3, o4): Uses reasoning effort and verbosity.
    For standard models: Uses temperature.

    Args:
        model_name: The model name (can be alias or full name)
        temperature: Temperature for standard models (ignored for reasoning models)
        max_tokens: Maximum tokens for response
        reasoning: Reasoning effort for reasoning models ('none', 'low', 'medium', 'high')
        verbosity: Verbosity for reasoning models ('low', 'medium', 'high')

    Returns:
        ModelSettings configured appropriately for the model type
    """
    normalized = normalize_model_name(model_name)

    if is_reasoning_model(normalized):
        # Reasoning models use reasoning effort instead of temperature
        return ModelSettings(
            max_tokens=max_tokens,
            reasoning={"effort": reasoning or "medium"},
            verbosity=verbosity or "medium",
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
    Tools are loaded lazily to avoid import issues.
    """
    tools = {}

    # Try to load tools from unified_agent.tools package
    # This will be populated as we port tools from agent/
    try:
        from ..tools import get_tool_registry

        tools.update(get_tool_registry())
    except ImportError:
        logger.debug("unified_agent.tools not available yet")

    # Fallback: Try loading from agent/ tools if available
    # This enables gradual migration
    try:
        from ai_agent.tools.kubernetes import (
            describe_deployment,
            describe_pod,
            get_deployment_history,
            get_pod_events,
            get_pod_logs,
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
            }
        )
    except ImportError:
        pass

    try:
        from ai_agent.tools.aws_tools import (
            describe_ec2_instance,
            get_cloudwatch_logs,
            get_cloudwatch_metrics,
            list_ecs_tasks,
        )

        tools.update(
            {
                "describe_ec2_instance": describe_ec2_instance,
                "get_cloudwatch_logs": get_cloudwatch_logs,
                "get_cloudwatch_metrics": get_cloudwatch_metrics,
                "list_ecs_tasks": list_ecs_tasks,
            }
        )
    except ImportError:
        pass

    try:
        from ai_agent.tools.grafana_tools import (
            grafana_get_dashboard,
            grafana_list_dashboards,
            grafana_query_prometheus,
        )

        tools.update(
            {
                "grafana_list_dashboards": grafana_list_dashboards,
                "grafana_get_dashboard": grafana_get_dashboard,
                "grafana_query_prometheus": grafana_query_prometheus,
            }
        )
    except ImportError:
        pass

    try:
        from ai_agent.tools.github_tools import (
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
    except ImportError:
        pass

    logger.debug(f"Available tools: {len(tools)}")
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
        result_names = set(all_tools.keys())
    else:
        result_names = set()
        for name in enabled:
            if name in all_tools:
                result_names.add(name)

    # Remove disabled tools
    if disabled:
        result_names -= set(disabled)

    # Get actual tool functions
    result_tools = [all_tools[name] for name in result_names if name in all_tools]

    logger.debug(
        f"Resolved {len(result_tools)} tools (enabled={len(enabled)}, disabled={len(disabled)})"
    )
    return result_tools


# =============================================================================
# Agent Builder
# =============================================================================


def get_default_prompt(agent_id: str) -> str:
    """Get the default system prompt for an agent."""
    prompts = {
        "planner": """You are an expert incident coordinator responsible for orchestrating investigation and remediation.

Your role is to:
1. Analyze the incident description and context
2. Delegate to specialized agents for deep-dive investigation
3. Synthesize findings from multiple sources
4. Recommend remediation actions
5. Track progress and ensure thorough investigation

Be systematic and thorough. Start with understanding the scope of the issue before diving into details.""",
        "investigation": """You are an expert SRE with deep expertise in incident investigation.

Your role is to:
1. Gather evidence from multiple sources (logs, metrics, traces)
2. Form hypotheses about root cause
3. Test hypotheses with targeted queries
4. Document findings with supporting evidence
5. Identify the root cause or escalate if unclear

Focus on the "why" not just the "what". Look for patterns and correlations.""",
        "k8s": """You are a Kubernetes expert specializing in troubleshooting container and cluster issues.

Your expertise includes:
- Pod lifecycle and crash analysis
- Resource limits and OOM conditions
- Network policies and service discovery
- Deployment strategies and rollbacks
- Node conditions and scheduling issues

Provide specific kubectl commands and YAML snippets when relevant.""",
        "aws": """You are an AWS expert specializing in cloud resource management and troubleshooting.

Your expertise includes:
- EC2 instance health and metrics
- ECS/EKS container orchestration
- CloudWatch logs and metrics
- IAM permissions and security
- Load balancers and networking

Reference specific AWS documentation and best practices.""",
        "metrics": """You are a metrics analysis expert specializing in anomaly detection and performance analysis.

Your expertise includes:
- Time series analysis
- Anomaly detection algorithms
- Correlation analysis
- Percentile and distribution analysis
- Dashboard interpretation

Explain statistical significance and confidence levels in your analysis.""",
        "coding": """You are an expert software engineer specializing in code analysis and debugging.

Your expertise includes:
- Code review and analysis
- Git history investigation
- Debugging and root cause analysis
- Performance optimization
- Security vulnerability identification

Reference specific lines and commits when discussing code changes.""",
        "log-analyst": """You are a log analysis specialist.

Your role is to:
1. Search and filter logs efficiently
2. Identify error patterns and anomalies
3. Correlate log events across services
4. Extract meaningful signals from noise
5. Summarize findings clearly

Use regex and structured queries for precise filtering.""",
        "remediator": """You are a remediation specialist responsible for safe system changes.

Your role is to:
1. Validate proposed remediation actions
2. Assess blast radius and risk
3. Execute changes with proper safeguards
4. Verify the fix resolved the issue
5. Document what was done

Always use dry-run first. Prefer rollbacks over rollforwards when safe.""",
    }
    return prompts.get(
        agent_id, "You are an AI assistant that helps with technical tasks."
    )


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
        logger.info(f"Agent {agent_id} is disabled in config")
        return None

    # Get agent settings
    name = agent_config.get("name", agent_id.replace("-", " ").title())
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

    # Build model settings
    model_name = model_config.get("name", "sonnet")  # Default to Claude Sonnet
    normalized_model = normalize_model_name(model_name)
    model_settings = create_model_settings(
        model_name=model_name,
        temperature=model_config.get("temperature"),
        max_tokens=model_config.get("max_tokens"),
        reasoning=model_config.get("reasoning"),
        verbosity=model_config.get("verbosity"),
    )

    # Resolve tools
    # Handle both formats: {enabled: [], disabled: []} and {tool_id: bool}
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

    # Build sub-agent tools
    sub_agents_config = agent_config.get("sub_agents", [])
    sub_agents_dict: dict[str, Agent] = {}

    if isinstance(sub_agents_config, dict):
        # Canonical format: Dict[str, bool]
        sub_agent_ids = [aid for aid, enabled in sub_agents_config.items() if enabled]
    elif isinstance(sub_agents_config, list):
        # Legacy format with disable/enable pattern
        disable_default = agent_config.get("disable_default_sub_agents", [])
        enable_extra = agent_config.get("enable_extra_sub_agents", [])

        sub_agent_ids = [sid for sid in sub_agents_config if sid not in disable_default]
        sub_agent_ids.extend(enable_extra)
        # Deduplicate while preserving order
        seen = set()
        sub_agent_ids = [
            sid for sid in sub_agent_ids if not (sid in seen or seen.add(sid))
        ]
    else:
        sub_agent_ids = []

    if sub_agent_ids:
        for sub_id in sub_agent_ids:
            # Check if it's a local agent
            if parent_agents and sub_id in parent_agents:
                sub_agent = parent_agents[sub_id]
                sub_agents_dict[sub_id] = sub_agent
                # Create agent-as-tool wrapper
                sub_tool = _create_agent_tool(sub_id, sub_agent, max_turns)
                tools.append(sub_tool)
            # Check if it's a remote A2A agent
            elif remote_agents and sub_id in remote_agents:
                tools.append(remote_agents[sub_id])
                logger.info(f"Added remote agent {sub_id} as tool for {agent_id}")
            else:
                logger.warning(f"Sub-agent {sub_id} not found for {agent_id}")

    logger.info(f"Built agent {agent_id}: model={normalized_model}, tools={len(tools)}")

    return Agent(
        name=name,
        instructions=system_prompt,
        model=normalized_model,
        model_settings=model_settings,
        tools=tools,
        output_type=AgentResult,
        sub_agents=sub_agents_dict,
    )


def _run_agent_in_thread(agent: Agent, query: str, max_turns: int = 25) -> Any:
    """
    Run an agent in a separate thread with its own event loop.

    If the agent hits MaxTurnsExceeded, partial work is captured and
    a partial result is returned instead of raising an exception.

    Returns:
        The agent result, or a partial work summary dict if max_turns was exceeded
    """
    result_holder = {"result": None, "error": None, "partial": False}
    agent_name = getattr(agent, "name", "unknown")

    def run_in_new_loop():
        try:
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)

            try:
                result = new_loop.run_until_complete(
                    Runner.run(agent, query, max_turns=max_turns)
                )
                result_holder["result"] = result
            except MaxTurnsExceeded as e:
                logger.warning(
                    f"Sub-agent {agent_name} exceeded max turns ({max_turns})"
                )
                result_holder["result"] = {
                    "status": "incomplete",
                    "message": f"Investigation exceeded {max_turns} turns",
                    "partial_messages": (
                        e.partial_messages[-5:] if e.partial_messages else []
                    ),
                }
                result_holder["partial"] = True
            finally:
                new_loop.close()
        except Exception as e:
            result_holder["error"] = e

    thread = threading.Thread(target=run_in_new_loop)
    thread.start()
    thread.join(timeout=300)  # 5 minute timeout

    if thread.is_alive():
        raise TimeoutError(f"Agent {agent_name} execution timed out")

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
            JSON with the agent's findings and recommendations.
            If max turns exceeded, returns partial findings with status="incomplete"
        """
        try:
            result = _run_agent_in_thread(agent, query, max_turns)
            # Check if result is a partial work summary
            if isinstance(result, dict) and result.get("status") == "incomplete":
                return json.dumps(result)
            if hasattr(result, "final_output"):
                if hasattr(result.final_output, "model_dump_json"):
                    return result.final_output.model_dump_json()
                return json.dumps({"result": str(result.final_output)})
            return json.dumps({"result": str(result)})
        except Exception as e:
            return json.dumps({"error": str(e), "agent": f"{agent_id}_agent"})

    # Rename the tool based on agent
    call_agent.__name__ = f"call_{agent_id.replace('-', '_')}_agent"
    call_agent.__doc__ = f"""
    Call the {agent.name} to investigate.

    This agent specializes in: {agent_id}

    Send a natural language query describing what you need investigated.
    The agent will use its tools and return findings.

    Args:
        query: Natural language investigation request

    Returns:
        JSON with findings, recommendations, and confidence.
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
        logger.error(f"Circular dependency detected: {missing}")
        # Still return what we could build
        result.extend(missing)

    return result


def build_agent_hierarchy(
    effective_config: dict[str, Any],
    team_config: Optional[Any] = None,
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

    # Load remote A2A agents (if integration available)
    remote_agents: dict[str, Callable] = {}
    if team_config:
        try:
            from ..integrations.a2a import get_remote_agents_for_team

            remote_agents = get_remote_agents_for_team(team_config)
            logger.info(f"Loaded {len(remote_agents)} remote agents")
        except ImportError:
            logger.debug("A2A integration not available")
        except Exception as e:
            logger.warning(f"Failed to load remote agents: {e}")

    # Topologically sort agents (dependencies first)
    build_order = _topological_sort_agents(agents_config)
    logger.info(f"Agent build order: {build_order}")

    # Build agents in dependency order
    for agent_id in build_order:
        config = agents_config.get(agent_id, {})
        if not config.get("enabled", True):
            logger.debug(f"Skipping disabled agent: {agent_id}")
            continue

        agent = build_agent_from_config(
            agent_id,
            effective_config,
            parent_agents=built_agents,
            remote_agents=remote_agents,
        )
        if agent:
            built_agents[agent_id] = agent

    logger.info(
        f"Built {len(built_agents)} agents (local) + {len(remote_agents)} (remote)"
    )
    return built_agents


def get_planner_agent(
    effective_config: dict[str, Any],
    team_config: Optional[Any] = None,
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
        # Valid model patterns for LiteLLM
        valid_patterns = (
            # Anthropic
            "anthropic/",
            "claude-",
            "sonnet",
            "opus",
            "haiku",
            # OpenAI
            "openai/",
            "gpt-",
            "o1",
            "o3",
            "o4",
            # Google
            "gemini/",
            "gemini-",
            "google/",
        )
        if not any(model_name.startswith(p) or model_name == p for p in valid_patterns):
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


# =============================================================================
# Generic Agent Creation (from config JSON)
# =============================================================================


def create_generic_agent_from_config(
    agent_config: dict[str, Any],
    available_tools: dict[str, Callable] | None = None,
) -> Agent:
    """
    Create an agent from a generic JSON config.

    This is the entry point for config-driven agent creation.

    Args:
        agent_config: Agent configuration with structure:
            {
                "name": "Agent Name",
                "description": "What this agent does",
                "model": "sonnet" | "opus" | "gpt-5.2" | ...,
                "prompt": "System instructions...",
                "tools": ["tool1", "tool2"] | {"tool1": true, "tool2": false},
                "max_turns": 20,
                "temperature": 0.4
            }
        available_tools: Optional dict of tool_name → tool_function

    Returns:
        Configured Agent instance
    """
    name = agent_config.get("name", "Agent")
    prompt = agent_config.get("prompt", agent_config.get("instructions", ""))
    model = agent_config.get("model", "sonnet")
    max_turns = agent_config.get("max_turns", 20)

    # Resolve model name
    normalized_model = normalize_model_name(model)

    # Create model settings
    model_settings = create_model_settings(
        model_name=model,
        temperature=agent_config.get("temperature"),
        max_tokens=agent_config.get("max_tokens"),
    )

    # Resolve tools
    tools_config = agent_config.get("tools", [])
    tools: list[Callable] = []

    if available_tools:
        if isinstance(tools_config, list):
            # List of tool names to enable
            for tool_name in tools_config:
                if tool_name in available_tools:
                    tools.append(available_tools[tool_name])
        elif isinstance(tools_config, dict):
            # Dict of tool_name → enabled
            for tool_name, enabled in tools_config.items():
                if enabled and tool_name in available_tools:
                    tools.append(available_tools[tool_name])

    return Agent(
        name=name,
        instructions=prompt,
        model=normalized_model,
        model_settings=model_settings,
        tools=tools,
    )
