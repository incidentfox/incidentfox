#!/usr/bin/env python3
"""
Tests for the observability backend abstraction in agent.py.

Tests backend detection, initialization, and helper functions for
Laminar, Langfuse, and disabled ("none") modes.

Run: cd sre-agent && uv run python -m pytest tests/test_observability.py -v
"""

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers to reset module state between tests
# ---------------------------------------------------------------------------


def _reset_observability():
    """Reset the observability module state so each test starts clean."""
    import agent

    agent._observability_backend = "none"
    agent._observability_initialized = False
    agent._Laminar = None
    agent._observe = None
    agent._langfuse_client = None


# ---------------------------------------------------------------------------
# Backend detection tests
# ---------------------------------------------------------------------------


class TestDetectBackend:
    """Tests for _detect_observability_backend()."""

    def setup_method(self):
        _reset_observability()

    def test_explicit_laminar(self):
        from agent import _detect_observability_backend

        with patch.dict(os.environ, {"OBSERVABILITY_BACKEND": "laminar"}, clear=False):
            assert _detect_observability_backend() == "laminar"

    def test_explicit_langfuse(self):
        from agent import _detect_observability_backend

        with patch.dict(os.environ, {"OBSERVABILITY_BACKEND": "langfuse"}, clear=False):
            assert _detect_observability_backend() == "langfuse"

    def test_explicit_none(self):
        from agent import _detect_observability_backend

        with patch.dict(os.environ, {"OBSERVABILITY_BACKEND": "none"}, clear=False):
            assert _detect_observability_backend() == "none"

    def test_explicit_case_insensitive(self):
        from agent import _detect_observability_backend

        with patch.dict(os.environ, {"OBSERVABILITY_BACKEND": "LAMINAR"}, clear=False):
            assert _detect_observability_backend() == "laminar"

    def test_autodetect_laminar_from_key(self):
        from agent import _detect_observability_backend

        env = {"LMNR_PROJECT_API_KEY": "test-key"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("OBSERVABILITY_BACKEND", None)
            assert _detect_observability_backend() == "laminar"

    def test_autodetect_langfuse_from_keys(self):
        from agent import _detect_observability_backend

        env = {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("OBSERVABILITY_BACKEND", None)
            os.environ.pop("LMNR_PROJECT_API_KEY", None)
            assert _detect_observability_backend() == "langfuse"

    def test_autodetect_langfuse_needs_both_keys(self):
        from agent import _detect_observability_backend

        env = {"LANGFUSE_PUBLIC_KEY": "pk-test"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("OBSERVABILITY_BACKEND", None)
            os.environ.pop("LMNR_PROJECT_API_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            assert _detect_observability_backend() == "none"

    def test_no_config_returns_none(self):
        from agent import _detect_observability_backend

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OBSERVABILITY_BACKEND", None)
            os.environ.pop("LMNR_PROJECT_API_KEY", None)
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            assert _detect_observability_backend() == "none"

    def test_explicit_overrides_autodetect(self):
        """Explicit OBSERVABILITY_BACKEND takes priority over credential env vars."""
        from agent import _detect_observability_backend

        env = {
            "OBSERVABILITY_BACKEND": "none",
            "LMNR_PROJECT_API_KEY": "test-key",
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
        }
        with patch.dict(os.environ, env, clear=False):
            assert _detect_observability_backend() == "none"

    def test_laminar_priority_over_langfuse(self):
        """When both credential sets exist, Laminar wins (checked first)."""
        from agent import _detect_observability_backend

        env = {
            "LMNR_PROJECT_API_KEY": "test-key",
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("OBSERVABILITY_BACKEND", None)
            assert _detect_observability_backend() == "laminar"


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestInitObservability:
    """Tests for init_observability()."""

    def setup_method(self):
        _reset_observability()

    def test_init_none_backend(self):
        import agent

        with patch.dict(os.environ, {"OBSERVABILITY_BACKEND": "none"}, clear=False):
            agent._observability_initialized = False
            agent.init_observability()
            assert agent._observability_backend == "none"
            assert agent._observability_initialized is True

    def test_init_laminar_success(self):
        import agent

        mock_laminar = MagicMock()
        mock_observe = MagicMock()

        with patch.dict(
            os.environ,
            {
                "OBSERVABILITY_BACKEND": "laminar",
                "LMNR_PROJECT_API_KEY": "test-key",
            },
            clear=False,
        ):
            with patch.dict(
                "sys.modules",
                {"lmnr": MagicMock(Laminar=mock_laminar, observe=mock_observe)},
            ):
                agent._observability_initialized = False
                agent.init_observability()
                assert agent._observability_backend == "laminar"
                assert agent._observability_initialized is True

    def test_init_laminar_import_failure_falls_back_to_none(self):
        import agent

        with patch.dict(
            os.environ,
            {
                "OBSERVABILITY_BACKEND": "laminar",
                "LMNR_PROJECT_API_KEY": "test-key",
            },
            clear=False,
        ):
            # Force ImportError by removing lmnr from sys.modules and patching import
            with patch("builtins.__import__", side_effect=ImportError("no lmnr")):
                agent._observability_initialized = False
                agent.init_observability()
                assert agent._observability_backend == "none"

    def test_init_langfuse_success(self):
        import agent

        mock_langfuse_cls = MagicMock()

        with patch.dict(
            os.environ,
            {
                "OBSERVABILITY_BACKEND": "langfuse",
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_HOST": "https://test.langfuse.com",
            },
            clear=False,
        ):
            with patch.dict(
                "sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse_cls)}
            ):
                agent._observability_initialized = False
                agent.init_observability()
                assert agent._observability_backend == "langfuse"
                assert agent._observability_initialized is True
                assert agent._langfuse_client is not None

    def test_init_langfuse_import_failure_falls_back_to_none(self):
        import agent

        with patch.dict(
            os.environ,
            {
                "OBSERVABILITY_BACKEND": "langfuse",
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
            },
            clear=False,
        ):
            with patch("builtins.__import__", side_effect=ImportError("no langfuse")):
                agent._observability_initialized = False
                agent.init_observability()
                assert agent._observability_backend == "none"

    def test_idempotent(self):
        """Calling init_observability() twice doesn't re-initialize."""
        import agent

        with patch.dict(os.environ, {"OBSERVABILITY_BACKEND": "none"}, clear=False):
            agent._observability_initialized = False
            agent.init_observability()
            assert agent._observability_initialized is True

            # Change env, but init should be a no-op
            with patch.dict(
                os.environ, {"OBSERVABILITY_BACKEND": "laminar"}, clear=False
            ):
                agent.init_observability()
                assert agent._observability_backend == "none"  # Still none


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Tests for observability_set_session, observability_set_tags, observability_observe."""

    def setup_method(self):
        _reset_observability()

    def test_set_session_noop_when_disabled(self):
        import agent

        agent._observability_backend = "none"
        # Should not raise
        agent.observability_set_session("thread-123", {"env": "test"})

    def test_set_session_calls_laminar(self):
        import agent

        mock_laminar = MagicMock()
        agent._observability_backend = "laminar"
        agent._Laminar = mock_laminar

        agent.observability_set_session("thread-123", {"env": "staging"})

        mock_laminar.set_trace_session_id.assert_called_once_with("thread-123")
        mock_laminar.set_trace_metadata.assert_called_once_with({"env": "staging"})

    def test_set_session_laminar_no_metadata(self):
        import agent

        mock_laminar = MagicMock()
        agent._observability_backend = "laminar"
        agent._Laminar = mock_laminar

        agent.observability_set_session("thread-123")

        mock_laminar.set_trace_session_id.assert_called_once_with("thread-123")
        mock_laminar.set_trace_metadata.assert_not_called()

    def test_set_tags_noop_when_disabled(self):
        import agent

        agent._observability_backend = "none"
        agent.observability_set_tags(["success"])  # Should not raise

    def test_set_tags_calls_laminar(self):
        import agent

        mock_laminar = MagicMock()
        agent._observability_backend = "laminar"
        agent._Laminar = mock_laminar

        agent.observability_set_tags(["error", "timeout"])

        mock_laminar.set_span_tags.assert_called_once_with(["error", "timeout"])

    def test_observe_returns_identity_when_disabled(self):
        import agent

        agent._observability_backend = "none"

        decorator = agent.observability_observe()

        async def my_func():
            return 42

        # Identity decorator should return the same function
        assert decorator(my_func) is my_func

    def test_observe_returns_laminar_decorator(self):
        import agent

        mock_observe = MagicMock(return_value=lambda fn: fn)
        agent._observability_backend = "laminar"
        agent._observe = mock_observe

        decorator = agent.observability_observe()
        mock_observe.assert_called_once()


# ---------------------------------------------------------------------------
# Helm template rendering test (requires helm CLI)
# ---------------------------------------------------------------------------


class TestHelmTemplate:
    """Test Helm chart renders correctly for each backend."""

    @pytest.fixture(autouse=True)
    def check_helm(self):
        import shutil

        if not shutil.which("helm"):
            pytest.skip("helm CLI not available")

    def _render(self, set_values: list[str]) -> str:
        import subprocess

        chart_path = str(Path(__file__).parent.parent.parent / "charts" / "incidentfox")
        cmd = [
            "helm",
            "template",
            "test",
            chart_path,
            "--show-only",
            "templates/agent.yaml",
            # Required globals to satisfy chart validation
            "--set",
            "global.configService.url=http://test:8080",
            "--set",
            "services.agent.image=test:latest",
        ]
        for sv in set_values:
            cmd.extend(["--set", sv])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            pytest.fail(f"helm template failed: {result.stderr}")
        return result.stdout

    def test_backend_none_no_observability_env(self):
        output = self._render(["services.agent.agentObservability.backend=none"])
        assert "OBSERVABILITY_BACKEND" not in output

    def test_backend_langfuse(self):
        output = self._render(
            [
                "services.agent.agentObservability.backend=langfuse",
                "services.agent.agentObservability.langfuse.secretName=my-secret",
                "services.agent.agentObservability.langfuse.publicKeyKey=pk",
                "services.agent.agentObservability.langfuse.secretKeyKey=sk",
            ]
        )
        assert "OBSERVABILITY_BACKEND" in output
        assert "langfuse" in output
        assert "LANGFUSE_HOST" in output
        assert "LANGFUSE_PUBLIC_KEY" in output
        assert "LANGFUSE_SECRET_KEY" in output

    def test_backend_laminar(self):
        output = self._render(
            [
                "services.agent.agentObservability.backend=laminar",
                "services.agent.agentObservability.laminar.secretName=my-laminar",
                "services.agent.agentObservability.laminar.apiKeyKey=key",
            ]
        )
        assert "OBSERVABILITY_BACKEND" in output
        assert "laminar" in output
        assert "LMNR_PROJECT_API_KEY" in output
        assert "LANGFUSE" not in output
