"""Tests for llm_proxy.py — model routing and resolution."""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from credential_resolver.llm_proxy import (
    get_provider_for_credentials,
    is_claude_model,
)
from fastapi import Request

# ---------------------------------------------------------------------------
# Model detection
# ---------------------------------------------------------------------------


class TestIsClaudeModel:
    def test_claude_prefix(self):
        assert is_claude_model("claude-sonnet-4-20250514") is True

    def test_claude_haiku(self):
        assert is_claude_model("claude-haiku-4-5-20251001") is True

    def test_anthropic_prefix(self):
        assert is_claude_model("anthropic/claude-sonnet-4") is True

    def test_openai_not_claude(self):
        assert is_claude_model("openai/gpt-4o") is False

    def test_gemini_not_claude(self):
        assert is_claude_model("gemini/gemini-2.5-flash") is False

    def test_openrouter_claude(self):
        # openrouter/anthropic/... is NOT treated as claude (goes via litellm)
        assert is_claude_model("openrouter/anthropic/claude-sonnet-4") is False


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


class TestGetProviderForCredentials:
    def test_claude(self):
        assert get_provider_for_credentials("claude-sonnet-4-20250514") == "anthropic"

    def test_anthropic_prefix(self):
        assert get_provider_for_credentials("anthropic/claude-sonnet-4") == "anthropic"

    def test_openai(self):
        assert get_provider_for_credentials("openai/gpt-4o") == "openai"

    def test_gpt_prefix(self):
        assert get_provider_for_credentials("gpt-4o-mini") == "openai"

    def test_gemini(self):
        assert get_provider_for_credentials("gemini/gemini-2.5-flash") == "gemini"

    def test_ollama(self):
        assert get_provider_for_credentials("ollama/llama3") == "ollama"

    def test_openrouter(self):
        assert get_provider_for_credentials("openrouter/openai/gpt-4o") == "openrouter"

    def test_deepseek(self):
        assert get_provider_for_credentials("deepseek/deepseek-chat") == "deepseek"

    def test_azure(self):
        assert get_provider_for_credentials("azure/my-gpt4o-deployment") == "azure"

    def test_bedrock(self):
        assert (
            get_provider_for_credentials("bedrock/anthropic.claude-3-sonnet")
            == "bedrock"
        )

    def test_mistral(self):
        assert get_provider_for_credentials("mistral/mistral-large-latest") == "mistral"

    def test_cohere(self):
        assert get_provider_for_credentials("cohere/command-r-plus") == "cohere"

    def test_cohere_shorthand(self):
        assert get_provider_for_credentials("command-r-plus") == "cohere"

    def test_together_ai(self):
        assert (
            get_provider_for_credentials("together_ai/meta-llama/Llama-3-70b")
            == "together_ai"
        )

    def test_groq(self):
        assert get_provider_for_credentials("groq/llama-3.1-70b-versatile") == "groq"

    def test_fireworks_ai(self):
        assert (
            get_provider_for_credentials(
                "fireworks_ai/accounts/fireworks/models/llama-v3p1-70b"
            )
            == "fireworks_ai"
        )

    def test_xai(self):
        assert get_provider_for_credentials("xai/grok-3-mini") == "xai"

    def test_moonshot(self):
        assert get_provider_for_credentials("moonshot/moonshot-v1-8k") == "moonshot"

    def test_minimax(self):
        assert get_provider_for_credentials("minimax/MiniMax-Text-01") == "minimax"

    def test_vertex_ai(self):
        assert get_provider_for_credentials("vertex_ai/gemini-2.5-flash") == "vertex_ai"

    def test_unknown_falls_to_openrouter(self):
        assert get_provider_for_credentials("some-random-model") == "openrouter"


# ---------------------------------------------------------------------------
# Model resolution priority
# ---------------------------------------------------------------------------


