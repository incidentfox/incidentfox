"""
Team configuration loader for sre-agent.

Fetches team-specific config (system prompts, tools, subagents) from the
config_service at sandbox startup. This enables per-team customization of
agent behavior without rebuilding the image.

Auth priority:
1. TEAM_TOKEN env var → Bearer token auth (resolves correct org/team via routing)
2. INCIDENTFOX_TENANT_ID + INCIDENTFOX_TEAM_ID → X-Org-Id/X-Team-Node-Id headers
"""

import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

CONFIG_SERVICE_URL = os.getenv(
    "CONFIG_SERVICE_URL",
    "http://incidentfox-config-service.incidentfox.svc.cluster.local:8080",
)


@dataclass
class PromptConfig:
    system: str = ""
    prefix: str = ""
    suffix: str = ""


@dataclass
class ToolsConfig:
    enabled: list[str] = field(default_factory=lambda: ["*"])
    disabled: list[str] = field(default_factory=list)


@dataclass
class AgentConfig:
    enabled: bool = True
    name: str = ""
    prompt: PromptConfig = field(default_factory=PromptConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)


@dataclass
class TeamConfig:
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    business_context: str = ""
    raw_config: dict = field(default_factory=dict)


def load_team_config() -> TeamConfig:
    """
    Load team config from config_service. Raises on failure.

    Auth priority:
    1. TEAM_TOKEN → Bearer auth (token encodes correct org/team from routing)
    2. INCIDENTFOX_TENANT_ID + INCIDENTFOX_TEAM_ID → header-based auth
    """
    team_token = os.getenv("TEAM_TOKEN")
    tenant_id = os.getenv("INCIDENTFOX_TENANT_ID")
    team_id = os.getenv("INCIDENTFOX_TEAM_ID")

    url = f"{CONFIG_SERVICE_URL}/api/v1/config/me/effective"

    if team_token:
        # Preferred: Bearer token auth (resolves correct org/team via routing)
        headers = {"Authorization": f"Bearer {team_token}"}
    elif tenant_id and team_id:
        # Fallback: direct header auth
        headers = {"X-Org-Id": tenant_id, "X-Team-Node-Id": team_id}
    else:
        raise RuntimeError(
            "Either TEAM_TOKEN or both INCIDENTFOX_TENANT_ID and "
            "INCIDENTFOX_TEAM_ID must be set. Cannot load team configuration."
        )

    resp = httpx.get(url, headers=headers, timeout=10.0)
    resp.raise_for_status()

    data = resp.json()
    effective = data.get("effective_config", data)

    # Parse agents
    agents: dict[str, AgentConfig] = {}
    for name, cfg in effective.get("agents", {}).items():
        prompt_data = cfg.get("prompt", {})
        tools_data = cfg.get("tools", {})
        agents[name] = AgentConfig(
            enabled=cfg.get("enabled", True),
            name=name,
            prompt=PromptConfig(
                system=prompt_data.get("system", ""),
                prefix=prompt_data.get("prefix", ""),
                suffix=prompt_data.get("suffix", ""),
            ),
            tools=ToolsConfig(
                enabled=tools_data.get("enabled", ["*"]),
                disabled=tools_data.get("disabled", []),
            ),
        )

    return TeamConfig(
        agents=agents,
        business_context=effective.get("business_context", ""),
        raw_config=effective,
    )


def get_root_agent_config(team_config: TeamConfig) -> Optional[AgentConfig]:
    """Find root agent: prefers 'investigator' > 'planner' > first enabled."""
    for name in ["investigator", "planner"]:
        if name in team_config.agents and team_config.agents[name].enabled:
            return team_config.agents[name]
    for cfg in team_config.agents.values():
        if cfg.enabled:
            return cfg
    return None
