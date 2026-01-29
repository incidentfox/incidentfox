"""Kubernetes troubleshooting and operations agent."""

from agents import Agent, Tool, function_tool
from pydantic import BaseModel, Field

from ..core.agent_builder import create_model_settings
from ..core.config import get_config
from ..core.logging import get_logger
from ..prompts.default_prompts import get_default_agent_prompt
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.kubernetes import (
    describe_deployment,
    describe_pod,
    describe_service,
    get_deployment_history,
    get_pod_events,
    get_pod_logs,
    get_pod_resource_usage,
    get_pod_resources,
    list_namespaces,
    list_pods,
)
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


def _load_k8s_tools():
    """Load K8s and container-related tools."""
    # Core K8s tools
    tools = [
        think,
        llm_call,
        web_search,
        ask_human,
        # Cluster tools
        list_namespaces,
        # Pod tools
        get_pod_logs,
        describe_pod,
        list_pods,
        get_pod_events,
        get_pod_resource_usage,
        get_pod_resources,
        # Deployment tools
        describe_deployment,
        get_deployment_history,
        # Service tools
        describe_service,
    ]

    # Docker tools for container-level debugging
    try:
        from ..tools.docker_tools import (
            docker_exec,
            docker_inspect,
            docker_logs,
            docker_ps,
            docker_stats,
        )

        tools.extend(
            [
                docker_ps,
                docker_logs,
                docker_inspect,
                docker_exec,
                docker_stats,
            ]
        )
        logger.debug("docker_tools_added_to_k8s_agent")
    except Exception as e:
        logger.warning("docker_tools_load_failed", error=str(e))

    # Wrap plain functions into Tool objects for SDK compatibility
    wrapped = []
    for t in tools:
        if isinstance(t, Tool) or hasattr(t, "name"):
            wrapped.append(t)
        else:
            try:
                wrapped.append(function_tool(t, strict_mode=False))
            except TypeError:
                wrapped.append(function_tool(t))
            except Exception as e:
                logger.warning(
                    "tool_wrap_failed",
                    tool=getattr(t, "__name__", str(t)),
                    error=str(e),
                )
                wrapped.append(t)
    return wrapped


class K8sAnalysis(BaseModel):
    """Kubernetes analysis result."""

    summary: str = Field(description="Summary of findings")
    pod_status: str = Field(description="Current pod status")
    issues_found: list[str] = Field(description="List of issues identified")
    recommendations: list[str] = Field(description="Recommended actions")
    requires_manual_intervention: bool = Field(default=False)
    resource_metrics: dict | None = Field(
        default=None,
        description="Resource metrics data if queried (CPU/memory usage, requests, limits)",
    )


def create_k8s_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create Kubernetes expert agent.

    The agent's role can be configured dynamically:
    - As entrance agent: default (no special guidance)
    - As sub-agent: is_subagent=True (adds response guidance for concise output)
    - As master agent: is_master=True or via team config (adds delegation guidance)

    Args:
        team_config: Team configuration for customization
        is_subagent: If True, agent is being called by another agent.
                     This adds guidance for concise, caller-focused responses.
        is_master: If True, agent can delegate to other agents.
                   This adds guidance for effective delegation.
                   Can also be set via team config: agents.k8s.is_master: true
    """
    from ..prompts.layers import apply_role_based_prompt, build_agent_prompt_sections

    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Check if team has custom prompt
    custom_prompt = None
    if team_cfg:
        agent_config = team_cfg.get_agent_config("k8s")
        if agent_config.prompt:
            custom_prompt = agent_config.get_system_prompt()
            if custom_prompt:
                logger.info("using_custom_k8s_prompt", prompt_length=len(custom_prompt))

    # Get base prompt from 01_slack template (single source of truth)
    base_prompt = custom_prompt or get_default_agent_prompt("k8s")

    # Build final system prompt with role-based sections
    # This handles is_subagent, is_master, and team config settings dynamically
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="k8s",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    # Load all K8s and Docker tools
    tools = _load_k8s_tools()
    logger.info("k8s_agent_tools_loaded", count=len(tools))

    # Add shared sections (K8s already has detailed error handling in base prompt,
    # so we add tool limits and evidence format for consistency)
    shared_sections = build_agent_prompt_sections(
        integration_name="kubernetes",
        is_subagent=is_subagent,
        include_error_handling=False,  # Already has comprehensive error handling
        include_tool_limits=True,
        include_evidence_format=True,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.3
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

    if team_cfg:
        agent_config = team_cfg.get_agent_config("k8s")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            reasoning = getattr(agent_config.model, "reasoning", None)
            verbosity = getattr(agent_config.model, "verbosity", None)
            logger.info(
                "using_team_model_config",
                agent="k8s",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=reasoning,
                verbosity=verbosity,
            )

    return Agent[TaskContext](
        name="K8sAgent",
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
        # Note: Removed output_type=K8sAnalysis to allow flexible responses
        # that include actual resource data (CPU/memory numbers) from tools.
        # Strict JSON schema doesn't support dict types needed for metrics.
    )
