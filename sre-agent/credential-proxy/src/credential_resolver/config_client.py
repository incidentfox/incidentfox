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

# AWS Secrets Manager secret name for shared Anthropic API key
SHARED_ANTHROPIC_SECRET = os.getenv(
    "SHARED_ANTHROPIC_SECRET", "incidentfox/prod/anthropic"
)

# Cache for shared key (avoid hitting Secrets Manager on every request)
_shared_key_cache: dict[str, tuple[str, datetime]] = {}
SHARED_KEY_CACHE_TTL_SECONDS = 300  # 5 minutes

# Cache for LLM model lookups (key: "tenant_id:team_id", value: (model_str, fetched_at))
_llm_model_cache: dict[str, tuple[str, datetime]] = {}
LLM_MODEL_CACHE_TTL_SECONDS = 30  # short TTL so local.yaml changes propagate quickly


def get_shared_anthropic_key() -> Optional[str]:
    """Get shared Anthropic API key for free trials.

    Priority order:
    1. SHARED_ANTHROPIC_API_KEY env var (K8s secret - simplest, best for self-hosting)
    2. AWS Secrets Manager (requires IRSA - for AWS-native deployments)

    Returns None if not configured.
    """
    cache_key = "anthropic"
    now = datetime.utcnow()

    # Check cache first
    if cache_key in _shared_key_cache:
        cached_key, cached_at = _shared_key_cache[cache_key]
        age_seconds = (now - cached_at).total_seconds()
        if age_seconds < SHARED_KEY_CACHE_TTL_SECONDS:
            return cached_key

    # Option 1: Environment variable (K8s secret) - simplest option
    env_key = os.getenv("SHARED_ANTHROPIC_API_KEY")
    if env_key:
        _shared_key_cache[cache_key] = (env_key, now)
        logger.info("Using shared Anthropic key from environment variable")
        return env_key

    # Option 2: AWS Secrets Manager (requires IRSA)
    try:
        client = boto3.client("secretsmanager", region_name=AWS_REGION)
        response = client.get_secret_value(SecretId=SHARED_ANTHROPIC_SECRET)
        secret_string = response.get("SecretString", "{}")

        # Support both raw string and JSON format
        try:
            secret_data = json.loads(secret_string)
            api_key = secret_data.get("api_key", secret_string)
        except json.JSONDecodeError:
            # Raw string format (just the key)
            api_key = secret_string.strip()

        if api_key and len(api_key) > 10:
            _shared_key_cache[cache_key] = (api_key, now)
            logger.info("Fetched shared Anthropic key from AWS Secrets Manager")
            return api_key
        else:
            logger.warning("AWS Secrets Manager secret exists but has no valid api_key")
            return None

    except Exception as e:
        logger.warning(
            f"AWS Secrets Manager not available: {e}. "
            f"Set SHARED_ANTHROPIC_API_KEY env var or configure IRSA."
        )
        return None


