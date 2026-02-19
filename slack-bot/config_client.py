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

# Local mode configuration
# When CONFIG_MODE=local, use 'local' org instead of 'slack-{team_id}'
CONFIG_MODE = os.environ.get("CONFIG_MODE", "")

# NOTE: INCIDENTFOX_ANTHROPIC_API_KEY is no longer needed here.
# The credential-resolver fetches the shared key from Secrets Manager at runtime.
# We only store trial metadata (is_trial=True, expiration) during provisioning.

# Team token cache: slack_team_id -> (token, issued_at)
# Tokens are cached for 1 hour to avoid excessive token issuance
_team_token_cache: Dict[str, tuple] = {}
_TEAM_TOKEN_CACHE_TTL = timedelta(hours=1)


class ConfigServiceClient:
    """Client for interacting with config_service."""

    def __init__(self, base_url: str = None, admin_token: str = None):
        self.base_url = (base_url or CONFIG_SERVICE_URL).rstrip("/")
        self.admin_token = admin_token or CONFIG_SERVICE_ADMIN_TOKEN
        # Reuse TCP connections (HTTP keep-alive) across requests
        self._session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        """Get headers for admin requests."""
        return {
            "Authorization": f"Bearer {self.admin_token}",
            "Content-Type": "application/json",
        }

    def _get_internal_headers(self) -> Dict[str, str]:
        """Get headers for internal service-to-service requests."""
        return {
            "X-Internal-Service": "slack-bot",
            "Content-Type": "application/json",
        }

    def provision_workspace(
        self,
        slack_team_id: str,
        slack_team_name: str,
        installer_user_id: str = None,
        slack_app_slug: str = None,
    ) -> Dict[str, Any]:
        """
        Provision a new workspace in config_service.

        Creates:
        1. Organization node with slack_team_id as org_id
        2. Default team node
        3. Issues a team token for API access
        4. Issues an org admin token for org-level management

        Returns dict with org_id, team_node_id, team_token, org_admin_token, and trial info.
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        try:
            # Step 1: Create org node
            metadata = {
                "slack_team_id": slack_team_id,
                "slack_team_name": slack_team_name,
                "installer_user_id": installer_user_id,
                "provisioned_at": datetime.utcnow().isoformat(),
            }
            if slack_app_slug:
                metadata["slack_app_slug"] = slack_app_slug

            org_response = self._create_org_node(
                org_id=org_id,
                name=slack_team_name,
                metadata=metadata,
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

            # Step 4: Issue org admin token
            org_admin_token_response = self._issue_org_admin_token(org_id=org_id)
            logger.info(f"Issued org admin token for {org_id}")

            # Step 5: Set up free trial if enabled (only for NEW orgs)
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
                "org_admin_token": org_admin_token_response.get("token"),
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

        response = self._session.post(
            url, json=payload, headers=self._headers(), timeout=10
        )

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

        response = self._session.post(
            url, json=payload, headers=self._headers(), timeout=10
        )

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

        response = self._session.post(url, json={}, headers=self._headers(), timeout=10)
        response.raise_for_status()
        return response.json()

    def list_team_nodes(self, org_id: str) -> list:
        """List all team nodes in an org.

        Returns:
            List of node dicts with org_id, node_id, parent_id, node_type, name.
            Returns empty list on error.
        """
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/nodes"
        try:
            response = self._session.get(url, headers=self._headers(), timeout=10)
            response.raise_for_status()
            return [n for n in response.json() if n.get("node_type") == "team"]
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to list team nodes for {org_id}: {e}")
            return []

    def setup_team(
        self,
        slack_team_id: str,
        team_node_id: str,
        team_name: str,
        channel_id: str,
    ) -> Dict[str, Any]:
        """Create a team node, mint a token, and wire a channel to it.

        Args:
            slack_team_id: Slack workspace ID
            team_node_id: Desired team node ID (slug)
            team_name: Human-readable team name
            channel_id: Slack channel ID to route to this team

        Returns:
            Dict with team_node_id, token, already_existed.

        Raises:
            requests.exceptions.RequestException on network/server errors.
        """
        if CONFIG_MODE == "local":
            org_id = "local"
        else:
            org_id = f"slack-{slack_team_id}"

        # Create team node (idempotent — returns exists: True if duplicate)
        create_result = self._create_team_node(org_id, team_node_id, team_name)
        already_existed = create_result.get("exists", False)

        if already_existed:
            return {
                "team_node_id": team_node_id,
                "token": None,
                "already_existed": True,
            }

        # Mint team token
        token_response = self._issue_team_token(org_id, team_node_id)
        token = token_response.get("token")

        # Wire channel to this team
        self._update_config(
            org_id,
            team_node_id,
            {"routing": {"slack_channel_ids": [channel_id]}},
        )

        return {
            "team_node_id": team_node_id,
            "token": token,
            "already_existed": False,
        }

    def get_team_token(self, slack_team_id: str) -> Optional[str]:
        """
        Get a team token for Config Service API access.

        This token enables config-driven agents - the agent can use it to
        load team configuration (agent definitions, tools, LLM settings, etc.)
        from Config Service.

        Tokens are cached for 1 hour to avoid excessive token issuance.

        Args:
            slack_team_id: Slack team ID

        Returns:
            Team token string, or None if workspace not provisioned.
        """
        global _team_token_cache

        # Check cache first
        if slack_team_id in _team_token_cache:
            token, issued_at = _team_token_cache[slack_team_id]
            if datetime.utcnow() - issued_at < _TEAM_TOKEN_CACHE_TTL:
                return token
            # Token expired, remove from cache
            del _team_token_cache[slack_team_id]

        # Issue new token
        # In local mode, use 'local' org instead of per-workspace orgs
        if CONFIG_MODE == "local":
            org_id = "local"
        else:
            org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        try:
            token_response = self._issue_team_token(org_id, team_node_id)
            token = token_response.get("token")
            if token:
                _team_token_cache[slack_team_id] = (token, datetime.utcnow())
                logger.debug(f"Issued team token for workspace {slack_team_id}")
                return token
            return None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                # Workspace not provisioned
                logger.warning(f"Workspace {slack_team_id} not provisioned")
                return None
            logger.error(f"Failed to issue team token for {slack_team_id}: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to issue team token for {slack_team_id}: {e}")
            return None

    def lookup_routing(
        self, channel_id: str, workspace_id: str = None
    ) -> Optional[Dict[str, str]]:
        """
        Look up team routing for a Slack message.

        Sends both channel ID and workspace ID to the routing endpoint.
        The endpoint tries channel-level routing first (specific team),
        then falls back to workspace-level routing (default team).

        Args:
            channel_id: Slack channel ID (e.g., "C0ADSDTFF41")
            workspace_id: Slack workspace ID (e.g., "T09UF9JAHD1") for fallback routing

        Returns:
            Dict with org_id and team_node_id if a match is found, None otherwise.
        """
        url = f"{self.base_url}/api/v1/internal/routing/lookup"
        headers = {
            "X-Internal-Service": "slack-bot",
            "Content-Type": "application/json",
        }
        identifiers = {"slack_channel_id": channel_id}
        if workspace_id:
            identifiers["slack_workspace_id"] = workspace_id
        payload = {"identifiers": identifiers}

        try:
            response = self._session.post(
                url, json=payload, headers=headers, timeout=10
            )
            response.raise_for_status()
            result = response.json()

            if result.get("found"):
                logger.info(
                    f"Routing found: channel={channel_id} -> "
                    f"org={result['org_id']}, team={result['team_node_id']} "
                    f"(matched_by={result.get('matched_by')})"
                )
                return {
                    "org_id": result["org_id"],
                    "team_node_id": result["team_node_id"],
                }

            logger.debug(
                f"No routing found for channel={channel_id}, workspace={workspace_id}"
            )
            return None

        except requests.exceptions.RequestException as e:
            logger.warning(f"Routing lookup failed for {channel_id}: {e}")
            return None

    def get_team_token_for_channel(
        self, slack_team_id: str, channel_id: str
    ) -> Optional[Dict[str, str]]:
        """
        Get a team token and routing info via the routing lookup.

        The routing endpoint handles both channel-level routing (specific team)
        and workspace-level fallback (default team) in a single lookup.

        Args:
            slack_team_id: Slack workspace ID (team_id)
            channel_id: Slack channel ID

        Returns:
            Dict with "token", "org_id", "team_node_id", or None if not found.
        """
        routing = self.lookup_routing(channel_id, workspace_id=slack_team_id)

        if not routing:
            logger.warning(
                f"No routing for channel={channel_id}, workspace={slack_team_id}"
            )
            return None

        org_id = routing["org_id"]
        team_node_id = routing["team_node_id"]

        try:
            token_response = self._issue_team_token(org_id, team_node_id)
            token = token_response.get("token")
            if token:
                logger.debug(f"Issued team token for org={org_id}, team={team_node_id}")
                return {"token": token, "org_id": org_id, "team_node_id": team_node_id}
            return None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"Team not found: org={org_id}, team={team_node_id}")
                return None
            logger.error(f"Failed to issue team token: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to issue team token: {e}")
            return None

    def _issue_org_admin_token(
        self,
        org_id: str,
    ) -> Dict[str, Any]:
        """Issue an org admin token for org-level management."""
        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/admin-tokens"

        response = self._session.post(url, json={}, headers=self._headers(), timeout=10)
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

        # Store trial metadata at org level (not nested under integrations)
        # The credential-resolver checks these fields at the top level
        config = {
            "is_trial": True,
            "trial_expires_at": expires_at.isoformat(),
            "trial_started_at": datetime.utcnow().isoformat(),
            "subscription_status": "none",  # Must subscribe after trial
            "integrations": {
                "anthropic": {
                    "workspace_attribution": org_id,  # For cost tracking
                }
            },
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
        response = self._session.patch(url, json=body, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def register_local_routing(self, workspace_id: str) -> None:
        """Register the Slack workspace ID as a routing identifier in local mode.

        Called at startup in single-workspace local mode so the routing lookup
        works without requiring the user to manually configure SLACK_WORKSPACE_ID.

        Args:
            workspace_id: Slack workspace ID (e.g., "T09UF9JAHD1")
        """
        try:
            self._update_config(
                "local",
                "default",
                {"routing": {"slack_workspace_ids": [workspace_id]}},
            )
            logger.info(f"Registered local routing for workspace {workspace_id}")
        except Exception as e:
            logger.warning(f"Failed to register local routing for {workspace_id}: {e}")

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
        # In local mode, use 'local' org instead of per-workspace orgs
        if CONFIG_MODE == "local":
            org_id = "local"
        else:
            org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        url = f"{self.base_url}/api/v1/config/me"

        headers = self._headers()
        headers["X-Org-Id"] = org_id
        headers["X-Team-Node-Id"] = team_node_id

        try:
            response = self._session.get(url, headers=headers, timeout=10)
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
        # In local mode, use 'local' org instead of per-workspace orgs
        if CONFIG_MODE == "local":
            org_id = "local"
        else:
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
            response = self._session.get(
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
        # In local mode, use 'local' org instead of per-workspace orgs
        if CONFIG_MODE == "local":
            org_id = "local"
        else:
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

    # =========================================================================
    # K8s Cluster Management (SaaS Mode)
    # =========================================================================

    def create_k8s_cluster(
        self,
        slack_team_id: str,
        cluster_name: str,
        display_name: str = None,
    ) -> Dict[str, Any]:
        """
        Register a new K8s cluster and generate an API key for the agent.

        Args:
            slack_team_id: Slack team ID
            cluster_name: Unique name for the cluster (e.g., 'prod-us-east-1')
            display_name: Human-friendly display name

        Returns:
            Dict with cluster_id, cluster_name, token, and helm_install_command.
            IMPORTANT: The token is only returned once.

        Raises:
            ConfigServiceError: If the request fails or cluster name already exists.
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/teams/{team_node_id}/k8s-clusters"

        payload = {
            "cluster_name": cluster_name,
        }
        if display_name:
            payload["display_name"] = display_name

        try:
            response = self._session.post(
                url, json=payload, headers=self._headers(), timeout=30
            )

            if response.status_code == 409:
                raise ConfigServiceError(
                    f"Cluster with name '{cluster_name}' already exists",
                    status_code=409,
                    response_text=response.text,
                )

            response.raise_for_status()
            result = response.json()
            logger.info(
                f"Created K8s cluster {cluster_name} for workspace {slack_team_id}"
            )
            return result

        except requests.exceptions.RequestException as e:
            if isinstance(e, ConfigServiceError):
                raise
            logger.error(
                f"Failed to create K8s cluster for {slack_team_id}: "
                f"status={getattr(e.response, 'status_code', 'N/A')}, "
                f"error={e}"
            )
            raise ConfigServiceError(
                f"Failed to create K8s cluster: {e}",
                status_code=getattr(e.response, "status_code", None),
                response_text=getattr(e.response, "text", None),
            ) from e

    def list_k8s_clusters(
        self,
        slack_team_id: str,
        include_revoked: bool = False,
    ) -> list:
        """
        List all K8s clusters for a workspace.

        Args:
            slack_team_id: Slack team ID
            include_revoked: Whether to include revoked clusters

        Returns:
            List of cluster summary dicts with cluster_id, cluster_name,
            display_name, status, last_heartbeat_at, etc.

        Raises:
            ConfigServiceError: If the request fails.
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/teams/{team_node_id}/k8s-clusters"
        params = {}
        if include_revoked:
            params["include_revoked"] = "true"

        try:
            response = self._session.get(
                url, params=params, headers=self._headers(), timeout=10
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(
                f"Failed to list K8s clusters for {slack_team_id}: "
                f"status={getattr(e.response, 'status_code', 'N/A')}, "
                f"error={e}"
            )
            raise ConfigServiceError(
                f"Failed to list K8s clusters: {e}",
                status_code=getattr(e.response, "status_code", None),
                response_text=getattr(e.response, "text", None),
            ) from e

    def delete_k8s_cluster(
        self,
        slack_team_id: str,
        cluster_id: str,
    ) -> None:
        """
        Revoke a K8s cluster's access.

        This disconnects the agent and revokes its API token.
        The cluster record is kept for audit purposes.

        Args:
            slack_team_id: Slack team ID
            cluster_id: ID of the cluster to revoke

        Raises:
            ConfigServiceError: If the request fails or cluster not found.
        """
        org_id = f"slack-{slack_team_id}"
        team_node_id = "default"

        url = f"{self.base_url}/api/v1/admin/orgs/{org_id}/teams/{team_node_id}/k8s-clusters/{cluster_id}"

        try:
            response = self._session.delete(url, headers=self._headers(), timeout=10)

            if response.status_code == 404:
                raise ConfigServiceError(
                    f"Cluster not found: {cluster_id}",
                    status_code=404,
                    response_text=response.text,
                )

            response.raise_for_status()
            logger.info(
                f"Deleted K8s cluster {cluster_id} for workspace {slack_team_id}"
            )

        except requests.exceptions.RequestException as e:
            if isinstance(e, ConfigServiceError):
                raise
            logger.error(
                f"Failed to delete K8s cluster {cluster_id} for {slack_team_id}: "
                f"status={getattr(e.response, 'status_code', 'N/A')}, "
                f"error={e}"
            )
            raise ConfigServiceError(
                f"Failed to delete K8s cluster: {e}",
                status_code=getattr(e.response, "status_code", None),
                response_text=getattr(e.response, "text", None),
            ) from e

    # =========================================================================
    # GitHub App Installation Management
    # =========================================================================

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
            response = self._session.get(
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

    def trigger_onboarding_scan(
        self,
        org_id: str,
        team_node_id: str,
        trigger: str,
        slack_team_id: str = None,
        integration_id: str = None,
    ) -> None:
        """
        Trigger an onboarding environment scan via the AI Pipeline API.

        Fire-and-forget: failures are logged but never propagated.

        Args:
            org_id: Organization ID (e.g., "slack-T12345")
            team_node_id: Team node ID (e.g., "default")
            trigger: "initial" or "integration"
            slack_team_id: Slack team ID (required for initial trigger)
            integration_id: Integration ID (required for integration trigger)
        """
        pipeline_url = os.environ.get(
            "AI_PIPELINE_API_URL",
            "http://ai-pipeline-api-svc.incidentfox-prod.svc.cluster.local:8085",
        )

        payload = {
            "org_id": org_id,
            "team_node_id": team_node_id,
            "trigger": trigger,
        }
        if slack_team_id:
            payload["slack_team_id"] = slack_team_id
        if integration_id:
            payload["integration_id"] = integration_id

        try:
            response = self._session.post(
                f"{pipeline_url}/api/v1/scan/trigger",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if response.status_code == 200:
                logger.info(
                    f"Triggered onboarding scan: trigger={trigger}, org={org_id}"
                )
            else:
                logger.warning(
                    f"Onboarding scan trigger returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
        except Exception as e:
            logger.warning(f"Failed to trigger onboarding scan: {e}")

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
            response = self._session.post(
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

    # =========================================================================
    # Session Cache (for View Session persistence)
    # =========================================================================

    def save_session_state(
        self,
        message_ts: str,
        state_json: dict,
        thread_ts: Optional[str] = None,
        org_id: Optional[str] = None,
        team_node_id: Optional[str] = None,
    ) -> bool:
        """Persist session state to DB for the View Session modal."""
        url = f"{self.base_url}/api/v1/internal/session-cache/{message_ts}"
        payload = {
            "state_json": state_json,
            "thread_ts": thread_ts,
            "org_id": org_id,
            "team_node_id": team_node_id,
        }
        try:
            response = self._session.put(
                url,
                json=payload,
                headers=self._get_internal_headers(),
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Failed to save session state for {message_ts}: {e}")
            return False

    def get_session_state(self, message_ts: str) -> Optional[dict]:
        """Fetch persisted session state from DB. Returns state_json dict or None."""
        url = f"{self.base_url}/api/v1/internal/session-cache/{message_ts}"
        try:
            response = self._session.get(
                url,
                headers=self._get_internal_headers(),
                timeout=10,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            return data.get("state_json")
        except Exception as e:
            logger.warning(f"Failed to fetch session state for {message_ts}: {e}")
            return None


# Global client instance
_client: Optional[ConfigServiceClient] = None


def get_config_client() -> ConfigServiceClient:
    """Get or create the global config service client."""
    global _client
    if _client is None:
        _client = ConfigServiceClient()
    return _client
