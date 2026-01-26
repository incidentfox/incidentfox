"""
Configuration management with AWS Config Service integration.

This module provides a flexible configuration system that can:
1. Load from environment variables
2. Load from local YAML files
3. Fetch from AWS Config Service (SSM Parameter Store / Secrets Manager)
4. Hot-reload configuration changes
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import boto3
import structlog
import yaml
from botocore.exceptions import ClientError
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import ConfigurationError

logger = structlog.get_logger(__name__)


class OpenAIConfig(BaseSettings):
    """OpenAI API configuration."""

    api_key: str = Field(..., description="OpenAI API key")
    # Default to a model compatible with structured outputs / JSON schema formatting
    # used by the Agents SDK.
    model: str = Field(default="gpt-4o", description="Default model to use")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=4000, gt=0)
    timeout: int = Field(default=60, description="Request timeout in seconds")

    model_config = SettingsConfigDict(env_prefix="OPENAI_")


class AWSConfig(BaseSettings):
    """AWS configuration."""

    region: str = Field(default="us-east-1")
    profile: str | None = Field(default=None, description="AWS profile name")
    config_service_enabled: bool = Field(
        default=False, description="Use AWS config service"
    )
    config_parameter_prefix: str = Field(
        default="/ai-agent/", description="SSM parameter prefix"
    )
    config_refresh_interval: int = Field(
        default=300, description="Config refresh interval in seconds"
    )

    model_config = SettingsConfigDict(env_prefix="AWS_")


class KubernetesConfig(BaseSettings):
    """Kubernetes configuration."""

    enabled: bool = Field(default=False)
    kubeconfig_path: str | None = Field(default=None)
    context: str | None = Field(default=None, description="K8s context to use")
    namespace: str = Field(default="default")

    model_config = SettingsConfigDict(env_prefix="K8S_")


class MetricsConfig(BaseSettings):
    """Metrics and monitoring configuration."""

    enabled: bool = Field(default=True)
    prometheus_port: int = Field(default=9090)
    cloudwatch_enabled: bool = Field(default=False)
    cloudwatch_namespace: str = Field(default="AIAgent")

    model_config = SettingsConfigDict(env_prefix="METRICS_")


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: str = Field(default="INFO")
    format: str = Field(default="json", description="json or console")
    enable_correlation_ids: bool = Field(default=True)

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v = v.upper()
        if v not in valid_levels:
            raise ValueError(f"Invalid log level. Must be one of {valid_levels}")
        return v

    model_config = SettingsConfigDict(env_prefix="LOG_")


class SlackConfig(BaseSettings):
    """Slack integration configuration."""

    enabled: bool = Field(default=False)
    bot_token: str | None = Field(default=None)
    app_token: str | None = Field(default=None)
    signing_secret: str | None = Field(default=None)

    model_config = SettingsConfigDict(env_prefix="SLACK_")


class Config(BaseSettings):
    """Main application configuration."""

    # Environment
    environment: str = Field(default="development")
    debug: bool = Field(default=False)

    # Sub-configs
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    aws: AWSConfig = Field(default_factory=AWSConfig)
    kubernetes: KubernetesConfig = Field(default_factory=KubernetesConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)

    # Agent settings
    max_concurrent_agents: int = Field(default=10, gt=0)
    agent_timeout: int = Field(default=300, description="Agent execution timeout")

    # Config service settings
    use_config_service: bool = Field(
        default=False, description="Use IncidentFox config service"
    )
    config_service_url: str | None = Field(
        default=None, description="Config service URL"
    )

    # Team-level config from config service (populated after init)
    # Use Any since TeamLevelConfig is dynamically imported to avoid circular imports
    team_config: Any = Field(default=None, exclude=True)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    @classmethod
    def from_yaml(cls, path: Path | str) -> Config:
        """Load configuration from YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        return cls(**data)

    @classmethod
    def from_aws_config_service(cls, aws_config: AWSConfig) -> dict[str, Any]:
        """
        Fetch configuration from AWS SSM Parameter Store.

        Args:
            aws_config: AWS configuration with parameter prefix

        Returns:
            Dictionary of configuration values
        """
        session_kwargs = {"region_name": aws_config.region}
        if aws_config.profile:
            session_kwargs["profile_name"] = aws_config.profile

        session = boto3.Session(**session_kwargs)
        ssm = session.client("ssm")

        try:
            # Get all parameters with the prefix
            paginator = ssm.get_paginator("get_parameters_by_path")
            parameters = {}

            for page in paginator.paginate(
                Path=aws_config.config_parameter_prefix,
                Recursive=True,
                WithDecryption=True,
            ):
                for param in page["Parameters"]:
                    # Remove prefix from parameter name
                    key = param["Name"][len(aws_config.config_parameter_prefix) :]
                    # Convert /path/to/key to nested dict structure
                    parameters[key.replace("/", "__")] = param["Value"]

            logger.info(
                "loaded_config_from_aws",
                parameter_count=len(parameters),
                prefix=aws_config.config_parameter_prefix,
            )
            return parameters

        except ClientError as e:
            logger.error("failed_to_load_aws_config", error=str(e))
            return {}

    def validate_required_config(self) -> list[str]:
        """
        Validate that required configuration is present.

        Returns:
            List of error messages. Empty if valid.
        """
        errors = []

        if not self.openai.api_key:
            errors.append("OpenAI API key is required")

        if self.slack.enabled:
            if not self.slack.bot_token:
                errors.append("Slack bot token required when Slack is enabled")
            if not self.slack.app_token:
                errors.append("Slack app token required when Slack is enabled")

        if self.kubernetes.enabled and not self.kubernetes.kubeconfig_path:
            # Check for local kubeconfig or in-cluster config
            has_local_config = Path("~/.kube/config").expanduser().exists()
            has_in_cluster_config = Path(
                "/var/run/secrets/kubernetes.io/serviceaccount/token"
            ).exists()
            if not has_local_config and not has_in_cluster_config:
                errors.append(
                    "Kubernetes config not found (no kubeconfig or in-cluster token)"
                )

        return errors


