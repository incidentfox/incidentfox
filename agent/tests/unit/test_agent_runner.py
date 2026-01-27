"""Tests for agent registry."""

from unittest.mock import Mock

import pytest
from ai_agent.core.agent_runner import AgentRegistry


class TestAgentRegistry:
    def test_register_factory_and_get_agent(self):
        """Test registering a factory and retrieving agents."""
        registry = AgentRegistry()
        mock_agent = Mock()
        mock_agent.name = "TestAgent"

        # Factory returns the mock agent
        factory = Mock(return_value=mock_agent)

        registry.register_factory("test", factory)

        # Factory should have been called once for warming (with None)
        factory.assert_called_once()

        # Should get the default agent
        agent = registry.get_agent("test")
        assert agent == mock_agent
        assert "test" in registry.list_agents()

    def test_get_nonexistent_agent(self):
        """Test getting agent that doesn't exist."""
        registry = AgentRegistry()
        assert registry.get_agent("nonexistent") is None

    def test_get_agent_with_team_config(self):
        """Test getting agent with team-specific config creates new instance."""
        registry = AgentRegistry()
        default_agent = Mock()
        default_agent.name = "DefaultAgent"
        team_agent = Mock()
        team_agent.name = "TeamAgent"

        # Factory returns default on first call (warming), team agent on second
        factory = Mock(side_effect=[default_agent, team_agent])

        registry.register_factory("test", factory)

        # Get with team config should create a new agent
        agent = registry.get_agent(
            "test",
            team_config_hash="team123",
            factory_kwargs={"team_id": "123"},
        )
        assert agent == team_agent

        # Factory should have been called twice now
        assert factory.call_count == 2

    def test_team_agent_caching(self):
        """Test that team agents are cached."""
        registry = AgentRegistry()
        default_agent = Mock()
        team_agent = Mock()

        factory = Mock(side_effect=[default_agent, team_agent])

        registry.register_factory("test", factory)

        # First call creates agent
        agent1 = registry.get_agent("test", team_config_hash="team123")
        # Second call should return cached
        agent2 = registry.get_agent("test", team_config_hash="team123")

        assert agent1 == agent2
        # Factory should only be called twice (warming + first team call)
        assert factory.call_count == 2

    def test_list_agents(self):
        """Test listing all registered agent names."""
        registry = AgentRegistry()

        factory1 = Mock(return_value=Mock())
        factory2 = Mock(return_value=Mock())

        registry.register_factory("agent1", factory1)
        registry.register_factory("agent2", factory2)

        agents = registry.list_agents()
        assert "agent1" in agents
        assert "agent2" in agents
        assert len(agents) == 2
