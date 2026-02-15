"""
Agent hierarchy builder for sre-agent.

Provides topological sorting for nested agent dependencies.
Ported from unified-agent/src/unified_agent/core/agent_builder.py
"""

import logging
from typing import Any

from config import AgentConfig

logger = logging.getLogger(__name__)


def _get_sub_agent_ids(agent_config: AgentConfig) -> list[str]:
    """
    Extract sub-agent IDs from agent config.

    Args:
        agent_config: AgentConfig with sub_agents dict

    Returns:
        List of enabled sub-agent IDs
    """
    if not agent_config.sub_agents:
        return []

    # sub_agents is dict[str, bool] where key=agent_id, value=enabled
    return [agent_id for agent_id, enabled in agent_config.sub_agents.items() if enabled]


def topological_sort_agents(agents_config: dict[str, AgentConfig]) -> list[str]:
    """
    Topologically sort agents so dependencies (sub_agents) are built first.

    Uses Kahn's algorithm to handle nested orchestrators correctly.
    Example build order:
    - Leaf agents first: github, k8s, aws, metrics, log_analysis
    - Then orchestrator: investigation (uses leaf agents)
    - Finally: planner (uses investigation)

    Args:
        agents_config: Dict mapping agent_id to AgentConfig

    Returns:
        List of agent_ids in build order (dependencies first)

    Raises:
        ValueError: If circular dependency detected
    """
    # Only process enabled agents
    enabled_agents = {
        agent_id: config
        for agent_id, config in agents_config.items()
        if config.enabled
    }

    # Build dependency graph
    # dependencies[agent_id] = set of agent_ids this agent depends on
    dependencies: dict[str, set[str]] = {}
    for agent_id, config in enabled_agents.items():
        sub_agent_ids = _get_sub_agent_ids(config)
        # Only include dependencies that exist in our enabled agents
        dependencies[agent_id] = {
            sid for sid in sub_agent_ids if sid in enabled_agents
        }

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
    if len(result) != len(enabled_agents):
        missing = set(enabled_agents.keys()) - set(result)
        error_msg = f"Circular dependency detected in agent configuration: {missing}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    return result


def validate_agent_dependencies(agents_config: dict[str, AgentConfig]) -> list[str]:
    """
    Validate that all sub_agent dependencies exist and are enabled.

    Args:
        agents_config: Dict mapping agent_id to AgentConfig

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    for agent_id, config in agents_config.items():
        if not config.enabled:
            continue

        sub_agent_ids = _get_sub_agent_ids(config)
        for sub_id in sub_agent_ids:
            # Check if sub-agent exists
            if sub_id not in agents_config:
                errors.append(
                    f"Agent '{agent_id}' depends on '{sub_id}' which does not exist"
                )
                continue

            # Check if sub-agent is enabled
            if not agents_config[sub_id].enabled:
                errors.append(
                    f"Agent '{agent_id}' depends on '{sub_id}' which is disabled"
                )

    return errors
