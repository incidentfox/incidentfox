"""
Configuration management for the unified agent.

Supports loading configuration from:
1. Environment variables (highest priority)
2. Config Service (for multi-tenant SaaS)
3. Local YAML files (for development)
4. Defaults (lowest priority)
"""

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class PromptConfig(BaseModel):
    """Prompt configuration for an agent."""

    system: str = ""
    prefix: str = ""
    suffix: str = ""


class ModelConfig(BaseModel):
    """Model configuration for an agent."""

    name: str = "sonnet"
    temperature: float = 0.4
    max_tokens: Optional[int] = None
    # For reasoning models
    reasoning: Optional[str] = None
    verbosity: Optional[str] = None


class ToolsConfig(BaseModel):
    """Tools configuration for an agent."""

    # Dict format: {tool_name: enabled}
    # Or legacy format with enabled/disabled lists
    enabled: list[str] = Field(default_factory=lambda: ["*"])
    disabled: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Configuration for a single agent."""

    enabled: bool = True
    name: Optional[str] = None
    model: ModelConfig = Field(default_factory=ModelConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    sub_agents: dict[str, bool] = Field(default_factory=dict)
    max_turns: int = 25
    timeout_seconds: int = 600


class ProviderConfig(BaseModel):
    """Configuration for the LLM provider."""

    model: str = "anthropic/claude-sonnet-4-20250514"
    cwd: str = "/workspace"
    allowed_tools: list[str] = Field(default_factory=list)
    subagents: dict[str, Any] = Field(default_factory=dict)


class TeamConfig(BaseModel):
    """Team-level configuration from Config Service."""

    agents_config: dict[str, AgentConfig] = Field(default_factory=dict)
    integrations: dict[str, dict] = Field(default_factory=dict)
    mcp_servers: dict[str, dict] = Field(default_factory=dict)

    def get_agent_config(self, agent_name: str) -> AgentConfig:
        """Get config for a specific agent, with defaults."""
        if agent_name in self.agents_config:
            return self.agents_config[agent_name]
        return AgentConfig(name=agent_name)


@dataclass
class Config:
    """Global configuration container."""

    # LLM settings
    llm_provider: str = "openhands"  # Always OpenHands for unified agent
    llm_model: str = "anthropic/claude-sonnet-4-20250514"

    # API keys (resolved from env)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Observability
    laminar_api_key: str = ""

    # Team config (from Config Service)
    team_config: Optional[TeamConfig] = None

    # Execution context
    tenant_id: str = "local"
    team_id: str = "local"

    # Agent defaults
    default_max_turns: int = 25
    default_timeout: int = 600


def load_config() -> Config:
    """
    Load configuration from all sources.

    Priority (highest to lowest):
    1. Environment variables
    2. Config Service (if TEAM_TOKEN is set)
    3. Local config file (.env or config.yaml)
    4. Defaults
    """
    config = Config()

    # Load from environment
    config.llm_model = os.getenv(
        "LLM_MODEL",
        os.getenv("ANTHROPIC_MODEL", "anthropic/claude-sonnet-4-20250514"),
    )
    config.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    config.openai_api_key = os.getenv("OPENAI_API_KEY", "")
    config.gemini_api_key = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
    config.laminar_api_key = os.getenv("LMNR_PROJECT_API_KEY", "")

    # Tenant context
    config.tenant_id = os.getenv("INCIDENTFOX_TENANT_ID", "local")
    config.team_id = os.getenv("INCIDENTFOX_TEAM_ID", "local")

    # Timeouts
    config.default_timeout = int(os.getenv("AGENT_TIMEOUT_SECONDS", "600"))

    # Try to load team config from Config Service
    team_token = os.getenv("TEAM_TOKEN")
    if team_token:
        try:
            config.team_config = _load_from_config_service(team_token)
        except Exception as e:
            import logging

            logging.warning(f"Failed to load team config: {e}")

    # Fallback to local config file
    if config.team_config is None:
        config.team_config = _load_local_config()

    return config


def _load_from_config_service(team_token: str) -> Optional[TeamConfig]:
    """Load configuration from the Config Service."""
    import httpx

    config_service_url = os.getenv(
        "CONFIG_SERVICE_URL",
        "http://config-service-svc.incidentfox-prod.svc.cluster.local:8080",
    )

    try:
        response = httpx.get(
            f"{config_service_url}/api/v1/config/me/effective",
            headers={"Authorization": f"Bearer {team_token}"},
            timeout=10.0,
        )
        response.raise_for_status()

        data = response.json()
        effective_config = data.get("effective_config", data)

        return TeamConfig(
            agents_config={
                name: AgentConfig(**cfg)
                for name, cfg in effective_config.get("agents", {}).items()
            },
            integrations=effective_config.get("integrations", {}),
            mcp_servers=effective_config.get("mcp_servers", {}),
        )
    except Exception:
        return None


def _load_local_config() -> TeamConfig:
    """Load configuration from local YAML file."""
    config_paths = [
        "config.yaml",
        "config.yml",
        ".incidentfox/config.yaml",
        os.path.expanduser("~/.incidentfox/config.yaml"),
    ]

    for path in config_paths:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
                    if data:
                        return TeamConfig(
                            agents_config={
                                name: AgentConfig(**cfg)
                                for name, cfg in data.get("agents", {}).items()
                            },
                            integrations=data.get("integrations", {}),
                            mcp_servers=data.get("mcp_servers", {}),
                        )
            except Exception:
                pass

    # Return empty config with defaults
    return TeamConfig()


# Global config instance (lazy loaded)
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> Config:
    """Force reload of configuration."""
    global _config
    _config = load_config()
    return _config
