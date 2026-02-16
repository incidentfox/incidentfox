"""Unit tests for Google Chat auto-provisioning."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from incidentfox_orchestrator.webhooks.google_chat_app import GoogleChatIntegration


def _make_integration(cfg=None, agent_api=None, audit_api=None):
    """Create a GoogleChatIntegration with mocked dependencies."""
    return GoogleChatIntegration(
        config_service=cfg or MagicMock(),
        agent_api=agent_api or MagicMock(),
        audit_api=audit_api,
        google_chat_project_id="test-project",
    )


class TestAutoProvision:
    """Tests for _auto_provision()."""

    @pytest.mark.asyncio
    async def test_creates_org_team_and_routing(self):
        """Happy path: creates org, team, patches routing."""
        cfg = MagicMock()
        cfg.create_org_node.return_value = {"org_id": "gchat-ABC123"}
        cfg.create_team_node.return_value = {"team_node_id": "default"}
        cfg.get_effective_config_for_node.side_effect = Exception("not found")
        cfg.patch_node_config.return_value = {}

        bot = _make_integration(cfg=cfg)
        with patch.dict("os.environ", {"ORCHESTRATOR_INTERNAL_ADMIN_TOKEN": "tok"}):
            result = await bot._auto_provision(
                space_id="ABC123",
                correlation_id="corr1",
            )

        assert result is not None
        assert result["org_id"] == "gchat-ABC123"
        assert result["team_node_id"] == "default"

        cfg.create_org_node.assert_called_once_with(
            "tok", "gchat-ABC123", "Google Chat ABC123"
        )
        cfg.create_team_node.assert_called_once_with(
            "tok", "gchat-ABC123", "default", "Default Team"
        )
        cfg.patch_node_config.assert_called_once_with(
            "tok",
            "gchat-ABC123",
            "default",
            {
                "routing": {"google_chat_space_ids": ["ABC123"]},
                "integrations": {
                    "anthropic": {
                        "is_trial": True,
                        "trial_expires_at": "2030-12-31T23:59:59.000000",
                        "subscription_status": "active",
                    },
                },
            },
        )

    @pytest.mark.asyncio
    async def test_existing_org_appends_space_id(self):
        """When org exists, appends new space_id to routing."""
        cfg = MagicMock()
        cfg.create_org_node.return_value = {"exists": True}
        cfg.create_team_node.return_value = {"exists": True}
        cfg.get_effective_config_for_node.return_value = {
            "routing": {"google_chat_space_ids": ["existing-space"]}
        }
        cfg.patch_node_config.return_value = {}

        bot = _make_integration(cfg=cfg)
        with patch.dict("os.environ", {"ORCHESTRATOR_INTERNAL_ADMIN_TOKEN": "tok"}):
            result = await bot._auto_provision(
                space_id="new-space",
                correlation_id="corr2",
            )

        assert result is not None
        cfg.patch_node_config.assert_called_once_with(
            "tok",
            "gchat-new-space",
            "default",
            {
                "routing": {"google_chat_space_ids": ["existing-space", "new-space"]},
                "integrations": {
                    "anthropic": {
                        "is_trial": True,
                        "trial_expires_at": "2030-12-31T23:59:59.000000",
                        "subscription_status": "active",
                    },
                },
            },
        )

    @pytest.mark.asyncio
    async def test_no_admin_token_returns_none(self):
        """Without admin token, returns None."""
        bot = _make_integration()
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN", None)
            result = await bot._auto_provision(
                space_id="ABC",
                correlation_id="corr3",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_config_service_error_returns_none(self):
        """On config-service error, returns None gracefully."""
        cfg = MagicMock()
        cfg.create_org_node.side_effect = Exception("timeout")

        bot = _make_integration(cfg=cfg)
        with patch.dict("os.environ", {"ORCHESTRATOR_INTERNAL_ADMIN_TOKEN": "tok"}):
            result = await bot._auto_provision(
                space_id="ABC",
                correlation_id="corr4",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_handle_added_to_space_fires_provision(self):
        """ADDED_TO_SPACE event triggers background provisioning."""
        cfg = MagicMock()
        cfg.create_org_node.return_value = {}
        cfg.create_team_node.return_value = {}
        cfg.get_effective_config_for_node.side_effect = Exception("nope")
        cfg.patch_node_config.return_value = {}

        bot = _make_integration(cfg=cfg)
        event_data = {
            "space": {"name": "spaces/XYZ789", "type": "ROOM"},
            "user": {"displayName": "Test User"},
        }

        import asyncio

        with patch.dict("os.environ", {"ORCHESTRATOR_INTERNAL_ADMIN_TOKEN": "tok"}):
            result = await bot._handle_added_to_space(event_data, "corr5")

            # Should return welcome message
            assert "IncidentFox" in result["text"]

            # Give background task time to run (must be inside patch context)
            await asyncio.sleep(0.1)

            # Verify provisioning was called
            cfg.create_org_node.assert_called_once_with(
                "tok", "gchat-XYZ789", "Google Chat XYZ789"
            )
