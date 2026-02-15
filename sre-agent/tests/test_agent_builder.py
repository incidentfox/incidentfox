"""Tests for agent_builder module (topological sort and validation)."""

import pytest

from agent_builder import (
    topological_sort_agents,
    validate_agent_dependencies,
    _get_sub_agent_ids,
)
from config import AgentConfig, PromptConfig


def test_get_sub_agent_ids_empty():
    """Test _get_sub_agent_ids with no sub_agents."""
    agent = AgentConfig(name="test", sub_agents={})
    assert _get_sub_agent_ids(agent) == []


def test_get_sub_agent_ids_with_enabled():
    """Test _get_sub_agent_ids with enabled subagents."""
    agent = AgentConfig(
        name="test",
        sub_agents={
            "k8s": True,
            "metrics": True,
            "logs": False,  # Disabled
        },
    )
    result = _get_sub_agent_ids(agent)
    assert set(result) == {"k8s", "metrics"}


def test_topological_sort_linear():
    """Test topological sort with linear dependency chain."""
    agents = {
        "a": AgentConfig(name="a", enabled=True, sub_agents={}),
        "b": AgentConfig(name="b", enabled=True, sub_agents={"a": True}),
        "c": AgentConfig(name="c", enabled=True, sub_agents={"b": True}),
    }

    result = topological_sort_agents(agents)
    assert result == ["a", "b", "c"]


def test_topological_sort_nested_hierarchy():
    """Test topological sort with STARSHIP TOPOLOGY (planner → investigation → leaf agents)."""
    agents = {
        "planner": AgentConfig(
            name="planner",
            enabled=True,
            sub_agents={"investigation": True},
        ),
        "investigation": AgentConfig(
            name="investigation",
            enabled=True,
            sub_agents={
                "k8s": True,
                "metrics": True,
            },
        ),
        "k8s": AgentConfig(name="k8s", enabled=True, sub_agents={}),
        "metrics": AgentConfig(name="metrics", enabled=True, sub_agents={}),
    }

    result = topological_sort_agents(agents)

    # k8s and metrics must come before investigation
    assert result.index("k8s") < result.index("investigation")
    assert result.index("metrics") < result.index("investigation")

    # investigation must come before planner
    assert result.index("investigation") < result.index("planner")


def test_topological_sort_parallel_branches():
    """Test topological sort with parallel dependency branches."""
    agents = {
        "root": AgentConfig(
            name="root",
            enabled=True,
            sub_agents={"branch1": True, "branch2": True},
        ),
        "branch1": AgentConfig(
            name="branch1",
            enabled=True,
            sub_agents={"leaf1": True},
        ),
        "branch2": AgentConfig(
            name="branch2",
            enabled=True,
            sub_agents={"leaf2": True},
        ),
        "leaf1": AgentConfig(name="leaf1", enabled=True, sub_agents={}),
        "leaf2": AgentConfig(name="leaf2", enabled=True, sub_agents={}),
    }

    result = topological_sort_agents(agents)

    # Leaves before branches
    assert result.index("leaf1") < result.index("branch1")
    assert result.index("leaf2") < result.index("branch2")

    # Branches before root
    assert result.index("branch1") < result.index("root")
    assert result.index("branch2") < result.index("root")


def test_topological_sort_circular_dependency():
    """Test that circular dependencies are detected and raise ValueError."""
    agents = {
        "a": AgentConfig(name="a", enabled=True, sub_agents={"b": True}),
        "b": AgentConfig(name="b", enabled=True, sub_agents={"a": True}),
    }

    with pytest.raises(ValueError, match="Circular dependency"):
        topological_sort_agents(agents)


def test_topological_sort_self_reference():
    """Test that self-referencing agent raises ValueError."""
    agents = {
        "a": AgentConfig(name="a", enabled=True, sub_agents={"a": True}),
    }

    with pytest.raises(ValueError, match="Circular dependency"):
        topological_sort_agents(agents)


def test_topological_sort_disabled_agents():
    """Test that disabled agents are excluded from sort."""
    agents = {
        "a": AgentConfig(name="a", enabled=True, sub_agents={}),
        "b": AgentConfig(name="b", enabled=False, sub_agents={"a": True}),
        "c": AgentConfig(name="c", enabled=True, sub_agents={"a": True}),
    }

    result = topological_sort_agents(agents)
    assert result == ["a", "c"]
    assert "b" not in result


def test_topological_sort_disabled_dependency():
    """Test that dependencies on disabled agents are ignored."""
    agents = {
        "a": AgentConfig(name="a", enabled=False, sub_agents={}),
        "b": AgentConfig(name="b", enabled=True, sub_agents={"a": True}),
    }

    result = topological_sort_agents(agents)
    # b should be built even though its dependency is disabled
    assert result == ["b"]


def test_validate_agent_dependencies_valid():
    """Test validation with valid dependencies."""
    agents = {
        "a": AgentConfig(name="a", enabled=True, sub_agents={}),
        "b": AgentConfig(name="b", enabled=True, sub_agents={"a": True}),
    }

    errors = validate_agent_dependencies(agents)
    assert errors == []


def test_validate_agent_dependencies_missing():
    """Test validation detects missing dependencies."""
    agents = {
        "b": AgentConfig(name="b", enabled=True, sub_agents={"missing": True}),
    }

    errors = validate_agent_dependencies(agents)
    assert len(errors) == 1
    assert "missing" in errors[0]
    assert "does not exist" in errors[0]


def test_validate_agent_dependencies_disabled():
    """Test validation detects dependencies on disabled agents."""
    agents = {
        "a": AgentConfig(name="a", enabled=False, sub_agents={}),
        "b": AgentConfig(name="b", enabled=True, sub_agents={"a": True}),
    }

    errors = validate_agent_dependencies(agents)
    assert len(errors) == 1
    assert "disabled" in errors[0]


def test_validate_agent_dependencies_multiple_errors():
    """Test validation reports multiple errors."""
    agents = {
        "a": AgentConfig(name="a", enabled=False, sub_agents={}),
        "b": AgentConfig(
            name="b",
            enabled=True,
            sub_agents={
                "a": True,  # Disabled
                "missing": True,  # Doesn't exist
            },
        ),
    }

    errors = validate_agent_dependencies(agents)
    assert len(errors) == 2


def test_topological_sort_complex_dag():
    """Test topological sort with complex DAG (multiple valid orderings)."""
    agents = {
        "a": AgentConfig(name="a", enabled=True, sub_agents={}),
        "b": AgentConfig(name="b", enabled=True, sub_agents={}),
        "c": AgentConfig(name="c", enabled=True, sub_agents={"a": True, "b": True}),
        "d": AgentConfig(name="d", enabled=True, sub_agents={"b": True}),
        "e": AgentConfig(name="e", enabled=True, sub_agents={"c": True, "d": True}),
    }

    result = topological_sort_agents(agents)

    # Verify constraints (multiple valid orderings exist)
    assert result.index("a") < result.index("c")
    assert result.index("b") < result.index("c")
    assert result.index("b") < result.index("d")
    assert result.index("c") < result.index("e")
    assert result.index("d") < result.index("e")
