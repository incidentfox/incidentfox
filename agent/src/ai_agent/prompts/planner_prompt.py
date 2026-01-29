"""
Planner Agent System Prompt Builder.

This module builds the planner system prompt following the standard agent pattern:

    base_prompt = custom_prompt or DEFAULT_PLANNER_PROMPT
    system_prompt = base_prompt
    system_prompt += build_capabilities_section(...)  # Dynamic capabilities
    system_prompt = apply_role_based_prompt(...)      # Role sections
    system_prompt += build_agent_prompt_sections(...) # Shared sections

Context (runtime metadata, team config) is now passed in the user message,
not the system prompt. This allows context to flow naturally to sub-agents.

NOTE: The custom_prompt from team config / templates is the source of truth.
DEFAULT_PLANNER_PROMPT is only used as a fallback when no template is configured.
"""

from typing import Any

from .agent_capabilities import AGENT_CAPABILITIES, get_enabled_agent_keys
from .layers import (
    apply_role_based_prompt,
    build_agent_prompt_sections,
    build_capabilities_section,
)

# =============================================================================
# Default Planner Prompt (Fallback)
# =============================================================================
# This is a minimal fallback prompt used ONLY when no template custom prompt
# is configured. In production, templates define the planner prompt.
#
# Behavioral principles, error handling, tool limits, evidence format, and
# transparency are added via build_agent_prompt_sections() from layers.py.

DEFAULT_PLANNER_PROMPT = """You are an expert AI SRE (Site Reliability Engineer) responsible for investigating incidents, diagnosing issues, and providing actionable recommendations.

## YOUR ROLE

You are the primary orchestrator for incident investigation. Your responsibilities:

1. **Understand the problem** - Analyze the issue, clarify scope, identify affected systems
2. **Investigate systematically** - Delegate to specialized agents, gather evidence, correlate findings
3. **Synthesize insights** - Combine findings from multiple sources into a coherent diagnosis
4. **Provide actionable recommendations** - Give specific, prioritized next steps

You are NOT a simple router. You are an expert who thinks before acting, asks clarifying questions when needed, and provides confident conclusions backed by evidence.

## REASONING FRAMEWORK

For every investigation:

1. **UNDERSTAND**: What's the problem? What systems? What's the business impact? When did it start?
2. **HYPOTHESIZE**: Top 3 likely causes? What evidence confirms/rules out each?
3. **INVESTIGATE**: Delegate to agents, start with most likely hypothesis, pivot if needed
4. **SYNTHESIZE**: Combine findings, build timeline, identify root cause
5. **RECOMMEND**: Immediate actions, prevention, who to notify

## DELEGATION RULES

- Delegate with GOALS, not commands - tell agents WHAT you need, not HOW to find it
- Provide context: symptoms, timing, findings from other agents
- Don't repeat: never call same agent twice for same question
- Trust specialists: agents are domain experts
- Parallelize when independent

Remember: You are an expert SRE. Think systematically, investigate thoroughly, provide actionable insights.
"""


