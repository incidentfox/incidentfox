"""
Integration with IncidentFox Config Service.

Fetches team-specific configuration from the centralized config service.
"""

import os
from typing import Any

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .errors import ConfigurationError
from .logging import get_logger

logger = get_logger(__name__)


class TokensVaultPath(BaseModel):
    """Vault paths for secrets."""

    openai_token: str | None = None
    slack_bot: str | None = None
    github_token: str | None = None
    aws_credentials: str | None = None


class KnowledgeSource(BaseModel):
    """Knowledge sources configuration."""

    grafana: list[str] = Field(default_factory=list)
    google: list[str] = Field(default_factory=list)
    confluence: list[str] = Field(default_factory=list)


class AgentPromptConfig(BaseModel):
    """Agent prompt configuration - supports system/prefix/suffix structure."""

    system: str | None = None
    prefix: str | None = None
    suffix: str | None = None


class AgentModelConfig(BaseModel):
    """Model configuration for an agent."""

    name: str = "gpt-4o"
    temperature: float = 0.2
    max_tokens: int = 4000


class AgentConfig(BaseModel):
    """Per-agent configuration."""

    model_config = {"extra": "allow"}

    enabled: bool = True
    # Prompt can be a string or a structured object with system/prefix/suffix
    prompt: AgentPromptConfig | str | None = None
    # Model configuration
    model: AgentModelConfig | None = None
    disable_default_tools: list[str] = Field(default_factory=list)
    enable_extra_tools: list[str] = Field(default_factory=list)
    # Per-agent MCP configuration: {mcp_id: True/False}
    # If empty {}, agent gets no MCP tools
    # If not specified (None), inherits all team-level MCPs
    mcps: dict[str, bool] | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    max_turns: int | None = None

    def get_system_prompt(self) -> str | None:
        """Get the system prompt, handling both string and structured formats."""
        if self.prompt is None:
            return None
        if isinstance(self.prompt, str):
            return self.prompt
        return self.prompt.system

    def get_model_name(self) -> str:
        """Get the model name."""
        if self.model:
            return self.model.name
        return "gpt-4o"

    def get_temperature(self) -> float:
        """Get the temperature."""
        if self.model:
            return self.model.temperature
        return 0.2


class EnvironmentConfig(BaseModel):
    """Environment context for the team's infrastructure."""

    model_config = {"extra": "allow"}

    platform: str | None = None
    k8s_namespace: str | None = None
    cloud: str | None = None
    region: str | None = None
    services: list[str] = Field(default_factory=list)
    observability: dict[str, Any] = Field(default_factory=dict)
    data_warehouse: dict[str, Any] = Field(default_factory=dict)


class RoutingConfig(BaseModel):
    """
    Routing configuration for mapping incoming webhooks to this team.

    Each identifier type can have multiple values. When a webhook arrives,
    we extract identifiers from the payload and look up which team owns them.

    Identifiers must be unique within an org - the same Slack channel cannot
    belong to multiple teams.
    """

    model_config = {"extra": "allow"}

    # Slack channels this team owns
    slack_channel_ids: list[str] = Field(default_factory=list)

    # Incident.io team IDs (from their Catalog)
    incidentio_team_ids: list[str] = Field(default_factory=list)

    # Incident.io alert source IDs
    incidentio_alert_source_ids: list[str] = Field(default_factory=list)

    # PagerDuty service IDs
    pagerduty_service_ids: list[str] = Field(default_factory=list)

    # Coralogix team names (normalized to lowercase)
    coralogix_team_names: list[str] = Field(default_factory=list)

    # GitHub repositories (owner/repo format)
    github_repos: list[str] = Field(default_factory=list)

    # Services this team owns (for service-based routing)
    services: list[str] = Field(default_factory=list)

    def normalize(self) -> "RoutingConfig":
        """Return a copy with all values normalized (lowercase, stripped)."""
        return RoutingConfig(
            slack_channel_ids=[v.strip() for v in self.slack_channel_ids],
            incidentio_team_ids=[v.strip() for v in self.incidentio_team_ids],
            incidentio_alert_source_ids=[
                v.strip() for v in self.incidentio_alert_source_ids
            ],
            pagerduty_service_ids=[v.strip() for v in self.pagerduty_service_ids],
            coralogix_team_names=[v.lower().strip() for v in self.coralogix_team_names],
            github_repos=[v.lower().strip() for v in self.github_repos],
            services=[v.lower().strip() for v in self.services],
        )

    def has_identifier(self, identifier_type: str, value: str) -> bool:
        """Check if this routing config contains a specific identifier."""
        normalized_value = (
            value.lower().strip()
            if identifier_type in ("coralogix_team_names", "github_repos", "services")
            else value.strip()
        )
        identifiers = getattr(self, identifier_type, [])
        return normalized_value in [
            (
                v.lower().strip()
                if identifier_type
                in ("coralogix_team_names", "github_repos", "services")
                else v.strip()
            )
            for v in identifiers
        ]