class ConfigServiceClient:
    """Client for IncidentFox Config Service."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv(
            "CONFIG_SERVICE_URL",
            "http://config-service-svc.incidentfox-prod.svc.cluster.local:8080",
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
            # Callers pass the real Config Service org_id as tenant_id
            # and the real team_node_id as team_id
            response = await self._client.get(
                f"{self.base_url}/api/v1/config/me",
                headers={
                    "Accept": "application/json",
                    "X-Org-Id": tenant_id,
                    "X-Team-Node-Id": team_id,
                },
            )
            response.raise_for_status()

            data = response.json()
            # API returns {"effective_config": {...}, "node_id": ..., ...}
            # Extract effective_config to get the actual configuration
            config = data.get("effective_config", data)
            integrations = config.get("integrations", {})

            integration_config = integrations.get(integration_id, {})

            # Handle Anthropic free trial logic
            # Pass full config for trial fields (is_trial, trial_expires_at)
            # which live at the top level, not inside integrations.anthropic
            if integration_id == "anthropic":
                return self._resolve_anthropic_credentials(config, tenant_id)

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
            # For Anthropic, fall back to shared key when tenant doesn't exist
            # This enables development/testing without full tenant setup
            if integration_id == "anthropic":
                logger.info(
                    f"Tenant {tenant_id} not found, falling back to shared Anthropic key"
                )
                shared_key = get_shared_anthropic_key()
                if shared_key:
                    return {
                        "api_key": shared_key,
                        "workspace_attribution": tenant_id,
                    }
            return None
        except Exception as e:
            logger.error(f"Config Service error: {e}")
            return None

    async def get_llm_model(self, tenant_id: str, team_id: str) -> str | None:
        """Get the configured LLM model string for a tenant/team.

        Returns the value of integrations.llm.model from the effective config
        (e.g. "openai/gpt-5.2"), or None if not configured.

        Results are cached for LLM_MODEL_CACHE_TTL_SECONDS seconds so that
        local.yaml changes hot-reload without requiring a container restart.
        """
        cache_key = f"{tenant_id}:{team_id}"
        cached = _llm_model_cache.get(cache_key)
        if cached:
            model_str, fetched_at = cached
            age = (datetime.utcnow() - fetched_at).total_seconds()
            if age < LLM_MODEL_CACHE_TTL_SECONDS:
                return model_str or None

        try:
            response = await self._client.get(
                f"{self.base_url}/api/v1/config/me/effective",
                headers={
                    "Accept": "application/json",
                    "X-Org-Id": tenant_id,
                    "X-Team-Node-Id": team_id,
                },
            )
            response.raise_for_status()
            data = response.json()
            effective = data.get("effective_config", data)
            model_str = (
                effective.get("integrations", {}).get("llm", {}).get("model", "") or ""
            )
            _llm_model_cache[cache_key] = (model_str, datetime.utcnow())
            return model_str or None
        except Exception as e:
            logger.warning(f"Could not fetch LLM model for {tenant_id}/{team_id}: {e}")
            return None

    def _resolve_anthropic_credentials(
        self, config: dict, tenant_id: str
    ) -> dict | None:
        """Resolve Anthropic credentials.

        Two distinct modes:

        Local / self-hosted (tenant_id == "local"):
          - No access control — operator owns the deployment.
          - BYOK required; no shared key fallback.

        SaaS (any other tenant):
          - Must have a valid trial OR active subscription to access the platform,
            even when bringing their own key.
          - If authorized: BYOK if configured, else our shared key with attribution.

        Args:
            config: Full effective_config from Config Service (trial fields at
                top level, API key inside integrations.anthropic)
            tenant_id: For attribution tagging and mode detection

        Returns:
            Dict with api_key and optional attribution metadata, or None if denied
        """
        anthropic_config = config.get("integrations", {}).get("anthropic", {})
        creds = self._extract_credentials(anthropic_config)
        customer_api_key = creds.get("api_key")

        # ── Local / self-hosted ───────────────────────────────────────────────
        # tenant_id == "local" means the operator is running their own instance.
        # No trial/subscription check — just use their own key.
        if tenant_id == "local":
            if customer_api_key:
                logger.info("Using BYOK Anthropic key (local mode)")
                return {"api_key": customer_api_key}
            # No Anthropic key — fine if using a different LLM provider (OpenAI, Gemini,
            # etc.); the LLM bypass in ext_authz_check handles that before reaching here.
            return None

        # ── SaaS ─────────────────────────────────────────────────────────────
        # Trial/subscription fields may be at top level or inside integrations.anthropic.
        # Use `is not None` checks to avoid falsy values (False, "") falling through.
        is_trial = (
            config.get("is_trial")
            if config.get("is_trial") is not None
            else anthropic_config.get("is_trial", False)
        )
        trial_expires_at = (
            config.get("trial_expires_at")
            if config.get("trial_expires_at") is not None
            else anthropic_config.get("trial_expires_at")
        )
        subscription_status = (
            config.get("subscription_status")
            if config.get("subscription_status") is not None
            else anthropic_config.get("subscription_status", "none")
        )

        has_valid_trial = False
        if is_trial and trial_expires_at:
            try:
                expires_at = datetime.fromisoformat(
                    trial_expires_at.replace("Z", "+00:00")
                )
                now = datetime.utcnow()
                if hasattr(expires_at, "tzinfo") and expires_at.tzinfo:
                    now = now.replace(tzinfo=expires_at.tzinfo)
                has_valid_trial = now < expires_at
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid trial_expires_at format: {e}")

        has_active_subscription = subscription_status == "active"

        # Access gate: must have trial or subscription (even for BYOK).
        if not has_valid_trial and not has_active_subscription:
            logger.warning(
                f"Access denied for tenant={tenant_id}: "
                f"trial_valid={has_valid_trial}, subscription={subscription_status}"
            )
            return None

        # Authorized — use BYOK if available, else fall back to shared key.
        if customer_api_key:
            logger.info(
                f"Using BYOK Anthropic key for tenant={tenant_id} "
                f"(trial={has_valid_trial}, subscription={subscription_status})"
            )
            return {"api_key": customer_api_key}

        shared_key = get_shared_anthropic_key()
        if not shared_key:
            logger.error(
                f"Shared Anthropic key not configured but needed for tenant={tenant_id}"
            )
            return None

        logger.info(
            f"Using shared Anthropic key for tenant={tenant_id} "
            f"(trial={has_valid_trial}, subscription={subscription_status})"
        )
        return {"api_key": shared_key, "workspace_attribution": tenant_id}

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
