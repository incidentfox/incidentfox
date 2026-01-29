"""AWS resource management and debugging agent."""

from agents import Agent
from pydantic import BaseModel, Field

from ..core.agent_builder import create_model_settings
from ..core.config import get_config
from ..core.logging import get_logger
from ..prompts.default_prompts import get_default_agent_prompt
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.aws_tools import (
    describe_ec2_instance,
    describe_lambda_function,
    get_cloudwatch_logs,
    get_cloudwatch_metrics,
    get_rds_instance_status,
    list_ecs_tasks,
    query_cloudwatch_insights,
)
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


class AWSAnalysis(BaseModel):
    """AWS analysis result."""

    summary: str = Field(description="Summary of findings")
    resource_status: str = Field(description="Current resource status")
    issues_found: list[str] = Field(description="Issues identified")
    recommendations: list[str] = Field(description="Recommended actions")
    estimated_cost_impact: str | None = Field(default=None)


def create_aws_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create AWS expert agent.

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
                   Can also be set via team config: agents.aws.is_master: true
    """
    from ..prompts.layers import (
        apply_role_based_prompt,
        build_agent_prompt_sections,
        build_tool_guidance,
    )

    config = get_config()
    team_cfg = team_config if team_config is not None else config.team_config

    # Check if team has custom prompt
    custom_prompt = None
    if team_cfg:
        agent_config = team_cfg.get_agent_config("aws")
        if agent_config.prompt:
            custom_prompt = agent_config.get_system_prompt()
            if custom_prompt:
                logger.info("using_custom_aws_prompt", prompt_length=len(custom_prompt))

    # Get base prompt from 01_slack template (single source of truth)
    base_prompt = custom_prompt or get_default_agent_prompt("aws")

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="aws",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    tools = [
        think,
        llm_call,
        web_search,
        ask_human,
        # Resource inspection
        describe_ec2_instance,
        describe_lambda_function,
        get_rds_instance_status,
        list_ecs_tasks,
        # Logging and monitoring
        get_cloudwatch_logs,
        query_cloudwatch_insights,
        get_cloudwatch_metrics,
    ]

    logger.info("aws_agent_tools_loaded", count=len(tools))

    # Add tool-specific guidance to the system prompt
    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Add shared sections (error handling, tool limits, evidence format)
    # Uses predefined AWS_ERRORS from registry
    shared_sections = build_agent_prompt_sections(
        integration_name="aws",
        is_subagent=is_subagent,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.3
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

    if team_cfg:
        agent_config = team_cfg.get_agent_config("aws")
        if agent_config.model:
            model_name = agent_config.model.name
            temperature = agent_config.model.temperature
            max_tokens = agent_config.model.max_tokens
            reasoning = getattr(agent_config.model, "reasoning", None)
            verbosity = getattr(agent_config.model, "verbosity", None)
            logger.info(
                "using_team_model_config",
                agent="aws",
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=reasoning,
                verbosity=verbosity,
            )

    return Agent[TaskContext](
        name="AWSAgent",
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
        # Removed output_type=AWSAnalysis to allow flexible XML-based output format
        # defined in system prompt. This enables hot-reloadable output schema via config.
    )
