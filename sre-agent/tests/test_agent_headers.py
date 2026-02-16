"""Tests for per-agent model settings via HTTP header injection."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_headers import clear_agent_context, get_agent_headers, set_agent_context


def test_agent_context_headers():
    """Test that agent context is correctly converted to headers."""
    # Set agent context with all settings
    set_agent_context(
        agent_name="test-agent",
        model_config={
            "temperature": 0.7,
            "max_tokens": 2000,
            "top_p": 0.9,
        },
    )

    headers = get_agent_headers()

    assert headers["X-Agent-Name"] == "test-agent"
    assert headers["X-Agent-Temperature"] == "0.7"
    assert headers["X-Agent-Max-Tokens"] == "2000"
    assert headers["X-Agent-Top-P"] == "0.9"

    # Clear context
    clear_agent_context()
    headers = get_agent_headers()
    assert headers == {}


def test_agent_context_partial_settings():
    """Test agent context with only some settings."""
    set_agent_context(
        agent_name="partial-agent",
        model_config={
            "temperature": 0.5,
            # max_tokens and top_p not set
        },
    )

    headers = get_agent_headers()

    assert headers["X-Agent-Name"] == "partial-agent"
    assert headers["X-Agent-Temperature"] == "0.5"
    assert "X-Agent-Max-Tokens" not in headers
    assert "X-Agent-Top-P" not in headers

    clear_agent_context()


def test_agent_context_none_values():
    """Test that None values are not included in headers."""
    set_agent_context(
        agent_name="none-agent",
        model_config={
            "temperature": None,
            "max_tokens": 1000,
            "top_p": None,
        },
    )

    headers = get_agent_headers()

    assert headers["X-Agent-Name"] == "none-agent"
    assert "X-Agent-Temperature" not in headers
    assert headers["X-Agent-Max-Tokens"] == "1000"
    assert "X-Agent-Top-P" not in headers

    clear_agent_context()


def test_no_context():
    """Test that no headers are returned when no context is set."""
    clear_agent_context()
    headers = get_agent_headers()
    assert headers == {}


def test_context_isolation():
    """Test that agent context is properly isolated."""
    # Set first context
    set_agent_context("agent1", {"temperature": 0.3})
    headers1 = get_agent_headers()
    assert headers1["X-Agent-Temperature"] == "0.3"

    # Set second context (overrides first)
    set_agent_context("agent2", {"temperature": 0.9})
    headers2 = get_agent_headers()
    assert headers2["X-Agent-Temperature"] == "0.9"

    # Clear
    clear_agent_context()
    assert get_agent_headers() == {}


if __name__ == "__main__":
    print("=" * 60)
    print("Agent Header Tests")
    print("=" * 60)

    tests = [
        test_agent_context_headers,
        test_agent_context_partial_settings,
        test_agent_context_none_values,
        test_no_context,
        test_context_isolation,
    ]

    for test in tests:
        try:
            test()
            print(f"✅ {test.__name__}")
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            exit(1)

    print("\n" + "=" * 60)
    print("🎉 ALL TESTS PASSED!")
    print("=" * 60)
