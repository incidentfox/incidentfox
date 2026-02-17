"""
Multi-destination output handler system for the orchestrator.

Posts agent results to non-Slack destinations (GitHub PR comments, etc.).
Slack is handled separately by slack-bot's SSE consumption path.

Ported from agent/src/ai_agent/core/output_handler.py with simplifications:
- No three-phase lifecycle (initial/progress/final) — only final posting
- No Slack handler — slack-bot handles that directly
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


def _log(event: str, **fields: Any) -> None:
    try:
        payload = {
            "service": "orchestrator",
            "component": "output_handlers",
            "event": event,
            **fields,
        }
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


@dataclass
class OutputResult:
    """Result of posting to an output destination."""

    success: bool
    destination_type: str
    message_id: str | None = None
    error: str | None = None


class OutputHandler(ABC):
    """Base class for output handlers."""

    @property
    @abstractmethod
    def destination_type(self) -> str:
        """The destination type this handler supports (e.g., 'github_pr_comment')."""

    @abstractmethod
    async def post_result(
        self,
        config: dict[str, Any],
        result_text: str,
        *,
        success: bool = True,
        agent_name: str = "IncidentFox",
        run_id: str | None = None,
        duration_seconds: float | None = None,
        error: str | None = None,
        team_config: dict[str, Any] | None = None,
    ) -> OutputResult:
        """Post agent result to the destination."""


class OutputHandlerRegistry:
    """Registry of output handlers by destination type."""

    def __init__(self) -> None:
        self._handlers: dict[str, OutputHandler] = {}

    def register(self, handler: OutputHandler) -> None:
        self._handlers[handler.destination_type] = handler

    def get(self, destination_type: str) -> OutputHandler | None:
        return self._handlers.get(destination_type)

    def list_types(self) -> list[str]:
        return list(self._handlers.keys())


_registry: OutputHandlerRegistry | None = None


def get_output_registry() -> OutputHandlerRegistry:
    """Get the global output handler registry (lazy singleton)."""
    global _registry
    if _registry is None:
        _registry = OutputHandlerRegistry()
        _register_default_handlers(_registry)
    return _registry


def _register_default_handlers(registry: OutputHandlerRegistry) -> None:
    from .github import GitHubIssueCommentHandler, GitHubPRCommentHandler

    registry.register(GitHubPRCommentHandler())
    registry.register(GitHubIssueCommentHandler())


async def post_to_destinations(
    destinations: list[dict[str, Any]],
    result_text: str,
    *,
    success: bool = True,
    agent_name: str = "IncidentFox",
    run_id: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    error: Optional[str] = None,
    team_config: Optional[dict[str, Any]] = None,
) -> list[OutputResult]:
    """
    Post agent result to all non-Slack destinations.

    Destinations with unknown types (including "slack") are silently skipped.
    """
    if not destinations:
        return []

    registry = get_output_registry()
    results: list[OutputResult] = []

    for dest in destinations:
        dest_type = dest.get("type", "")
        handler = registry.get(dest_type)
        if not handler:
            # Silently skip unknown types (e.g., "slack" handled elsewhere)
            continue

        try:
            result = await handler.post_result(
                config=dest,
                result_text=result_text,
                success=success,
                agent_name=agent_name,
                run_id=run_id,
                duration_seconds=duration_seconds,
                error=error,
                team_config=team_config,
            )
            results.append(result)
            _log(
                "output_posted",
                destination_type=dest_type,
                success=result.success,
                message_id=result.message_id,
            )
        except Exception as e:
            _log("output_post_failed", destination_type=dest_type, error=str(e))
            results.append(
                OutputResult(success=False, destination_type=dest_type, error=str(e))
            )

    return results