# Global configuration instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def load_config(
    config_file: Path | str | None = None,
    use_aws_config: bool = None,
    use_config_service: bool = None,
) -> Config:
    """
    Load configuration from multiple sources with precedence:
    1. Environment variables (highest priority)
    2. IncidentFox Config Service (if enabled)
    3. AWS SSM Parameters (if enabled)
    4. Local YAML file
    5. Defaults (lowest priority)

    Args:
        config_file: Optional path to YAML config file
        use_aws_config: Override AWS config service setting
        use_config_service: Override IncidentFox config service setting

    Returns:
        Loaded configuration
    """
    # Start with defaults and env vars
    config = Config()

    # Load from YAML if provided
    if config_file:
        yaml_config = Config.from_yaml(config_file)
        # Merge with existing config (env vars take precedence)
        config = Config(
            **{
                **yaml_config.model_dump(),
                **{k: v for k, v in config.model_dump().items() if v is not None},
            }
        )

    # Load from AWS SSM Parameters if enabled (optional, mainly for testing)
    if use_aws_config or (use_aws_config is None and config.aws.config_service_enabled):
        try:
            aws_params = Config.from_aws_config_service(config.aws)
            if aws_params:
                # Merge AWS parameters
                config = Config(**{**config.model_dump(), **aws_params})
        except Exception as e:
            logger.warning("aws_ssm_unavailable", error=str(e))

    # Load from IncidentFox Config Service if enabled (production default)
    if use_config_service or (use_config_service is None and config.use_config_service):
        try:
            from .config_service import initialize_config_service

            # Shared-runtime mode: if no team token is configured at process level,
            # we cannot resolve "me/effective" at startup. Team scoping will be done
            # per-request in the API layer using an explicit team token header.
            if not os.getenv("INCIDENTFOX_TEAM_TOKEN"):
                logger.info(
                    "config_service_enabled_shared_runtime_mode",
                    note="skipping_startup_team_config_load",
                )
                return config

            client = initialize_config_service(
                base_url=config.config_service_url,
            )
            team_config = client.fetch_effective_config()
            config.team_config = team_config

            # Apply config service overrides
            config = _apply_team_config(config, team_config)

            logger.info(
                "team_config_loaded",
                mcp_servers=len(team_config.mcp_servers),
                agents=len(team_config.agents),
            )
        except ConfigurationError as e:
            logger.warning("config_service_unavailable", error=str(e))
            # Continue with local config if service unavailable

    # Validate
    errors = config.validate_required_config()
    if errors:
        error_msg = "\n".join(f"  - {err}" for err in errors)
        raise ValueError(f"Configuration validation failed:\n{error_msg}")

    logger.info(
        "config_loaded",
        environment=config.environment,
        openai_model=config.openai.model,
        k8s_enabled=config.kubernetes.enabled,
        slack_enabled=config.slack.enabled,
        config_service_enabled=config.use_config_service,
    )

    return config


def _apply_team_config(config: Config, team_config: TeamLevelConfig) -> Config:
    """
    Apply team-level configuration from config service to main config.

    Team config takes precedence over local config but not over env vars.
    """
    config_dict = config.model_dump()

    # Apply Slack overrides
    if team_config.slack_channel:
        # Store in metadata for agents to use
        if "metadata" not in config_dict:
            config_dict["metadata"] = {}
        config_dict["metadata"]["slack_channel"] = team_config.slack_channel

    if team_config.slack_group_to_ping:
        if "metadata" not in config_dict:
            config_dict["metadata"] = {}
        config_dict["metadata"]["slack_group_to_ping"] = team_config.slack_group_to_ping

    # Note: We don't override OpenAI/AWS credentials here since those come from vault
    # The vault path info is stored in team_config for agents to fetch secrets

    new_config = Config(**config_dict)
    # Preserve team_config since it's excluded from model_dump()
    new_config.team_config = team_config
    return new_config


def reload_config() -> Config:
    """Reload configuration from sources."""
    global _config
    _config = None
    return get_config()