def build_planner_system_prompt(
    # Capabilities
    enabled_agents: list[str] | None = None,
    agent_capabilities: dict[str, dict[str, Any]] | None = None,
    remote_agents: dict[str, dict[str, Any]] | None = None,
    # Team config (for custom prompt override)
    team_config: dict[str, Any] | None = None,
    # Custom prompt override
    custom_prompt: str | None = None,
) -> str:
    """
    Build the planner system prompt following the standard agent pattern.

    Pattern:
        base_prompt = custom_prompt or DEFAULT_PLANNER_PROMPT
        system_prompt = base_prompt + capabilities
        system_prompt = apply_role_based_prompt(...)  # Add delegation guidance
        system_prompt += shared_sections (behavioral principles, error handling, etc.)

    NOTE: Runtime metadata and contextual info are now passed in the user message,
    not the system prompt. Use build_user_context() to build the user message context.

    Args:
        enabled_agents: List of agent keys to include in capabilities
        agent_capabilities: Custom capability descriptors (uses defaults if not provided)
        remote_agents: Dict of remote A2A agent configs
        team_config: Team configuration dict (used for custom prompt override)
        custom_prompt: Custom base prompt to use instead of DEFAULT_PLANNER_PROMPT

    Returns:
        Complete system prompt string
    """
    # Get enabled agents from team config if not provided
    if enabled_agents is None:
        enabled_agents = get_enabled_agent_keys(team_config)

    if agent_capabilities is None:
        agent_capabilities = AGENT_CAPABILITIES

    # 1. Base prompt (can be overridden from config or parameter)
    # Template custom prompt is the source of truth; DEFAULT_PLANNER_PROMPT is fallback
    if custom_prompt:
        base_prompt = custom_prompt
    elif team_config:
        # Check for custom prompt in team config
        # Config structure: agents.planner.prompt.system (string) or agents.planner.prompt (string)
        planner_config = team_config.get("agents", {}).get("planner", {})
        config_prompt = None
        prompt_cfg = planner_config.get("prompt")
        if isinstance(prompt_cfg, str) and prompt_cfg:
            config_prompt = prompt_cfg
        elif isinstance(prompt_cfg, dict):
            config_prompt = prompt_cfg.get("system")
        base_prompt = config_prompt if config_prompt else DEFAULT_PLANNER_PROMPT
    else:
        base_prompt = DEFAULT_PLANNER_PROMPT

    # 2. Capabilities section (dynamic based on enabled agents)
    capabilities = build_capabilities_section(
        enabled_agents=enabled_agents,
        agent_capabilities=agent_capabilities,
        remote_agents=remote_agents,
    )
    system_prompt = base_prompt + "\n\n" + capabilities

    # 3. Role-based sections (planner is always a master, never a subagent)
    system_prompt = apply_role_based_prompt(
        base_prompt=system_prompt,
        agent_name="planner",
        team_config=team_config,
        is_subagent=False,
        is_master=True,
    )

    # 4. Shared sections (error handling, tool limits, evidence format)
    shared_sections = build_agent_prompt_sections(
        integration_name="planner",
        is_subagent=False,
        include_error_handling=True,
        include_tool_limits=True,
        include_evidence_format=True,
    )
    system_prompt = system_prompt + "\n\n" + shared_sections

    return system_prompt


def build_planner_system_prompt_from_team_config(
    team_config: Any,
    remote_agents: dict[str, dict[str, Any]] | None = None,
) -> str:
    """
    Build planner system prompt from a TeamLevelConfig object.

    This is a convenience wrapper that extracts the relevant fields from
    a TeamLevelConfig object and passes them to build_planner_system_prompt.

    NOTE: Runtime metadata and contextual info are now passed in the user message.
    Use build_user_context() to build the user message context.

    Args:
        team_config: TeamLevelConfig object from config service
        remote_agents: Dict of remote A2A agent configs

    Returns:
        Complete system prompt string
    """
    # Convert team config to dict if needed
    config_dict = {}

    if team_config:
        if isinstance(team_config, dict):
            config_dict = team_config
        elif hasattr(team_config, "__dict__"):
            # Extract relevant fields from config object
            config_dict = {}

            # Check for agents config
            if hasattr(team_config, "agents"):
                agents = team_config.agents
                if isinstance(agents, dict):
                    config_dict["agents"] = agents
                elif hasattr(agents, "__dict__"):
                    config_dict["agents"] = {
                        k: v
                        for k, v in agents.__dict__.items()
                        if not k.startswith("_")
                    }

            # Check for planner-specific config
            if hasattr(team_config, "get_agent_config"):
                planner_config = team_config.get_agent_config("planner")
                if planner_config:
                    if "agents" not in config_dict:
                        config_dict["agents"] = {}
                    if hasattr(planner_config, "__dict__"):
                        config_dict["agents"]["planner"] = {
                            k: v
                            for k, v in planner_config.__dict__.items()
                            if not k.startswith("_")
                        }
                    elif isinstance(planner_config, dict):
                        config_dict["agents"]["planner"] = planner_config

    return build_planner_system_prompt(
        remote_agents=remote_agents,
        team_config=config_dict,
    )
