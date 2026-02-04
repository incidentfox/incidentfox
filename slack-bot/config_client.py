"""
Config Service Client for Slack Bot

Handles multi-tenant workspace provisioning and credential management.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class ConfigServiceError(Exception):
    """Raised when config service operations fail."""

    def __init__(
        self, message: str, status_code: int = None, response_text: str = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


# Config service URL
CONFIG_SERVICE_URL = os.environ.get(
    "CONFIG_SERVICE_URL",
    "http://config-service-svc.incidentfox-prod.svc.cluster.local:8080",
)

# Admin token for provisioning (set via environment)
CONFIG_SERVICE_ADMIN_TOKEN = os.environ.get("CONFIG_SERVICE_ADMIN_TOKEN", "")

# Free trial configuration
FREE_TRIAL_DAYS = int(os.environ.get("FREE_TRIAL_DAYS", "7"))
FREE_TRIAL_ENABLED = os.environ.get("FREE_TRIAL_ENABLED", "true").lower() == "true"

# NOTE: INCIDENTFOX_ANTHROPIC_API_KEY is no longer needed here.
# The credential-resolver fetches the shared key from Secrets Manager at runtime.
# We only store trial metadata (is_trial=True, expiration) during provisioning.


class ConfigServiceClient:
    """Client for interacting with config_service."""

    def __init__(self, base_url: str = None, admin_token: str = None):
        self.base_url = (base_url or CONFIG_SERVICE_URL).rstrip("/")
        self.admin_token = admin_token or CONFIG_SERVICE_ADMIN_TOKEN

    def _headers(self) -> Dict[str, str]:
        """Get headers for admin requests."""
        return {
            "Authorization": f"Bearer {self.admin_token}",
            "Content-Type": "application/json",
        }

    def provision_workspace(
        self,
        slack_team_id: str,
        slack_team_name: str,
        installer_user_id: str = None,
    ) -> Dict[str, Any]:
        """
        Provision a new workspace in config_service.

        Creates:
        1. Organization node with slack_team_id as org_id
        2. Default team node
        3. Issues a team token for API access

        Returns dict with org_id, team_node_id, team_token, and trial info.
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        try:
            # Step 1: Create org node
            org_response = self._create_org_node(
                org_id=org_id,
                name=slack_team_name,
                metadata={
                    "slack_team_id": slack_team_id,
                    "slack_team_name": slack_team_name,
                    "installer_user_id": installer_user_id,
                    "provisioned_at": datetime.utcnow().isoformat(),
                },
            )
            logger.info(
                f"Created org node for workspace {slack_team_name}: {org_response}"
            )

            # Step 2: Create default team node
            team_response = self._create_team_node(
                org_id=org_id,
                team_node_id=team_node_id,
                name="Default Team",
            )
            logger.info(f"Created team node: {team_response}")

            # Step 3: Issue team token
            token_response = self._issue_team_token(
                org_id=org_id,
                team_node_id=team_node_id,
            )
            logger.info(f"Issued team token for {org_id}")

            # Step 4: Set up free trial if enabled (only for NEW orgs)
            trial_info = None
            org_already_existed = org_response.get("exists", False)

            if FREE_TRIAL_ENABLED and not org_already_existed:
                # Note: We only store trial metadata here.
                # The credential-resolver fetches the actual API key from Secrets Manager.
                trial_info = self._setup_free_trial(org_id, team_node_id)
                logger.info(
                    f"Free trial enabled for {org_id}: expires {trial_info.get('expires_at')}"
                )
            elif org_already_existed:
                logger.info(
                    f"Org {org_id} already exists - skipping free trial setup (no double trials!)"
                )

            return {
                "org_id": org_id,
                "team_node_id": team_node_id,
                "team_token": token_response.get("token"),
                "trial_info": trial_info,
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to provision workspace: {e}")
            raise

    def _create_org_node(
        self, org_id: str, name: str, metadata: Dict = None
    ) -> Dict[str, Any]:
        """Create organization node."""
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/nodes"

        payload = {
            "node_id": org_id,  # Org node_id = org_id
            "node_type": "org",
            "name": name,
            "parent_id": None,
        }

        response = requests.post(url, json=payload, headers=self._headers(), timeout=10)

        # 400 might mean org already exists, which is fine
        if response.status_code == 400 and "already exists" in response.text.lower():
            logger.info(f"Org {org_id} already exists")
            return {"org_id": org_id, "exists": True}

        response.raise_for_status()
        return response.json()

    def _create_team_node(
        self,
        org_id: str,
        team_node_id: str,
        name: str,
    ) -> Dict[str, Any]:
        """Create team node under org."""
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/nodes"

        payload = {
            "node_id": team_node_id,
            "node_type": "team",
            "name": name,
            "parent_id": org_id,
        }

        response = requests.post(url, json=payload, headers=self._headers(), timeout=10)

        # 400 might mean team already exists
        if response.status_code == 400 and "already exists" in response.text.lower():
            logger.info(f"Team {team_node_id} already exists in org {org_id}")
            return {"org_id": org_id, "team_node_id": team_node_id, "exists": True}

        response.raise_for_status()
        return response.json()

    def _issue_team_token(
        self,
        org_id: str,
        team_node_id: str,
    ) -> Dict[str, Any]:
        """Issue a team token for API access."""
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/teams/{team_node_id}/tokens"

        response = requests.post(url, json={}, headers=self._headers(), timeout=10)
        response.raise_for_status()
        return response.json()

    def _setup_free_trial(
        self,
        org_id: str,
        team_node_id: str,
    ) -> Dict[str, Any]:
        """Set up free trial metadata.

        Note: We do NOT store the shared API key here. The credential-resolver
        will fetch the shared key from AWS Secrets Manager at runtime when it
        sees is_trial=True and the trial hasn't expired.

        After trial expires, user must:
        1. Activate a paid subscription
        2. Provide their own API key
        """
        expires_at = datetime.utcnow() + timedelta(days=FREE_TRIAL_DAYS)

        # Store trial metadata (not the shared key)
        # subscription_status="none" means they need to subscribe after trial
        config = {
            "integrations": {
                "anthropic": {
                    "is_trial": True,
                    "trial_expires_at": expires_at.isoformat(),
                    "trial_started_at": datetime.utcnow().isoformat(),
                    "workspace_attribution": org_id,  # For cost tracking
                    "subscription_status": "none",  # Must subscribe after trial
                }
            }
        }

        self._update_config(org_id, team_node_id, config)

        return {
            "enabled": True,
            "expires_at": expires_at.isoformat(),
            "days_remaining": FREE_TRIAL_DAYS,
        }

    def _update_config(
        self,
        org_id: str,
        team_node_id: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update node configuration."""
        url = f"{self.base_url}/api/v1/config/me"

        headers = self._headers()
        headers["X-Org-Id"] = org_id
        headers["X-Team-Node-Id"] = team_node_id

        # API expects {"config": ...} wrapper per ConfigPatchRequest schema
        body = {"config": config}
        response = requests.patch(url, json=body, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_workspace_config(
        self,
        slack_team_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get configuration for a Slack workspace.

        Returns:
            Configuration dict, or None if workspace not found (404).

        Raises:
            ConfigServiceError: If the config service request fails (non-404 errors).
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        url = f"{self.base_url}/api/v1/config/me"

        headers = self._headers()
        headers["X-Org-Id"] = org_id
        headers["X-Team-Node-Id"] = team_node_id

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 404:
                logger.info(f"No config found for workspace {slack_team_id}")
                return None
            response.raise_for_status()
            data = response.json()
            # API returns {"effective_config": {...}, "node_id": ..., ...}
            # Extract effective_config for compatibility
            return data.get("effective_config", data)
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Failed to get workspace config for {slack_team_id}: "
                f"status={getattr(e.response, 'status_code', 'N/A')}, "
                f"error={e}"
            )
            raise ConfigServiceError(
                f"Failed to get workspace config: {e}",
                status_code=getattr(e.response, "status_code", None),
                response_text=getattr(e.response, "text", None),
            ) from e

    def has_access(self, slack_team_id: str) -> bool:
        """Check if workspace has access to the service.

        Access is granted if:
        1. Workspace is on a valid (non-expired) free trial, OR
        2. Workspace has an active subscription AND has an API key configured

        Note: Having an API key alone is NOT sufficient after trial expires.
        Users must have an active subscription to continue using the service.
        """
        config = self.get_workspace_config(slack_team_id)
        if not config:
            return False

        integrations = config.get("integrations", {})
        anthropic = integrations.get("anthropic", {})

        # Case 1: Valid trial grants access
        trial_info = self.get_trial_status(slack_team_id)
        if trial_info and not trial_info.get("expired"):
            return True

        # Case 2: Active subscription + API key grants access
        subscription_status = anthropic.get("subscription_status", "none")
        api_key = anthropic.get("api_key", "")
        if subscription_status == "active" and api_key and len(api_key) > 10:
            return True

        return False

    def has_api_key(self, slack_team_id: str) -> bool:
        """Check if workspace has an API key configured.

        Note: This only checks if an API key exists, not if they have access.
        Use has_access() to check if they can actually use the service.
        """
        config = self.get_workspace_config(slack_team_id)
        if not config:
            return False

        integrations = config.get("integrations", {})
        anthropic = integrations.get("anthropic", {})
        api_key = anthropic.get("api_key", "")
        return bool(api_key and len(api_key) > 10)

    def get_subscription_status(self, slack_team_id: str) -> Dict[str, Any]:
        """Get subscription status for a workspace.

        Returns dict with:
        - status: "trial", "active", "expired", "none"
        - trial_info: Trial details if on trial
        - has_api_key: Whether they have a custom API key
        - can_access: Whether they can use the service
        """
        config = self.get_workspace_config(slack_team_id)
        if not config:
            return {
                "status": "none",
                "trial_info": None,
                "has_api_key": False,
                "can_access": False,
            }

        integrations = config.get("integrations", {})
        anthropic = integrations.get("anthropic", {})

        subscription_status = anthropic.get("subscription_status", "none")
        api_key = anthropic.get("api_key", "")
        has_key = bool(api_key and len(api_key) > 10)

        trial_info = self.get_trial_status(slack_team_id)

        # Determine effective status
        if trial_info and not trial_info.get("expired"):
            effective_status = "trial"
            can_access = True
        elif subscription_status == "active" and has_key:
            effective_status = "active"
            can_access = True
        elif trial_info and trial_info.get("expired"):
            effective_status = "expired"
            can_access = False
        else:
            effective_status = subscription_status
            can_access = False

        return {
            "status": effective_status,
            "subscription_status": subscription_status,
            "trial_info": trial_info,
            "has_api_key": has_key,
            "can_access": can_access,
        }

    def activate_subscription(self, slack_team_id: str) -> None:
        """Activate subscription for a workspace (called after payment).

        Sets subscription_status to "active", allowing BYOK access.

        Raises:
            ConfigServiceError: If the config service request fails.
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        config = {
            "integrations": {
                "anthropic": {
                    "subscription_status": "active",
                    "subscription_activated_at": datetime.utcnow().isoformat(),
                }
            }
        }

        try:
            self._update_config(org_id, team_node_id, config)
            logger.info(f"Activated subscription for workspace {slack_team_id}")
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Failed to activate subscription for {slack_team_id}: "
                f"status={getattr(e.response, 'status_code', 'N/A')}, "
                f"error={e}"
            )
            raise ConfigServiceError(
                f"Failed to activate subscription: {e}",
                status_code=getattr(e.response, "status_code", None),
                response_text=getattr(e.response, "text", None),
            ) from e

    def get_trial_status(self, slack_team_id: str) -> Optional[Dict[str, Any]]:
        """Get free trial status for a workspace."""
        config = self.get_workspace_config(slack_team_id)
        if not config:
            return None

        integrations = config.get("integrations", {})
        anthropic = integrations.get("anthropic", {})

        if not anthropic.get("is_trial"):
            return None

        expires_at_str = anthropic.get("trial_expires_at")
        if not expires_at_str:
            return None

        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            now = datetime.utcnow().replace(tzinfo=expires_at.tzinfo)
            days_remaining = max(0, (expires_at - now).days)

            return {
                "is_trial": True,
                "expires_at": expires_at_str,
                "days_remaining": days_remaining,
                "expired": days_remaining <= 0,
            }
        except (ValueError, TypeError):
            return None

    def save_api_key(
        self,
        slack_team_id: str,
        api_key: str,
        api_endpoint: str = None,
    ) -> None:
        """Save user's Anthropic API key.

        Raises:
            ConfigServiceError: If the config service request fails.
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        config = {
            "integrations": {
                "anthropic": {
                    "api_key": api_key,
                    "is_trial": False,  # Clear trial flag when user provides their own key
                }
            }
        }

        if api_endpoint:
            config["integrations"]["anthropic"]["api_endpoint"] = api_endpoint

        try:
            self._update_config(org_id, team_node_id, config)
            logger.info(f"Saved API key for workspace {slack_team_id}")
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Failed to save API key for {slack_team_id}: "
                f"status={getattr(e.response, 'status_code', 'N/A')}, "
                f"error={e}"
            )
            raise ConfigServiceError(
                f"Failed to save API key: {e}",
                status_code=getattr(e.response, "status_code", None),
                response_text=getattr(e.response, "text", None),
            ) from e

    def get_integration_schemas(
        self, category: str = None, featured: bool = None
    ) -> list:
        """
        Fetch integration schemas from config-service.

        Args:
            category: Filter by category (observability, cloud, scm, etc.)
            featured: Filter by featured flag

        Returns:
            List of integration schema dictionaries

        Raises:
            ConfigServiceError: If the config service request fails.
        """
        url = f"{self.base_url}/api/v1/integrations/schemas"
        params = {}
        if category:
            params["category"] = category
        if featured is not None:
            params["featured"] = str(featured).lower()

        try:
            response = requests.get(
                url, params=params, headers=self._headers(), timeout=10
            )
            response.raise_for_status()
            return response.json().get("integrations", [])
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Failed to get integration schemas: "
                f"status={getattr(e.response, 'status_code', 'N/A')}, "
                f"error={e}"
            )
            raise ConfigServiceError(
                f"Failed to get integration schemas: {e}",
                status_code=getattr(e.response, "status_code", None),
                response_text=getattr(e.response, "text", None),
            ) from e

    def get_configured_integrations(self, slack_team_id: str) -> dict:
        """
        Get configured integrations for a workspace.

        Returns dict of integration_id -> config, excluding 'anthropic'
        (which is handled separately as the API key).

        Args:
            slack_team_id: Slack team ID

        Returns:
            Dict mapping integration IDs to their configs
        """
        config = self.get_workspace_config(slack_team_id)
        if not config:
            return {}

        integrations = config.get("integrations", {})
        # Filter out anthropic (API key) and empty configs
        return {
            k: v
            for k, v in integrations.items()
            if k != "anthropic" and v and isinstance(v, dict)
        }

    def get_integration_config(
        self, slack_team_id: str, integration_id: str
    ) -> Optional[dict]:
        """
        Get configuration for a specific integration.

        Args:
            slack_team_id: Slack team ID
            integration_id: Integration identifier (e.g., "anthropic", "datadog")

        Returns:
            Integration config dict or None if not configured
        """
        config = self.get_workspace_config(slack_team_id)
        if not config:
            return None

        integrations = config.get("integrations", {})
        return integrations.get(integration_id)

    def save_integration_config(
        self, slack_team_id: str, integration_id: str, config: dict
    ) -> None:
        """
        Save configuration for a specific integration.

        Args:
            slack_team_id: Slack team ID
            integration_id: Integration identifier (e.g., "datadog", "cloudwatch")
            config: Configuration dict for the integration

        Raises:
            ConfigServiceError: If the config service request fails.
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        update = {"integrations": {integration_id: config}}

        try:
            self._update_config(org_id, team_node_id, update)
            logger.info(f"Saved {integration_id} config for workspace {slack_team_id}")
        except requests.exceptions.RequestException as e:
            logger.error(
                f"Failed to save {integration_id} config for {slack_team_id}: "
                f"status={getattr(e.response, 'status_code', 'N/A')}, "
                f"error={e}"
            )
            raise ConfigServiceError(
                f"Failed to save {integration_id} config: {e}",
                status_code=getattr(e.response, "status_code", None),
                response_text=getattr(e.response, "text", None),
            ) from e

    def get_linked_github_installation(self, slack_team_id: str) -> dict | None:
        """
        Get the GitHub installation linked to this Slack workspace.

        Args:
            slack_team_id: Slack team ID

        Returns:
            Installation dict with account_login, installation_id, etc. or None if not linked.
        """
        org_id = f"slack-{slack_team_id}"

        url = f"{self.base_url}/api/v1/internal/github/installations"

        try:
            response = requests.get(
                url,
                params={"org_id": org_id, "status": "active", "limit": 1},
                headers=self._get_internal_headers(),
                timeout=10,
            )
            response.raise_for_status()
            installations = response.json()
            if installations:
                return installations[0]
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(
                f"Failed to get linked GitHub installation for {slack_team_id}: {e}"
            )
            return None

    def link_github_installation(self, slack_team_id: str, github_org: str) -> dict:
        """
        Link a GitHub installation to this Slack workspace.

        Args:
            slack_team_id: Slack team ID
            github_org: GitHub org or username (account_login from GitHub App installation)

        Returns:
            dict with installation details and status message

        Raises:
            ConfigServiceError: If linking fails (not found, already linked, etc.)
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        url = f"{self.base_url}/api/v1/internal/github/installations/link-by-account"

        try:
            response = requests.post(
                url,
                json={
                    "account_login": github_org,
                    "org_id": org_id,
                    "team_node_id": team_node_id,
                },
                headers=self._get_internal_headers(),
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(
                f"Linked GitHub installation '{github_org}' to workspace {slack_team_id}"
            )
            return result
        except requests.exceptions.RequestException as e:
            status_code = getattr(e.response, "status_code", None)
            response_text = getattr(e.response, "text", None)

            # Try to extract error detail from response
            error_detail = None
            if response_text:
                try:
                    error_json = e.response.json()
                    error_detail = error_json.get("detail")
                except Exception:
                    pass

            logger.error(
                f"Failed to link GitHub installation '{github_org}' for {slack_team_id}: "
                f"status={status_code}, error={error_detail or response_text}"
            )
            raise ConfigServiceError(
                error_detail or f"Failed to link GitHub: {e}",
                status_code=status_code,
                response_text=response_text,
            ) from e


# Global client instance
_client: Optional[ConfigServiceClient] = None


def get_config_client() -> ConfigServiceClient:
    """Get or create the global config service client."""
    global _client
    if _client is None:
        _client = ConfigServiceClient()
    return _client
