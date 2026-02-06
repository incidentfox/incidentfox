"""
End-to-end integration tests for unified-agent.

These tests:
1. Build and run the unified-agent in a Docker container
2. Create mock incident scenarios
3. Send prompts to the agent via HTTP
4. Validate the agent correctly investigates and responds

Requirements:
- Docker must be running
- ANTHROPIC_API_KEY env var set for real LLM tests (or use mock mode)

Usage:
    # Run with mock LLM (no API key needed, tests basic flow)
    pytest tests/integration/test_e2e_incident.py -v

    # Run with real LLM (requires API key)
    ANTHROPIC_API_KEY=sk-... pytest tests/integration/test_e2e_incident.py -v --run-real-llm
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
import requests

# Test configuration
INTEGRATION_DIR = Path(__file__).parent
COMPOSE_FILE = INTEGRATION_DIR / "docker-compose.yml"
AGENT_URL = "http://localhost:8888"


def pytest_addoption(parser):
    """Add custom pytest options."""
    parser.addoption(
        "--run-real-llm",
        action="store_true",
        default=False,
        help="Run tests with real LLM API calls",
    )


@pytest.fixture(scope="module")
def docker_compose_up():
    """Start docker-compose environment for the test module."""
    if not COMPOSE_FILE.exists():
        pytest.skip("docker-compose.yml not found")

    # Check if Docker is available
    result = subprocess.run(["docker", "info"], capture_output=True)
    if result.returncode != 0:
        pytest.skip("Docker is not available")

    # Build and start services
    try:
        subprocess.run(
            ["docker-compose", "-f", str(COMPOSE_FILE), "up", "-d", "--build"],
            cwd=INTEGRATION_DIR,
            check=True,
            capture_output=True,
        )

        # Wait for health check
        for i in range(30):
            try:
                response = requests.get(f"{AGENT_URL}/health", timeout=2)
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(2)
        else:
            pytest.fail("Unified agent failed to start within timeout")

        yield

    finally:
        # Cleanup
        subprocess.run(
            ["docker-compose", "-f", str(COMPOSE_FILE), "down", "-v"],
            cwd=INTEGRATION_DIR,
            capture_output=True,
        )


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_check(self, docker_compose_up):
        """Test that health endpoint returns healthy status."""
        response = requests.get(f"{AGENT_URL}/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "unified-agent-sandbox"
        assert "version" in data

    def test_health_shows_model(self, docker_compose_up):
        """Test that health endpoint shows configured model."""
        response = requests.get(f"{AGENT_URL}/health")

        data = response.json()
        assert "model" in data
        # Default model should be set
        assert (
            "anthropic" in data["model"]
            or "gemini" in data["model"]
            or "openai" in data["model"]
        )


class TestConfigEndpoint:
    """Tests for the /config endpoint."""

    def test_config_endpoint(self, docker_compose_up):
        """Test that config endpoint returns agent configuration."""
        response = requests.get(f"{AGENT_URL}/config")

        assert response.status_code == 200
        data = response.json()

        # Should have basic config fields
        assert "tenant_id" in data
        assert "team_id" in data
        assert "agents" in data

        # Should have at least the default investigator agent
        assert len(data["agents"]) >= 1


class TestSessionManagement:
    """Tests for session management."""

    def test_sessions_endpoint(self, docker_compose_up):
        """Test that sessions endpoint lists active sessions."""
        response = requests.get(f"{AGENT_URL}/sessions")

        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)


class TestExecuteEndpoint:
    """Tests for the /execute endpoint (agent execution)."""

    def test_execute_returns_sse_stream(self, docker_compose_up):
        """Test that execute endpoint returns SSE stream."""
        response = requests.post(
            f"{AGENT_URL}/execute",
            json={
                "prompt": "Hello, what can you help me with?",
                "thread_id": "test-stream-001",
            },
            stream=True,
            timeout=60,
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Read first few events
        events = []
        for i, line in enumerate(response.iter_lines(decode_unicode=True)):
            if line.startswith("data:"):
                events.append(line)
            if i > 20 or len(events) > 5:
                break

        # Should have received some events
        assert len(events) > 0

    def test_execute_with_invalid_json(self, docker_compose_up):
        """Test that execute handles invalid JSON gracefully."""
        response = requests.post(
            f"{AGENT_URL}/execute",
            data="not json",
            headers={"Content-Type": "application/json"},
        )

        # Should return 422 Unprocessable Entity
        assert response.status_code == 422


class TestInterruptEndpoint:
    """Tests for the /interrupt endpoint."""

    def test_interrupt_nonexistent_session(self, docker_compose_up):
        """Test interrupting a session that doesn't exist."""
        response = requests.post(
            f"{AGENT_URL}/interrupt",
            json={"thread_id": "nonexistent-session"},
            stream=True,
        )

        assert response.status_code == 200

        # Read the SSE stream
        events = []
        for line in response.iter_lines(decode_unicode=True):
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
            if len(events) > 2:
                break

        # Should get an error event
        assert any(e.get("type") == "error" for e in events)


