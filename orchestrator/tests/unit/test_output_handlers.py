"""Unit tests for output handler system."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from incidentfox_orchestrator.output_handlers import (
    OutputHandlerRegistry,
    get_output_registry,
    post_to_destinations,
)
from incidentfox_orchestrator.output_handlers.github import (
    GitHubIssueCommentHandler,
    GitHubPRCommentHandler,
    _format_markdown,
    _format_structured,
    _resolve_token,
    _try_parse_structured,
)


class TestRegistry:
    def test_register_and_get(self):
        registry = OutputHandlerRegistry()
        handler = GitHubPRCommentHandler()
        registry.register(handler)
        assert registry.get("github_pr_comment") is handler

    def test_get_unknown_returns_none(self):
        registry = OutputHandlerRegistry()
        assert registry.get("nonexistent") is None

    def test_list_types(self):
        registry = OutputHandlerRegistry()
        registry.register(GitHubPRCommentHandler())
        registry.register(GitHubIssueCommentHandler())
        types = registry.list_types()
        assert "github_pr_comment" in types
        assert "github_issue_comment" in types

    def test_default_registry_has_github(self):
        registry = get_output_registry()
        assert registry.get("github_pr_comment") is not None
        assert registry.get("github_issue_comment") is not None

    def test_slack_not_registered(self):
        """Slack is intentionally not in the registry — handled by slack-bot."""
        registry = get_output_registry()
        assert registry.get("slack") is None


class TestTokenResolution:
    def test_explicit_token(self):
        assert _resolve_token({"token": "gh_explicit"}) == "gh_explicit"

    def test_team_config_token(self):
        team = {"integrations": {"github": {"token": "gh_team"}}}
        assert _resolve_token({}, team) == "gh_team"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh_env")
        assert _resolve_token({}) == "gh_env"

    def test_explicit_overrides_team(self):
        team = {"integrations": {"github": {"token": "gh_team"}}}
        assert _resolve_token({"token": "gh_explicit"}, team) == "gh_explicit"

    def test_empty_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert _resolve_token({}) == ""


class TestMarkdownFormatting:
    def test_success_with_text(self):
        md = _format_markdown("Hello world", True, "TestAgent", 5.2, None, "run123")
        assert "TestAgent" in md
        assert "\u2705" in md  # checkmark
        assert "Hello world" in md
        assert "5.2s" in md
        assert "<!-- incidentfox:run_id=run123 -->" in md

    def test_error_formatting(self):
        md = _format_markdown("", False, "TestAgent", 3.0, "Something broke", "run456")
        assert "\u274c" in md  # X mark
        assert "Something broke" in md
        assert "<!-- incidentfox:run_id=run456 -->" in md

    def test_no_run_id(self):
        md = _format_markdown("Result", True, "Agent", None, None, None)
        assert "incidentfox:run_id" not in md

    def test_empty_result(self):
        md = _format_markdown("", True, "Agent", None, None, None)
        assert "_No output returned_" in md

    def test_structured_json_result(self):
        structured = json.dumps(
            {
                "summary": "Service was down",
                "root_cause": "OOM kill",
                "recommendations": ["Increase memory", "Add alerts"],
                "confidence": 85,
            }
        )
        md = _format_markdown(structured, True, "Agent", 10.0, None, None)
        assert "### Summary" in md
        assert "Service was down" in md
        assert "### Root Cause" in md
        assert "OOM kill" in md
        assert "### Recommendations" in md
        assert "- Increase memory" in md
        assert "**Confidence:** 85%" in md


class TestTryParseStructured:
    def test_valid_structured(self):
        text = json.dumps({"summary": "test", "root_cause": "bug"})
        result = _try_parse_structured(text)
        assert result is not None
        assert result["summary"] == "test"

    def test_plain_text(self):
        assert _try_parse_structured("just plain text") is None

    def test_dict_without_known_fields(self):
        text = json.dumps({"foo": "bar"})
        assert _try_parse_structured(text) is None

    def test_list_json(self):
        text = json.dumps([1, 2, 3])
        assert _try_parse_structured(text) is None


class TestFormatStructured:
    def test_all_fields(self):
        lines = _format_structured(
            {
                "summary": "S",
                "root_cause": "R",
                "recommendations": ["A", "B"],
                "confidence": 90,
            }
        )
        text = "\n".join(lines)
        assert "### Summary" in text
        assert "### Root Cause" in text
        assert "### Recommendations" in text
        assert "**Confidence:** 90%" in text

    def test_summary_only(self):
        lines = _format_structured({"summary": "Just a summary"})
        text = "\n".join(lines)
        assert "### Summary" in text
        assert "Root Cause" not in text

    def test_fallback_to_json(self):
        """Dict with known keys but all None values falls back to JSON."""
        lines = _format_structured({"summary": None, "other": "data"})
        text = "\n".join(lines)
        assert "```json" in text

    def test_recommendations_limited_to_10(self):
        recs = [f"rec_{i}" for i in range(20)]
        lines = _format_structured({"recommendations": recs})
        text = "\n".join(lines)
        assert "- rec_9" in text
        assert "- rec_10" not in text


class TestPostToDestinations:
    @pytest.mark.asyncio
    async def test_skips_slack_destinations(self):
        """Slack destinations should be silently skipped."""
        results = await post_to_destinations(
            destinations=[{"type": "slack", "channel_id": "C123"}],
            result_text="test",
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_destinations(self):
        results = await post_to_destinations(destinations=[], result_text="test")
        assert results == []

    @pytest.mark.asyncio
    async def test_github_pr_missing_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        results = await post_to_destinations(
            destinations=[
                {"type": "github_pr_comment", "repo": "org/repo", "pr_number": 1}
            ],
            result_text="test",
        )
        assert len(results) == 1
        assert results[0].success is False
        assert "token" in results[0].error.lower()

    @pytest.mark.asyncio
    async def test_github_pr_posts_comment(self):
        # Response methods (json, raise_for_status) are sync in httpx
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 12345}
        mock_response.raise_for_status.return_value = None

        with patch(
            "incidentfox_orchestrator.output_handlers.github.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            results = await post_to_destinations(
                destinations=[
                    {
                        "type": "github_pr_comment",
                        "repo": "org/repo",
                        "pr_number": 42,
                        "token": "gh_test_token",
                    }
                ],
                result_text="Investigation complete",
                success=True,
                agent_name="TestAgent",
                run_id="run_abc",
            )

            assert len(results) == 1
            assert results[0].success is True
            assert results[0].message_id == "12345"

            # Verify the API call
            call_args = mock_client.post.call_args
            assert "org/repo" in call_args.args[0]
            assert "issues/42/comments" in call_args.args[0]
            body = call_args.kwargs["json"]["body"]
            assert "Investigation complete" in body
            assert "TestAgent" in body
            assert "<!-- incidentfox:run_id=run_abc -->" in body

    @pytest.mark.asyncio
    async def test_github_issue_posts_comment(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 67890}
        mock_response.raise_for_status.return_value = None

        with patch(
            "incidentfox_orchestrator.output_handlers.github.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            results = await post_to_destinations(
                destinations=[
                    {
                        "type": "github_issue_comment",
                        "repo": "org/repo",
                        "issue_number": 99,
                        "token": "gh_test_token",
                    }
                ],
                result_text="Bug analyzed",
            )

            assert len(results) == 1
            assert results[0].success is True
            call_args = mock_client.post.call_args
            assert "issues/99/comments" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_mixed_destinations(self, monkeypatch):
        """Slack skipped, GitHub processed."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        results = await post_to_destinations(
            destinations=[
                {"type": "slack", "channel_id": "C123"},
                {"type": "github_pr_comment", "repo": "org/repo", "pr_number": 1},
            ],
            result_text="test",
        )
        # Only GitHub result (Slack silently skipped)
        assert len(results) == 1
        assert results[0].destination_type == "github_pr_comment"

    @pytest.mark.asyncio
    async def test_handler_exception_returns_error_result(self):
        with patch(
            "incidentfox_orchestrator.output_handlers.github.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            results = await post_to_destinations(
                destinations=[
                    {
                        "type": "github_pr_comment",
                        "repo": "org/repo",
                        "pr_number": 1,
                        "token": "gh_token",
                    }
                ],
                result_text="test",
            )

            assert len(results) == 1
            assert results[0].success is False
            assert "Connection refused" in results[0].error
