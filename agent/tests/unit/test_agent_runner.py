"""Tests for agent runner."""

from unittest.mock import Mock, patch

import pytest
from ai_agent.core.agent_runner import AgentRegistry, AgentRunner


class TestAgentRunner:
    @pytest.fixture
    def mock_agent(self):
        """Create a mock agent."""
        agent = Mock()
        agent.name = "TestAgent"
        return agent

    @pytest.fixture
    def agent_runner(self, mock_agent):
        """Create agent runner with mock agent."""
        with patch("ai_agent.core.agent_runner.get_metrics_collector"):
            runner = AgentRunner(mock_agent, max_retries=2, timeout=30)
            return runner

    @pytest.mark.asyncio
    async def test_successful_execution(self, agent_runner, mock_agent):
        """Test successful agent execution."""
        # Mock the runner
        mock_run_result = Mock()
        mock_run_result.output = "test output"
        mock_run_result.status = "success"

        with patch.object(agent_runner.runner, "run", return_value=mock_run_result):
            context = Mock()
            result = await agent_runner.run(context, "test message")

            assert result.success
            assert result.output == "test output"
            assert result.error is None

    @pytest.mark.asyncio
    async def test_timeout_handling(self, agent_runner):
        """Test that timeout is handled properly."""

        with patch.object(agent_runner.runner, "run", side_effect=TimeoutError()):
            context = Mock()
            result = await agent_runner.run(context, "test message")

            assert not result.success
            assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_error_handling(self, agent_runner):
        """Test that errors are caught and logged."""
        with patch.object(
            agent_runner.runner, "run", side_effect=Exception("Test error")
        ):
            context = Mock()
            result = await agent_runner.run(context, "test message")

            assert not result.success
            assert "Test error" in result.error


class TestAgentRegistry:
    def test_register_and_get_agent(self):
        """Test registering and retrieving agents."""
        registry = AgentRegistry()
        mock_agent = Mock()
        mock_agent.name = "TestAgent"

        registry.register("test", mock_agent)

        assert registry.get_agent("test") == mock_agent
        assert "test" in registry.list_agents()

    def test_get_nonexistent_agent(self):
        """Test getting agent that doesn't exist."""
        registry = AgentRegistry()
        assert registry.get_agent("nonexistent") is None
