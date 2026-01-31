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

# IncidentFox's API key for free trial (managed by us)
INCIDENTFOX_ANTHROPIC_API_KEY = os.environ.get("INCIDENTFOX_ANTHROPIC_API_KEY", "")


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

            # Step 4: Set up free trial if enabled
            trial_info = None
            if FREE_TRIAL_ENABLED and INCIDENTFOX_ANTHROPIC_API_KEY:
                trial_info = self._setup_free_trial(org_id, team_node_id)
                logger.info(
                    f"Free trial enabled for {org_id}: expires {trial_info.get('expires_at')}"
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
        url = f"{self.base_url}/api/v2/config"

        headers = self._headers()
        headers["X-Org-Id"] = org_id
        headers["X-Team-Node-Id"] = team_node_id

        response = requests.patch(url, json=config, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_workspace_config(
        self,
        slack_team_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get configuration for a Slack workspace."""
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        url = f"{self.base_url}/api/v2/config/effective"

        headers = self._headers()
        headers["X-Org-Id"] = org_id
        headers["X-Team-Node-Id"] = team_node_id

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get workspace config: {e}")
            return None

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

    def activate_subscription(self, slack_team_id: str) -> bool:
        """Activate subscription for a workspace (called after payment).

        Sets subscription_status to "active", allowing BYOK access.
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
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to activate subscription: {e}")
            return False

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
    ) -> bool:
        """Save user's Anthropic API key."""
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
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to save API key: {e}")
            return False


# Global client instance
_client: Optional[ConfigServiceClient] = None


def get_config_client() -> ConfigServiceClient:
    """Get or create the global config service client."""
    global _client
    if _client is None:
        _client = ConfigServiceClient()
    return _client
