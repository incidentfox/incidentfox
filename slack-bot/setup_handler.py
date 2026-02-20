"""
Setup, onboarding, configuration, and home tab handlers.

Handles API key setup, team provisioning, integration configuration,
K8s cluster management, AI model selection, and App Home tab rendering.
"""

import json
import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)


def get_config_client():
    from config_client import get_config_client as _get_config_client

    return _get_config_client()


def get_onboarding_modules():
    import onboarding

    return onboarding


# =============================================================================
# Onboarding: API Key Setup Modal
# =============================================================================


def handle_open_api_key_modal(ack, body, client):
    """Open the API key setup modal."""
    ack()

    team_id = body.get("team", {}).get("id")
    if not team_id:
        logger.error("No team_id in body for API key modal")
        return

    try:
        # Get trial status
        config_client = get_config_client()
        trial_info = config_client.get_trial_status(team_id)

        # Build and open modal
        onboarding = get_onboarding_modules()
        modal = onboarding.build_api_key_modal(team_id, trial_info=trial_info)

        client.views_open(trigger_id=body["trigger_id"], view=modal)
        logger.info(f"Opened API key modal for team {team_id}")
    except Exception as e:
        logger.error(f"Failed to open API key modal: {e}", exc_info=True)


def handle_dismiss_setup(ack, body, client):
    """Dismiss the setup prompt message."""
    ack()
    # Optionally delete or update the message
    try:
        channel = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        if channel and message_ts:
            client.chat_update(
                channel=channel,
                ts=message_ts,
                text="You can still use me! Mention me anytime you need help.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                ":wave: No problem! You can still mention me and I'll help you investigate issues.\n\n"
                                "This was just a nudge to set up more integrations for better insights. "
                                "You can always configure them later!"
                            ),
                        },
                    }
                ],
            )
    except Exception as e:
        logger.warning(f"Failed to update dismissed message: {e}")


def handle_api_key_submission(ack, body, client, view):
    """Handle API key modal submission."""
    team_id = view.get("private_metadata")
    values = view.get("state", {}).get("values", {})

    # Extract values
    api_key = (
        values.get("api_key_block", {})
        .get("api_key_input", {})
        .get("value", "")
        .strip()
    )
    api_endpoint = (
        values.get("api_endpoint_block", {})
        .get("api_endpoint_input", {})
        .get("value", "")
    )
    if api_endpoint:
        api_endpoint = api_endpoint.strip()

    # Validate API key
    onboarding = get_onboarding_modules()
    is_valid, error_message = onboarding.validate_api_key(api_key)

    if not is_valid:
        # Return validation error to keep modal open
        ack(response_action="errors", errors={"api_key_block": error_message})
        return

    # Save the API key
    try:
        config_client = get_config_client()
        config_client.save_api_key(
            slack_team_id=team_id,
            api_key=api_key,
            api_endpoint=api_endpoint if api_endpoint else None,
        )
    except Exception as e:
        logger.error(f"Error saving API key: {e}", exc_info=True)
        # Extract error details
        error_detail = str(e)
        status_code = getattr(e, "status_code", None)
        if status_code:
            error_detail = f"HTTP {status_code}"

        # Show error in a push modal so it's clearly visible
        error_modal = {
            "type": "modal",
            "title": {"type": "plain_text", "text": "Save Failed"},
            "close": {"type": "plain_text", "text": "Try Again"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":x: *Failed to save API key*\n\nPlease try again. If the problem persists, contact support@incidentfox.ai",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Error: {error_detail}",
                        }
                    ],
                },
            ],
        }
        ack(response_action="push", view=error_modal)
        return

    ack()

    # Send success message to user
    user_id = body.get("user", {}).get("id")
    if user_id:
        try:
            # Open a DM with the user
            dm_response = client.conversations_open(users=[user_id])
            dm_channel = dm_response.get("channel", {}).get("id")

            if dm_channel:
                success_blocks = onboarding.build_setup_complete_message()
                client.chat_postMessage(
                    channel=dm_channel,
                    text="Setup complete! Your API key has been saved.",
                    blocks=success_blocks,
                )
        except Exception as dm_error:
            logger.warning(f"Failed to send DM confirmation: {dm_error}")

    logger.info(f"API key saved for team {team_id}")


def _resolve_org_id(cc, slack_team_id, channel_id=None):
    """Resolve org_id for a Slack workspace via routing lookup.

    Tries the routing table first (matches slack_workspace_id in team configs).
    Falls back to the convention-based slack-{workspace_id} format.
    """
    if os.environ.get("CONFIG_MODE", "").lower() == "local":
        return "local", None

    routing = cc.lookup_routing(channel_id or "", workspace_id=slack_team_id)
    if routing:
        return routing["org_id"], routing
    return f"slack-{slack_team_id}", None


def _build_team_setup_modal(
    slack_team_id, channel_id, channel_name, existing_teams=None, org_id=None
):
    """Build the unified team setup modal with join dropdown + create input."""
    metadata = {
        "slack_team_id": slack_team_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
    }
    if org_id:
        metadata["org_id"] = org_id
    private_metadata = json.dumps(metadata)

    default_name = (
        re.sub(r"[^a-z0-9-]", "-", channel_name.lower()).strip("-") or "new-team"
    )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Configure team for *#{channel_name}*\n\n"
                    "This channel currently uses the workspace default configuration."
                ),
            },
        },
    ]

    # "Use existing team" section — only shown when teams exist
    if existing_teams:
        team_options = []
        for team in existing_teams:
            node_id = team.get("node_id", "")
            name = team.get("name") or node_id
            team_options.append(
                {
                    "text": {"type": "plain_text", "text": name},
                    "value": node_id,
                }
            )

        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "input",
                "block_id": "existing_team_block",
                "optional": True,
                "label": {"type": "plain_text", "text": "Use existing team"},
                "element": {
                    "type": "static_select",
                    "action_id": "existing_team_select",
                    "placeholder": {"type": "plain_text", "text": "Select a team..."},
                    "options": team_options,
                },
            }
        )

    # "Create new team" section
    blocks.append({"type": "divider"})
    create_block = {
        "type": "input",
        "block_id": "new_team_block",
        "optional": bool(existing_teams),
        "label": {"type": "plain_text", "text": "Create a new team"},
        "element": {
            "type": "plain_text_input",
            "action_id": "new_team_input",
            "placeholder": {
                "type": "plain_text",
                "text": f"e.g. {default_name}",
            },
            "max_length": 64,
        },
        "hint": {
            "type": "plain_text",
            "text": "Lowercase letters, numbers, and hyphens.",
        },
    }
    blocks.append(create_block)

    return {
        "type": "modal",
        "callback_id": "team_setup_choice",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Set Up Team"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def _open_team_setup_modal(
    client, trigger_id, slack_team_id, channel_id, channel_name, user_id=None
):
    """Open the appropriate team setup modal (choice or create).

    If existing non-default teams are found, opens the choice modal.
    Otherwise, opens the create-team modal directly.
    """
    cc = get_config_client()

    # Resolve org_id via routing lookup (finds the real org, e.g. "incidentfox-demo")
    org_id, routing = _resolve_org_id(cc, slack_team_id, channel_id)

    # Check if this channel is already routed to a non-default team
    if routing:
        team_node_id = routing.get("team_node_id", "default")
        matched_by = routing.get("matched_by", "")

        if team_node_id != "default" and matched_by == "slack_channel_id":
            web_ui_url = os.environ.get("WEB_UI_URL", "")
            msg = f"This channel is already configured as team *{team_node_id}*."
            if web_ui_url:
                msg += f"\nConfigure it at <{web_ui_url}/team/tools|Web Dashboard>."
            if user_id and channel_id:
                client.chat_postEphemeral(channel=channel_id, user=user_id, text=msg)
            return

    # Check for existing non-default teams
    existing_teams = [
        t for t in cc.list_team_nodes(org_id) if t.get("node_id") != "default"
    ]

    modal = _build_team_setup_modal(
        slack_team_id, channel_id, channel_name, existing_teams or None, org_id
    )
    client.views_open(trigger_id=trigger_id, view=modal)


