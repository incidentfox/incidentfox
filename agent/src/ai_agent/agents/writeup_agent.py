"""Incident writeup and postmortem generation agent."""

from agents import Agent
from pydantic import BaseModel, Field

from ..core.agent_builder import create_model_settings
from ..core.config import get_config
from ..core.logging import get_logger
from ..prompts.default_prompts import get_default_agent_prompt
from ..tools.agent_tools import ask_human, llm_call, web_search
from ..tools.thinking import think
from .base import TaskContext

logger = get_logger(__name__)


# =============================================================================
# Output Models
# =============================================================================


class ActionItem(BaseModel):
    """An action item from the postmortem."""

    description: str = Field(description="What needs to be done")
    owner: str = Field(default="TBD", description="Who is responsible")
    priority: str = Field(
        default="medium", description="Priority: critical, high, medium, low"
    )
    due_date: str = Field(default="TBD", description="When it should be completed")
    status: str = Field(
        default="open", description="Status: open, in_progress, completed"
    )


class PostmortemDocument(BaseModel):
    """Postmortem document structure."""

    title: str = Field(description="Incident title")
    severity: str = Field(
        default="", description="Incident severity (SEV1, SEV2, etc.)"
    )
    duration: str = Field(default="", description="How long the incident lasted")

    summary: str = Field(description="Executive summary (2-3 sentences)")

    impact: str = Field(description="Impact description - users, business, technical")

    timeline: list[str] = Field(
        default_factory=list,
        description="Timeline of events with timestamps",
    )

    root_cause: str = Field(description="Root cause analysis")
    contributing_factors: list[str] = Field(
        default_factory=list, description="Contributing factors"
    )

    detection: str = Field(default="", description="How was the incident detected?")
    resolution: str = Field(default="", description="How was the incident resolved?")

    action_items: list[ActionItem] = Field(
        default_factory=list, description="Action items with owners"
    )

    lessons_learned: list[str] = Field(
        default_factory=list, description="Lessons learned"
    )

    what_went_well: list[str] = Field(
        default_factory=list, description="What went well during the incident"
    )


# =============================================================================
# System Prompt (loaded from 01_slack template at runtime)
# =============================================================================


# =============================================================================
# Agent Factory
# =============================================================================


def create_writeup_agent(
    team_config=None,
    is_subagent: bool = False,
    is_master: bool = False,
) -> Agent[TaskContext]:
    """
    Create incident writeup and postmortem generation agent.

    This agent specializes in generating well-structured incident documentation
    based on investigation findings.

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
                   Can also be set via team config: agents.writeup.is_master: true
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
        try:
            agent_config = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_config = team_cfg.get_agent_config("writeup")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_config = agents.get("writeup")

            if agent_config:
                if hasattr(agent_config, "get_system_prompt"):
                    custom_prompt = agent_config.get_system_prompt()
                elif isinstance(agent_config, dict) and agent_config.get("prompt"):
                    prompt_cfg = agent_config["prompt"]
                    if isinstance(prompt_cfg, str):
                        custom_prompt = prompt_cfg
                    elif isinstance(prompt_cfg, dict):
                        custom_prompt = prompt_cfg.get("system")

                if custom_prompt:
                    logger.info(
                        "using_custom_writeup_prompt", prompt_length=len(custom_prompt)
                    )
        except Exception:
            pass

    # Get base prompt from 01_slack template (single source of truth)
    base_prompt = custom_prompt or get_default_agent_prompt("writeup")

    # Build final system prompt with role-based sections
    system_prompt = apply_role_based_prompt(
        base_prompt=base_prompt,
        agent_name="writeup",
        team_config=team_cfg,
        is_subagent=is_subagent,
        is_master=is_master,
    )

    # Writeup agent has minimal tools - mostly synthesis
    tools = [think, llm_call, web_search, ask_human]
    logger.info("writeup_agent_tools_loaded", count=len(tools))

    # Add tool-specific guidance to the system prompt
    tool_guidance = build_tool_guidance(tools)
    if tool_guidance:
        system_prompt = system_prompt + "\n\n" + tool_guidance

    # Add shared sections (error handling, tool limits, evidence format)
    shared_sections = build_agent_prompt_sections(
        integration_name="coding",  # Writeup is similar to coding - no specific integration
        is_subagent=is_subagent,
        include_error_handling=True,
        include_tool_limits=True,
        include_evidence_format=False,  # Writeup doesn't need evidence format
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    # Get model settings from team config if available
    model_name = config.openai.model
    temperature = 0.5  # Slightly higher for creative writing
    max_tokens = config.openai.max_tokens
    reasoning = None
    verbosity = None

    if team_cfg:
        try:
            agent_config = None
            if hasattr(team_cfg, "get_agent_config"):
                agent_config = team_cfg.get_agent_config("writeup")
            elif isinstance(team_cfg, dict):
                agents = team_cfg.get("agents", {})
                agent_config = agents.get("writeup")

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
                        agent="writeup",
                        model=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        reasoning=reasoning,
                        verbosity=verbosity,
                    )
        except Exception:
            pass

    return Agent[TaskContext](
        name="WriteupAgent",
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
        # Removed output_type=PostmortemDocument to allow flexible XML-based output format
        # defined in system prompt. This enables hot-reloadable output schema via config.
    )
