"""Unit tests for Teams bot auto-provisioning."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock botbuilder before importing teams_bot
# ---------------------------------------------------------------------------
_botbuilder_core = types.ModuleType("botbuilder.core")
_botbuilder_schema = types.ModuleType("botbuilder.schema")
_botbuilder = types.ModuleType("botbuilder")


# Core classes — use plain classes to avoid Python 3.14 InvalidSpecError
class _FakeAdapter:
    def __init__(self, *a, **kw):
        pass


_botbuilder_core.BotFrameworkAdapter = _FakeAdapter
_botbuilder_core.BotFrameworkAdapterSettings = lambda *a, **kw: None
_botbuilder_core.TurnContext = MagicMock

# Schema classes
_botbuilder_schema.Activity = MagicMock
_botbuilder_schema.ActivityTypes = MagicMock
_botbuilder_schema.ConversationReference = MagicMock

sys.modules.setdefault("botbuilder", _botbuilder)
sys.modules.setdefault("botbuilder.core", _botbuilder_core)
sys.modules.setdefault("botbuilder.schema", _botbuilder_schema)

from incidentfox_orchestrator.webhooks.teams_bot import TeamsIntegration


def _make_integration(cfg=None, agent_api=None, audit_api=None):
    """Create a TeamsIntegration with mocked dependencies."""
    return TeamsIntegration(
        config_service=cfg or MagicMock(),
        agent_api=agent_api or MagicMock(),
        audit_api=audit_api,
        app_id="test-app-id",
        app_password="test-app-password",
    )


class TestAutoProvision:
    """Tests for _auto_provision()."""

    @pytest.mark.asyncio
    async def test_creates_org_team_and_routing(self):
        """Happy path: creates org, team, patches routing."""
        cfg = MagicMock()
        cfg.create_org_node.return_value = {"org_id": "teams-tenant123"}
        cfg.create_team_node.return_value = {"team_node_id": "default"}
        cfg.get_effective_config_for_node.side_effect = Exception("not found")
        cfg.patch_node_config.return_value = {}

        bot = _make_integration(cfg=cfg)
        with patch.dict("os.environ", {"ORCHESTRATOR_INTERNAL_ADMIN_TOKEN": "tok"}):
            result = await bot._auto_provision(
                routing_id="19:abc@thread.tacv2",
                tenant_id="tenant123",
                correlation_id="corr1",
            )

        assert result is not None
        assert result["org_id"] == "teams-tenant123"
        assert result["team_node_id"] == "default"

        cfg.create_org_node.assert_called_once_with(
            "tok", "teams-tenant123", "Teams Tenant tenant12"
        )
        cfg.create_team_node.assert_called_once_with(
            "tok", "teams-tenant123", "default", "Default Team"
        )
        cfg.patch_node_config.assert_called_once_with(
            "tok",
            "teams-tenant123",
            "default",
            {
                "routing": {"teams_channel_ids": ["19:abc@thread.tacv2"]},
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
    async def test_existing_org_is_idempotent(self):
        """When org already exists, proceeds without error."""
        cfg = MagicMock()
        cfg.create_org_node.return_value = {"org_id": "teams-t1", "exists": True}
        cfg.create_team_node.return_value = {"team_node_id": "default", "exists": True}
        cfg.get_effective_config_for_node.return_value = {
            "routing": {"teams_channel_ids": ["existing-id"]}
        }
        cfg.patch_node_config.return_value = {}

        bot = _make_integration(cfg=cfg)
        with patch.dict("os.environ", {"ORCHESTRATOR_INTERNAL_ADMIN_TOKEN": "tok"}):
            result = await bot._auto_provision(
                routing_id="new-channel",
                tenant_id="t1",
                correlation_id="corr2",
            )

        assert result is not None
        # Should append, not replace
        cfg.patch_node_config.assert_called_once_with(
            "tok",
            "teams-t1",
            "default",
            {
                "routing": {"teams_channel_ids": ["existing-id", "new-channel"]},
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
    async def test_duplicate_channel_not_added_twice(self):
        """If channel already in routing, don't add again."""
        cfg = MagicMock()
        cfg.create_org_node.return_value = {"exists": True}
        cfg.create_team_node.return_value = {"exists": True}
        cfg.get_effective_config_for_node.return_value = {
            "routing": {"teams_channel_ids": ["ch1"]}
        }
        cfg.patch_node_config.return_value = {}

        bot = _make_integration(cfg=cfg)
        with patch.dict("os.environ", {"ORCHESTRATOR_INTERNAL_ADMIN_TOKEN": "tok"}):
            result = await bot._auto_provision(
                routing_id="ch1",
                tenant_id="t1",
                correlation_id="corr3",
            )

        assert result is not None
        cfg.patch_node_config.assert_called_once_with(
            "tok",
            "teams-t1",
            "default",
            {
                "routing": {"teams_channel_ids": ["ch1"]},
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
            # Also ensure ORCHESTRATOR_INTERNAL_ADMIN_TOKEN is not set
            import os

            os.environ.pop("ORCHESTRATOR_INTERNAL_ADMIN_TOKEN", None)
            result = await bot._auto_provision(
                routing_id="ch1",
                tenant_id="t1",
                correlation_id="corr4",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_config_service_error_returns_none(self):
        """On config-service error, returns None gracefully."""
        cfg = MagicMock()
        cfg.create_org_node.side_effect = Exception("connection refused")

        bot = _make_integration(cfg=cfg)
        with patch.dict("os.environ", {"ORCHESTRATOR_INTERNAL_ADMIN_TOKEN": "tok"}):
            result = await bot._auto_provision(
                routing_id="ch1",
                tenant_id="t1",
                correlation_id="corr5",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_no_tenant_id_uses_routing_id(self):
        """Without tenant_id, derives org_id from routing_id."""
        cfg = MagicMock()
        cfg.create_org_node.return_value = {}
        cfg.create_team_node.return_value = {}
        cfg.get_effective_config_for_node.side_effect = Exception("nope")
        cfg.patch_node_config.return_value = {}

        bot = _make_integration(cfg=cfg)
        with patch.dict("os.environ", {"ORCHESTRATOR_INTERNAL_ADMIN_TOKEN": "tok"}):
            result = await bot._auto_provision(
                routing_id="19:very-long-conversation-id@thread.tacv2",
                tenant_id="",
                correlation_id="corr6",
            )

        assert result is not None
        # org_id derived from routing_id (first 40 chars)
        assert result["org_id"] == "teams-19:very-long-conversation-id@thread.tacv"