def _make_request(headers: list[tuple[bytes, bytes]], body: dict) -> Request:
    """Build a mock Request with given headers and body."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/messages",
        "headers": headers,
        "query_string": b"",
    }
    request = Request(scope)
    request._body = json.dumps(body).encode()
    return request


class TestModelResolutionPriority:
    """Test that model resolution follows the priority chain:
    1. Per-tenant config (llm.model from Config Service)
    2. x-llm-model header (env var via ext_authz)
    3. Body model field (SDK default)
    4. Hardcoded default
    """

    @pytest.mark.asyncio
    async def test_tenant_config_takes_priority(self):
        """Per-tenant llm config should override everything."""
        from credential_resolver.llm_proxy import llm_proxy

        async def mock_get_credentials(tenant_id, team_id, integration_id):
            if integration_id == "llm":
                return {"model": "openai/gpt-4o"}
            if integration_id == "openai":
                return {"api_key": "sk-test"}
            return None

        request = _make_request(
            headers=[
                (b"x-tenant-id", b"test-tenant"),
                (b"x-team-id", b"test-team"),
                (b"x-llm-model", b"gemini/gemini-2.5-flash"),
                (b"content-type", b"application/json"),
            ],
            body={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

        with patch(
            "credential_resolver.main.get_credentials",
            side_effect=mock_get_credentials,
        ):
            with patch(
                "credential_resolver.llm_proxy._forward_to_provider",
                new_callable=AsyncMock,
            ) as mock_forward:
                await llm_proxy(request)

                # Should use tenant config model (openai/gpt-4o), not header (gemini)
                mock_forward.assert_called_once()
                assert mock_forward.call_args[0][1] == "openai/gpt-4o"

    @pytest.mark.asyncio
    async def test_header_overrides_body(self):
        """x-llm-model header should override body model when no tenant config."""
        from credential_resolver.llm_proxy import llm_proxy

        async def mock_get_credentials(tenant_id, team_id, integration_id):
            if integration_id == "llm":
                return None  # No tenant config
            if integration_id == "openrouter":
                return {"api_key": "sk-or-test"}
            return None

        request = _make_request(
            headers=[
                (b"x-tenant-id", b"test-tenant"),
                (b"x-team-id", b"test-team"),
                (b"x-llm-model", b"openrouter/openai/gpt-4o"),
                (b"content-type", b"application/json"),
            ],
            body={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

        with patch(
            "credential_resolver.main.get_credentials",
            side_effect=mock_get_credentials,
        ):
            with patch(
                "credential_resolver.llm_proxy._forward_to_provider",
                new_callable=AsyncMock,
            ) as mock_forward:
                await llm_proxy(request)

                mock_forward.assert_called_once()
                assert mock_forward.call_args[0][1] == "openrouter/openai/gpt-4o"

    @pytest.mark.asyncio
    async def test_body_model_used_when_no_overrides(self):
        """Body model (SDK default) used when no tenant config or header."""
        from credential_resolver.llm_proxy import llm_proxy

        async def mock_get_credentials(tenant_id, team_id, integration_id):
            if integration_id == "llm":
                return None
            if integration_id == "anthropic":
                return {"api_key": "sk-ant-test"}
            return None

        # Remove LLM_MODEL if set
        os.environ.pop("LLM_MODEL", None)

        request = _make_request(
            headers=[
                (b"x-tenant-id", b"test-tenant"),
                (b"x-team-id", b"test-team"),
                (b"content-type", b"application/json"),
            ],
            body={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

        with patch(
            "credential_resolver.main.get_credentials",
            side_effect=mock_get_credentials,
        ):
            with patch(
                "credential_resolver.llm_proxy._forward_to_anthropic",
                new_callable=AsyncMock,
            ) as mock_claude:
                await llm_proxy(request)

                # Body model is claude-*, so should go to _forward_to_anthropic
                mock_claude.assert_called_once()

    @pytest.mark.asyncio
    async def test_tenant_config_empty_model_falls_through(self):
        """Empty model in tenant config should fall through to next priority."""
        from credential_resolver.llm_proxy import llm_proxy

        async def mock_get_credentials(tenant_id, team_id, integration_id):
            if integration_id == "llm":
                return {"model": ""}  # Empty model
            if integration_id == "openrouter":
                return {"api_key": "sk-or-test"}
            return None

        request = _make_request(
            headers=[
                (b"x-tenant-id", b"test-tenant"),
                (b"x-team-id", b"test-team"),
                (b"x-llm-model", b"openrouter/google/gemini-2.5-flash"),
                (b"content-type", b"application/json"),
            ],
            body={
                "model": "claude-sonnet-4-20250514",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

        with patch(
            "credential_resolver.main.get_credentials",
            side_effect=mock_get_credentials,
        ):
            with patch(
                "credential_resolver.llm_proxy._forward_to_provider",
                new_callable=AsyncMock,
            ) as mock_forward:
                await llm_proxy(request)

                # Should fall through to header value
                mock_forward.assert_called_once()
                assert (
                    mock_forward.call_args[0][1] == "openrouter/google/gemini-2.5-flash"
                )

    @pytest.mark.asyncio
    async def test_hardcoded_default_when_nothing_set(self):
        """When no config, no header, and body model is empty, use hardcoded default."""
        from credential_resolver.llm_proxy import llm_proxy

        async def mock_get_credentials(tenant_id, team_id, integration_id):
            if integration_id == "llm":
                return None
            if integration_id == "anthropic":
                return {"api_key": "sk-ant-test"}
            return None

        os.environ.pop("LLM_MODEL", None)

        request = _make_request(
            headers=[
                (b"x-tenant-id", b"test-tenant"),
                (b"x-team-id", b"test-team"),
                (b"content-type", b"application/json"),
            ],
            body={
                "messages": [{"role": "user", "content": "Hi"}],
                # No model field in body
            },
        )

        with patch(
            "credential_resolver.main.get_credentials",
            side_effect=mock_get_credentials,
        ):
            with patch(
                "credential_resolver.llm_proxy._forward_to_anthropic",
                new_callable=AsyncMock,
            ) as mock_claude:
                await llm_proxy(request)

                # Default model is claude-sonnet-4-20250514, so goes to Anthropic
                mock_claude.assert_called_once()