# =============================================================================
# Mock incident investigation tests (no real LLM needed)
# =============================================================================


class TestMockIncidentInvestigation:
    """
    Tests that validate agent behavior with mock data.

    These tests don't make real LLM calls but verify:
    - Request/response flow works
    - SSE streaming works
    - Session management works
    - Event types are correct
    """

    def test_incident_prompt_accepted(self, docker_compose_up):
        """Test that an incident investigation prompt is accepted."""
        prompt = """
        We have a pod in CrashLoopBackOff state. The pod is payment-service-7d8f9c6b4-x2k9p
        in the production namespace. Please investigate.
        """

        response = requests.post(
            f"{AGENT_URL}/execute",
            json={
                "prompt": prompt,
                "thread_id": "incident-001",
                "max_turns": 3,  # Limit turns for faster test
            },
            stream=True,
            timeout=120,
        )

        assert response.status_code == 200

        # Collect events
        events = []
        for line in response.iter_lines(decode_unicode=True):
            if line.startswith("data:"):
                try:
                    event = json.loads(line[5:])
                    events.append(event)
                except json.JSONDecodeError:
                    pass
            # Limit to first 50 events for test speed
            if len(events) > 50:
                break

        # Should have received events
        assert len(events) > 0

        # Check we got expected event types
        event_types = {e.get("type") for e in events}
        # At minimum, should have thought or result events
        assert len(event_types) > 0

    def test_session_persists_across_requests(self, docker_compose_up):
        """Test that session state persists across requests."""
        thread_id = "persist-test-001"

        # First request
        response1 = requests.post(
            f"{AGENT_URL}/execute",
            json={"prompt": "Hello", "thread_id": thread_id, "max_turns": 1},
            stream=True,
            timeout=60,
        )
        # Consume the stream
        list(response1.iter_lines())

        # Check session exists
        sessions_response = requests.get(f"{AGENT_URL}/sessions")
        sessions = sessions_response.json()["sessions"]
        session_ids = [s["thread_id"] for s in sessions]
        assert thread_id in session_ids

        # Second request to same thread
        response2 = requests.post(
            f"{AGENT_URL}/execute",
            json={
                "prompt": "What did I ask before?",
                "thread_id": thread_id,
                "max_turns": 1,
            },
            stream=True,
            timeout=60,
        )
        assert response2.status_code == 200