def handle_setup_team_command(ack, body, client):
    """Open a modal to set up team for this channel."""
    ack()

    slack_team_id = body.get("team_id")
    channel_id = body.get("channel_id")
    channel_name = body.get("channel_name", "")
    user_id = body.get("user_id")

    if not slack_team_id or not channel_id:
        logger.error("Missing team_id or channel_id in /setup-team command")
        return

    try:
        _open_team_setup_modal(
            client=client,
            trigger_id=body["trigger_id"],
            slack_team_id=slack_team_id,
            channel_id=channel_id,
            channel_name=channel_name,
            user_id=user_id,
        )
        logger.info(
            f"Opened /setup-team modal for channel {channel_id} in workspace {slack_team_id}"
        )

    except Exception as e:
        logger.error(f"Failed to open /setup-team modal: {e}", exc_info=True)
        if user_id and channel_id:
            try:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=":warning: Failed to open team setup. Please try again.",
                )
            except Exception:
                pass


def handle_open_team_setup(ack, body, client):
    """Open the team setup modal from the channel join welcome button."""
    ack()

    slack_team_id = body.get("team", {}).get("id")
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")

    if not slack_team_id or not channel_id:
        logger.error("Missing team_id or channel_id in open_team_setup action")
        return

    try:
        # Get channel name for the modal
        channel_name = ""
        try:
            info = client.conversations_info(channel=channel_id)
            channel_name = info.get("channel", {}).get("name", "")
        except Exception:
            pass

        _open_team_setup_modal(
            client=client,
            trigger_id=body["trigger_id"],
            slack_team_id=slack_team_id,
            channel_id=channel_id,
            channel_name=channel_name,
            user_id=user_id,
        )
        logger.info(f"Opened team setup modal from button for channel {channel_id}")

    except Exception as e:
        logger.error(f"Failed to open team setup from button: {e}", exc_info=True)
        if user_id and channel_id:
            try:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=":warning: Failed to open team setup. Please try again or use `/setup-team`.",
                )
            except Exception:
                pass


