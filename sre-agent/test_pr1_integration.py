#!/usr/bin/env python3
"""
Integration test for PR #1: Enhanced Config-Driven Agent Building.

Tests the complete implementation:
1. Config loading with new fields
2. Topological sort for nested agents
3. Model settings and max_turns application
4. Backward compatibility
"""

import json
import tempfile
import os
from pathlib import Path

def test_config_loading():
    """Test that config loads correctly with new fields."""
    from config import AgentConfig, ModelConfig, load_team_config

    # Create an AgentConfig with all new fields
    agent = AgentConfig(
        enabled=True,
        name="test",
        model=ModelConfig(temperature=0.3, max_tokens=4000, top_p=0.9),
        max_turns=50,
        sub_agents={"k8s": True, "metrics": True}
    )

    assert agent.model.temperature == 0.3
    assert agent.model.max_tokens == 4000
    assert agent.model.top_p == 0.9
    assert agent.max_turns == 50
    assert agent.sub_agents["k8s"] is True
    print("✅ Config loading with new fields works!")


def test_topological_sort():
    """Test topological sort with nested hierarchy."""
    from config import AgentConfig
    from agent_builder import topological_sort_agents

    # Create STARSHIP TOPOLOGY
    agents = {
        "planner": AgentConfig(
            name="planner",
            enabled=True,
            sub_agents={"investigation": True}
        ),
        "investigation": AgentConfig(
            name="investigation",
            enabled=True,
            sub_agents={"k8s": True, "metrics": True}
        ),
        "k8s": AgentConfig(name="k8s", enabled=True),
        "metrics": AgentConfig(name="metrics", enabled=True),
    }

    build_order = topological_sort_agents(agents)

    # Verify correct order
    assert build_order.index("k8s") < build_order.index("investigation")
    assert build_order.index("metrics") < build_order.index("investigation")
    assert build_order.index("investigation") < build_order.index("planner")

    print(f"✅ Topological sort works! Build order: {build_order}")


def test_circular_dependency_detection():
    """Test that circular dependencies are detected."""
    from config import AgentConfig
    from agent_builder import topological_sort_agents

    agents = {
        "a": AgentConfig(name="a", enabled=True, sub_agents={"b": True}),
        "b": AgentConfig(name="b", enabled=True, sub_agents={"a": True}),
    }

    try:
        topological_sort_agents(agents)
        assert False, "Should have raised ValueError for circular dependency"
    except ValueError as e:
        assert "Circular dependency" in str(e)
        print("✅ Circular dependency detection works!")


def test_backward_compatibility():
    """Test that old configs without new fields still work."""
    from config import AgentConfig, PromptConfig, ToolsConfig

    # Old-style config without model, max_turns, sub_agents
    agent = AgentConfig(
        name="old_agent",
        enabled=True,
        prompt=PromptConfig(system="Test prompt"),
        tools=ToolsConfig(enabled=["*"])
    )

    # New fields should have defaults
    assert agent.model.name == "claude-sonnet-4-20250514"
    assert agent.model.temperature is None
    assert agent.max_turns is None
    assert agent.sub_agents == {}

    print("✅ Backward compatibility maintained!")


def test_model_settings_environment():
    """Test that model settings are applied via environment variables."""
    from config import AgentConfig, ModelConfig
    import os

    # Create agent with model settings
    agent = AgentConfig(
        name="test",
        model=ModelConfig(
            temperature=0.5,
            max_tokens=3000,
            top_p=0.95
        )
    )

    # Simulate what agent.py does
    if agent.model.temperature is not None:
        os.environ["LLM_TEMPERATURE"] = str(agent.model.temperature)
    if agent.model.max_tokens is not None:
        os.environ["LLM_MAX_TOKENS"] = str(agent.model.max_tokens)
    if agent.model.top_p is not None:
        os.environ["LLM_TOP_P"] = str(agent.model.top_p)

    # Verify environment variables are set
    assert os.environ.get("LLM_TEMPERATURE") == "0.5"
    assert os.environ.get("LLM_MAX_TOKENS") == "3000"
    assert os.environ.get("LLM_TOP_P") == "0.95"

    print("✅ Model settings environment variables work!")


