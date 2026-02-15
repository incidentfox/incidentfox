"""Tests for per-subagent model settings via PreToolUse hook."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import AgentConfig, ModelConfig, PromptConfig
from agent_headers import set_agent_context, get_agent_headers, clear_agent_context


def test_subagent_context_switching():
    """Test that agent context switches when different subagents are invoked."""
    # Create multiple agent configs with different model settings
    agents = {
        "planner": AgentConfig(
            name="planner",
            enabled=True,
            model=ModelConfig(temperature=0.2, max_tokens=2000),
            prompt=PromptConfig(system="Planner"),
        ),
        "creative": AgentConfig(
            name="creative",
            enabled=True,
            model=ModelConfig(temperature=0.9, max_tokens=4000),
            prompt=PromptConfig(system="Creative"),
        ),
        "analyzer": AgentConfig(
            name="analyzer",
            enabled=True,
            model=ModelConfig(temperature=0.0, max_tokens=1000, top_p=0.5),
            prompt=PromptConfig(system="Analyzer"),
        ),
    }

    # Simulate PreToolUse hook behavior for each subagent
    for agent_name, agent_cfg in agents.items():
        # This is what the PreToolUse hook does
        set_agent_context(
            agent_name=agent_name,
            model_config={
                "temperature": agent_cfg.model.temperature,
                "max_tokens": agent_cfg.model.max_tokens,
                "top_p": agent_cfg.model.top_p,
            }
        )

        # Verify headers match this subagent's settings
        headers = get_agent_headers()

        assert headers["X-Agent-Name"] == agent_name
        assert headers["X-Agent-Temperature"] == str(agent_cfg.model.temperature)
        assert headers["X-Agent-Max-Tokens"] == str(agent_cfg.model.max_tokens)

        if agent_cfg.model.top_p is not None:
            assert headers["X-Agent-Top-P"] == str(agent_cfg.model.top_p)

        print(f"✅ Context correctly set for subagent '{agent_name}'")

    clear_agent_context()


def test_subagent_with_partial_config():
    """Test subagent with only some model settings defined."""
    agent = AgentConfig(
        name="partial",
        enabled=True,
        model=ModelConfig(temperature=0.5),  # Only temperature set
        prompt=PromptConfig(system="Partial"),
    )

    set_agent_context(
        agent_name=agent.name,
        model_config={
            "temperature": agent.model.temperature,
            "max_tokens": agent.model.max_tokens,  # None
            "top_p": agent.model.top_p,  # None
        }
    )

    headers = get_agent_headers()

    assert headers["X-Agent-Name"] == "partial"
    assert headers["X-Agent-Temperature"] == "0.5"
    assert "X-Agent-Max-Tokens" not in headers  # None values not included
    assert "X-Agent-Top-P" not in headers

    print("✅ Partial config handled correctly")

    clear_agent_context()


def test_subagent_context_isolation():
    """Test that context changes don't affect previous subagent calls."""
    # Set context for first subagent
    set_agent_context(
        "subagent1",
        {"temperature": 0.3, "max_tokens": 1000, "top_p": None}
    )
    headers1 = get_agent_headers()
    assert headers1["X-Agent-Temperature"] == "0.3"

    # Switch to second subagent (this is what happens on next PreToolUse)
    set_agent_context(
        "subagent2",
        {"temperature": 0.8, "max_tokens": 3000, "top_p": 0.95}
    )
    headers2 = get_agent_headers()
    assert headers2["X-Agent-Temperature"] == "0.8"
    assert headers2["X-Agent-Max-Tokens"] == "3000"
    assert headers2["X-Agent-Top-P"] == "0.95"

    # Context should be for subagent2 now
    assert get_agent_headers()["X-Agent-Name"] == "subagent2"

    print("✅ Context isolation verified")

    clear_agent_context()


def test_differentiated_agent_temperatures():
    """Test that different agents can have very different temperature settings."""
    agents_scenarios = [
        ("deterministic-analyzer", 0.0, "For code analysis, need deterministic output"),
        ("balanced-investigator", 0.5, "For investigation, balanced creativity"),
        ("creative-writer", 1.0, "For brainstorming, maximum creativity"),
    ]

    for name, temp, description in agents_scenarios:
        set_agent_context(
            name,
            {"temperature": temp, "max_tokens": None, "top_p": None}
        )

        headers = get_agent_headers()
        assert headers["X-Agent-Temperature"] == str(temp)

        print(f"✅ {name} (temp={temp}): {description}")

    clear_agent_context()


if __name__ == "__main__":
    print("=" * 60)
    print("Per-Subagent Model Settings Tests")
    print("=" * 60)

    tests = [
        test_subagent_context_switching,
        test_subagent_with_partial_config,
        test_subagent_context_isolation,
        test_differentiated_agent_temperatures,
    ]

    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            exit(1)

    print("\n" + "=" * 60)
    print("🎉 ALL TESTS PASSED!")
    print("=" * 60)
    print("\nPer-subagent model settings are working! Each subagent")
    print("can now have its own temperature, max_tokens, and top_p.")