class TeamLevelConfig(BaseModel):
    """Team-level configuration from IncidentFox Config Service."""

    model_config = {"extra": "allow"}  # Allow additional fields

    # Routing configuration (maps incoming webhooks to this team)
    routing: RoutingConfig | None = None

    # Environment context (structured info about the team's infrastructure)
    environment: EnvironmentConfig | None = None

    # Tool defaults (per-tool argument defaults)
    tool_defaults: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Secrets/tokens
    tokens_vault_path: TokensVaultPath | None = None

    # Slack configuration
    slack_group_to_ping: str | None = None
    slack_channel: str | None = None

    # Integrations
    google_account: str | None = None
    confluence_space: str | None = None
    integrations: dict[str, Any] = Field(
        default_factory=dict
    )  # Integration configurations

    # Canonical format fields
    mcp_servers: dict[str, Any] = Field(
        default_factory=dict
    )  # MCP server configurations (dict keyed by ID)
    tools: dict[str, bool] = Field(
        default_factory=dict
    )  # Team-level tool overrides (tool_id -> enabled)
    built_in_tools: list[Any] = Field(
        default_factory=list
    )  # Built-in tools catalog from config service

    # Feature flags
    feature_flags: dict[str, bool] = Field(default_factory=dict)

    # Knowledge sources
    knowledge_source: KnowledgeSource | None = None

    # Agent configurations
    agents: dict[str, AgentConfig] = Field(default_factory=dict)

    # Remote A2A agents (flat dict by agent_id)
    remote_agents: dict[str, Any] = Field(default_factory=dict)

    # Remote A2A agents (flat dict by agent_id)
    remote_agents: dict[str, Any] = Field(default_factory=dict)

    # Disabled alerts
    alerts: dict[str, list[str]] | None = None

    def get_agent_config(self, agent_name: str) -> AgentConfig:
        """Get configuration for a specific agent."""
        return self.agents.get(agent_name, AgentConfig())

    def is_feature_enabled(self, feature: str) -> bool:
        """Check if a feature flag is enabled."""
        return self.feature_flags.get(feature, False)


class AuthIdentity(BaseModel):
    """Identity information from /auth/me endpoint."""

    role: str
    auth_kind: str
    org_id: str
    team_node_id: str
    subject: str | None = None
    email: str | None = None
    can_write: bool
    permissions: list[str]