def handle_team_setup_choice(ack, body, client, view):
    """Handle the unified team setup modal (join existing or create new)."""
    private_metadata = json.loads(view.get("private_metadata", "{}"))
    slack_team_id = private_metadata.get("slack_team_id")
    channel_id = private_metadata.get("channel_id")
    channel_name = private_metadata.get("channel_name", "")
    org_id = private_metadata.get("org_id")

    values = view.get("state", {}).get("values", {})

    # Check which option the user filled in
    selected_team = (
        values.get("existing_team_block", {})
        .get("existing_team_select", {})
        .get("selected_option", {})
        or {}
    ).get("value")

    new_team_name = (
        values.get("new_team_block", {}).get("new_team_input", {}).get("value", "")
        or ""
    ).strip()

    # Validate: user must pick exactly one option
    if selected_team and new_team_name:
        ack(
            response_action="errors",
            errors={
                "new_team_block": "Choose one: select an existing team OR enter a new name, not both."
            },
        )
        return

    if not selected_team and not new_team_name:
        error_block = (
            "existing_team_block"
            if "existing_team_block"
            in [b.get("block_id") for b in view.get("blocks", [])]
            else "new_team_block"
        )
        ack(
            response_action="errors",
            errors={
                error_block: "Select an existing team or enter a name for a new one."
            },
        )
        return

    cc = get_config_client()

    # Resolve org_id if not in metadata
    if not org_id:
        org_id, _ = _resolve_org_id(cc, slack_team_id, channel_id)

    # --- Path A: Join existing team ---
    if selected_team:
        team_node_id = selected_team
        try:
            cc.add_channel_to_team(org_id, team_node_id, channel_id)

            import threading

            def _trigger():
                try:
                    cc.trigger_onboarding_scan(
                        org_id=org_id,
                        team_node_id=team_node_id,
                        trigger="team_joined",
                        slack_team_id=slack_team_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to trigger scan after team join: {e}")

            threading.Thread(target=_trigger, daemon=True).start()

            web_ui_url = os.environ.get("WEB_UI_URL", "")
            confirm_blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "Team Joined"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Team:* `{team_node_id}`\n"
                            f"*Channel:* #{channel_name}\n\n"
                            "This channel now uses the team's configuration."
                        ),
                    },
                },
            ]
            if web_ui_url:
                confirm_blocks.append({"type": "divider"})
                confirm_blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"<{web_ui_url}/team/tools|Open Web Dashboard>",
                        },
                    }
                )

            ack(
                response_action="update",
                view={
                    "type": "modal",
                    "title": {"type": "plain_text", "text": "Team Joined"},
                    "close": {"type": "plain_text", "text": "Done"},
                    "blocks": confirm_blocks,
                },
            )
            logger.info(
                f"Channel {channel_id} joined team {team_node_id} in workspace {slack_team_id}"
            )

        except Exception as e:
            logger.error(f"Failed to join team: {e}", exc_info=True)
            ack(
                response_action="errors",
                errors={
                    "existing_team_block": "Something went wrong. Please try again."
                },
            )
        return

    # --- Path B: Create new team ---
    team_node_id = re.sub(r"[^a-z0-9-]", "-", new_team_name.lower()).strip("-")
    team_node_id = re.sub(r"-+", "-", team_node_id)

    if not team_node_id:
        ack(
            response_action="errors",
            errors={
                "new_team_block": "Team name must contain at least one letter or number."
            },
        )
        return

    if team_node_id == "default":
        ack(
            response_action="errors",
            errors={
                "new_team_block": '"default" is reserved. Choose a different name.'
            },
        )
        return

    try:
        result = cc.setup_team(
            slack_team_id=slack_team_id,
            team_node_id=team_node_id,
            team_name=new_team_name,
            channel_id=channel_id,
            org_id=org_id,
        )

        if result.get("already_existed"):
            ack(
                response_action="errors",
                errors={
                    "new_team_block": f'A team named "{team_node_id}" already exists. Choose a different name.'
                },
            )
            return

        token = result.get("token", "")
        web_ui_url = os.environ.get("WEB_UI_URL", "")

        import threading

        def _trigger():
            try:
                cc.trigger_onboarding_scan(
                    org_id=org_id,
                    team_node_id=team_node_id,
                    trigger="team_created",
                    slack_team_id=slack_team_id,
                )
            except Exception as e:
                logger.warning(f"Failed to trigger scan after team creation: {e}")

        threading.Thread(target=_trigger, daemon=True).start()

        # Build confirmation view with the token shown once
        confirm_blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Team Created"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Team:* `{team_node_id}`\n"
                        f"*Channel:* #{channel_name}\n\n"
                        "This channel now uses its own team configuration."
                    ),
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Save this token now — you will not see it again.*\n\n"
                        "Use it to sign in to the web dashboard where you can configure "
                        "this team's integrations, agents, and prompts."
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{token}```",
                },
            },
        ]

        if web_ui_url:
            confirm_blocks.append({"type": "divider"})
            confirm_blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"<{web_ui_url}/team/tools|Open Web Dashboard>",
                    },
                }
            )

        ack(
            response_action="update",
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Team Created"},
                "close": {"type": "plain_text", "text": "Done"},
                "blocks": confirm_blocks,
            },
        )

        logger.info(
            f"Created team {team_node_id} for channel {channel_id} in workspace {slack_team_id}"
        )

    except Exception as e:
        logger.error(f"Failed to create team: {e}", exc_info=True)
        ack(
            response_action="errors",
            errors={"new_team_block": "Something went wrong. Please try again."},
        )


def handle_open_setup_wizard(ack, body, client):
    """Open the setup wizard modal (goes directly to integrations page)."""
    ack()

    team_id = body.get("team", {}).get("id")
    user_id = body.get("user", {}).get("id")
    channel_id = body.get("channel", {}).get("id")

    if not team_id:
        logger.error("No team_id in body for setup wizard")
        return

    try:
        config_client = get_config_client()
        trial_info = config_client.get_trial_status(team_id)
        configured = config_client.get_configured_integrations(team_id)

        # Add GitHub status from GitHubInstallation table
        github_installation = config_client.get_linked_github_installation(team_id)
        if github_installation:
            configured["github"] = {"enabled": True, "_github_linked": True}

        onboarding = get_onboarding_modules()
        modal = onboarding.build_integrations_page(
            team_id=team_id,
            configured=configured,
            trial_info=trial_info,
        )

        client.views_open(trigger_id=body["trigger_id"], view=modal)
        logger.info(f"Opened setup wizard (integrations page) for team {team_id}")
    except Exception as e:
        logger.error(f"Failed to open setup wizard: {e}", exc_info=True)
        # Show error to user via ephemeral message
        if user_id and channel_id:
            try:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=":warning: Failed to open setup wizard. Please try again. If the problem persists, contact support@incidentfox.ai",
                )
            except Exception:
                pass  # Best effort


def handle_dismiss_welcome(ack, body, client):
    """Dismiss the welcome message with helpful tips."""
    ack()

    try:
        channel = body.get("channel", {}).get("id")
        message_ts = body.get("message", {}).get("ts")
        if channel and message_ts:
            client.chat_update(
                channel=channel,
                ts=message_ts,
                text="No problem! Mention @IncidentFox anytime to start investigating.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                ":wave: No problem! You can start investigating right away.\n\n"
                                "Just mention `@IncidentFox` in any channel with your question. "
                                "To set up integrations later, click on my avatar and select *Open App*."
                            ),
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": ":bulb: Tip: Type `help` in this DM anytime for guidance.",
                            }
                        ],
                    },
                ],
            )
    except Exception as e:
        logger.warning(f"Failed to update dismissed welcome message: {e}")


def handle_configure_integration(ack, body, client):
    """Handle integration configuration button click."""
    ack()

    action = body.get("actions", [{}])[0]
    action_id = action.get("action_id", "")

    # Extract integration_id from action_id (e.g., "configure_integration_datadog")
    integration_id = action_id.replace("configure_integration_", "")

    team_id = body.get("team", {}).get("id")
    if not team_id:
        logger.error("No team_id for configure_integration action")
        return

    # Extract category_filter from parent view's private_metadata
    category_filter = "all"
    try:
        parent_metadata = body.get("view", {}).get("private_metadata", "{}")
        parent_data = json.loads(parent_metadata)
        category_filter = parent_data.get("category_filter", "all")
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        onboarding = get_onboarding_modules()
        config_client = get_config_client()

        # Check for custom flow integrations (e.g., kubernetes_saas)
        integration_def = onboarding.get_integration_by_id(integration_id)
        custom_flow = integration_def.get("custom_flow") if integration_def else None

        if custom_flow == "k8s_saas":
            # K8s SaaS has a custom flow - show clusters management modal
            clusters = config_client.list_k8s_clusters(team_id)
            modal = onboarding.build_k8s_saas_clusters_modal(
                team_id=team_id,
                clusters=clusters,
                category_filter=category_filter,
                entry_point="integrations",
            )
        else:
            # Standard field-based config modal
            configured = config_client.get_configured_integrations(team_id)
            existing_config = configured.get(integration_id, {})

            # Special handling for GitHub: check if already linked via GitHub App
            if integration_id == "github":
                github_installation = config_client.get_linked_github_installation(
                    team_id
                )
                if github_installation:
                    # Pre-fill the github_org field with the linked org
                    existing_config["github_org"] = github_installation.get(
                        "account_login", ""
                    )
                    existing_config["_github_linked"] = True
                    existing_config["_github_installation"] = github_installation

            modal = onboarding.build_integration_config_modal(
                team_id=team_id,
                integration_id=integration_id,
                existing_config=existing_config,
                category_filter=category_filter,
                entry_point="integrations",
            )

        # Use views_update to replace current modal instead of views_push
        # This prevents stale modal accumulation
        view_id = body.get("view", {}).get("id")
        client.views_update(view_id=view_id, view=modal)
        logger.info(f"Updated modal to config for {integration_id}")

    except Exception as e:
        logger.error(f"Failed to open integration config modal: {e}", exc_info=True)


def handle_filter_category(ack, body, client):
    """Handle category filter button click on integrations page."""
    ack()

    action = body.get("actions", [{}])[0]
    action_id = action.get("action_id", "")

    # Extract category from action_id (e.g., "filter_category_observability")
    category = action_id.replace("filter_category_", "")

    team_id = body.get("team", {}).get("id")
    if not team_id:
        logger.error("No team_id for filter_category action")
        return

    try:
        # Get configured integrations to show checkmarks
        config_client = get_config_client()
        configured = config_client.get_configured_integrations(team_id)
        trial_info = config_client.get_trial_status(team_id)

        # Add GitHub status from GitHubInstallation table
        github_installation = config_client.get_linked_github_installation(team_id)
        if github_installation:
            configured["github"] = {"enabled": True, "_github_linked": True}

        # Rebuild the integrations page with new category filter (reset to page 0)
        onboarding = get_onboarding_modules()
        modal = onboarding.build_integrations_page(
            team_id=team_id,
            category_filter=category,
            configured=configured,
            trial_info=trial_info,
            page=0,
        )

        # Update the current modal view
        client.views_update(
            view_id=body.get("view", {}).get("id"),
            view=modal,
        )
        logger.info(f"Filtered integrations to category: {category}")

    except Exception as e:
        logger.error(f"Failed to filter integrations: {e}", exc_info=True)


def handle_integrations_pagination(ack, body, client):
    """Handle pagination buttons on integrations page."""
    ack()

    action_id = body.get("actions", [{}])[0].get("action_id", "")
    view = body.get("view", {})
    private_metadata = json.loads(view.get("private_metadata", "{}"))

    team_id = private_metadata.get("team_id") or body.get("team", {}).get("id")
    category_filter = private_metadata.get("category_filter", "all")
    current_page = private_metadata.get("page", 0)

    if action_id == "integrations_next_page":
        page = current_page + 1
    else:
        page = max(0, current_page - 1)

    try:
        config_client = get_config_client()
        configured = config_client.get_configured_integrations(team_id)
        trial_info = config_client.get_trial_status(team_id)

        github_installation = config_client.get_linked_github_installation(team_id)
        if github_installation:
            configured["github"] = {"enabled": True, "_github_linked": True}

        onboarding = get_onboarding_modules()
        modal = onboarding.build_integrations_page(
            team_id=team_id,
            category_filter=category_filter,
            configured=configured,
            trial_info=trial_info,
            page=page,
        )

        client.views_update(
            view_id=view.get("id"),
            view=modal,
        )
        logger.info(f"Paginated integrations to page {page}")

    except Exception as e:
        logger.error(f"Failed to paginate integrations: {e}", exc_info=True)


def handle_integrations_page_done(ack, body, client, view):
    """Handle Done button on integrations page."""
    import json

    ack()

    private_metadata = json.loads(view.get("private_metadata", "{}"))
    team_id = private_metadata.get("team_id")

    logger.info(f"Closed integrations page for team {team_id}")


# =============================================================================
# KUBERNETES SAAS HANDLERS
# =============================================================================


def handle_k8s_saas_add_cluster(ack, body, client):
    """Handle Add Cluster button click on K8s SaaS clusters modal."""
    ack()

    team_id = body.get("team", {}).get("id")
    if not team_id:
        logger.error("No team_id for k8s_saas_add_cluster action")
        return

    # Extract metadata from parent view
    category_filter = "all"
    entry_point = "integrations"
    try:
        parent_metadata = body.get("view", {}).get("private_metadata", "{}")
        parent_data = json.loads(parent_metadata)
        category_filter = parent_data.get("category_filter", "all")
        entry_point = parent_data.get("entry_point", "integrations")
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        onboarding = get_onboarding_modules()
        modal = onboarding.build_k8s_saas_add_cluster_modal(
            team_id=team_id,
            category_filter=category_filter,
            entry_point=entry_point,
        )

        # Push as new modal on stack
        client.views_push(trigger_id=body["trigger_id"], view=modal)
        logger.info(f"Pushed add cluster modal for team {team_id}")

    except Exception as e:
        logger.error(f"Failed to open add cluster modal: {e}", exc_info=True)


def handle_k8s_saas_add_cluster_submission(ack, body, client, view):
    """Handle form submission for adding a new K8s cluster."""
    private_metadata = json.loads(view.get("private_metadata", "{}"))
    team_id = private_metadata.get("team_id")
    category_filter = private_metadata.get("category_filter", "all")
    entry_point = private_metadata.get("entry_point", "integrations")

    # Extract form values
    values = view.get("state", {}).get("values", {})
    cluster_name = (
        values.get("cluster_name", {}).get("cluster_name_input", {}).get("value", "")
    )
    display_name = (
        values.get("display_name", {}).get("display_name_input", {}).get("value")
    )

    # Validate cluster name
    cluster_name = cluster_name.strip().lower()
    if not cluster_name:
        ack(
            response_action="errors",
            errors={"cluster_name": "Cluster name is required"},
        )
        return

    # Validate cluster name format (lowercase alphanumeric and hyphens)
    import re

    if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", cluster_name):
        ack(
            response_action="errors",
            errors={
                "cluster_name": "Use lowercase letters, numbers, and hyphens. Must start and end with alphanumeric."
            },
        )
        return

    ack()

    try:
        config_client = get_config_client()

        # Create the cluster
        result = config_client.create_k8s_cluster(
            slack_team_id=team_id,
            cluster_name=cluster_name,
            display_name=display_name,
        )

        # Show the cluster created modal with Helm command
        onboarding = get_onboarding_modules()
        modal = onboarding.build_k8s_saas_cluster_created_modal(
            team_id=team_id,
            cluster_name=result.get("cluster_name"),
            display_name=result.get("display_name"),
            token=result.get("token"),
            helm_command=result.get("helm_install_command"),
            category_filter=category_filter,
            entry_point=entry_point,
        )

        # Update the modal to show the Helm command
        client.views_update(
            view_id=body.get("view", {}).get("id"),
            view=modal,
        )
        logger.info(f"Created K8s cluster {cluster_name} for team {team_id}")

    except Exception as e:
        error_msg = str(e)
        if "already exists" in error_msg.lower():
            # Show error in modal
            logger.warning(f"Cluster name conflict for team {team_id}: {cluster_name}")
        else:
            logger.error(f"Failed to create K8s cluster: {e}", exc_info=True)


def handle_k8s_saas_remove_cluster(ack, body, client):
    """Handle Remove Cluster button click."""
    ack()

    team_id = body.get("team", {}).get("id")
    if not team_id:
        logger.error("No team_id for k8s_saas_remove_cluster action")
        return

    action = body.get("actions", [{}])[0]
    cluster_id = action.get("value")

    if not cluster_id:
        logger.error("No cluster_id in k8s_saas_remove_cluster action")
        return

    # Extract metadata from parent view
    category_filter = "all"
    entry_point = "integrations"
    try:
        parent_metadata = body.get("view", {}).get("private_metadata", "{}")
        parent_data = json.loads(parent_metadata)
        category_filter = parent_data.get("category_filter", "all")
        entry_point = parent_data.get("entry_point", "integrations")
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        config_client = get_config_client()

        # Delete the cluster
        config_client.delete_k8s_cluster(
            slack_team_id=team_id,
            cluster_id=cluster_id,
        )

        # Refresh the clusters list
        clusters = config_client.list_k8s_clusters(team_id)

        onboarding = get_onboarding_modules()
        modal = onboarding.build_k8s_saas_clusters_modal(
            team_id=team_id,
            clusters=clusters,
            category_filter=category_filter,
            entry_point=entry_point,
        )

        # Update the modal
        client.views_update(
            view_id=body.get("view", {}).get("id"),
            view=modal,
        )
        logger.info(f"Removed K8s cluster {cluster_id} for team {team_id}")

    except Exception as e:
        logger.error(f"Failed to remove K8s cluster: {e}", exc_info=True)


def handle_k8s_saas_clusters_modal_close(ack, body, client, view):
    """Handle Back/Close on K8s SaaS clusters modal - return to integrations page."""
    ack()

    private_metadata = json.loads(view.get("private_metadata", "{}"))
    team_id = private_metadata.get("team_id")

    logger.info(f"Closed K8s SaaS clusters modal for team {team_id}")


def handle_k8s_saas_cluster_created_close(ack, body, client, view):
    """Handle Done on cluster created modal."""
    ack()

    private_metadata = json.loads(view.get("private_metadata", "{}"))
    team_id = private_metadata.get("team_id")

    logger.info(f"Closed K8s cluster created modal for team {team_id}")


# =============================================================================
# AI MODEL SELECTION HANDLERS
# =============================================================================


def _detect_provider_from_model(model: str) -> Optional[str]:
    """Detect provider ID from a LiteLLM model string.

    Delegates to onboarding.detect_provider_from_model (single source of truth).
    """
    onboarding = get_onboarding_modules()
    return onboarding.detect_provider_from_model(model)


def handle_open_ai_model_selector(ack, body, client):
    """Open the unified AI model configuration modal from Home Tab."""
    ack()

    team_id = body.get("team", {}).get("id")
    if not team_id:
        logger.error("No team_id in home_open_ai_model_selector")
        return

    # Open modal immediately with empty state to avoid trigger_id expiration
    # (trigger_id has ~3s TTL, config-service calls can be slow)
    try:
        onboarding = get_onboarding_modules()
        modal = onboarding.build_ai_model_modal(team_id=team_id)
        resp = client.views_open(trigger_id=body["trigger_id"], view=modal)
        view_id = resp["view"]["id"]
    except Exception as e:
        logger.error(f"Failed to open AI model modal: {e}", exc_info=True)
        return

    # Now fetch existing config and update the modal with pre-filled values
    try:
        config_client = get_config_client()
        workspace_config = config_client.get_workspace_config(team_id) or {}
        integrations = workspace_config.get("integrations", {})
        llm_config = integrations.get("llm", {})
        current_model = llm_config.get("model", "")

        if current_model:
            current_provider = _detect_provider_from_model(current_model)
            existing_provider_config = integrations.get(current_provider) or {}

            modal = onboarding.build_ai_model_modal(
                team_id=team_id,
                provider_id=current_provider,
                current_model=current_model,
                existing_provider_config=existing_provider_config,
            )
            client.views_update(view_id=view_id, view=modal)

        logger.info(f"Opened AI model modal for team {team_id}")

    except Exception as e:
        logger.warning(f"Failed to pre-fill AI model modal: {e}")


# Guard against provider-switch race conditions: slow model catalog fetches
# (e.g. OpenAI) can overwrite a fast provider switch (e.g. Cloudflare).
# Each selection increments the counter; stale handlers skip their update.
_provider_switch_seq: dict = {}  # view_id → sequence number


def handle_ai_provider_change(ack, body, client):
    """Handle provider dropdown change — update the modal with provider-specific fields."""
    ack()

    view = body.get("view", {})
    view_id = view.get("id")

    # Get selected provider from the action
    selected_provider = (
        body.get("actions", [{}])[0].get("selected_option", {}).get("value")
    )
    if not selected_provider or not view_id:
        return

    # Claim a sequence number before doing any slow work
    _provider_switch_seq[view_id] = _provider_switch_seq.get(view_id, 0) + 1
    my_seq = _provider_switch_seq[view_id]

    try:
        private_metadata = json.loads(view.get("private_metadata", "{}"))
        team_id = private_metadata.get("team_id")

        config_client = get_config_client()
        existing_provider_config = (
            config_client.get_integration_config(team_id, selected_provider) or {}
        )

        onboarding = get_onboarding_modules()
        modal = onboarding.build_ai_model_modal(
            team_id=team_id,
            provider_id=selected_provider,
            current_model=None,  # Don't carry over model from different provider
            existing_provider_config=existing_provider_config,
        )

        # Skip update if user already switched to another provider
        if _provider_switch_seq.get(view_id) != my_seq:
            logger.info(
                f"Skipping stale provider update for {selected_provider} (view {view_id})"
            )
            return

        client.views_update(view_id=view_id, view=modal)
        logger.info(
            f"Updated AI model modal for provider {selected_provider}, team {team_id}"
        )

    except Exception as e:
        logger.error(f"Failed to update AI model modal: {e}", exc_info=True)


def handle_model_select_change(ack, body, client):
    """Handle model dropdown change — show model description."""
    ack()

    view = body.get("view", {})
    view_id = view.get("id")
    selected_model = (
        body.get("actions", [{}])[0].get("selected_option", {}).get("value")
    )
    if not selected_model or not view_id:
        return

    # Snapshot the provider-switch sequence — if it changes, a provider switch
    # happened and this model description update is stale.
    seq_before = _provider_switch_seq.get(view_id, 0)

    try:
        private_metadata = json.loads(view.get("private_metadata", "{}"))
        team_id = private_metadata.get("team_id")

        # Get provider from form state
        values = view.get("state", {}).get("values", {})
        provider_id = (
            values.get("provider_block", {})
            .get("ai_provider_select", {})
            .get("selected_option", {})
            .get("value")
        ) or private_metadata.get("provider_id")

        if not provider_id:
            return

        # Look up model description
        from model_catalog import get_model_description

        description = get_model_description(provider_id, selected_model)

        config_client = get_config_client()
        existing_provider_config = (
            config_client.get_integration_config(team_id, provider_id) or {}
        )

        onboarding = get_onboarding_modules()
        modal = onboarding.build_ai_model_modal(
            team_id=team_id,
            provider_id=provider_id,
            current_model=selected_model,
            existing_provider_config=existing_provider_config,
            model_description=description,
        )

        # Skip if provider changed while we were building the modal
        if _provider_switch_seq.get(view_id, 0) != seq_before:
            logger.info(
                f"Skipping stale model description update (provider switched, view {view_id})"
            )
            return

        client.views_update(view_id=view_id, view=modal)
    except Exception as e:
        logger.error(f"Failed to update model description: {e}", exc_info=True)


def handle_ai_model_config_submission(ack, body, client, view):
    """Handle AI model config submission: validate key + save provider + model."""
    private_metadata = json.loads(view.get("private_metadata", "{}"))
    team_id = private_metadata.get("team_id")
    provider_id = private_metadata.get("provider_id")
    field_names = private_metadata.get("field_names", [])
    values = view.get("state", {}).get("values", {})

    # Also read provider from form state (authoritative if present)
    dropdown_provider = (
        values.get("provider_block", {})
        .get("ai_provider_select", {})
        .get("selected_option")
        or {}
    ).get("value")
    if dropdown_provider:
        provider_id = dropdown_provider

    # 1. Extract model ID — block_id is provider-specific (field_model_id_{provider})
    model_field = {}
    model_block_id = "field_model_id"
    for block_id, block_vals in values.items():
        if block_id.startswith("field_model_id") and "input_model_id" in block_vals:
            model_field = block_vals["input_model_id"]
            model_block_id = block_id
            break
    selected_option = model_field.get("selected_option")
    model_id = (
        selected_option.get("value", "").strip()
        if selected_option
        else model_field.get("value", "").strip()  # fallback for plain_text_input
    )
    if not model_id:
        ack(
            response_action="errors",
            errors={model_block_id: "Model ID is required."},
        )
        return

    import re

    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._/:@\-]*$", model_id):
        ack(
            response_action="errors",
            errors={
                model_block_id: "Invalid model ID. Use letters, numbers, hyphens, slashes, dots, colons, or underscores."
            },
        )
        return

    # 2. Extract provider-specific fields
    config_client = get_config_client()
    try:
        existing_provider_config = (
            config_client.get_integration_config(team_id, provider_id) or {}
        )
    except Exception:
        existing_provider_config = {}

    # Cloudflare: map per-upstream provider_api_key into generic field for the form loop
    _cf_upstream = ""
    if provider_id == "cloudflare_ai" and model_id and "/" in model_id:
        _cf_upstream = model_id.split("/")[0]
        stored_key = existing_provider_config.get(f"provider_api_key_{_cf_upstream}")
        if stored_key:
            existing_provider_config["provider_api_key"] = stored_key

    provider_config = {}
    for field_id in field_names:
        block_id = f"field_{field_id}"
        action_id = f"input_{field_id}"
        field_value = values.get(block_id, {}).get(action_id, {})

        if "value" in field_value:
            val = (field_value.get("value") or "").strip()
            if val and re.fullmatch(r"\*+", val):
                # Masked secret field unchanged — preserve existing value
                if field_id in existing_provider_config:
                    provider_config[field_id] = existing_provider_config[field_id]
            elif val:
                provider_config[field_id] = val
            # Blank field = user intentionally cleared it — don't preserve old value
        elif "selected_option" in field_value:
            selected = field_value.get("selected_option", {})
            if selected:
                provider_config[field_id] = selected.get("value")
            elif field_id in existing_provider_config:
                provider_config[field_id] = existing_provider_config[field_id]
        elif "selected_options" in field_value:
            # Checkboxes (boolean)
            selected = field_value.get("selected_options", [])
            provider_config[field_id] = len(selected) > 0

    # Cloudflare: store provider_api_key per upstream provider (openai, anthropic, etc.)
    if provider_id == "cloudflare_ai":
        upstream = model_id.split("/")[0] if "/" in model_id else ""
        if upstream:
            # Move the form value to per-provider key (if user entered one)
            generic_val = provider_config.pop("provider_api_key", "")
            if generic_val:
                provider_config[f"provider_api_key_{upstream}"] = generic_val
        # Clear generic key so it doesn't persist from previous saves
        provider_config.setdefault("provider_api_key", "")

    # 3. Show loading state immediately (Slack requires ack within 3 seconds)
    #    Push on top of form so user can go Back on error (form fields preserved)
    from assets_config import get_asset_url

    user_id = body.get("user", {}).get("id")
    validation_ext_id = f"ai_validation_{team_id}_{user_id or 'u'}_{int(time.time())}"
    loading_url = get_asset_url("loading")
    loading_elements = []
    if loading_url:
        loading_elements.append(
            {"type": "image", "image_url": loading_url, "alt_text": "Loading"}
        )
    loading_elements.append({"type": "mrkdwn", "text": "*Validating your API key...*"})
    ack(
        response_action="push",
        view={
            "type": "modal",
            "external_id": validation_ext_id,
            "title": {"type": "plain_text", "text": "AI Model"},
            "blocks": [{"type": "context", "elements": loading_elements}],
        },
    )

    # 4. Validate API key via live test request (no time pressure now)
    onboarding = get_onboarding_modules()
    validation_config = {**existing_provider_config, **provider_config}
    is_valid, error_msg = onboarding.validate_provider_api_key(
        provider_id, validation_config, model_id
    )

    if not is_valid:
        # Update the pushed loading view to show error; "Back" pops it, revealing the form
        client.views_update(
            external_id=validation_ext_id,
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "AI Model"},
                "close": {"type": "plain_text", "text": "Back"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":x: *Validation failed*\n{error_msg[:300]}",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "Press *Back* to fix your API key and try again.",
                            }
                        ],
                    },
                ],
            },
        )
        return

    # 5. Save provider config (API key + provider-specific fields)
    try:
        if provider_id != "llm" and provider_config:
            config_client.save_integration_config(
                slack_team_id=team_id,
                integration_id=provider_id,
                config=provider_config,
            )
            logger.info(f"Saved {provider_id} provider config for team {team_id}")

        # 6. Save LLM model preference
        #    Prepend provider prefix for routing (user doesn't type it)
        save_model_id = model_id
        _prefix_providers = {"cloudflare_ai", "custom_endpoint"}
        if provider_id in _prefix_providers and not model_id.startswith(
            f"{provider_id}/"
        ):
            save_model_id = f"{provider_id}/{model_id}"
        config_client.save_integration_config(
            slack_team_id=team_id,
            integration_id="llm",
            config={"model": save_model_id},
        )
        logger.info(f"Saved llm model={save_model_id} for team {team_id}")

    except Exception as e:
        logger.error(f"Failed to save AI model config: {e}", exc_info=True)
        client.views_update(
            external_id=validation_ext_id,
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "AI Model"},
                "close": {"type": "plain_text", "text": "Back"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":x: *Failed to save:* {str(e)[:300]}",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "Press *Back* to try again.",
                            }
                        ],
                    },
                ],
            },
        )
        return

    logger.info(
        f"AI model config saved: provider={provider_id}, model={model_id}, team={team_id}"
    )

    # 7. Show success + refresh Home Tab
    done_url = get_asset_url("done")
    success_elements = []
    if done_url:
        success_elements.append(
            {"type": "image", "image_url": done_url, "alt_text": "Done"}
        )
    success_elements.append({"type": "mrkdwn", "text": "*Model saved!*"})
    success_blocks = [
        {"type": "context", "elements": success_elements},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Using `{model_id}`",
            },
        },
    ]
    # Update pushed validation view with success
    # clear_on_close=True closes the entire modal stack (not just pop back to form)
    client.views_update(
        external_id=validation_ext_id,
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "AI Model"},
            "close": {"type": "plain_text", "text": "Done"},
            "clear_on_close": True,
            "blocks": success_blocks,
        },
    )

    if user_id and team_id:
        try:
            from home_tab import build_home_tab_view

            trial_info = config_client.get_trial_status(team_id)
            configured = config_client.get_configured_integrations(team_id)

            home_view = build_home_tab_view(
                team_id=team_id,
                trial_info=trial_info,
                configured_integrations=configured,
            )
            client.views_publish(user_id=user_id, view=home_view)
            logger.info(f"Refreshed Home Tab after AI model config for {user_id}")
        except Exception as e:
            logger.warning(f"Failed to refresh Home Tab: {e}")


def handle_integration_config_submission(ack, body, client, view):
    """Handle integration configuration modal submission."""
    import json

    private_metadata = json.loads(view.get("private_metadata", "{}"))
    team_id = private_metadata.get("team_id")
    integration_id = private_metadata.get("integration_id")
    field_names = private_metadata.get("field_names", [])
    secret_fields = set(private_metadata.get("secret_fields", []))

    values = view.get("state", {}).get("values", {})

    # Get existing config to preserve values not provided (e.g., secret fields left blank)
    try:
        config_client = get_config_client()
        existing_integrations = config_client.get_configured_integrations(team_id)
        existing_config = existing_integrations.get(integration_id, {})
    except Exception:
        existing_config = {}

    # Extract field values
    config = {}
    validation_errors = []

    for field_id in field_names:
        block_id = f"field_{field_id}"
        action_id = f"input_{field_id}"

        block_values = values.get(block_id, {})
        field_value = block_values.get(action_id, {})

        # Handle different field types
        if "value" in field_value:
            # Plain text input
            val = field_value.get("value")
            if val:
                val = val.strip()

                # Secret fields: if value is all asterisks, user didn't change it
                # Preserve the existing value instead of saving the redacted mask
                if (
                    field_id in secret_fields
                    and val == "*" * len(val)
                    and field_id in existing_config
                ):
                    config[field_id] = existing_config[field_id]
                    continue

                # Special handling for Coralogix domain field
                if integration_id == "coralogix" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_domain, error_msg = (
                        onboarding.extract_coralogix_domain(val)
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_domain
                # Special handling for Grafana URL field
                elif integration_id == "grafana" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_grafana_url(
                        val
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for Elasticsearch URL field
                elif integration_id == "elasticsearch" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = (
                        onboarding.extract_elasticsearch_url(val)
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for Prometheus URL field
                elif integration_id == "prometheus" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_generic_url(
                        val, "Prometheus"
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for Jaeger URL field
                elif integration_id == "jaeger" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_generic_url(
                        val, "Jaeger"
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for Kubernetes API URL field
                elif integration_id == "kubernetes" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_generic_url(
                        val, "Kubernetes"
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for GitHub Enterprise URL field
                elif integration_id == "github" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_generic_url(
                        val, "GitHub Enterprise"
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for Confluence URL field
                # Extract base URL from any Confluence page URL
                elif integration_id == "confluence" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_confluence_url(
                        val
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for Datadog URL field
                # Note: UI field is "domain" but backend expects "site" key
                elif integration_id == "datadog" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_site, error_msg = onboarding.extract_datadog_site(
                        val
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config["site"] = parsed_site
                # Special handling for Honeycomb URL field
                elif integration_id == "honeycomb" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_generic_url(
                        val, "Honeycomb"
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for Loki URL field
                elif integration_id == "loki" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_generic_url(
                        val, "Loki"
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for Splunk URL field
                elif integration_id == "splunk" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_generic_url(
                        val, "Splunk"
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for Sentry URL field (self-hosted)
                elif integration_id == "sentry" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_generic_url(
                        val, "Sentry"
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                # Special handling for GitLab URL field (self-hosted)
                elif integration_id == "gitlab" and field_id == "domain":
                    onboarding = get_onboarding_modules()
                    is_valid, parsed_url, error_msg = onboarding.extract_generic_url(
                        val, "GitLab"
                    )
                    if not is_valid:
                        validation_errors.append(error_msg)
                    else:
                        config[field_id] = parsed_url
                else:
                    config[field_id] = val
            elif field_id in existing_config:
                # Field was left blank but exists in config - preserve existing value
                # This is especially important for secret fields
                config[field_id] = existing_config[field_id]
        elif "selected_option" in field_value:
            # Select
            selected = field_value.get("selected_option", {})
            if selected:
                config[field_id] = selected.get("value")
            elif field_id in existing_config:
                # No selection but exists in config - preserve
                config[field_id] = existing_config[field_id]
        elif "selected_options" in field_value:
            # Checkboxes (boolean)
            selected = field_value.get("selected_options", [])
            config[field_id] = len(selected) > 0

    # If validation errors, show error modal
    if validation_errors:
        error_modal = {
            "type": "modal",
            "title": {"type": "plain_text", "text": "Validation Error"},
            "close": {"type": "plain_text", "text": "Fix"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":warning: *Please fix the following:*\n\n"
                        + "\n".join(f"• {err}" for err in validation_errors),
                    },
                },
            ],
        }
        ack(response_action="push", view=error_modal)
        return

    # Save the integration config
    if team_id and integration_id and config:
        try:
            config_client = get_config_client()

            # Special handling for GitHub App integration
            if integration_id == "github" and "github_org" in config:
                github_org = config.get("github_org", "").strip()
                if not github_org:
                    error_modal = {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Missing Info"},
                        "close": {"type": "plain_text", "text": "Fix"},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": ":warning: *Please enter your GitHub organization/username*\n\n"
                                    "This should be the org or user you installed the IncidentFox GitHub App on.",
                                },
                            },
                        ],
                    }
                    ack(response_action="push", view=error_modal)
                    return

                # Link the GitHub installation
                result = config_client.link_github_installation(
                    slack_team_id=team_id,
                    github_org=github_org,
                )
                logger.info(
                    f"Linked GitHub org '{github_org}' for team {team_id}: {result.get('message')}"
                )

                # Also save context_prompt if provided (standard integration config)
                if config.get("context_prompt") or config.get("enabled") is not None:
                    integration_config = {}
                    if "context_prompt" in config:
                        integration_config["context_prompt"] = config["context_prompt"]
                    if "enabled" in config:
                        integration_config["enabled"] = config["enabled"]
                    if integration_config:
                        config_client.save_integration_config(
                            slack_team_id=team_id,
                            integration_id=integration_id,
                            config=integration_config,
                        )
            else:
                # Standard integration config save
                config_client.save_integration_config(
                    slack_team_id=team_id,
                    integration_id=integration_id,
                    config=config,
                )
            logger.info(f"Saved {integration_id} config for team {team_id}")

            # Trigger integration scan (fire-and-forget, never blocks save)
            import threading

            def _trigger_integration_scan(
                _team_id=team_id, _integration_id=integration_id
            ):
                try:
                    scan_client = get_config_client()
                    scan_client.trigger_onboarding_scan(
                        org_id=f"slack-{_team_id}",
                        team_node_id="default",
                        trigger="integration",
                        integration_id=_integration_id,
                    )
                except Exception as scan_err:
                    logger.warning(f"Integration scan trigger failed: {scan_err}")

            threading.Thread(target=_trigger_integration_scan, daemon=True).start()

        except Exception as e:
            logger.error(f"Error saving integration config: {e}", exc_info=True)

            # Extract error message - ConfigServiceError includes the actual API error
            error_message = str(e)
            status_code = getattr(e, "status_code", None)

            # For GitHub integration, show user-friendly error messages
            if integration_id == "github":
                if status_code == 404:
                    error_modal = {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Not Found"},
                        "close": {"type": "plain_text", "text": "Try Again"},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": (
                                        ":warning: *GitHub installation not found*\n\n"
                                        "Make sure you have:\n"
                                        "1. Clicked 'Install GitHub App' button above\n"
                                        "2. Completed the installation on GitHub\n"
                                        "3. Entered the exact org/username you installed on\n\n"
                                        "_Note: It may take a few seconds for the installation to be registered._"
                                    ),
                                },
                            },
                        ],
                    }
                    ack(response_action="push", view=error_modal)
                    return
                elif status_code == 409:
                    error_modal = {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Already Connected"},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": [
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": (
                                        ":x: *This GitHub org is already connected*\n\n"
                                        "This GitHub organization is already linked to another "
                                        "IncidentFox workspace. Each GitHub org can only be connected "
                                        "to one workspace.\n\n"
                                        "If you believe this is an error, please contact support@incidentfox.ai"
                                    ),
                                },
                            },
                        ],
                    }
                    ack(response_action="push", view=error_modal)
                    return

            # Generic error for other integrations or unexpected errors
            error_modal = {
                "type": "modal",
                "title": {"type": "plain_text", "text": "Save Failed"},
                "close": {"type": "plain_text", "text": "Try Again"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":x: *Failed to save {integration_id} configuration*\n\nPlease try again. If the problem persists, contact support@incidentfox.ai",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Error: {error_message[:200]}",
                            }
                        ],
                    },
                ],
            }
            ack(response_action="push", view=error_modal)
            return

    # Check entry point to decide how to handle modal after save
    entry_point = private_metadata.get("entry_point", "integrations")

    if entry_point == "home":
        # Opened from home tab - close all modals (home tab shows status)
        ack(response_action="clear")
        logger.info(f"Closed modal after saving {integration_id} from Home Tab")
    else:
        # Opened from integrations page - return to integrations list with updated state
        # Since we use views_update (not views_push) to open the config modal,
        # there's only one modal, so response_action="update" works correctly
        category_filter = private_metadata.get("category_filter", "all")
        try:
            config_client = get_config_client()
            trial_info = config_client.get_trial_status(team_id)
            configured = config_client.get_configured_integrations(team_id)

            # Add GitHub status from GitHubInstallation table
            github_installation = config_client.get_linked_github_installation(team_id)
            if github_installation:
                configured["github"] = {"enabled": True, "_github_linked": True}

            onboarding = get_onboarding_modules()
            integrations_view = onboarding.build_integrations_page(
                team_id=team_id,
                category_filter=category_filter,
                configured=configured,
                trial_info=trial_info,
            )
            ack(response_action="update", view=integrations_view)
            logger.info(f"Returned to integrations page after saving {integration_id}")
        except Exception as e:
            logger.warning(f"Failed to rebuild integrations page: {e}")
            ack(response_action="clear")

    # Try to refresh Home Tab if user is there
    user_id = body.get("user", {}).get("id")
    if user_id and team_id:
        try:
            config_client = get_config_client()
            trial_info = config_client.get_trial_status(team_id)
            configured = config_client.get_configured_integrations(team_id)
            schemas = config_client.get_integration_schemas()

            # Only refresh if home_tab module exists
            try:
                from home_tab import build_home_tab_view

                home_view = build_home_tab_view(
                    team_id=team_id,
                    trial_info=trial_info,
                    configured_integrations=configured,
                    available_schemas=schemas,
                )
                client.views_publish(user_id=user_id, view=home_view)
                logger.info(f"Refreshed Home Tab for user {user_id}")
            except ImportError:
                pass  # home_tab not yet created
        except Exception as e:
            logger.warning(f"Failed to refresh Home Tab: {e}")


def handle_app_home_opened(client, event, context):
    """Render the Home Tab when user opens it."""
    user_id = event.get("user")
    team_id = context.get("team_id")

    if not team_id:
        logger.warning("No team_id in app_home_opened event")
        return

    try:
        config_client = get_config_client()
        trial_info = config_client.get_trial_status(team_id)
        configured = config_client.get_configured_integrations(team_id)
        schemas = config_client.get_integration_schemas()

        from home_tab import build_home_tab_view

        view = build_home_tab_view(
            team_id=team_id,
            trial_info=trial_info,
            configured_integrations=configured,
            available_schemas=schemas,
        )

        client.views_publish(user_id=user_id, view=view)
        logger.info(f"Published Home Tab for user {user_id}, team {team_id}")

    except Exception as e:
        logger.error(f"Failed to publish Home Tab: {e}", exc_info=True)
        # Show error view to user
        error_view = {
            "type": "home",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":warning: *Unable to load IncidentFox*\n\nWe encountered an error loading your configuration. Please try again in a few moments.\n\nIf the problem persists, contact support@incidentfox.ai",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Retry"},
                            "action_id": "home_retry_load",
                        }
                    ],
                },
            ],
        }
        try:
            client.views_publish(user_id=user_id, view=error_view)
        except Exception:
            pass  # Best effort


def handle_home_retry_load(ack, body, client, context):
    """Handle retry button when Home Tab fails to load."""
    ack()

    user_id = body.get("user", {}).get("id")
    team_id = body.get("team", {}).get("id") or context.get("team_id")

    if not user_id or not team_id:
        return

    # Re-trigger the Home Tab load
    try:
        config_client = get_config_client()
        trial_info = config_client.get_trial_status(team_id)
        configured = config_client.get_configured_integrations(team_id)
        schemas = config_client.get_integration_schemas()

        from home_tab import build_home_tab_view

        view = build_home_tab_view(
            team_id=team_id,
            trial_info=trial_info,
            configured_integrations=configured,
            available_schemas=schemas,
        )

        client.views_publish(user_id=user_id, view=view)
        logger.info(f"Retry: Published Home Tab for user {user_id}, team {team_id}")

    except Exception as e:
        logger.error(f"Retry failed for Home Tab: {e}", exc_info=True)
        # Show error again
        error_view = {
            "type": "home",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":warning: *Unable to load IncidentFox*\n\nWe're still having trouble connecting. Please try again later or contact support@incidentfox.ai",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Retry"},
                            "action_id": "home_retry_load",
                        }
                    ],
                },
            ],
        }
        try:
            client.views_publish(user_id=user_id, view=error_view)
        except Exception:
            pass


def handle_home_pagination(ack, body, client, context):
    """Handle pagination buttons on Home Tab."""
    ack()

    user_id = body.get("user", {}).get("id")
    team_id = body.get("team", {}).get("id") or context.get("team_id")

    if not user_id or not team_id:
        return

    action = body.get("actions", [{}])[0]
    try:
        action_value = json.loads(action.get("value", "{}"))
        page = action_value.get("page", 1)
    except (json.JSONDecodeError, TypeError):
        page = 1

    try:
        config_client = get_config_client()
        trial_info = config_client.get_trial_status(team_id)
        configured = config_client.get_configured_integrations(team_id)

        from home_tab import build_home_tab_view

        view = build_home_tab_view(
            team_id=team_id,
            trial_info=trial_info,
            configured_integrations=configured,
            page=page,
        )

        client.views_publish(user_id=user_id, view=view)
        logger.info(f"Home Tab page {page} for user {user_id}, team {team_id}")

    except Exception as e:
        logger.error(f"Failed to paginate Home Tab: {e}", exc_info=True)


def handle_home_integration_action(ack, body, client):
    """Handle Edit/Connect buttons on Home Tab."""
    ack()

    action = body.get("actions", [{}])[0]
    action_id = action.get("action_id", "")

    # Parse action: home_edit_integration_datadog or home_add_integration_datadog
    parts = action_id.split("_")
    action_type = parts[1]  # "edit" or "add"
    integration_id = "_".join(parts[3:])  # Handle IDs with underscores

    team_id = body.get("team", {}).get("id")
    if not team_id:
        logger.error("No team_id in home integration action")
        return

    try:
        config_client = get_config_client()
        onboarding = get_onboarding_modules()

        # Get existing config if editing
        existing_config = None
        if action_type == "edit":
            configured = config_client.get_configured_integrations(team_id)
            existing_config = configured.get(integration_id, {})

        # Check for custom flow integrations (e.g., kubernetes_saas)
        integration_def = onboarding.get_integration_by_id(integration_id)
        custom_flow = integration_def.get("custom_flow") if integration_def else None

        if custom_flow == "k8s_saas":
            clusters = config_client.list_k8s_clusters(team_id)
            modal = onboarding.build_k8s_saas_clusters_modal(
                team_id=team_id,
                clusters=clusters,
                entry_point="home",
            )
        else:
            # Special handling for GitHub App integration
            if integration_id == "github" and action_type == "edit":
                github_installation = config_client.get_linked_github_installation(
                    team_id
                )
                if github_installation:
                    if existing_config is None:
                        existing_config = {}
                    existing_config["github_org"] = github_installation.get(
                        "account_login", ""
                    )
                    existing_config["_github_linked"] = True
                    existing_config["_github_installation"] = github_installation

            modal = onboarding.build_integration_config_modal(
                team_id=team_id,
                integration_id=integration_id,
                existing_config=existing_config,
                entry_point="home",
            )

        try:
            client.views_open(trigger_id=body["trigger_id"], view=modal)
        except Exception as views_err:
            # Modal open failed — most likely due to the video block requiring
            # the video_url domain to be registered as a Slack media domain.
            # Retry without the video block.
            logger.warning(
                f"views_open failed for {integration_id}, retrying without video: {views_err}"
            )
            if custom_flow != "k8s_saas":
                modal = onboarding.build_integration_config_modal(
                    team_id=team_id,
                    integration_id=integration_id,
                    existing_config=existing_config,
                    entry_point="home",
                    include_video=False,
                )
                client.views_open(trigger_id=body["trigger_id"], view=modal)
            else:
                raise

        logger.info(f"Opened {action_type} modal for {integration_id} from Home Tab")

    except Exception as e:
        logger.error(
            f"Failed to open integration modal from Home Tab: {e}", exc_info=True
        )
        # Show error modal so the user knows something went wrong
        try:
            client.views_open(
                trigger_id=body["trigger_id"],
                view={
                    "type": "modal",
                    "title": {"type": "plain_text", "text": "Error"},
                    "close": {"type": "plain_text", "text": "Close"},
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    ":warning: *Could not open settings*\n\n"
                                    "Something went wrong opening the configuration for "
                                    f"*{integration_id}*. Please try again."
                                ),
                            },
                        }
                    ],
                },
            )
        except Exception:
            pass


def handle_home_book_demo(ack):
    """Ack the Book a Demo URL button click (URL opens in browser)."""
    ack()


def handle_home_api_key_modal(ack, body, client):
    """Open API key modal from Home Tab."""
    ack()

    team_id = body.get("team", {}).get("id")
    if not team_id:
        logger.error("No team_id in home_open_api_key_modal")
        return

    try:
        config_client = get_config_client()
        trial_info = config_client.get_trial_status(team_id)

        onboarding = get_onboarding_modules()
        modal = onboarding.build_api_key_modal(team_id, trial_info=trial_info)

        client.views_open(trigger_id=body["trigger_id"], view=modal)
        logger.info(f"Opened API key modal from Home Tab for team {team_id}")

    except Exception as e:
        logger.error(f"Failed to open API key modal from Home Tab: {e}", exc_info=True)


def handle_mention_setup_wizard(ack, body, client):
    """Open setup wizard when user clicks 'Configure IncidentFox' from channel mention."""
    ack()

    team_id = body.get("team", {}).get("id")
    if not team_id:
        logger.error("No team_id in mention_open_setup_wizard")
        return

    try:
        config_client = get_config_client()
        trial_info = config_client.get_trial_status(team_id)
        configured = config_client.get_configured_integrations(team_id)

        onboarding = get_onboarding_modules()
        wizard_view = onboarding.build_integrations_page(
            team_id=team_id,
            configured=configured,
            trial_info=trial_info,
        )

        client.views_open(trigger_id=body["trigger_id"], view=wizard_view)
        logger.info(f"Opened setup wizard from channel mention for team {team_id}")

    except Exception as e:
        logger.error(
            f"Failed to open setup wizard from channel mention: {e}", exc_info=True
        )


def handle_member_joined_channel(event, client, context):
    """
    Handle when a member joins a channel.

    Only sends a welcome message when the BOT itself joins a channel,
    not when other users join.
    """
    user_id = event.get("user")
    channel_id = event.get("channel")
    team_id = event.get("team") or context.get("team_id", "unknown")

    # Get bot's user ID
    bot_user_id = context.get("bot_user_id")
    if not bot_user_id:
        try:
            auth_response = client.auth_test()
            bot_user_id = auth_response.get("user_id")
        except Exception as e:
            logger.warning(f"Failed to get bot user ID: {e}")
            return

    # Only send welcome when the BOT joins, not when other users join
    if user_id != bot_user_id:
        return

    logger.info(f"🤖 Bot joined channel {channel_id} in team {team_id}")

    # Send a short, glanceable welcome message with team setup prompt
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":wave: *I'm here!*\n"
                    ":zap: I'll auto-investigate alerts posted in this channel\n"
                    ":speech_balloon: `@mention` me with questions, errors, or files\n"
                    ":gear: Run `/setup-team` to configure this channel's team"
                ),
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Set Up Team",
                    "emoji": True,
                },
                "action_id": "open_team_setup",
            },
        },
    ]

    try:
        client.chat_postMessage(
            channel=channel_id,
            text="I'm here! Run /setup-team to configure this channel's team.",
            blocks=blocks,
        )
        logger.info(f"Sent welcome message to channel {channel_id}")
    except Exception as e:
        logger.warning(f"Error sending welcome message: {e}")


# =============================================================================
# =============================================================================
# Options Handlers (external_select dynamic data)
# =============================================================================


def handle_model_options(ack, body):
    """Handle dynamic model search for AI model selector (external_select)."""
    query = body.get("value", "")

    # Extract provider_id from the modal's private_metadata
    provider_id = ""
    view = body.get("view", {})
    try:
        metadata = json.loads(view.get("private_metadata", "{}"))
        provider_id = metadata.get("provider_id", "")
    except (json.JSONDecodeError, TypeError):
        pass

    logger.info(f"Model options request: provider={provider_id!r}, query={query!r}")

    try:
        from model_catalog import get_models_for_provider

        models = get_models_for_provider(provider_id, query=query, limit=100)
        options = [
            {
                "text": {"type": "plain_text", "text": m["name"][:75]},
                "value": m["id"],
            }
            for m in models
        ]
        logger.info(f"Returning {len(options)} model options for {provider_id}")
        ack(options=options)
    except Exception as e:
        logger.error(f"Failed to load model options: {e}", exc_info=True)
        ack(options=[])
