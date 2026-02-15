"""Tests for enhanced config loading (ModelConfig, max_turns, sub_agents)."""

import pytest

from config import AgentConfig, ModelConfig, PromptConfig, ToolsConfig


def test_model_config_defaults():
    """Test ModelConfig with default values."""
    model = ModelConfig()
    assert model.name == "claude-sonnet-4-20250514"
    assert model.temperature is None
    assert model.max_tokens is None
    assert model.top_p is None


def test_model_config_custom():
    """Test ModelConfig with custom values."""
    model = ModelConfig(
        name="claude-opus-4",
        temperature=0.5,
        max_tokens=4000,
        top_p=0.9,
    )
    assert model.name == "claude-opus-4"
    assert model.temperature == 0.5
    assert model.max_tokens == 4000
    assert model.top_p == 0.9


def test_agent_config_with_model():
    """Test AgentConfig with ModelConfig."""
    agent = AgentConfig(
        name="test",
        enabled=True,
        model=ModelConfig(temperature=0.3, max_tokens=2000),
    )
    assert agent.model.temperature == 0.3
    assert agent.model.max_tokens == 2000


def test_agent_config_with_max_turns():
    """Test AgentConfig with max_turns."""
    agent = AgentConfig(
        name="test",
        enabled=True,
        max_turns=50,
    )
    assert agent.max_turns == 50


def test_agent_config_with_sub_agents():
    """Test AgentConfig with sub_agents dict."""
    agent = AgentConfig(
        name="orchestrator",
        enabled=True,
        sub_agents={
            "k8s": True,
            "metrics": True,
            "logs": False,
        },
    )
    assert agent.sub_agents["k8s"] is True
    assert agent.sub_agents["metrics"] is True
    assert agent.sub_agents["logs"] is False


def test_agent_config_backward_compatibility():
    """Test that AgentConfig works without new fields (backward compatibility)."""
    # Old config without model, max_turns, sub_agents
    agent = AgentConfig(
        name="test",
        enabled=True,
        prompt=PromptConfig(system="You are a test agent"),
        tools=ToolsConfig(enabled=["*"], disabled=[]),
    )

    # New fields should have sensible defaults
    assert agent.model.name == "claude-sonnet-4-20250514"
    assert agent.model.temperature is None
    assert agent.max_turns is None
    assert agent.sub_agents == {}


def test_agent_config_full_example():
    """Test AgentConfig with all fields populated."""
    agent = AgentConfig(
        enabled=True,
        name="investigator",
        prompt=PromptConfig(
            system="You are an SRE investigator",
            prefix="Use for incident investigation",
            suffix="",
        ),
        tools=ToolsConfig(
            enabled=["*"],
            disabled=["Write", "Edit"],
        ),
        model=ModelConfig(
            name="claude-sonnet-4-20250514",
            temperature=0.3,
            max_tokens=4000,
            top_p=0.9,
        ),
        max_turns=50,
        sub_agents={
            "k8s": True,
            "metrics": True,
        },
    )

    assert agent.enabled is True
    assert agent.name == "investigator"
    assert agent.prompt.system == "You are an SRE investigator"
    assert agent.tools.disabled == ["Write", "Edit"]
    assert agent.model.temperature == 0.3
    assert agent.max_turns == 50
    assert len(agent.sub_agents) == 2


def test_model_config_temperature_bounds():
    """Test ModelConfig accepts valid temperature values."""
    # Valid temperatures (0.0-1.0)
    model1 = ModelConfig(temperature=0.0)
    assert model1.temperature == 0.0

    model2 = ModelConfig(temperature=1.0)
    assert model2.temperature == 1.0

    model3 = ModelConfig(temperature=0.5)
    assert model3.temperature == 0.5


def test_model_config_top_p_bounds():
    """Test ModelConfig accepts valid top_p values."""
    # Valid top_p (0.0-1.0)
    model1 = ModelConfig(top_p=0.0)
    assert model1.top_p == 0.0

    model2 = ModelConfig(top_p=1.0)
    assert model2.top_p == 1.0

    model3 = ModelConfig(top_p=0.95)
    assert model3.top_p == 0.95


def test_agent_config_max_turns_positive():
    """Test AgentConfig with positive max_turns."""
    agent = AgentConfig(name="test", max_turns=100)
    assert agent.max_turns == 100


def test_agent_config_empty_sub_agents():
    """Test AgentConfig with empty sub_agents (leaf agent)."""
    agent = AgentConfig(name="leaf", sub_agents={})
    assert agent.sub_agents == {}
    assert len(agent.sub_agents) == 0


def test_agent_config_nested_hierarchy_example():
    """Test creating agents for STARSHIP TOPOLOGY."""
    # Planner (top level)
    planner = AgentConfig(
        name="planner",
        enabled=True,
        model=ModelConfig(temperature=0.3, max_tokens=4000),
        max_turns=50,
        sub_agents={"investigation": True},
    )

    # Investigation (orchestrator)
    investigation = AgentConfig(
        name="investigation",
        enabled=True,
        max_turns=40,
        sub_agents={
            "k8s": True,
            "metrics": True,
            "logs": True,
        },
    )

    # Leaf agents
    k8s = AgentConfig(name="k8s", enabled=True, sub_agents={})
    metrics = AgentConfig(name="metrics", enabled=True, sub_agents={})
    logs = AgentConfig(name="logs", enabled=True, sub_agents={})

    # Verify hierarchy
    assert "investigation" in planner.sub_agents
    assert "k8s" in investigation.sub_agents
    assert "metrics" in investigation.sub_agents
    assert "logs" in investigation.sub_agents
    assert len(k8s.sub_agents) == 0
    assert len(metrics.sub_agents) == 0
    assert len(logs.sub_agents) == 0
