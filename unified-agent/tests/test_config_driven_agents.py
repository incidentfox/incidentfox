"""
Tests for config-driven agent functionality.

These tests verify:
1. Config loads correctly from environment and Config Service
2. Agents are built from config with correct model selection
3. Tool resolution works based on enabled/disabled lists
4. Agent hierarchy is built with topological sorting
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_config_defaults(self):
        """Test default configuration values."""
        from unified_agent.core.config import Config, TeamConfig

        config = Config()
        assert config.llm_model == "anthropic/claude-sonnet-4-20250514"
        assert config.tenant_id == "local"
        assert config.team_id == "local"
        assert config.team_config is None

    def test_config_from_environment(self):
        """Test config loading from environment variables."""
        from unified_agent.core.config import load_config

        with patch.dict(
            os.environ,
            {
                "LLM_MODEL": "gemini/gemini-2.0-flash",
                "INCIDENTFOX_TENANT_ID": "test-tenant",
                "INCIDENTFOX_TEAM_ID": "test-team",
            },
        ):
            config = load_config()
            assert config.llm_model == "gemini/gemini-2.0-flash"
            assert config.tenant_id == "test-tenant"
            assert config.team_id == "test-team"

    def test_team_config_model(self):
        """Test TeamConfig pydantic model."""
        from unified_agent.core.config import AgentConfig, ModelConfig, TeamConfig

        team_config = TeamConfig(
            agents_config={
                "investigator": AgentConfig(
                    enabled=True,
                    name="Custom Investigator",
                    model=ModelConfig(name="gemini/gemini-2.0-flash", temperature=0.3),
                ),
            },
            integrations={"datadog": {"api_key": "configured"}},
        )

        agent = team_config.get_agent_config("investigator")
        assert agent.name == "Custom Investigator"
        assert agent.model.name == "gemini/gemini-2.0-flash"
        assert agent.model.temperature == 0.3

        # Test default for unknown agent
        unknown = team_config.get_agent_config("unknown")
        assert unknown.name == "unknown"


class TestAgentBuilder:
    """Tests for config-driven agent building."""

    def test_build_agent_hierarchy_empty(self):
        """Test building with empty config."""
        from unified_agent.core.agent_builder import build_agent_hierarchy

        # Empty config should still work
        agents = build_agent_hierarchy({"agents": {}})
        assert isinstance(agents, dict)

    def test_build_agent_hierarchy_single(self):
        """Test building a single agent from config."""
        from unified_agent.core.agent_builder import build_agent_hierarchy

        config = {
            "agents": {
                "investigator": {
                    "enabled": True,
                    "name": "Test Investigator",
                    "model": {"name": "sonnet", "temperature": 0.5},
                    "tools": {"enabled": ["*"]},
                }
            }
        }

        agents = build_agent_hierarchy(config)
        assert "investigator" in agents
        assert agents["investigator"].name == "Test Investigator"
        assert "sonnet" in agents["investigator"].model

    def test_build_agent_hierarchy_multi_model(self):
        """Test building agents with different models."""
        from unified_agent.core.agent_builder import build_agent_hierarchy

        config = {
            "agents": {
                "claude_agent": {
                    "enabled": True,
                    "model": {"name": "anthropic/claude-sonnet-4-20250514"},
                },
                "gemini_agent": {
                    "enabled": True,
                    "model": {"name": "gemini/gemini-2.0-flash"},
                },
                "openai_agent": {
                    "enabled": True,
                    "model": {"name": "openai/gpt-4o"},
                },
            }
        }

        agents = build_agent_hierarchy(config)

        assert "anthropic" in agents["claude_agent"].model
        assert "gemini" in agents["gemini_agent"].model
        assert "openai" in agents["openai_agent"].model

    def test_build_agent_disabled(self):
        """Test that disabled agents are not built."""
        from unified_agent.core.agent_builder import build_agent_hierarchy

        config = {
            "agents": {
                "active": {"enabled": True},
                "disabled": {"enabled": False},
            }
        }

        agents = build_agent_hierarchy(config)
        assert "active" in agents
        assert "disabled" not in agents

    def test_topological_sort(self):
        """Test that agents are built in dependency order."""
        from unified_agent.core.agent_builder import _topological_sort_agents

        # planner depends on investigator, investigator depends on k8s
        config = {
            "planner": {"sub_agents": {"investigator": True}},
            "investigator": {"sub_agents": {"k8s": True}},
            "k8s": {},
        }

        order = _topological_sort_agents(config)

        # k8s should come before investigator, investigator before planner
        k8s_idx = order.index("k8s")
        inv_idx = order.index("investigator")
        plan_idx = order.index("planner")

        assert k8s_idx < inv_idx < plan_idx


class TestModelNormalization:
    """Tests for model name normalization."""

    def test_alias_resolution(self):
        """Test model alias resolution."""
        from unified_agent.core.agent_builder import normalize_model_name

        # Short aliases
        assert "anthropic/claude-sonnet" in normalize_model_name("sonnet")
        assert "anthropic/claude-opus" in normalize_model_name("opus")
        assert "anthropic/claude-haiku" in normalize_model_name("haiku")

    def test_provider_prefix_passthrough(self):
        """Test that provider-prefixed names pass through."""
        from unified_agent.core.agent_builder import normalize_model_name

        # Already prefixed should pass through
        assert (
            normalize_model_name("anthropic/claude-sonnet-4-20250514")
            == "anthropic/claude-sonnet-4-20250514"
        )
        assert (
            normalize_model_name("gemini/gemini-2.0-flash") == "gemini/gemini-2.0-flash"
        )
        assert normalize_model_name("openai/gpt-4o") == "openai/gpt-4o"

    def test_unprefixed_model_normalization(self):
        """Test normalizing unprefixed model names."""
        from unified_agent.core.agent_builder import normalize_model_name

        # Claude models
        assert (
            normalize_model_name("claude-sonnet-4-20250514")
            == "anthropic/claude-sonnet-4-20250514"
        )

        # OpenAI models
        assert normalize_model_name("gpt-4o") == "openai/gpt-4o"
        assert normalize_model_name("gpt-4o-mini") == "openai/gpt-4o-mini"

        # Gemini models
        assert normalize_model_name("gemini-2.0-flash") == "gemini/gemini-2.0-flash"

    def test_reasoning_model_detection(self):
        """Test detection of reasoning models."""
        from unified_agent.core.agent_builder import is_reasoning_model

        # Reasoning models (don't support temperature)
        assert is_reasoning_model("openai/o1") is True
        assert is_reasoning_model("openai/o3") is True
        assert is_reasoning_model("o1-preview") is True

        # Standard models
        assert is_reasoning_model("anthropic/claude-sonnet-4-20250514") is False
        assert is_reasoning_model("gemini/gemini-2.0-flash") is False
        assert is_reasoning_model("gpt-4o") is False


class TestToolResolution:
    """Tests for tool resolution from config."""

    def test_resolve_all_tools(self):
        """Test resolving all tools with '*'."""
        from unified_agent.core.agent_builder import resolve_tools

        # With some tools registered
        tools = resolve_tools(enabled=["*"], disabled=[])
        # Should work even if empty (no tools registered in test env)
        assert isinstance(tools, list)

    def test_resolve_specific_tools(self):
        """Test resolving specific tools by name."""
        from unified_agent.core.agent_builder import (
            get_all_available_tools,
            resolve_tools,
        )

        available = get_all_available_tools()
        if available:
            # Get first available tool name
            tool_name = next(iter(available.keys()))
            tools = resolve_tools(enabled=[tool_name], disabled=[])
            assert len(tools) == 1
        else:
            # No tools available in test env
            tools = resolve_tools(enabled=["nonexistent"], disabled=[])
            assert len(tools) == 0

    def test_resolve_with_disabled(self):
        """Test that disabled tools are excluded."""
        from unified_agent.core.agent_builder import (
            get_all_available_tools,
            resolve_tools,
        )

        available = get_all_available_tools()
        if len(available) >= 2:
            names = list(available.keys())
            # Enable all, disable one
            tools = resolve_tools(enabled=["*"], disabled=[names[0]])
            assert len(tools) == len(available) - 1


class TestSandboxServerConfig:
    """Tests for sandbox server configuration integration."""

    def test_effective_config_conversion(self):
        """Test converting TeamConfig to effective config dict."""
        from unified_agent.core.config import (
            AgentConfig,
            ModelConfig,
            TeamConfig,
            ToolsConfig,
        )

        team_config = TeamConfig(
            agents_config={
                "investigator": AgentConfig(
                    enabled=True,
                    name="Test Agent",
                    model=ModelConfig(name="gemini/gemini-2.0-flash"),
                    tools=ToolsConfig(enabled=["*"], disabled=["remediation"]),
                ),
            },
            integrations={"slack": {}},
        )

        # Simulate server's _get_effective_config
        from unittest.mock import MagicMock, patch

        mock_config = MagicMock()
        mock_config.team_config = team_config
        mock_config.llm_model = "anthropic/claude-sonnet-4-20250514"

        with patch("unified_agent.sandbox.server.get_config", return_value=mock_config):
            from unified_agent.sandbox.server import _get_effective_config

            effective = _get_effective_config()

            assert "agents" in effective
            assert "investigator" in effective["agents"]
            assert (
                effective["agents"]["investigator"]["model"]["name"]
                == "gemini/gemini-2.0-flash"
            )
            assert (
                "remediation"
                in effective["agents"]["investigator"]["tools"]["disabled"]
            )


class TestSandboxManager:
    """Tests for SandboxManager configuration."""

    def test_default_image(self):
        """Test default image is unified-agent."""
        from unified_agent.sandbox.manager import SandboxManager

        manager = SandboxManager()
        assert "unified-agent" in manager.image

    def test_image_from_env(self):
        """Test image can be set from environment."""
        from unified_agent.sandbox.manager import SandboxManager

        with patch.dict(os.environ, {"UNIFIED_AGENT_IMAGE": "custom/image:v1"}):
            manager = SandboxManager()
            assert manager.image == "custom/image:v1"

    def test_image_override(self):
        """Test image can be overridden in constructor."""
        from unified_agent.sandbox.manager import SandboxManager

        manager = SandboxManager(image="my/custom:latest")
        assert manager.image == "my/custom:latest"

    def test_build_container_env(self):
        """Test container environment variable building."""
        from unified_agent.sandbox.manager import SandboxManager

        manager = SandboxManager()
        env = manager._build_container_env(
            tenant_id="test-tenant",
            team_id="test-team",
            thread_id="thread-123",
            sandbox_name="investigation-thread-123",
            jwt_token="test-jwt",
            team_token="test-team-token",
            llm_model="gemini/gemini-2.0-flash",
            configured_integrations="[]",
        )

        # Check env is a list
        assert isinstance(env, list)

        # Convert to dict for easier checking
        env_dict = {}
        for item in env:
            if "value" in item:
                env_dict[item["name"]] = item["value"]
            else:
                env_dict[item["name"]] = item  # valueFrom

        # Check key values
        assert env_dict["INCIDENTFOX_TENANT_ID"] == "test-tenant"
        assert env_dict["INCIDENTFOX_TEAM_ID"] == "test-team"
        assert env_dict["THREAD_ID"] == "thread-123"
        assert env_dict["TEAM_TOKEN"] == "test-team-token"
        assert env_dict["LLM_MODEL"] == "gemini/gemini-2.0-flash"

    def test_build_container_env_no_team_token(self):
        """Test container env without team token."""
        from unified_agent.sandbox.manager import SandboxManager

        manager = SandboxManager()
        env = manager._build_container_env(
            tenant_id="test",
            team_id="test",
            thread_id="t1",
            sandbox_name="s1",
            jwt_token="jwt",
            team_token=None,  # No team token
            llm_model=None,  # No model override
            configured_integrations="[]",
        )

        env_names = [item["name"] for item in env]

        # TEAM_TOKEN should not be present
        assert "TEAM_TOKEN" not in env_names

        # LLM_MODEL should be from secret (valueFrom)
        llm_model_item = next(item for item in env if item["name"] == "LLM_MODEL")
        assert "valueFrom" in llm_model_item