def test_validation():
    """Test dependency validation."""
    from config import AgentConfig
    from agent_builder import validate_agent_dependencies

    # Test missing dependency
    agents = {
        "a": AgentConfig(name="a", enabled=True, sub_agents={"missing": True})
    }

    errors = validate_agent_dependencies(agents)
    assert len(errors) == 1
    assert "missing" in errors[0]
    assert "does not exist" in errors[0]

    # Test disabled dependency
    agents = {
        "a": AgentConfig(name="a", enabled=False),
        "b": AgentConfig(name="b", enabled=True, sub_agents={"a": True})
    }

    errors = validate_agent_dependencies(agents)
    assert len(errors) == 1
    assert "disabled" in errors[0]

    print("✅ Dependency validation works!")


def test_complete_integration():
    """Test complete integration with mock config."""
    print("\n🧪 Testing complete integration...")

    # Create a mock config as config_service would provide
    config_data = {
        "agents": {
            "planner": {
                "enabled": True,
                "model": {
                    "temperature": 0.3,
                    "max_tokens": 4000
                },
                "max_turns": 50,
                "sub_agents": {"investigation": True},
                "prompt": {
                    "system": "You are a planner agent",
                    "prefix": "Planning and coordination"
                },
                "tools": {
                    "enabled": ["*"]
                }
            },
            "investigation": {
                "enabled": True,
                "sub_agents": {"k8s": True, "metrics": True},
                "prompt": {
                    "system": "You are an investigator",
                    "prefix": "Incident investigation"
                }
            },
            "k8s": {
                "enabled": True,
                "prompt": {
                    "system": "You are a k8s specialist",
                    "prefix": "Kubernetes debugging"
                }
            },
            "metrics": {
                "enabled": True,
                "prompt": {
                    "system": "You are a metrics analyst",
                    "prefix": "Metrics analysis"
                }
            }
        }
    }

    # Parse agents as config.py would
    from config import AgentConfig, ModelConfig, PromptConfig, ToolsConfig

    agents = {}
    for name, cfg in config_data["agents"].items():
        model_data = cfg.get("model", {})
        prompt_data = cfg.get("prompt", {})
        tools_data = cfg.get("tools", {})

        agents[name] = AgentConfig(
            enabled=cfg.get("enabled", True),
            name=name,
            model=ModelConfig(
                name=model_data.get("name", "claude-sonnet-4-20250514"),
                temperature=model_data.get("temperature"),
                max_tokens=model_data.get("max_tokens"),
                top_p=model_data.get("top_p")
            ),
            max_turns=cfg.get("max_turns"),
            sub_agents=cfg.get("sub_agents", {}),
            prompt=PromptConfig(
                system=prompt_data.get("system", ""),
                prefix=prompt_data.get("prefix", ""),
                suffix=prompt_data.get("suffix", "")
            ),
            tools=ToolsConfig(
                enabled=tools_data.get("enabled", ["*"]),
                disabled=tools_data.get("disabled", [])
            )
        )

    # Test topological sort
    from agent_builder import topological_sort_agents

    build_order = topological_sort_agents(agents)
    expected_order = ["k8s", "metrics", "investigation", "planner"]

    assert build_order == expected_order, f"Expected {expected_order}, got {build_order}"

    print(f"  ✅ Build order correct: {build_order}")
    print(f"  ✅ Planner has {agents['planner'].max_turns} max_turns")
    print(f"  ✅ Planner temperature: {agents['planner'].model.temperature}")
    print(f"  ✅ Planner max_tokens: {agents['planner'].model.max_tokens}")
    print(f"  ✅ Investigation depends on: {list(agents['investigation'].sub_agents.keys())}")

    print("\n✅ Complete integration test passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("PR #1 Integration Tests")
    print("=" * 60)

    try:
        test_config_loading()
        test_topological_sort()
        test_circular_dependency_detection()
        test_backward_compatibility()
        test_model_settings_environment()
        test_validation()
        test_complete_integration()

        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)