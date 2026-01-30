"""Config Service client for credential resolution.

Fetches integration credentials from the IncidentFox Config Service.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


class ConfigServiceClient:
    """Client for IncidentFox Config Service."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv(
            "CONFIG_SERVICE_URL", "http://incidentfox-config-service:8080"
        )
        self._client = httpx.AsyncClient(timeout=10.0)

    async def get_integration_config(
        self,
        tenant_id: str,
        team_id: str,
        integration_id: str,
    ) -> dict | None:
        """Get integration configuration for a tenant/team.

        Args:
            tenant_id: Organization/tenant ID
            team_id: Team node ID
            integration_id: Integration identifier (e.g., "coralogix", "anthropic")

        Returns:
            Integration configuration dict with credentials, or None if not found
        """
        try:
            # Call Config Service to get team's effective config
            response = await self._client.get(
                f"{self.base_url}/api/v1/config/effective",
                params={"org_id": tenant_id, "team_node_id": team_id},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()

            config = response.json()
            integrations = config.get("integrations", {})

            integration_config = integrations.get(integration_id, {})
            if not integration_config:
                logger.warning(
                    f"Integration {integration_id} not configured for "
                    f"tenant={tenant_id}, team={team_id}"
                )
                return None

            # Filter out metadata fields, return only credential fields
            return self._extract_credentials(integration_config)

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Config Service HTTP error: {e.response.status_code} - "
                f"{e.response.text}"
            )
            return None
        except Exception as e:
            logger.error(f"Config Service error: {e}")
            return None

    def _extract_credentials(self, config: dict) -> dict:
        """Extract credential fields from integration config.

        Filters out metadata fields like 'level', 'locked', 'config_schema'.
        """
        metadata_keys = {
            "level",
            "locked",
            "config_schema",
            "team_config_schema",
            "name",
            "description",
        }
        return {k: v for k, v in config.items() if k not in metadata_keys}

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
