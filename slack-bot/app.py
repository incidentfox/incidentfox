#!/usr/bin/env python3
"""
IncidentFox Slack Bot

Connects Slack to sre-agent for AI-powered incident investigation.
Uses chat.update for progressive disclosure UI with Block Kit.

Version: 2.0.0 - SSE streaming with structured events
"""

import logging
import os
import re

from dotenv import load_dotenv
from flask import Flask, render_template, request
from installation_store import ConfigServiceInstallationStore
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk.oauth.state_store import FileOAuthStateStore

load_dotenv()


# Import onboarding modules (lazy import to avoid circular deps)
def get_config_client():
    from config_client import get_config_client as _get_config_client

    return _get_config_client()


def get_onboarding_modules():
    import onboarding

    return onboarding


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# OAuth configuration for multi-workspace support
SLACK_CLIENT_ID = os.environ.get("SLACK_CLIENT_ID")
SLACK_CLIENT_SECRET = os.environ.get("SLACK_CLIENT_SECRET")
SLACK_SCOPES = [
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

# Check if OAuth is configured (for public distribution)
oauth_enabled = bool(SLACK_CLIENT_ID and SLACK_CLIENT_SECRET)

# Base URL for Slack OAuth redirects (configurable for staging/prod)
SLACK_BASE_URL = os.environ.get("SLACK_BASE_URL", "https://slack.incidentfox.ai")

if oauth_enabled:
    # Multi-workspace OAuth mode with database-backed installation store
    # This enables horizontal scaling (multiple replicas) and persistence
    oauth_settings = OAuthSettings(
        client_id=SLACK_CLIENT_ID,
        client_secret=SLACK_CLIENT_SECRET,
        scopes=SLACK_SCOPES,
        installation_store=ConfigServiceInstallationStore(
            client_id=SLACK_CLIENT_ID,
        ),
        # State store is ephemeral (CSRF tokens) - file store is fine
        state_store=FileOAuthStateStore(
            expiration_seconds=600, base_dir="/tmp/slack-oauth-states"
        ),
        redirect_uri=f"{SLACK_BASE_URL}/slack/oauth_redirect",
    )
    app = App(
        signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
        oauth_settings=oauth_settings,
    )
    logger.info("OAuth mode enabled (multi-workspace, database-backed)")
else:
    # Single-workspace mode (dev/testing)
    app = App(
        token=os.environ.get("SLACK_BOT_TOKEN"),
        signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    )
    logger.info("Single-workspace mode (dev/testing)")

# SRE Agent configuration
SRE_AGENT_URL = os.environ.get("SRE_AGENT_URL", "http://localhost:8000")

# Incident.io API configuration (API key fetched per-workspace from config-service)
INCIDENT_IO_API_BASE = "https://api.incident.io"

# Rate limit updates to avoid Slack API throttling
UPDATE_INTERVAL_SECONDS = 0.5

# Deployment mode: "socket" for local dev, "http" for production
SLACK_APP_MODE = os.environ.get("SLACK_APP_MODE", "socket")


# =============================================================================
# Multi-App Handler Registration
# =============================================================================


def register_all_handlers(bolt_app):
    """
    Register all event/action/view handlers on a Bolt App instance.

    Used by SlackAppRegistry to register the same handlers on multiple
    Bolt App instances (one per white-label Slack app). Handler functions
    are defined in domain-specific modules.
    """
    from investigation_handler import (
        handle_coralogix_dismiss,
        handle_coralogix_investigate,
        handle_mention,
        handle_message,
        handle_stop_listening,
    )
    from modal_handler import (
        action_button_click,
        handle_answer_submit,
        handle_checkbox_action,
        handle_feedback,
        handle_github_app_install_button,
        handle_modal_page_info,
        handle_modal_pagination,
        handle_negative_feedback,
        handle_positive_feedback,
        handle_subagent_modal_pagination,
        handle_toggle_button,
        handle_view_full_output,
        handle_view_session,
        handle_view_subagent_details,
        handle_view_tool_output,
    )
    from setup_handler import (
        handle_ai_model_config_submission,
        handle_ai_provider_change,
        handle_api_key_submission,
        handle_app_home_opened,
        handle_configure_integration,
        handle_dismiss_setup,
        handle_dismiss_welcome,
        handle_filter_category,
        handle_home_api_key_modal,
        handle_home_book_demo,
        handle_home_integration_action,
        handle_home_pagination,
        handle_home_retry_load,
        handle_integration_config_submission,
        handle_integrations_page_done,
        handle_integrations_pagination,
        handle_k8s_saas_add_cluster,
        handle_k8s_saas_add_cluster_submission,
        handle_k8s_saas_cluster_created_close,
        handle_k8s_saas_clusters_modal_close,
        handle_k8s_saas_remove_cluster,
        handle_member_joined_channel,
        handle_mention_setup_wizard,
        handle_model_options,
        handle_model_select_change,
        handle_open_ai_model_selector,
        handle_open_api_key_modal,
        handle_open_setup_wizard,
        handle_open_team_setup,
        handle_setup_team_command,
        handle_team_setup_choice,
    )

    # Command handlers
    bolt_app.command("/setup-team")(handle_setup_team_command)

    # Event handlers
    bolt_app.event("app_mention")(handle_mention)
    bolt_app.event("message")(handle_message)
    bolt_app.event("app_home_opened")(handle_app_home_opened)
    bolt_app.event("member_joined_channel")(handle_member_joined_channel)

    # Action handlers (string patterns)
    bolt_app.action("stop_listening")(handle_stop_listening)
    bolt_app.action("coralogix_investigate")(handle_coralogix_investigate)
    bolt_app.action("coralogix_dismiss")(handle_coralogix_dismiss)
    bolt_app.action("feedback_positive")(handle_positive_feedback)
    bolt_app.action("feedback_negative")(handle_negative_feedback)
    bolt_app.action("view_investigation_session")(handle_view_session)
    bolt_app.action("modal_page_prev")(handle_modal_pagination)
    bolt_app.action("modal_page_next")(handle_modal_pagination)
    bolt_app.action("modal_page_info")(handle_modal_page_info)
    bolt_app.action("view_tool_output")(handle_view_tool_output)
    bolt_app.action("view_full_output")(handle_view_full_output)
    bolt_app.action("view_subagent_details")(handle_view_subagent_details)
    bolt_app.action("subagent_modal_page_prev")(handle_subagent_modal_pagination)
    bolt_app.action("subagent_modal_page_next")(handle_subagent_modal_pagination)
    bolt_app.action("feedback")(handle_feedback)
    bolt_app.action("button_click")(action_button_click)
    bolt_app.action("github_app_install_button")(handle_github_app_install_button)
    bolt_app.action("open_api_key_modal")(handle_open_api_key_modal)
    bolt_app.action("dismiss_setup_message")(handle_dismiss_setup)
    bolt_app.action("open_setup_wizard")(handle_open_setup_wizard)
    bolt_app.action("open_team_setup")(handle_open_team_setup)
    bolt_app.action("dismiss_welcome")(handle_dismiss_welcome)
    bolt_app.action("k8s_saas_add_cluster")(handle_k8s_saas_add_cluster)
    bolt_app.action("k8s_saas_remove_cluster")(handle_k8s_saas_remove_cluster)
    bolt_app.action("home_retry_load")(handle_home_retry_load)
    bolt_app.action("home_book_demo")(handle_home_book_demo)
    bolt_app.action("home_open_api_key_modal")(handle_home_api_key_modal)
    bolt_app.action("mention_open_setup_wizard")(handle_mention_setup_wizard)
    bolt_app.action("home_open_ai_model_selector")(handle_open_ai_model_selector)
    bolt_app.action("ai_provider_select")(handle_ai_provider_change)
    bolt_app.action("input_model_id")(handle_model_select_change)

    # Action handlers (regex patterns)
    bolt_app.action(re.compile(r"^answer_q\d+_.*"))(handle_checkbox_action)
    bolt_app.action(re.compile(r"^toggle_q\d+_opt\d+_.*"))(handle_toggle_button)
    bolt_app.action(re.compile(r"^submit_answer_.*"))(handle_answer_submit)
    bolt_app.action(re.compile(r"^configure_integration_.*"))(
        handle_configure_integration
    )
    bolt_app.action(re.compile(r"^filter_category_.*"))(handle_filter_category)
    bolt_app.action(re.compile(r"^integrations_(prev|next)_page$"))(
        handle_integrations_pagination
    )
    bolt_app.action(re.compile(r"^home_page_(prev|next)$"))(handle_home_pagination)
    bolt_app.action(re.compile(r"^home_(edit|add)_integration_.*"))(
        handle_home_integration_action
    )

    # View handlers
    bolt_app.view("team_setup_choice")(handle_team_setup_choice)
    bolt_app.view("api_key_submission")(handle_api_key_submission)
    bolt_app.view("integrations_page")(handle_integrations_page_done)
    bolt_app.view("k8s_saas_add_cluster_submission")(
        handle_k8s_saas_add_cluster_submission
    )
    bolt_app.view("k8s_saas_clusters_modal")(handle_k8s_saas_clusters_modal_close)
    bolt_app.view("k8s_saas_cluster_created_modal")(
        handle_k8s_saas_cluster_created_close
    )
    bolt_app.view("integration_config_submission")(handle_integration_config_submission)
    bolt_app.view("ai_model_config_submission")(handle_ai_model_config_submission)

    # Options handlers (external_select dynamic data)
    bolt_app.options("input_model_id")(handle_model_options)


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("IncidentFox Slack Bot v2.0.0")
    logger.info("=" * 50)
    logger.info(f"Mode: {SLACK_APP_MODE.upper()}")
    logger.info(f"SRE Agent URL: {SRE_AGENT_URL}")
    logger.info("Starting...")

    # Validate required Slack credentials
    # OAuth mode (production) needs SLACK_CLIENT_ID + SLACK_CLIENT_SECRET (already validated at module level)
    # Single-workspace mode (dev) needs SLACK_BOT_TOKEN
    if not oauth_enabled:
        missing_tokens = []
        if not os.environ.get("SLACK_BOT_TOKEN"):
            missing_tokens.append("SLACK_BOT_TOKEN")
        if SLACK_APP_MODE == "socket" and not os.environ.get("SLACK_APP_TOKEN"):
            missing_tokens.append("SLACK_APP_TOKEN")

        if missing_tokens:
            logger.warning("=" * 70)
            logger.warning(
                "⚠️  Slack credentials not configured - slack-bot will not start"
            )
            logger.warning("=" * 70)
            logger.warning("")
            logger.warning(
                f"Missing environment variables: {', '.join(missing_tokens)}"
            )
            logger.warning("")
            logger.warning("To enable Slack integration, add these to your .env file:")
            logger.warning("  SLACK_BOT_TOKEN=xoxb-your-bot-token")
            logger.warning("  SLACK_APP_TOKEN=xapp-your-app-token  (for Socket Mode)")
            logger.warning("")
            logger.warning("Then restart with: docker compose restart slack-bot")
            logger.warning("=" * 70)
            exit(0)  # Exit gracefully (not an error)

    if SLACK_APP_MODE == "http":
        # Production: HTTP mode with Flask
        # Configure Flask to find templates and assets
        import os as os_module

        from app_registry import SlackAppRegistry

        base_dir = os_module.path.dirname(os_module.path.abspath(__file__))
        flask_app = Flask(
            __name__,
            template_folder=os_module.path.join(base_dir, "templates"),
            static_folder=os_module.path.join(base_dir, "assets"),
            static_url_path="/assets",
        )

        # Load multi-app registry from config service
        registry = SlackAppRegistry()
        registry.load_all()

        # Legacy handler for backward compat (default app)
        # Register handlers on the module-level app so the legacy
        # /slack/events route works (not just the slug-based routes).
        register_all_handlers(app)
        handler = SlackRequestHandler(app)

        # --- Slug-based routes (multi-app) ---

        @flask_app.route("/slack/<slug>/events", methods=["POST"])
        def slack_events_for_app(slug):
            """Handle incoming Slack events for a specific app."""
            app_handler = registry.get_handler(slug)
            if not app_handler:
                return {"error": f"Unknown app: {slug}"}, 404
            return app_handler.handle(request)

        @flask_app.route("/slack/<slug>/install", methods=["GET"])
        def slack_install_for_app(slug):
            """Initiate OAuth flow for a specific app."""
            creds = registry.get_credentials(slug)
            if not creds:
                return {"error": f"Unknown app: {slug}"}, 404

            client_id = creds.get("client_id")
            if not client_id:
                return {"error": "OAuth not configured for this app"}, 400

            import uuid

            from slack_sdk.oauth.authorize_url_generator import AuthorizeUrlGenerator

            bot_scopes = (creds.get("bot_scopes") or "").split(",")
            bot_scopes = [s.strip() for s in bot_scopes if s.strip()] or SLACK_SCOPES
            redirect_uri = creds.get("oauth_redirect_url", "")

            authorize_url_generator = AuthorizeUrlGenerator(
                client_id=client_id,
                scopes=bot_scopes,
                redirect_uri=redirect_uri,
            )

            state = str(uuid.uuid4())
            install_url = authorize_url_generator.generate(state)

            return render_template("install.html", install_url=install_url)

        @flask_app.route("/slack/<slug>/oauth_redirect", methods=["GET"])
        def slack_oauth_redirect_for_app(slug):
            """Handle OAuth callback for a specific app."""
            creds = registry.get_credentials(slug)
            if not creds:
                return {"error": f"Unknown app: {slug}"}, 404

            client_id = creds.get("client_id")
            client_secret = creds.get("client_secret")
            if not client_id or not client_secret:
                return {"error": "OAuth not configured for this app"}, 400

            redirect_uri = creds.get("oauth_redirect_url", "")

            code = request.args.get("code")
            if not code:
                error = request.args.get("error", "unknown_error")
                logger.error(f"OAuth error for app {slug}: {error}")
                return (
                    f"<html><body><h1>Installation Failed</h1><p>Error: {error}</p></body></html>",
                    400,
                )

            try:
                from slack_sdk import WebClient
                from slack_sdk.oauth.installation_store import Installation

                ws_client = WebClient()

                oauth_response = ws_client.oauth_v2_access(
                    client_id=client_id,
                    client_secret=client_secret,
                    code=code,
                    redirect_uri=redirect_uri,
                )

                if not oauth_response.get("ok"):
                    error_msg = oauth_response.get("error", "unknown_error")
                    logger.error(f"OAuth v2 access failed for app {slug}: {error_msg}")
                    return (
                        f"<html><body><h1>Installation Failed</h1><p>Error: {error_msg}</p></body></html>",
                        400,
                    )

                team_id = oauth_response["team"]["id"]
                team_name = oauth_response["team"]["name"]
                bot_token = oauth_response["access_token"]
                bot_id = oauth_response["bot_user_id"]
                bot_user_id = oauth_response["bot_user_id"]

                enterprise = oauth_response.get("enterprise") or {}
                authed_user = oauth_response.get("authed_user") or {}

                installation = Installation(
                    app_id=oauth_response.get("app_id"),
                    enterprise_id=enterprise.get("id"),
                    team_id=team_id,
                    bot_token=bot_token,
                    bot_id=bot_id,
                    bot_user_id=bot_user_id,
                    bot_scopes=oauth_response.get("scope", "").split(","),
                    user_id=authed_user.get("id"),
                    user_token=authed_user.get("access_token"),
                    user_scopes=(authed_user.get("scope") or "").split(","),
                )

                # Save via the app-specific installation store
                bolt_app_instance = registry.get_app(slug)
                if (
                    bolt_app_instance
                    and bolt_app_instance._oauth_flow
                    and bolt_app_instance._oauth_flow.settings
                ):
                    bolt_app_instance._oauth_flow.settings.installation_store.save(
                        installation
                    )
                else:
                    # Fallback: use a direct store with slug
                    store = ConfigServiceInstallationStore(
                        client_id=client_id,
                        slack_app_slug=slug,
                    )
                    store.save(installation)

                logger.info(
                    f"Successfully installed app {slug} for team {team_name} ({team_id})"
                )

                # Provision workspace in config_service
                trial_enabled = False
                try:
                    config_client = get_config_client()
                    provision_result = config_client.provision_workspace(
                        slack_team_id=team_id,
                        slack_team_name=team_name,
                        installer_user_id=authed_user.get("id"),
                        slack_app_slug=slug,
                    )
                    logger.info(
                        f"Provisioned workspace in config_service: {provision_result}"
                    )
                    trial_enabled = provision_result.get("trial_info", {}).get(
                        "enabled", False
                    )
                except Exception as provision_error:
                    logger.warning(
                        f"Failed to provision workspace in config_service: {provision_error}"
                    )
                    provision_result = None

                # Send welcome DM to installer
                installer_user_id = authed_user.get("id")
                if installer_user_id and bot_token:
                    try:
                        from slack_sdk import WebClient

                        dm_client = WebClient(token=bot_token)
                        dm_response = dm_client.conversations_open(
                            users=[installer_user_id]
                        )
                        dm_channel = dm_response.get("channel", {}).get("id")

                        if dm_channel:
                            onboarding = get_onboarding_modules()
                            trial_info = (
                                provision_result.get("trial_info")
                                if provision_result
                                else None
                            )
                            display_name = creds.get("display_name", "IncidentFox")
                            welcome_blocks = onboarding.build_welcome_message(
                                trial_info=trial_info, team_name=team_name
                            )
                            dm_client.chat_postMessage(
                                channel=dm_channel,
                                text=f"Welcome to {display_name}!",
                                blocks=welcome_blocks,
                            )
                            logger.info(
                                f"Sent welcome DM to installer {installer_user_id}"
                            )
                    except Exception as dm_error:
                        logger.warning(f"Failed to send welcome DM: {dm_error}")

                # Trigger onboarding scan (fire-and-forget, never blocks OAuth)
                if provision_result:
                    import threading

                    def _trigger_initial_scan():
                        try:
                            scan_client = get_config_client()
                            scan_client.trigger_onboarding_scan(
                                org_id=provision_result["org_id"],
                                team_node_id=provision_result["team_node_id"],
                                trigger="initial",
                                slack_team_id=team_id,
                            )
                        except Exception as scan_err:
                            logger.warning(
                                f"Onboarding scan trigger failed: {scan_err}"
                            )

                    threading.Thread(target=_trigger_initial_scan, daemon=True).start()

                return render_template(
                    "success.html",
                    team_name=team_name,
                    team_id=team_id,
                    trial_enabled=trial_enabled,
                )

            except Exception as e:
                logger.error(f"OAuth error for app {slug}: {e}", exc_info=True)
                return (
                    "<html><body><h1>Installation Failed</h1><p>An unexpected error occurred. Please try again.</p></body></html>",
                    500,
                )

        # --- Legacy routes (backward compat, forward to default app) ---

        @flask_app.route("/slack/events", methods=["POST"])
        def slack_events():
            """Legacy: Handle Slack events for default app."""
            return handler.handle(request)

        @flask_app.route("/slack/install", methods=["GET"])
        def slack_install():
            """Legacy: Initiate OAuth for default app."""
            default = registry.default_slug
            if default:
                return slack_install_for_app(default)
            # Fallback to original behavior
            if not oauth_enabled:
                return {"error": "OAuth not configured"}, 400

            import uuid

            from slack_sdk.oauth.authorize_url_generator import AuthorizeUrlGenerator

            authorize_url_generator = AuthorizeUrlGenerator(
                client_id=SLACK_CLIENT_ID,
                scopes=SLACK_SCOPES,
                redirect_uri=oauth_settings.redirect_uri,
            )

            state = str(uuid.uuid4())
            install_url = authorize_url_generator.generate(state)
            return render_template("install.html", install_url=install_url)

        @flask_app.route("/slack/oauth_redirect", methods=["GET"])
        def slack_oauth_redirect():
            """Legacy: Handle OAuth callback for default app."""
            default = registry.default_slug
            if default:
                return slack_oauth_redirect_for_app(default)
            return {"error": "No app configured"}, 500

        @flask_app.route("/health", methods=["GET"])
        def health():
            """Health check endpoint."""
            return {"status": "healthy", "apps": registry.list_slugs()}, 200

        port = int(os.environ.get("PORT", 3000))
        logger.info(f"Starting HTTP server on port {port}")
        logger.info(f"Apps loaded: {registry.list_slugs()}")
        flask_app.run(host="0.0.0.0", port=port)
    else:
        # Local dev: Socket Mode
        # Register all handlers on the app instance (in HTTP mode, this is done by SlackAppRegistry)
        register_all_handlers(app)

        # In local mode, auto-register the workspace routing so the routing lookup
        # works without requiring the user to manually set SLACK_WORKSPACE_ID.
        if os.environ.get("CONFIG_MODE", "").lower() == "local":
            try:
                auth_resp = app.client.auth_test()
                workspace_id = auth_resp.get("team_id")
                if workspace_id:
                    get_config_client().register_local_routing(workspace_id)
            except Exception as e:
                logger.warning(f"Could not auto-register local routing: {e}")

        handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
        handler.start()
