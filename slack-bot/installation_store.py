"""
Config Service Installation Store for Slack OAuth

Implements the Slack SDK InstallationStore interface using the config-service
database for persistent, horizontally-scalable OAuth token storage.

This replaces FileInstallationStore to enable:
- Multiple slack-bot replicas (HPA)
- Token persistence across pod restarts
- Centralized token management
"""

import logging
import os
from typing import Optional

import requests
from slack_sdk.oauth.installation_store import Bot, Installation, InstallationStore

logger = logging.getLogger(__name__)

# Config service URL
CONFIG_SERVICE_URL = os.environ.get(
    "CONFIG_SERVICE_URL",
    "http://config-service-svc.incidentfox-prod.svc.cluster.local:8080",
)


class ConfigServiceInstallationStore(InstallationStore):
    """
    Slack OAuth InstallationStore backed by the config-service database.

    Uses internal API endpoints to store and retrieve Slack installations.
    """

    def __init__(
        self,
        base_url: str = None,
        service_name: str = "slack-bot",
        client_id: str = None,
    ):
        self.base_url = (base_url or CONFIG_SERVICE_URL).rstrip("/")
        self.service_name = service_name
        self.client_id = client_id

    def _headers(self):
        """Headers for internal service calls."""
        return {
            "Content-Type": "application/json",
            "X-Internal-Service": self.service_name,
        }

    def save(self, installation: Installation):
        """
        Save an installation to the config-service.

        Called by the Slack SDK after a successful OAuth flow.
        Saves both bot-level (user_id=None) and user-level installations.
        """
        logger.info(
            f"Saving installation for team {installation.team_id} "
            f"(enterprise: {installation.enterprise_id}, user: {installation.user_id})"
        )

        # Always save a bot-level installation (user_id=None) for event handling
        # This is required for the Slack SDK to authorize incoming events
        if installation.bot_token:
            bot_payload = {
                "enterprise_id": installation.enterprise_id,
                "team_id": installation.team_id,
                "user_id": None,  # Bot-level installation
                "app_id": installation.app_id,
                "bot_token": installation.bot_token,
                "bot_id": installation.bot_id,
                "bot_user_id": installation.bot_user_id,
                "bot_scopes": installation.bot_scopes,
                "user_token": None,  # No user token for bot installation
                "user_scopes": None,
                "is_enterprise_install": installation.is_enterprise_install or False,
                "token_type": installation.token_type,
            }

            if installation.incoming_webhook_url:
                bot_payload["incoming_webhook_url"] = installation.incoming_webhook_url
                bot_payload["incoming_webhook_channel"] = (
                    installation.incoming_webhook_channel
                )
                bot_payload["incoming_webhook_channel_id"] = (
                    installation.incoming_webhook_channel_id
                )
                bot_payload["incoming_webhook_configuration_url"] = (
                    installation.incoming_webhook_configuration_url
                )

            try:
                response = requests.post(
                    f"{self.base_url}/api/v1/internal/slack/installations",
                    json=bot_payload,
                    headers=self._headers(),
                    timeout=10,
                )
                response.raise_for_status()
                logger.info(f"Bot installation saved for team {installation.team_id}")
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to save bot installation: {e}")
                raise

        # Also save user-level installation if we have a user_id
        if installation.user_id:
            user_payload = {
                "enterprise_id": installation.enterprise_id,
                "team_id": installation.team_id,
                "user_id": installation.user_id,
                "app_id": installation.app_id,
                "bot_token": installation.bot_token,
                "bot_id": installation.bot_id,
                "bot_user_id": installation.bot_user_id,
                "bot_scopes": installation.bot_scopes,
                "user_token": installation.user_token,
                "user_scopes": installation.user_scopes,
                "is_enterprise_install": installation.is_enterprise_install or False,
                "token_type": installation.token_type,
            }

            if installation.incoming_webhook_url:
                user_payload["incoming_webhook_url"] = installation.incoming_webhook_url
                user_payload["incoming_webhook_channel"] = (
                    installation.incoming_webhook_channel
                )
                user_payload["incoming_webhook_channel_id"] = (
                    installation.incoming_webhook_channel_id
                )
                user_payload["incoming_webhook_configuration_url"] = (
                    installation.incoming_webhook_configuration_url
                )

            try:
                response = requests.post(
                    f"{self.base_url}/api/v1/internal/slack/installations",
                    json=user_payload,
                    headers=self._headers(),
                    timeout=10,
                )
                response.raise_for_status()
                logger.info(
                    f"User installation saved for team {installation.team_id}, user {installation.user_id}"
                )
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to save user installation: {e}")
                # Don't raise - user installation is secondary to bot installation

    def find_installation(
        self,
        *,
        enterprise_id: Optional[str] = None,
        team_id: Optional[str] = None,
        user_id: Optional[str] = None,
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Installation]:
        """
        Find an installation by team_id, enterprise_id, and optionally user_id.

        Called by the Slack SDK to retrieve bot tokens for incoming events.
        """
        if not team_id:
            logger.warning("find_installation called without team_id")
            return None

        # Log at INFO level for debugging
        logger.info(
            f"find_installation called: team_id={team_id}, "
            f"enterprise_id={enterprise_id}, user_id={user_id}, "
            f"is_enterprise_install={is_enterprise_install}"
        )

        params = {
            "team_id": team_id,
            "is_enterprise_install": is_enterprise_install or False,
        }
        if enterprise_id:
            params["enterprise_id"] = enterprise_id
        if user_id:
            params["user_id"] = user_id

        try:
            response = requests.get(
                f"{self.base_url}/api/v1/internal/slack/installations/find",
                params=params,
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()

            data = response.json()
            if not data:
                logger.debug(f"No installation found for team {team_id}")
                return None

            # Convert response to Installation object
            installation = Installation(
                app_id=data.get("app_id"),
                enterprise_id=data.get("enterprise_id"),
                team_id=data.get("team_id"),
                user_id=data.get("user_id"),
                bot_token=data.get("bot_token"),
                bot_id=data.get("bot_id"),
                bot_user_id=data.get("bot_user_id"),
                bot_scopes=data.get("bot_scopes"),
                user_token=data.get("user_token"),
                user_scopes=data.get("user_scopes"),
                incoming_webhook_url=data.get("incoming_webhook_url"),
                incoming_webhook_channel=data.get("incoming_webhook_channel"),
                incoming_webhook_channel_id=data.get("incoming_webhook_channel_id"),
                incoming_webhook_configuration_url=data.get(
                    "incoming_webhook_configuration_url"
                ),
                is_enterprise_install=data.get("is_enterprise_install", False),
                token_type=data.get("token_type"),
            )

            logger.debug(f"Found installation for team {team_id}")
            return installation

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to find installation: {e}")
            return None

    def find_bot(
        self,
        *,
        enterprise_id: Optional[str] = None,
        team_id: Optional[str] = None,
        is_enterprise_install: Optional[bool] = False,
    ) -> Optional[Bot]:
        """
        Find a bot installation (workspace-level, no user_id).

        Called by the Slack SDK for bot-level operations.
        """
        installation = self.find_installation(
            enterprise_id=enterprise_id,
            team_id=team_id,
            user_id=None,  # Bot installation has no user_id
            is_enterprise_install=is_enterprise_install,
        )

        if not installation:
            return None

        return Bot(
            app_id=installation.app_id,
            enterprise_id=installation.enterprise_id,
            team_id=installation.team_id,
            bot_token=installation.bot_token,
            bot_id=installation.bot_id,
            bot_user_id=installation.bot_user_id,
            bot_scopes=installation.bot_scopes,
            is_enterprise_install=installation.is_enterprise_install,
        )

    def delete_installation(
        self,
        *,
        enterprise_id: Optional[str] = None,
        team_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Delete an installation.

        Called when an app is uninstalled from a workspace.
        """
        if not team_id:
            logger.warning("delete_installation called without team_id")
            return

        logger.info(
            f"Deleting installation for team {team_id} "
            f"(enterprise: {enterprise_id}, user: {user_id})"
        )

        params = {"team_id": team_id}
        if enterprise_id:
            params["enterprise_id"] = enterprise_id
        if user_id:
            params["user_id"] = user_id

        try:
            response = requests.delete(
                f"{self.base_url}/api/v1/internal/slack/installations",
                params=params,
                headers=self._headers(),
                timeout=10,
            )
            # 404 is okay - installation might already be deleted
            if response.status_code != 404:
                response.raise_for_status()
            logger.info(f"Installation deleted for team {team_id}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to delete installation: {e}")
            # Don't raise - deletion failures shouldn't break uninstall flow

    def delete_bot(
        self,
        *,
        enterprise_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """
        Delete a bot installation.

        Called when a bot is removed from a workspace.
        """
        self.delete_installation(
            enterprise_id=enterprise_id,
            team_id=team_id,
            user_id=None,
        )
