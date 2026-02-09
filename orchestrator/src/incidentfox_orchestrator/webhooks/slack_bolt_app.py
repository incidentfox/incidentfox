"""
Slack Bolt app for multi-tenant, multi-app webhook handling.

Integrates Slack Bolt SDK with the existing multi-tenant architecture:
- Signature verification via Bolt (automatic, per-app signing secret)
- Event handling with async background processing
- Interaction handling for feedback buttons

Supports multiple Slack apps (white-label): each app has its own
AsyncApp instance with a unique signing_secret. Apps are loaded from
the config service at startup.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Dict, Optional

from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp

if TYPE_CHECKING:
    from incidentfox_orchestrator.clients import (
        AgentApiClient,
        AuditApiClient,
        ConfigServiceClient,
    )

logger = logging.getLogger(__name__)


def create_bolt_app(signing_secret: str) -> AsyncApp:
    """
    Create Slack Bolt async app for webhook handling.

    Does not use a bot token here - tokens are resolved per-team
    when processing events via Config Service.
    """
    app = AsyncApp(
        signing_secret=signing_secret,
        # Don't use a global token - we resolve per-team
        token=None,
        # Process events asynchronously (important for 3s timeout)
        process_before_response=True,
    )

    return app


def create_bolt_handler(app: AsyncApp) -> AsyncSlackRequestHandler:
    """Create FastAPI request handler for the Bolt app."""
    return AsyncSlackRequestHandler(app)


class SlackBoltIntegration:
    """
    Manages multiple Slack Bolt app instances for multi-app support.

    Each registered Slack app (from config service) gets its own AsyncApp
    with its own signing_secret. The handler is selected by slug from the
    webhook URL path.
    """

    def __init__(
        self,
        config_service: ConfigServiceClient,
        agent_api: AgentApiClient,
        audit_api: AuditApiClient | None,
    ):
        self.config_service = config_service
        self.agent_api = agent_api
        self.audit_api = audit_api

        self._apps: Dict[str, AsyncApp] = {}
        self._handlers: Dict[str, AsyncSlackRequestHandler] = {}

        # Load apps from config service, fall back to env var
        self._load_apps()

        # Legacy: also keep a default app/handler for backward compat
        if not self._apps:
            signing_secret = (os.getenv("SLACK_SIGNING_SECRET") or "").strip()
            if signing_secret:
                self._create_app("default", signing_secret)

        # Expose first app as legacy .app/.handler for backward compat
        if self._apps:
            first_slug = next(iter(self._apps))
            self.app = self._apps[first_slug]
            self.handler = self._handlers[first_slug]
        else:
            self.app = create_bolt_app("")
            self.handler = create_bolt_handler(self.app)

    def _load_apps(self):
        """Load Slack app configs from config service."""
        try:
            apps = self.config_service.list_slack_apps()
        except Exception as e:
            logger.warning(f"Failed to load Slack apps from config service: {e}")
            apps = []

        for app_config in apps:
            slug = app_config.get("slug")
            signing_secret = app_config.get("signing_secret")
            if slug and signing_secret:
                self._create_app(slug, signing_secret)
            else:
                logger.warning(f"Skipping Slack app with missing slug or signing_secret: {app_config}")

        if apps:
            logger.info(f"Loaded {len(self._apps)} Slack app(s): {list(self._apps.keys())}")

    def _create_app(self, slug: str, signing_secret: str):
        """Create a Bolt AsyncApp for a given slug and register handlers."""
        bolt_app = create_bolt_app(signing_secret)

        from incidentfox_orchestrator.webhooks.slack_handlers import register_handlers

        register_handlers(bolt_app, self)

        self._apps[slug] = bolt_app
        self._handlers[slug] = create_bolt_handler(bolt_app)

    def get_handler(self, slug: str) -> Optional[AsyncSlackRequestHandler]:
        """Get the request handler for a specific app slug."""
        return self._handlers.get(slug)

    def get_app(self, slug: str) -> Optional[AsyncApp]:
        """Get the AsyncApp for a specific app slug."""
        return self._apps.get(slug)

    def list_slugs(self) -> list:
        """List all loaded app slugs."""
        return list(self._apps.keys())
