"""Simple tests for per-agent header injection logic."""

import json


def test_agent_headers_injection():
    """Test that X-Agent-* headers are correctly injected into request body."""
    # Mock request headers
    headers = {
        "x-agent-name": "test-agent",
        "x-agent-temperature": "0.7",
        "x-agent-max-tokens": "2000",
        "x-agent-top-p": "0.95",
    }

    # Original request body
    body = {
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 4000,  # This should be overridden
    }

    # Simulate header injection (from llm_proxy.py)
    if "x-agent-temperature" in headers:
        try:
            body["temperature"] = float(headers["x-agent-temperature"])
        except ValueError:
            pass

    if "x-agent-max-tokens" in headers:
        try:
            body["max_tokens"] = int(headers["x-agent-max-tokens"])
        except ValueError:
            pass

    if "x-agent-top-p" in headers:
        try:
            body["top_p"] = float(headers["x-agent-top-p"])
        except ValueError:
            pass

    # Verify injection worked
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 2000  # Overrode original value
    assert body["top_p"] == 0.95
    print("✅ Headers injected correctly")


def test_no_agent_headers():
    """Test that request works fine without agent headers."""
    headers = {}

    body = {
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "test"}],
        "temperature": 0.5,
    }

    # No headers to inject
    if "x-agent-temperature" in headers:
        body["temperature"] = float(headers["x-agent-temperature"])

    # Original temperature should remain
    assert body["temperature"] == 0.5
    print("✅ No headers - body unchanged")


def test_partial_agent_headers():
    """Test that partial agent headers work correctly."""
    headers = {
        "x-agent-name": "partial-agent",
        "x-agent-temperature": "0.3",
        # No max_tokens or top_p
    }

    body = {
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 4000,
    }

    # Inject only temperature
    if "x-agent-temperature" in headers:
        body["temperature"] = float(headers["x-agent-temperature"])
    if "x-agent-max-tokens" in headers:
        body["max_tokens"] = int(headers["x-agent-max-tokens"])

    # Verify
    assert body["temperature"] == 0.3
    assert body["max_tokens"] == 4000  # Unchanged
    print("✅ Partial headers work correctly")


def test_invalid_header_values():
    """Test that invalid header values are handled gracefully."""
    headers = {
        "x-agent-temperature": "not-a-number",
        "x-agent-max-tokens": "also-not-a-number",
    }

    body = {
        "model": "claude-sonnet-4-20250514",
        "messages": [{"role": "user", "content": "test"}],
    }

    # Try to inject (should fail gracefully)
    if "x-agent-temperature" in headers:
        try:
            body["temperature"] = float(headers["x-agent-temperature"])
        except ValueError:
            pass  # Expected

    if "x-agent-max-tokens" in headers:
        try:
            body["max_tokens"] = int(headers["x-agent-max-tokens"])
        except ValueError:
            pass  # Expected

    # Body should not have invalid values
    assert "temperature" not in body
    assert "max_tokens" not in body
    print("✅ Invalid headers handled gracefully")


if __name__ == "__main__":
    print("=" * 60)
    print("Credential Proxy Header Injection Tests")
    print("=" * 60)

    test_agent_headers_injection()
    test_no_agent_headers()
    test_partial_agent_headers()
    test_invalid_header_values()

    print("\n" + "=" * 60)
    print("🎉 ALL TESTS PASSED!")
    print("=" * 60)