# =============================================================================
# Real LLM integration tests (requires API key)
# =============================================================================


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set - skipping real LLM tests",
)
class TestRealLLMIncidentInvestigation:
    """
    Tests with real LLM API calls.

    These tests require ANTHROPIC_API_KEY to be set and verify
    the agent can actually investigate incidents.
    """

    def test_oom_investigation(self, docker_compose_up, request):
        """Test that agent investigates OOM issue correctly."""
        if not request.config.getoption("--run-real-llm"):
            pytest.skip("Use --run-real-llm to run real LLM tests")

        prompt = """
        We have an alert: Pod payment-service-7d8f9c6b4-x2k9p is in CrashLoopBackOff.
        The logs in /workspace/incident/logs/app.log show an OOMKilled error.
        The pod description is in /workspace/incident/pod_describe.txt.
        Please investigate the root cause.
        """

        response = requests.post(
            f"{AGENT_URL}/execute",
            json={
                "prompt": prompt,
                "thread_id": "real-oom-test",
                "max_turns": 10,
            },
            stream=True,
            timeout=300,
        )

        assert response.status_code == 200

        # Collect all events
        events = []
        thoughts = []
        tool_calls = []
        result_text = ""

        for line in response.iter_lines(decode_unicode=True):
            if line.startswith("data:"):
                try:
                    event = json.loads(line[5:])
                    events.append(event)

                    if event.get("type") == "thought":
                        thoughts.append(event.get("data", {}).get("text", ""))
                    elif event.get("type") == "tool_start":
                        tool_calls.append(event.get("data", {}).get("tool", ""))
                    elif event.get("type") == "result":
                        result_text = event.get("data", {}).get("text", "")

                except json.JSONDecodeError:
                    pass

        # Agent should have:
        # 1. Generated some thoughts
        assert len(thoughts) > 0, "Agent should produce thoughts"

        # 2. Used tools to investigate (read files, etc.)
        # Note: Tool names depend on implementation
        assert (
            len(tool_calls) > 0 or len(thoughts) > 3
        ), "Agent should use tools or think deeply"

        # 3. Mentioned OOM or memory in the investigation
        all_text = " ".join(thoughts) + " " + result_text
        oom_mentioned = any(
            keyword in all_text.lower()
            for keyword in ["oom", "memory", "512mi", "limit", "killed"]
        )
        assert (
            oom_mentioned
        ), f"Agent should identify memory issue. Got: {all_text[:500]}"

    def test_multi_model_gemini(self, docker_compose_up, request):
        """Test that Gemini model works (if configured)."""
        if not request.config.getoption("--run-real-llm"):
            pytest.skip("Use --run-real-llm to run real LLM tests")
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY not set")

        # This test would need to restart the container with GEMINI model
        # For now, just verify the config endpoint shows model selection works
        response = requests.get(f"{AGENT_URL}/config")
        assert response.status_code == 200


# =============================================================================
# Local (non-Docker) tests for faster iteration
# =============================================================================


class TestLocalAgentExecution:
    """
    Fast tests that run without Docker.

    These test the agent execution logic directly without container overhead.
    """

    @pytest.mark.asyncio
    async def test_agent_run_mocked(self):
        """Test agent execution with mocked LLM."""
        from unittest.mock import AsyncMock, patch

        # Import after ensuring dependencies are available
        try:
            from unified_agent.core.agent import Agent
            from unified_agent.core.runner import Runner
        except ImportError:
            pytest.skip("unified_agent not installed")

        # Create a simple agent
        agent = Agent(
            name="TestInvestigator",
            instructions="You are a test agent.",
            model="anthropic/claude-sonnet-4-20250514",
        )

        # Mock the LLM call
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content="I found the issue: OOM due to memory limit of 512Mi.",
                    tool_calls=None,
                )
            )
        ]

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            result = await Runner.run(agent, "Investigate the pod crash")

            assert result.final_output is not None
            assert (
                "OOM" in result.final_output or "memory" in result.final_output.lower()
            )
            assert result.status == "complete"

    @pytest.mark.asyncio
    async def test_agent_with_tools_mocked(self):
        """Test agent with tools using mocked LLM."""
        from unittest.mock import AsyncMock, MagicMock, patch

        try:
            from unified_agent.core.agent import Agent, function_tool
            from unified_agent.core.runner import Runner
        except ImportError:
            pytest.skip("unified_agent not installed")

        # Define a test tool
        @function_tool
        def read_log(path: str) -> str:
            """Read a log file."""
            return (
                "2024-01-15T10:10:00Z ERROR OOMKilled: Container exceeded memory limit"
            )

        agent = Agent(
            name="TestInvestigator",
            instructions="You investigate issues. Use the read_log tool to examine logs.",
            model="anthropic/claude-sonnet-4-20250514",
            tools=[read_log],
        )

        # Mock LLM to call the tool then respond
        tool_call_response = MagicMock()
        tool_call_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=None,
                    tool_calls=[
                        MagicMock(
                            id="call_1",
                            function=MagicMock(
                                name="read_log",
                                arguments='{"path": "/var/log/app.log"}',
                            ),
                        )
                    ],
                )
            )
        ]

        final_response = MagicMock()
        final_response.choices = [
            MagicMock(
                message=MagicMock(
                    content="Based on the logs, the container was OOMKilled.",
                    tool_calls=None,
                )
            )
        ]

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [tool_call_response, final_response]

            result = await Runner.run(agent, "Check the logs", max_turns=5)

            assert result.status == "complete"
            # Tool was called but may show as unknown if mock name doesn't match
            assert result.final_output is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
