"""Tests for unified_agent.core module."""

import json
from unittest.mock import MagicMock, patch

import pytest


# Test imports work
def test_imports():
    """Verify all core imports work."""
    from unified_agent.core import (
        Agent,
        AgentConfig,
        AgentDefinition,
        AgentResult,
        MaxTurnsExceeded,
        ModelSettings,
        ProviderConfig,
        Runner,
        RunResult,
        build_agent_from_config,
        build_agent_hierarchy,
        create_generic_agent_from_config,
        function_tool,
        validate_agent_config,
    )

    # Verify classes exist
    assert Agent is not None
    assert Runner is not None
    assert AgentResult is not None


def test_agent_creation():
    """Test basic agent creation."""
    from unified_agent.core import Agent, ModelSettings

    agent = Agent(
        name="Test Agent",
        instructions="You are a test agent.",
        model="sonnet",
        tools=[],
        model_settings=ModelSettings(temperature=0.5),
    )

    assert agent.name == "Test Agent"
    assert agent.model == "sonnet"
    assert agent.model_settings.temperature == 0.5


def test_function_tool_decorator():
    """Test the function_tool decorator."""
    from unified_agent.core import function_tool

    @function_tool
    def my_tool(query: str) -> str:
        """A test tool.

        Args:
            query: The search query
        """
        return f"Result: {query}"

    assert my_tool._is_tool is True
    assert my_tool._tool_schema is not None
    assert my_tool._tool_schema["function"]["name"] == "my_tool"


def test_model_settings_defaults():
    """Test ModelSettings defaults."""
    from unified_agent.core import ModelSettings

    settings = ModelSettings()
    assert settings.temperature == 0.4
    assert settings.max_tokens is None


def test_agent_tools_schema():
    """Test that agent generates tools schema correctly."""
    from unified_agent.core import Agent, function_tool

    @function_tool
    def test_tool(param1: str, param2: int = 10) -> str:
        """Test tool description.

        Args:
            param1: First parameter
            param2: Second parameter
        """
        return "result"

    agent = Agent(
        name="Test",
        instructions="Test",
        model="sonnet",
        tools=[test_tool],
    )

    schema = agent.get_tools_schema()
    assert len(schema) == 1
    assert schema[0]["function"]["name"] == "test_tool"
    assert "param1" in schema[0]["function"]["parameters"]["properties"]


def test_agent_get_tool_by_name():
    """Test finding tool by name."""
    from unified_agent.core import Agent, function_tool

    @function_tool
    def my_tool() -> str:
        """My tool."""
        return "result"

    agent = Agent(
        name="Test",
        instructions="Test",
        model="sonnet",
        tools=[my_tool],
    )

    found = agent.get_tool_by_name("my_tool")
    assert found is not None
    assert found.__name__ == "my_tool"

    not_found = agent.get_tool_by_name("nonexistent")
    assert not_found is None


def test_config_driven_agent_creation():
    """Test creating agent from config."""
    from unified_agent.core import create_generic_agent_from_config, function_tool

    @function_tool
    def available_tool() -> str:
        """An available tool."""
        return "result"

    config = {
        "name": "Config Agent",
        "prompt": "You are helpful.",
        "model": "opus",
        "temperature": 0.2,
        "tools": ["available_tool"],
    }

    agent = create_generic_agent_from_config(
        config,
        available_tools={"available_tool": available_tool},
    )

    assert agent.name == "Config Agent"
    assert "opus" in agent.model
    assert len(agent.tools) == 1


def test_validate_agent_config():
    """Test agent config validation."""
    from unified_agent.core import validate_agent_config

    # Valid config
    valid_config = {
        "model": {"name": "sonnet", "temperature": 0.5},
        "max_turns": 20,
    }
    errors = validate_agent_config(valid_config)
    assert len(errors) == 0

    # Invalid temperature
    invalid_config = {
        "model": {"temperature": 5.0},  # Too high
    }
    errors = validate_agent_config(invalid_config)
    assert any("temperature" in e.lower() for e in errors)

    # Invalid max_turns
    invalid_config = {
        "max_turns": 500,  # Too high
    }
    errors = validate_agent_config(invalid_config)
    assert any("max_turns" in e.lower() for e in errors)


def test_agent_result_model():
    """Test AgentResult pydantic model."""
    from unified_agent.core import AgentResult

    result = AgentResult(
        summary="Test summary",
        details="Test details",
        confidence=85,
        recommendations=["Do this", "Do that"],
        requires_followup=False,
    )

    assert result.summary == "Test summary"
    assert result.confidence == 85
    assert len(result.recommendations) == 2


def test_run_result_model():
    """Test RunResult dataclass."""
    from unified_agent.core import RunResult

    result = RunResult(
        final_output="Test output",
        messages=[{"role": "user", "content": "test"}],
        tool_calls=[],
        status="complete",
    )

    assert result.final_output == "Test output"
    assert result.status == "complete"


def test_model_alias_resolution():
    """Test that model aliases are resolved correctly."""
    from unified_agent.core.agent_builder import normalize_model_name

    assert "anthropic/claude-sonnet" in normalize_model_name("sonnet")
    assert "anthropic/claude-opus" in normalize_model_name("opus")
    # gpt-5.2 is the current default, gpt-4o still supported for backwards compatibility
    assert normalize_model_name("gpt-5.2") == "openai/gpt-5.2"
    assert normalize_model_name("gpt-4o") == "openai/gpt-4o"
    assert normalize_model_name("gemini-2.0-flash") == "gemini/gemini-2.0-flash"

    # Already normalized should pass through
    assert (
        normalize_model_name("anthropic/claude-sonnet-4-20250514")
        == "anthropic/claude-sonnet-4-20250514"
    )
