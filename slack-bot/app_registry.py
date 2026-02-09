"""
Multi-app Slack Bot registry.

Manages multiple Slack Bolt App instances, one per configured Slack app
(white-label support). Each App has its own signing_secret, client_id,
and client_secret. Handlers are shared across all apps.

Usage:
    registry = SlackAppRegistry(config_service_url="http://...")
    registry.load_all()

    handler = registry.get_handler("incidentfox")
    handler.handle(flask_request)
"""

import logging
import os
from typing import Dict, Optional

import requests
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk.oauth.state_store import FileOAuthStateStore

from installation_store import ConfigServiceInstallationStore

logger = logging.getLogger(__name__)

CONFIG_SERVICE_URL = os.environ.get(
    "CONFIG_SERVICE_URL",
    "http://config-service-svc.incidentfox-prod.svc.cluster.local:8080",
)


class SlackAppRegistry:
    """
    Registry of Slack Bolt App instances, one per configured Slack app.

    Loads app configurations from the config service and creates a Bolt App
    per slug. All apps share the same event/action/view handlers but have
    independent signing secrets and OAuth credentials.
    """

    def __init__(self, config_service_url: str = None):
        self._config_service_url = (config_service_url or CONFIG_SERVICE_URL).rstrip("/")
        self._apps: Dict[str, App] = {}
        self._handlers: Dict[str, SlackRequestHandler] = {}
        self._credentials: Dict[str, dict] = {}

    def load_all(self):
        """Fetch all active Slack apps from config service and create Bolt instances."""
        try:
            response = requests.get(
                f"{self._config_service_url}/api/v1/internal/slack/apps",
                headers={"X-Internal-Service": "slack-bot"},
                timeout=15,
            )
            response.raise_for_status()
            apps = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to load Slack apps from config service: {e}")
            apps = []

        if not apps:
            logger.warning("No Slack apps found in config service, falling back to env vars")
            self._create_from_env()
            return

        for app_config in apps:
            try:
                self._create_bolt_app(app_config)
            except Exception as e:
                logger.error(
                    f"Failed to create Bolt app for slug={app_config.get('slug')}: {e}"
                )

        logger.info(f"Loaded {len(self._apps)} Slack app(s): {list(self._apps.keys())}")

    def _create_from_env(self):
        """Fallback: create a single app from environment variables (backward compat)."""
        signing_secret = os.environ.get("SLACK_SIGNING_SECRET")
        client_id = os.environ.get("SLACK_CLIENT_ID")
        client_secret = os.environ.get("SLACK_CLIENT_SECRET")
        bot_token = os.environ.get("SLACK_BOT_TOKEN")
        base_url = os.environ.get("SLACK_BASE_URL", "https://slack.incidentfox.ai")

        slug = "default"

        if client_id and client_secret:
            oauth_settings = OAuthSettings(
                client_id=client_id,
                client_secret=client_secret,
                scopes=_default_scopes(),
                installation_store=ConfigServiceInstallationStore(
                    client_id=client_id,
                    slack_app_slug=slug,
                ),
                state_store=FileOAuthStateStore(
                    expiration_seconds=600, base_dir="/tmp/slack-oauth-states"
                ),
                redirect_uri=f"{base_url}/slack/{slug}/oauth_redirect",
            )
            bolt_app = App(
                signing_secret=signing_secret,
                oauth_settings=oauth_settings,
            )
        else:
            bolt_app = App(
                token=bot_token,
                signing_secret=signing_secret,
            )

        self._register_handlers(bolt_app)
        self._apps[slug] = bolt_app
        self._handlers[slug] = SlackRequestHandler(bolt_app)
        self._credentials[slug] = {
            "slug": slug,
            "display_name": "IncidentFox",
            "client_id": client_id,
            "client_secret": client_secret,
            "signing_secret": signing_secret,
            "oauth_redirect_url": f"{base_url}/slack/{slug}/oauth_redirect",
            "bot_scopes": ",".join(_default_scopes()),
        }
        logger.info(f"Created default app from env vars (slug={slug})")

    def _create_bolt_app(self, app_config: dict):
        """Create a Bolt App from a config service app record."""
        slug = app_config["slug"]
        signing_secret = app_config.get("signing_secret")
        client_id = app_config.get("client_id")
        client_secret = app_config.get("client_secret")
        bot_scopes = (app_config.get("bot_scopes") or "").split(",")
        bot_scopes = [s.strip() for s in bot_scopes if s.strip()] or _default_scopes()
        redirect_uri = app_config.get("oauth_redirect_url") or ""

        if client_id and client_secret:
            oauth_settings = OAuthSettings(
                client_id=client_id,
                client_secret=client_secret,
                scopes=bot_scopes,
                installation_store=ConfigServiceInstallationStore(
                    client_id=client_id,
                    slack_app_slug=slug,
                ),
                state_store=FileOAuthStateStore(
                    expiration_seconds=600,
                    base_dir=f"/tmp/slack-oauth-states-{slug}",
                ),
                redirect_uri=redirect_uri,
            )
            bolt_app = App(
                signing_secret=signing_secret,
                oauth_settings=oauth_settings,
            )
        else:
            bolt_app = App(
                signing_secret=signing_secret,
            )

        self._register_handlers(bolt_app)
        self._apps[slug] = bolt_app
        self._handlers[slug] = SlackRequestHandler(bolt_app)
        self._credentials[slug] = app_config
        logger.info(f"Created Bolt app for slug={slug} (display_name={app_config.get('display_name')})")

    def _register_handlers(self, bolt_app: App):
        """Register all event/action/view handlers on a Bolt App instance."""
        # Import from app module — handlers are defined there as module-level functions
        from app import register_all_handlers

        register_all_handlers(bolt_app)

    def get_handler(self, slug: str) -> Optional[SlackRequestHandler]:
        """Get the Flask request handler for a given app slug."""
        return self._handlers.get(slug)

    def get_app(self, slug: str) -> Optional[App]:
        """Get the Bolt App for a given app slug."""
        return self._apps.get(slug)

    def get_credentials(self, slug: str) -> Optional[dict]:
        """Get the app credentials for a given slug."""
        return self._credentials.get(slug)

    def list_slugs(self) -> list:
        """List all loaded app slugs."""
        return list(self._apps.keys())

    @property
    def default_slug(self) -> Optional[str]:
        """Return the first available slug as default."""
        slugs = self.list_slugs()
        return slugs[0] if slugs else None


def _default_scopes() -> list:
    """Default Slack bot scopes."""
    return [
        "app_mentions:read",
        "channels:history",
        "channels:join",
        "channels:read",
        "chat:write",
        "chat:write.customize",
        "commands",
        "files:read",
        "files:write",
        "groups:history",
        "groups:read",
        "im:history",
        "im:read",
        "im:write",
        "links:read",
        "links:write",
        "links.embed:write",
        "metadata.message:read",
        "mpim:history",
        "mpim:read",
        "reactions:read",
        "reactions:write",
        "usergroups:read",
        "users:read",
    ]
