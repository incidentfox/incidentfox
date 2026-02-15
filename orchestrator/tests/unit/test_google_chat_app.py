"""Unit tests for Google Chat welcome message and help command."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from incidentfox_orchestrator.webhooks.google_chat_app import (
    HELP_MESSAGE,
    WELCOME_MESSAGE,
    GoogleChatIntegration,
)


def _make_integration() -> GoogleChatIntegration:
    """Create a GoogleChatIntegration with mocked dependencies."""
    return GoogleChatIntegration(
        config_service=MagicMock(),
        agent_api=MagicMock(),
        audit_api=None,
        google_chat_project_id="test-project",
    )


def _message_event(text: str) -> dict:
    """Build a minimal MESSAGE event_data."""
    return {
        "message": {
            "argumentText": text,
            "text": f"@IncidentFox {text}",
            "name": "spaces/AAA/messages/bbb",
            "thread": {"name": "spaces/AAA/threads/ccc"},
        },
        "space": {"name": "spaces/AAA", "type": "SPACE"},
        "user": {"name": "users/123", "displayName": "Test User"},
    }


class TestAddedToSpace:
    """ADDED_TO_SPACE should return the welcome message."""

    def test_returns_welcome_for_space(self):
        integration = _make_integration()
        event_data = {
            "space": {"name": "spaces/AAA", "type": "SPACE"},
            "user": {"name": "users/123", "displayName": "Test User"},
        }
        result = asyncio.get_event_loop().run_until_complete(
            integration.handle_event("ADDED_TO_SPACE", event_data, "corr-1")
        )
        assert result["text"] == WELCOME_MESSAGE

    def test_returns_welcome_for_dm(self):
        integration = _make_integration()
        event_data = {
            "space": {"name": "spaces/BBB", "type": "DM"},
            "user": {"name": "users/456", "displayName": "DM User"},
        }
        result = asyncio.get_event_loop().run_until_complete(
            integration.handle_event("ADDED_TO_SPACE", event_data, "corr-2")
        )
        assert result["text"] == WELCOME_MESSAGE


class TestHelpCommand:
    """MESSAGE with 'help' text should return static help, no LLM."""

    def test_help_returns_help_message(self):
        integration = _make_integration()
        result = asyncio.get_event_loop().run_until_complete(
            integration.handle_event("MESSAGE", _message_event("help"), "corr-3")
        )
        assert result["text"] == HELP_MESSAGE

    def test_help_case_insensitive(self):
        integration = _make_integration()
        result = asyncio.get_event_loop().run_until_complete(
            integration.handle_event("MESSAGE", _message_event("HELP"), "corr-4")
        )
        assert result["text"] == HELP_MESSAGE

    @patch("incidentfox_orchestrator.webhooks.google_chat_app.asyncio.create_task")
    def test_help_does_not_trigger_agent(self, mock_create_task):
        integration = _make_integration()
        asyncio.get_event_loop().run_until_complete(
            integration.handle_event("MESSAGE", _message_event("help"), "corr-5")
        )
        mock_create_task.assert_not_called()


class TestRegularMessage:
    """Non-help MESSAGE should trigger async agent processing."""

    @patch("incidentfox_orchestrator.webhooks.google_chat_app.asyncio.create_task")
    def test_regular_message_triggers_agent(self, mock_create_task):
        integration = _make_integration()
        result = asyncio.get_event_loop().run_until_complete(
            integration.handle_event(
                "MESSAGE", _message_event("investigate high error rate"), "corr-6"
            )
        )
        # Should return empty (async handler will reply)
        assert result == {}
        mock_create_task.assert_called_once()
