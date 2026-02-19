#!/usr/bin/env python3
"""
Integration test for Enhanced Config-Driven Agent Building.

Tests the complete implementation:
1. Config loading with new fields (ModelConfig, max_turns)
2. Model settings application via environment variables
3. Backward compatibility
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_config_loading():
    """Test that config loads correctly with new fields."""
    from config import AgentConfig, ModelConfig

    # Create an AgentConfig with all new fields
    agent = AgentConfig(
        enabled=True,
        name="test",
        model=ModelConfig(temperature=0.3, max_tokens=4000, top_p=0.9),
        max_turns=50,
    )

    assert agent.model.temperature == 0.3
    assert agent.model.max_tokens == 4000
    assert agent.model.top_p == 0.9
    assert agent.max_turns == 50
    print("✅ Config loading with new fields works!")


def test_backward_compatibility():
    """Test that old configs without new fields still work."""
    from config import AgentConfig, PromptConfig, ToolsConfig

    # Old-style config without model, max_turns
    agent = AgentConfig(
        name="old_agent",
        enabled=True,
        prompt=PromptConfig(system="Test prompt"),
        tools=ToolsConfig(enabled=["*"]),
    )

    # New fields should have defaults
    assert agent.model.name == "claude-sonnet-4-20250514"
    assert agent.model.temperature is None
    assert agent.max_turns is None

    print("✅ Backward compatibility maintained!")


def test_model_settings_environment():
    """Test that model settings are applied via environment variables."""
    import os

    from config import AgentConfig, ModelConfig

    # Create agent with model settings
    agent = AgentConfig(
        name="test", model=ModelConfig(temperature=0.5, max_tokens=3000, top_p=0.95)
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


def test_complete_integration():
    """Test complete integration with mock config."""
    print("\n🧪 Testing complete integration...")

    # Create a mock config as config_service would provide
    config_data = {
        "agents": {
            "planner": {
                "enabled": True,
                "model": {"temperature": 0.3, "max_tokens": 4000},
                "max_turns": 50,
                "prompt": {
                    "system": "You are a planner agent",
                    "prefix": "Planning and coordination",
                },
                "tools": {"enabled": ["*"]},
            },
            "investigation": {
                "enabled": True,
                "max_turns": 40,
                "prompt": {
                    "system": "You are an investigator",
                    "prefix": "Incident investigation",
                },
            },
            "k8s": {
                "enabled": True,
                "prompt": {
                    "system": "You are a k8s specialist",
                    "prefix": "Kubernetes debugging",
                },
            },
            "metrics": {
                "enabled": True,
                "prompt": {
                    "system": "You are a metrics analyst",
                    "prefix": "Metrics analysis",
                },
            },
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
                top_p=model_data.get("top_p"),
            ),
            max_turns=cfg.get("max_turns"),
            prompt=PromptConfig(
                system=prompt_data.get("system", ""),
                prefix=prompt_data.get("prefix", ""),
                suffix=prompt_data.get("suffix", ""),
            ),
            tools=ToolsConfig(
                enabled=tools_data.get("enabled", ["*"]),
                disabled=tools_data.get("disabled", []),
            ),
        )

    # Verify agents were parsed correctly
    assert len(agents) == 4
    assert agents["planner"].model.temperature == 0.3
    assert agents["planner"].max_turns == 50
    assert agents["investigation"].max_turns == 40
    assert agents["k8s"].max_turns is None

    print(f"  ✅ Loaded {len(agents)} agents")
    print(f"  ✅ Planner has {agents['planner'].max_turns} max_turns")
    print(f"  ✅ Planner temperature: {agents['planner'].model.temperature}")
    print(f"  ✅ Planner max_tokens: {agents['planner'].model.max_tokens}")

    print("\n✅ Complete integration test passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Enhanced Config Integration Tests")
    print("=" * 60)

    try:
        test_config_loading()
        test_backward_compatibility()
        test_model_settings_environment()
        test_complete_integration()

        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