class ConfigServiceClient:
    """
    Client for IncidentFox Config Service.

    Handles fetching and caching team configuration with proper error handling.
    """

    def __init__(
        self,
        base_url: str | None = None,
    ):
        """
        Initialize config service client.

        Args:
            base_url: Config service base URL (defaults to env var)
        """
        self.base_url = base_url or os.getenv(
            "CONFIG_BASE_URL", "http://localhost:8080"
        )
        # In shared-runtime mode, the team token is expected per-request (header).
        # For single-tenant/dev mode, callers may rely on INCIDENTFOX_TEAM_TOKEN as a default.
        self._default_team_token = os.getenv("INCIDENTFOX_TEAM_TOKEN")

        logger.info(
            "config_service_client_initialized",
            base_url=self.base_url,
        )

    @property
    def _headers(self) -> dict[str, str]:
        raise RuntimeError("Use _headers_for(team_token=...)")

    def _headers_for(self, team_token: str | None) -> dict[str, str]:
        """Get auth headers for requests."""
        tok = team_token or self._default_team_token
        if not tok:
            raise ConfigurationError(
                "Team token not provided. Pass team_token explicitly (shared runtime) or set INCIDENTFOX_TEAM_TOKEN (single-tenant/dev)."
            )
        return {"Authorization": f"Bearer {tok}"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def fetch_effective_config(
        self, *, team_token: str | None = None
    ) -> TeamLevelConfig:
        """
        Fetch the team's effective configuration.

        Args:
            team_token: Team authentication token (shared runtime). If omitted, falls back to INCIDENTFOX_TEAM_TOKEN.

        Returns:
            Parsed team configuration

        Raises:
            ConfigurationError: If fetch fails after retries
        """
        url = f"{self.base_url}/api/v1/config/me"

        try:
            logger.info("fetching_team_config", url=url)

            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers=self._headers_for(team_token))
                response.raise_for_status()
                data = response.json()

            # v2 API returns {effective_config: {...}, ...}, extract the config
            config_data = (
                data.get("effective_config", data)
                if "effective_config" in data
                else data
            )

            # Parse and validate
            config = TeamLevelConfig.model_validate(config_data)

            logger.info(
                "team_config_fetched",
                mcp_servers=len(config.mcp_servers),
                agents_configured=len(config.agents),
                feature_flags=len(config.feature_flags),
            )

            return config

        except httpx.HTTPStatusError as e:
            logger.error(
                "config_service_http_error",
                status_code=e.response.status_code,
                error=str(e),
            )
            raise ConfigurationError(
                f"Failed to fetch config: HTTP {e.response.status_code}"
            ) from e

        except httpx.HTTPError as e:
            logger.error("config_service_request_failed", error=str(e))
            raise ConfigurationError(f"Config service request failed: {e}") from e

        except Exception as e:
            logger.error("config_parsing_failed", error=str(e), exc_info=True)
            raise ConfigurationError(f"Failed to parse config: {e}") from e

    def fetch_auth_identity(self, *, team_token: str | None = None) -> AuthIdentity:
        """
        Fetch authentication identity.

        Returns:
            Identity information for the authenticated team

        Raises:
            ConfigurationError: If fetch fails
        """
        url = f"{self.base_url}/api/v1/auth/me"

        try:
            logger.info("fetching_auth_identity", url=url)

            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers=self._headers_for(team_token))
                response.raise_for_status()
                data = response.json()

            identity = AuthIdentity.model_validate(data)

            logger.info(
                "auth_identity_fetched",
                role=identity.role,
                org_id=identity.org_id,
                team_node_id=identity.team_node_id,
            )

            return identity

        except Exception as e:
            logger.error("failed_to_fetch_identity", error=str(e), exc_info=True)
            raise ConfigurationError(f"Failed to fetch identity: {e}") from e

    def fetch_raw_config(self, *, team_token: str | None = None) -> dict[str, Any]:
        """
        Fetch raw lineage and per-node configs.

        Useful for debugging and understanding config inheritance.

        Returns:
            Dict with 'lineage' and 'configs' keys
        """
        url = f"{self.base_url}/api/v1/config/orgs/{org_id}/nodes/{team_node_id}/raw"

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers=self._headers_for(team_token))
                response.raise_for_status()
                return response.json()

        except Exception as e:
            logger.error("failed_to_fetch_raw_config", error=str(e))
            raise ConfigurationError(f"Failed to fetch raw config: {e}") from e

    def update_team_config(
        self, overrides: dict[str, Any], *, team_token: str | None = None
    ) -> None:
        """
        Update team configuration overrides.

        Uses PATCH semantics - deep merges with existing config.

        Args:
            overrides: Configuration overrides to apply

        Raises:
            ConfigurationError: If update fails
        """
        url = f"{self.base_url}/api/v1/config/me"

        try:
            logger.info("updating_team_config", override_keys=list(overrides.keys()))

            with httpx.Client(timeout=10.0) as client:
                # v2 API expects {config: ..., merge: true} format
                payload = {"config": overrides, "merge": True}
                response = client.patch(
                    url, headers=self._headers_for(team_token), json=payload
                )
                response.raise_for_status()

            # Invalidate cache after update (best-effort)
            if team_token or self._default_team_token:
                cache_key = self._token_cache_key(team_token or self._default_team_token)  # type: ignore[arg-type]
                self._cached_config.pop(cache_key, None)
                self._cached_identity.pop(cache_key, None)

            logger.info("team_config_updated")

        except httpx.HTTPStatusError as e:
            logger.error("config_update_failed", status_code=e.response.status_code)
            raise ConfigurationError(
                f"Failed to update config: HTTP {e.response.status_code}"
            ) from e

        except Exception as e:
            logger.error("config_update_error", error=str(e), exc_info=True)
            raise ConfigurationError(f"Config update failed: {e}") from e

    def lookup_routing(
        self,
        identifiers: dict[str, str | None],
        org_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Look up which team owns the given identifiers.

        Tries identifiers in priority order:
        1. incidentio_team_id
        2. pagerduty_service_id
        3. slack_channel_id
        4. github_repo
        5. coralogix_team_name
        6. incidentio_alert_source_id
        7. service

        Args:
            identifiers: Dict of identifier_type -> value
            org_id: Optional org ID to scope the lookup

        Returns:
            Dict with org_id, team_node_id, team_token, matched_by, matched_value
            or None if no match found
        """
        url = f"{self.base_url}/api/v1/internal/routing/lookup"

        # Filter out None values
        clean_identifiers = {k: v for k, v in identifiers.items() if v}

        if not clean_identifiers:
            logger.debug("routing_lookup_no_identifiers")
            return None

        try:
            payload = {"identifiers": clean_identifiers}
            if org_id:
                payload["org_id"] = org_id

            logger.info("routing_lookup", identifiers=list(clean_identifiers.keys()))

            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    url,
                    json=payload,
                    headers={"X-Internal-Service": "agent"},
                )

                if response.status_code == 404:
                    logger.info(
                        "routing_lookup_not_found", tried=list(clean_identifiers.keys())
                    )
                    return None

                response.raise_for_status()
                result = response.json()

                if result.get("found"):
                    logger.info(
                        "routing_lookup_found",
                        org_id=result.get("org_id"),
                        team_node_id=result.get("team_node_id"),
                        matched_by=result.get("matched_by"),
                    )
                    return result

                return None

        except httpx.HTTPError as e:
            logger.warning("routing_lookup_error", error=str(e))
            return None
        except Exception as e:
            logger.warning("routing_lookup_failed", error=str(e))
            return None

    def invalidate_cache(self) -> None:
        """Invalidate cached config to force refresh on next fetch."""
        self._cached_config.clear()
        self._cached_identity.clear()
        logger.info("config_cache_invalidated_all")


# Global config service client
_config_service_client: ConfigServiceClient | None = None


def get_config_service_client() -> ConfigServiceClient:
    """Get or create the global config service client."""
    global _config_service_client
    if _config_service_client is None:
        _config_service_client = ConfigServiceClient()
    return _config_service_client


def initialize_config_service(
    base_url: str | None = None,
    team_token: str | None = None,
) -> ConfigServiceClient:
    """
    Initialize the config service client.

    Args:
        base_url: Config service URL
        team_token: Team authentication token

    Returns:
        Initialized client
    """
    global _config_service_client
    # Backwards compatible: if a team_token is provided explicitly, set it as
    # the process default for single-tenant usage.
    if team_token:
        os.environ.setdefault("INCIDENTFOX_TEAM_TOKEN", team_token)

    _config_service_client = ConfigServiceClient(
        base_url=base_url,
    )
    return _config_service_client
