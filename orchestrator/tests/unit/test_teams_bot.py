"""Unit tests for MS Teams welcome message and help command."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock botbuilder modules before importing teams_bot
_botbuilder_core = MagicMock()
_botbuilder_schema = MagicMock()
sys.modules.setdefault("botbuilder", MagicMock())
sys.modules.setdefault("botbuilder.core", _botbuilder_core)
sys.modules.setdefault("botbuilder.schema", _botbuilder_schema)

# Provide minimal mocks for the classes teams_bot imports
_botbuilder_core.BotFrameworkAdapter = MagicMock
_botbuilder_core.BotFrameworkAdapterSettings = MagicMock
_botbuilder_core.TurnContext = MagicMock()
_botbuilder_schema.Activity = MagicMock
_botbuilder_schema.ActivityTypes = MagicMock()
_botbuilder_schema.ActivityTypes.typing = "typing"
_botbuilder_schema.ConversationReference = MagicMock

from incidentfox_orchestrator.webhooks.teams_bot import (  # noqa: E402
    HELP_MESSAGE,
    WELCOME_MESSAGE,
    TeamsIntegration,
)


def _make_activity(text: str = "", members_added=None):
    """Build a minimal mock Activity."""
    activity = MagicMock()
    activity.type = "message"
    activity.text = text
    activity.entities = []
    activity.channel_data = {}
    activity.conversation = MagicMock()
    activity.conversation.id = "conv-123"
    activity.from_property = MagicMock()
    activity.from_property.id = "user-1"
    activity.from_property.name = "Test User"
    activity.recipient = MagicMock()
    activity.recipient.id = "bot-1"
    activity.members_added = members_added or []
    activity.members_removed = []
    return activity


def _make_turn_context(activity):
    """Build a mock TurnContext."""
    ctx = AsyncMock()
    ctx.activity = activity
    ctx.send_activity = AsyncMock(return_value=MagicMock(id="msg-1"))
    return ctx


def _make_integration():
    """Create a TeamsIntegration with mocked dependencies."""
    return TeamsIntegration(
        config_service=MagicMock(),
        agent_api=MagicMock(),
        audit_api=None,
        app_id="test-app-id",
        app_password="test-password",
    )


class TestBotAdded:
    """Bot added to conversation should send welcome message."""

    @pytest.mark.asyncio
    async def test_welcome_on_bot_added(self):
        integration = _make_integration()
        bot_member = MagicMock()
        bot_member.id = "bot-1"
        activity = _make_activity(members_added=[bot_member])
        ctx = _make_turn_context(activity)

        await integration._handle_conversation_update(ctx)

        ctx.send_activity.assert_called_once_with(WELCOME_MESSAGE)


class TestHelpCommand:
    """MESSAGE with 'help' should return static help, no LLM."""

    @pytest.mark.asyncio
    async def test_help_returns_help_message(self):
        integration = _make_integration()
        activity = _make_activity(text="help")
        ctx = _make_turn_context(activity)

        await integration._handle_message(ctx)

        ctx.send_activity.assert_called_once_with(HELP_MESSAGE)

    @pytest.mark.asyncio
    async def test_help_case_insensitive(self):
        integration = _make_integration()
        activity = _make_activity(text="HELP")
        ctx = _make_turn_context(activity)

        await integration._handle_message(ctx)

        ctx.send_activity.assert_called_once_with(HELP_MESSAGE)

    @pytest.mark.asyncio
    @patch("incidentfox_orchestrator.webhooks.teams_bot.asyncio.create_task")
    async def test_help_does_not_trigger_agent(self, mock_create_task):
        integration = _make_integration()
        activity = _make_activity(text="help")
        ctx = _make_turn_context(activity)

        await integration._handle_message(ctx)

        mock_create_task.assert_not_called()


class TestRegularMessage:
    """Non-help MESSAGE should trigger async agent processing."""

    @pytest.mark.asyncio
    @patch("incidentfox_orchestrator.webhooks.teams_bot.asyncio.create_task")
    async def test_regular_message_triggers_agent(self, mock_create_task):
        integration = _make_integration()
        activity = _make_activity(text="investigate high error rate")
        ctx = _make_turn_context(activity)

        await integration._handle_message(ctx)

        mock_create_task.assert_called_once()
