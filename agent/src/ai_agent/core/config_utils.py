"""
Configuration Utilities

Shared utilities for parsing agent configuration, particularly
the sub_agents field which can be in multiple formats.
"""

from __future__ import annotations

from typing import Any

from .logging import get_logger

logger = get_logger(__name__)


def parse_sub_agents_config(
    sub_agents_config: Any,
    defaults: list[str],
) -> list[str]:
    """
    Parse sub_agents configuration from various formats.

    The sub_agents field can be specified in multiple formats:
    - List: ["agent1", "agent2", "agent3"]
    - Dict with enabled flags: {agent1: {enabled: true}, agent2: {enabled: false}}
    - Dict with bool values: {agent1: true, agent2: false}

    Args:
        sub_agents_config: The sub_agents configuration value (list, dict, or object)
        defaults: Default list of agents to return if config is invalid/empty

    Returns:
        List of enabled agent names
    """
    if sub_agents_config is None:
        return defaults.copy()

    # List format: ["agent1", "agent2"]
    if isinstance(sub_agents_config, list):
        return list(sub_agents_config)

    # Dict format: {agent1: {enabled: true}, agent2: false}
    if isinstance(sub_agents_config, dict):
        enabled = []
        for name, cfg in sub_agents_config.items():
            if isinstance(cfg, dict):
                # {agent1: {enabled: true, ...}}
                if cfg.get("enabled", True):
                    enabled.append(name)
            elif isinstance(cfg, bool):
                # {agent1: true, agent2: false}
                if cfg:
                    enabled.append(name)
            elif hasattr(cfg, "enabled"):
                # Object with enabled attribute
                if cfg.enabled:
                    enabled.append(name)
            else:
                # Unknown format - default to enabled
                enabled.append(name)
        return enabled if enabled else defaults.copy()

    return defaults.copy()


def get_agent_sub_agents(
    team_cfg: Any,
    agent_name: str,
    defaults: list[str],
) -> list[str]:
    """
    Get the list of enabled sub-agents for a specific agent from team config.

    This handles the common pattern of:
    1. Getting the agent's config from team_cfg
    2. Reading the sub_agents field
    3. Parsing it in various formats
    4. Falling back to defaults if not found

    Args:
        team_cfg: Team configuration object (dict or object with get_agent_config)
        agent_name: Name of the agent (e.g., "planner", "investigation")
        defaults: Default list of sub-agents to return if not configured

    Returns:
        List of enabled sub-agent names
    """
    if not team_cfg:
        return defaults.copy()

    try:
        # Get the agent's config from team config
        agent_cfg = None
        if hasattr(team_cfg, "get_agent_config"):
            agent_cfg = team_cfg.get_agent_config(agent_name)
        elif isinstance(team_cfg, dict):
            agents = team_cfg.get("agents", {})
            agent_cfg = agents.get(agent_name, {})

        if not agent_cfg:
            return defaults.copy()

        # Get sub_agents from the agent config
        sub_agents_config = None
        if hasattr(agent_cfg, "sub_agents"):
            sub_agents_config = agent_cfg.sub_agents
        elif isinstance(agent_cfg, dict):
            sub_agents_config = agent_cfg.get("sub_agents", None)

        if sub_agents_config is None:
            return defaults.copy()

        return parse_sub_agents_config(sub_agents_config, defaults)

    except Exception as e:
        logger.warning(
            "failed_to_get_sub_agents",
            agent=agent_name,
            error=str(e),
        )
        return defaults.copy()
