"""Config Service client for credential resolution.

Fetches integration credentials from the IncidentFox Config Service.
Handles free trial logic with shared API key fallback.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

import boto3
import httpx

logger = logging.getLogger(__name__)

# AWS region for Secrets Manager
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")

# Shared API key secret name for free trials
SHARED_ANTHROPIC_SECRET = os.getenv(
    "SHARED_ANTHROPIC_SECRET", "incidentfox/prod/anthropic"
)

# Cache for shared key (avoid hitting Secrets Manager on every request)
_shared_key_cache: dict[str, tuple[str, datetime]] = {}
SHARED_KEY_CACHE_TTL_SECONDS = 300  # 5 minutes


def get_shared_anthropic_key() -> Optional[str]:
    """Get shared Anthropic API key for free trial users.

    First tries environment variable (simpler, no IRSA needed).
    Falls back to AWS Secrets Manager if configured.

    Returns None if not configured.
    """
    cache_key = "anthropic"
    now = datetime.utcnow()

    # Check cache
    if cache_key in _shared_key_cache:
        cached_key, cached_at = _shared_key_cache[cache_key]
        age_seconds = (now - cached_at).total_seconds()
        if age_seconds < SHARED_KEY_CACHE_TTL_SECONDS:
            return cached_key

    # First: try environment variable (simpler, no IRSA setup required)
    env_key = os.getenv("SHARED_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if env_key:
        _shared_key_cache[cache_key] = (env_key, now)
        logger.info("Using shared Anthropic key from environment")
        return env_key

    # Fallback: try AWS Secrets Manager (requires IRSA)
    try:
        client = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = client.get_secret_value(SecretId=SHARED_ANTHROPIC_SECRET)
        secret_string = response.get("SecretString", "{}")

        secret_data = json.loads(secret_string)
        api_key = secret_data.get("api_key")

        if api_key:
            _shared_key_cache[cache_key] = (api_key, now)
            logger.info("Fetched shared Anthropic key from Secrets Manager")
            return api_key
        else:
            logger.warning("Shared Anthropic secret exists but has no api_key")
            return None

    except Exception as e:
        logger.warning(f"Failed to fetch from Secrets Manager (expected without IRSA): {e}")
        return None


class ConfigServiceClient:
    """Client for IncidentFox Config Service."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv(
            "CONFIG_SERVICE_URL", "http://config-service-svc.incidentfox-prod.svc.cluster.local:8080"
        )
        self._client = httpx.AsyncClient(timeout=10.0)

    async def get_integration_config(
        self,
        tenant_id: str,
        team_id: str,
        integration_id: str,
    ) -> dict | None:
        """Get integration configuration for a tenant/team.

        For Anthropic integration, implements free trial logic:
        1. If custom api_key exists -> return it
        2. If on valid trial -> return shared key with attribution
        3. Otherwise -> return None

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
                f"{self.base_url}/api/v2/config/effective",
                params={"org_id": tenant_id, "team_node_id": team_id},
                headers={
                    "Accept": "application/json",
                    "X-Org-Id": tenant_id,
                    "X-Team-Node-Id": team_id,
                },
            )
            response.raise_for_status()

            config = response.json()
            integrations = config.get("integrations", {})

            integration_config = integrations.get(integration_id, {})

            # Handle Anthropic free trial logic
            if integration_id == "anthropic":
                return self._resolve_anthropic_credentials(
                    integration_config, tenant_id
                )

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

    def _resolve_anthropic_credentials(
        self, config: dict, tenant_id: str
    ) -> dict | None:
        """Resolve Anthropic credentials with subscription + trial support.

        Access control logic:
        1. Valid trial (not expired) -> allow with shared key
        2. Active subscription + custom api_key -> allow with their key
        3. Expired trial without subscription -> DENY (even with BYOK)
        4. No trial, no subscription -> DENY

        This ensures users can't use the software forever for free by just
        bringing their own API key after trial expires.

        Args:
            config: Anthropic integration config from Config Service
            tenant_id: For attribution tagging

        Returns:
            Dict with api_key and optional attribution metadata, or None if access denied
        """
        creds = self._extract_credentials(config)
        api_key = creds.get("api_key")
        is_trial = config.get("is_trial", False)
        trial_expires_at = config.get("trial_expires_at")
        subscription_status = config.get("subscription_status", "none")

        # Helper to check if trial is valid (not expired)
        trial_valid = False
        if is_trial and trial_expires_at:
            try:
                expires_at = datetime.fromisoformat(
                    trial_expires_at.replace("Z", "+00:00")
                )
                now = datetime.utcnow()
                if hasattr(expires_at, "tzinfo") and expires_at.tzinfo:
                    now = now.replace(tzinfo=expires_at.tzinfo)
                trial_valid = now < expires_at
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid trial_expires_at format: {e}")
                trial_valid = False

        # Case 1: Valid trial - use shared key
        if trial_valid:
            shared_key = get_shared_anthropic_key()
            if shared_key:
                logger.info(
                    f"Using shared Anthropic key for trial tenant={tenant_id}"
                )
                return {
                    "api_key": shared_key,
                    "is_trial": True,
                    "workspace_attribution": tenant_id,
                }
            else:
                logger.error(
                    f"Trial active but shared key not available for "
                    f"tenant={tenant_id}"
                )
                return None

        # Case 2: Active subscription with custom API key
        if subscription_status == "active" and api_key:
            logger.info(
                f"Using custom Anthropic key for subscribed tenant={tenant_id}"
            )
            return {"api_key": api_key}

        # Case 3: Trial expired, no active subscription
        if is_trial and not trial_valid:
            logger.warning(
                f"Trial expired for tenant={tenant_id}, no active subscription. "
                f"Access denied (upgrade required)."
            )
            return None

        # Case 4: No trial, no subscription, no access
        logger.warning(
            f"No valid trial or subscription for tenant={tenant_id}. "
            f"Subscription status: {subscription_status}"
        )
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
            "is_trial",
            "trial_expires_at",
            "trial_started_at",
            "workspace_attribution",
            "subscription_status",
            "subscription_activated_at",
        }
        return {k: v for k, v in config.items() if k not in metadata_keys}

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
