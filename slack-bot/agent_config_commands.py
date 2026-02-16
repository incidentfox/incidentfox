#!/usr/bin/env python3
"""
Agent Configuration Commands for Slack Bot

Provides slash commands for managing SRE agent configurations:
- /incidentfox config agents - Show current agent config
- /incidentfox config update - Open JSON editor modal
"""

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def validate_agent_config(json_str: str) -> tuple[bool, str, Dict[str, Any] | None]:
    """Validate agent configuration JSON.

    Returns: (is_valid, error_message, parsed_data)
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {str(e)}", None

    # Validate structure
    if "agents" not in data:
        return False, "Config must have 'agents' key", None

    if not isinstance(data["agents"], dict):
        return False, "'agents' must be an object/dict", None

    # Validate each agent
    for agent_name, agent_config in data["agents"].items():
        if not isinstance(agent_config, dict):
            return False, f"Agent '{agent_name}' config must be an object", None

        # Check for common mistakes
        if "model" in agent_config:
            model = agent_config["model"]
            if not isinstance(model, dict):
                return False, f"Agent '{agent_name}' model must be an object", None

            # Validate model fields
            if "temperature" in model:
                temp = model["temperature"]
                if not isinstance(temp, (int, float)) or temp < 0 or temp > 1:
                    return (
                        False,
                        f"Agent '{agent_name}' temperature must be between 0 and 1",
                        None,
                    )

            if "max_tokens" in model:
                max_tok = model["max_tokens"]
                if not isinstance(max_tok, int) or max_tok <= 0:
                    return (
                        False,
                        f"Agent '{agent_name}' max_tokens must be a positive integer",
                        None,
                    )

            if "top_p" in model:
                top_p = model["top_p"]
                if not isinstance(top_p, (int, float)) or top_p < 0 or top_p > 1:
                    return (
                        False,
                        f"Agent '{agent_name}' top_p must be between 0 and 1",
                        None,
                    )

        if "max_turns" in agent_config:
            max_turns = agent_config["max_turns"]
            if not isinstance(max_turns, int) or max_turns <= 0:
                return (
                    False,
                    f"Agent '{agent_name}' max_turns must be a positive integer",
                    None,
                )

    return True, "", data


def format_agent_list(agents_config: Dict[str, Any]) -> str:
    """Format agents config for display in Slack."""
    if not agents_config:
        return "_No agents configured_"

    lines = []
    for name, config in agents_config.items():
        if not config.get("enabled", True):
            lines.append(f"⚪ *{name}* (disabled)")
            continue

        model = config.get("model", {})
        model_name = model.get("name", "claude-sonnet-4-20250514")
        temp = model.get("temperature")
        max_tokens = model.get("max_tokens")

        # Format agent line
        parts = [f"🤖 *{name}*"]

        # Model name (short version)
        if "gpt" in model_name.lower():
            parts.append("(GPT-4o")
        elif "claude" in model_name.lower():
            parts.append("(Claude")
        else:
            parts.append(f"({model_name}")

        # Temperature
        if temp is not None:
            parts.append(f"temp={temp}")

        # Max tokens
        if max_tokens is not None:
            parts.append(f"max={max_tokens})")
        else:
            parts[-1] += ")"

        lines.append(" ".join(parts))

    return "\n".join(lines)


def create_config_agents_modal(agents_config: Dict[str, Any]) -> Dict:
    """Create modal showing current agent configuration (removed - now directly shows JSON editor)."""
    # This function is kept for backward compatibility but not used
    agent_list = format_agent_list(agents_config)

    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Agent Configuration"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Current Agent Configuration*\n\n" + agent_list,
                },
            },
        ],
    }


def create_json_editor_modal(current_config: Dict[str, Any] | None = None) -> Dict:
    """Create modal with JSON editor for agent configuration."""
    # Format current config nicely
    if current_config and "agents" in current_config:
        initial_value = json.dumps({"agents": current_config["agents"]}, indent=2)
    else:
        # Provide example config
        initial_value = json.dumps(
            {
                "agents": {
                    "investigator": {
                        "enabled": True,
                        "model": {"temperature": 0.3, "max_tokens": 4000},
                        "prompt": {
                            "system": "You are an SRE investigator",
                            "prefix": "Use for incident investigation",
                        },
                    }
                }
            },
            indent=2,
        )

    return {
        "type": "modal",
        "callback_id": "agent_config_update",
        "title": {"type": "plain_text", "text": "Edit Agent Config"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Edit your agent configuration as JSON:*\n"
                    "Configure model settings (temperature, max_tokens, top_p) per agent.",
                },
            },
            {
                "type": "input",
                "block_id": "config_json",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "json_input",
                    "multiline": True,
                    "initial_value": initial_value,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Paste your JSON configuration here...",
                    },
                },
                "label": {"type": "plain_text", "text": "Configuration JSON"},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "💡 *Tip:* Use temp=0.0 for deterministic, 0.3-0.5 for balanced, 0.7-1.0 for creative agents",
                    }
                ],
            },
        ],
    }


def register_agent_config_commands(app):
    """Register agent config slash commands and handlers with the Slack app."""

    @app.action("view_agent_config")
    def handle_view_agent_config(ack, body, client):
        """Handle button click from home tab - directly opens JSON editor."""
        ack()

        # Get current config
        try:
            from config_client import get_config_client

            config_client = get_config_client()
            team_id = body["team"]["id"]
            current_config = config_client.get_workspace_config(team_id)
        except Exception as e:
            logger.error(f"Failed to get config: {e}", exc_info=True)
            current_config = None

        # Open JSON editor modal directly
        try:
            client.views_open(
                trigger_id=body["trigger_id"],
                view=create_json_editor_modal(current_config),
            )
        except Exception as e:
            logger.error(f"Failed to open modal: {e}", exc_info=True)
            # Try to send error message to user
            try:
                client.chat_postMessage(
                    channel=body["user"]["id"],
                    text=f"❌ Failed to open agent config modal: {str(e)}",
                )
            except:
                pass

    @app.view("agent_config_update")
    def handle_agent_config_update(ack, body, view, client):
        """Handle agent config update from JSON editor modal."""
        logger.info("=== handle_agent_config_update called ===")
        logger.info(f"Team ID: {body.get('team', {}).get('id')}")
        logger.info(f"User ID: {body.get('user', {}).get('id')}")

        # Get the JSON input
        json_str = view["state"]["values"]["config_json"]["json_input"]["value"]
        logger.info(f"Received JSON (first 200 chars): {json_str[:200]}")

        # Validate
        is_valid, error_msg, parsed_data = validate_agent_config(json_str)
        logger.info(f"Validation result: is_valid={is_valid}, error={error_msg}")

        if not is_valid:
            # Show validation error
            logger.warning(f"Validation failed: {error_msg}")
            ack(
                response_action="errors",
                errors={"config_json": error_msg},
            )
            return

        # Validation passed, acknowledge
        logger.info("Validation passed, acknowledging modal submission")
        ack()

        # Save configuration
        try:
            from config_client import get_config_client

            config_client = get_config_client()
            team_id = body["team"]["id"]

            # Update config via config_service using the internal _update_config method
            org_id = f"slack-{team_id}"
            team_node_id = "default"
            logger.info(f"Calling _update_config with org_id={org_id}, team_node_id={team_node_id}")
            logger.info(f"Config data: {json.dumps(parsed_data, indent=2)}")

            config_client._update_config(org_id, team_node_id, parsed_data)
            logger.info("Config update completed successfully")

            # Notify user of success
            logger.info(f"Sending success DM to user: {body['user']['id']}")
            client.chat_postMessage(
                channel=body["user"]["id"],
                text=(
                    "✅ *Agent configuration updated!*\n\n"
                    f"Updated {len(parsed_data.get('agents', {}))} agent(s). "
                    "Changes will take effect on the next investigation."
                ),
            )
            logger.info("Success DM sent")

        except Exception as e:
            logger.error(f"Failed to save config: {e}", exc_info=True)
            client.chat_postMessage(
                channel=body["user"]["id"],
                text=f"❌ Failed to save configuration: {str(e)}",
            )

    # Add slash command handler to app.py or integrate into existing command structure
    logger.info("Agent config commands registered successfully")
