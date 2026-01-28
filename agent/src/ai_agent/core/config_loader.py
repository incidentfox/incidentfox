"""
Configuration Loader

Loads team-specific configuration from the Config Service
and provides it to the agent builder.
"""

from __future__ import annotations

import os
from typing import Any

from .logging import get_logger

logger = get_logger(__name__)

# Use same default as agent_runner.py for k8s service discovery
CONFIG_SERVICE_URL = os.getenv(
    "CONFIG_SERVICE_URL", "http://incidentfox-config-service:8080"
)


def fetch_team_config(
    org_id: str,
    team_node_id: str,
) -> dict[str, Any]:
    """
    Fetch the effective configuration for a team from the Config Service.

    Args:
        org_id: Organization ID
        team_node_id: Team node ID

    Returns:
        The effective (merged) configuration
    """
    try:
        import httpx
    except ImportError:
        logger.warning("httpx_not_available_using_defaults")
        from .hierarchical_config_defaults import get_full_default_config

        return get_full_default_config()

    try:
        url = f"{CONFIG_SERVICE_URL}/api/v1/config/orgs/{org_id}/nodes/{team_node_id}/effective"

        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)

            if response.status_code == 200:
                data = response.json()
                logger.info(
                    "team_config_fetched", org_id=org_id, team_node_id=team_node_id
                )
                return data.get("effective_config", {})
            else:
                logger.warning(
                    "config_fetch_failed",
                    status=response.status_code,
                    org_id=org_id,
                    team_node_id=team_node_id,
                )
    except Exception as e:
        logger.warning("config_fetch_error", error=str(e))

    # Fallback to defaults
    logger.info("using_default_config")

    # Return inline defaults to avoid import issues
    return _get_inline_defaults()


def _get_inline_defaults() -> dict[str, Any]:
    """Inline defaults to avoid circular imports."""
    return {
        "agents": {
            "planner": {
                "enabled": True,
                "name": "Planner",
                "model": {"name": "gpt-4o", "temperature": 0.3},
                "prompt": {"system": "", "prefix": "", "suffix": ""},
                "max_turns": 30,
                "tools": {
                    "enabled": ["think", "llm_call", "web_search"],
                    "disabled": [],
                },
                "sub_agents": ["investigation", "k8s", "aws", "metrics", "coding"],
            },
            "investigation": {
                "enabled": True,
                "name": "Investigation Agent",
                "model": {"name": "gpt-4o", "temperature": 0.4},
                "prompt": {"system": ""},
                "max_turns": 20,
                "tools": {"enabled": ["*"], "disabled": []},
                "sub_agents": [],
            },
            "k8s": {
                "enabled": True,
                "name": "Kubernetes Agent",
                "model": {"name": "gpt-4o", "temperature": 0.3},
                "prompt": {"system": ""},
                "max_turns": 15,
                "tools": {"enabled": ["*"], "disabled": []},
                "sub_agents": [],
            },
            "aws": {
                "enabled": True,
                "name": "AWS Agent",
                "model": {"name": "gpt-4o", "temperature": 0.3},
                "prompt": {"system": ""},
                "max_turns": 15,
                "tools": {"enabled": ["*"], "disabled": []},
                "sub_agents": [],
            },
            "metrics": {
                "enabled": True,
                "name": "Metrics Agent",
                "model": {"name": "gpt-4o", "temperature": 0.2},
                "prompt": {"system": ""},
                "max_turns": 15,
                "tools": {"enabled": ["*"], "disabled": []},
                "sub_agents": [],
            },
            "coding": {
                "enabled": True,
                "name": "Coding Agent",
                "model": {"name": "gpt-4o", "temperature": 0.4},
                "prompt": {"system": ""},
                "max_turns": 20,
                "tools": {"enabled": ["*"], "disabled": []},
                "sub_agents": [],
            },
        },
        "tools": {},
        "mcps": {"default": [], "team_added": [], "disabled": []},
        "integrations": {},
        "runtime": {
            "max_concurrent_agents": 5,
            "default_timeout_seconds": 300,
        },
    }


def validate_team_config(
    org_id: str,
    team_node_id: str,
) -> dict[str, Any]:
    """
    Validate team configuration and return any issues.

    Returns:
        {
            'valid': bool,
            'missing_required': [...],
            'errors': [...]
        }
    """
    try:
        import httpx
    except ImportError:
        return {"valid": True, "missing_required": [], "errors": []}

    try:
        url = f"{CONFIG_SERVICE_URL}/api/v1/config/orgs/{org_id}/nodes/{team_node_id}/validate"

        with httpx.Client(timeout=10.0) as client:
            response = client.post(url)

            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.warning("config_validation_error", error=str(e))

    return {"valid": True, "missing_required": [], "errors": []}


class ConfigContext:
    """
    Context manager for team-specific configuration.

    Usage:
        async with ConfigContext(org_id, team_node_id) as config:
            planner = get_planner_agent(config)
            result = await Runner.run(planner, query)
    """

    def __init__(self, org_id: str, team_node_id: str):
        self.org_id = org_id
        self.team_node_id = team_node_id
        self.config: dict[str, Any] | None = None

    async def __aenter__(self) -> dict[str, Any]:
        self.config = fetch_team_config(self.org_id, self.team_node_id)
        return self.config

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def __enter__(self) -> dict[str, Any]:
        self.config = fetch_team_config(self.org_id, self.team_node_id)
        return self.config

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


# =============================================================================
# Convenience Functions
# =============================================================================


def get_agent_for_team(
    agent_id: str,
    org_id: str,
    team_node_id: str,
    team_config=None,
):
    """
    Get a specific agent configured for a team.

    This is the main entry point for running agents with team config.

    Args:
        agent_id: Agent identifier
        org_id: Organization ID
        team_node_id: Team node ID
        team_config: Optional pre-loaded team config object

    Returns:
        Agent or None
    """
    from .agent_builder import build_agent_hierarchy

    config = fetch_team_config(org_id, team_node_id)
    agents = build_agent_hierarchy(config, team_config=team_config)

    return agents.get(agent_id)


def get_planner_for_team(org_id: str, team_node_id: str, team_config=None):
    """Get the planner agent for a team."""
    return get_agent_for_team("planner", org_id, team_node_id, team_config=team_config)
