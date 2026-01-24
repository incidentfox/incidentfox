"""
Multi-destination output handler system.

Supports posting agent results to multiple destinations:
- Slack (Block Kit)
- GitHub (PR comments, issue comments)
- PagerDuty (incident notes)
- Incident.io (timeline updates)

The output destination is determined by:
1. Explicit override in request
2. Trigger-specific default (Slack → same thread, GitHub → same PR)
3. Team's configured default output
4. No output (silent)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class OutputDestination:
    """
    Represents a destination for agent output.

    Attributes:
        type: Destination type (slack, github_pr_comment, etc.)
        config: Type-specific configuration
    """

    type: str
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.config is None:
            self.config = {}


@dataclass
class OutputResult:
    """Result of posting to an output destination."""

    success: bool
    destination_type: str
    message_id: str | None = None  # Slack ts, GitHub comment ID, etc.
    error: str | None = None


class OutputHandler(ABC):
    """Base class for output handlers."""

    @property
    @abstractmethod
    def destination_type(self) -> str:
        """The destination type this handler supports."""
        pass

    @abstractmethod
    async def post_initial(
        self,
        config: dict[str, Any],
        task_description: str,
        agent_name: str = "IncidentFox",
    ) -> str | None:
        """
        Post initial "working on it" message.

        Returns: Message ID for updates (e.g., Slack ts)
        """
        pass

    @abstractmethod
    async def update_progress(
        self,
        config: dict[str, Any],
        message_id: str,
        status_text: str,
    ) -> None:
        """Update with progress."""
        pass

    @abstractmethod
    async def post_final(
        self,
        config: dict[str, Any],
        message_id: str | None,
        output: Any,
        success: bool = True,
        duration_seconds: float | None = None,
        error: str | None = None,
        agent_name: str = "IncidentFox",
    ) -> OutputResult:
        """Post final result."""
        pass


class OutputHandlerRegistry:
    """
    Registry of output handlers by destination type.

    Usage:
        registry = OutputHandlerRegistry()
        registry.register(SlackOutputHandler())
        registry.register(GitHubPRCommentHandler())

        for dest in output_destinations:
            handler = registry.get(dest.type)
            await handler.post_final(dest.config, output)
    """

    def __init__(self):
        self._handlers: dict[str, OutputHandler] = {}

    def register(self, handler: OutputHandler) -> None:
        """Register an output handler."""
        self._handlers[handler.destination_type] = handler
        logger.debug("output_handler_registered", type=handler.destination_type)

    def get(self, destination_type: str) -> OutputHandler | None:
        """Get handler for destination type."""
        return self._handlers.get(destination_type)

    def list_types(self) -> list[str]:
        """List all registered destination types."""
        return list(self._handlers.keys())


# Global registry instance
_registry: OutputHandlerRegistry | None = None


def get_output_registry() -> OutputHandlerRegistry:
    """Get the global output handler registry."""
    global _registry
    if _registry is None:
        _registry = OutputHandlerRegistry()
        _register_default_handlers(_registry)
    return _registry


def _register_default_handlers(registry: OutputHandlerRegistry) -> None:
    """Register default output handlers."""
    from .output_handlers.github import (
        GitHubIssueCommentHandler,
        GitHubPRCommentHandler,
    )
    from .output_handlers.slack import SlackOutputHandler

    registry.register(SlackOutputHandler())
    registry.register(GitHubPRCommentHandler())
    registry.register(GitHubIssueCommentHandler())

    # Future handlers:
    # registry.register(PagerDutyNoteHandler())
    # registry.register(IncidentIOTimelineHandler())


async def post_to_destinations(
    destinations: list[OutputDestination],
    output: Any,
    *,
    success: bool = True,
    duration_seconds: float | None = None,
    error: str | None = None,
    agent_name: str = "IncidentFox",
    message_ids: dict[str, str] | None = None,
) -> list[OutputResult]:
    """
    Post output to all destinations.

    Args:
        destinations: List of output destinations
        output: Agent output to post
        success: Whether agent run was successful
        duration_seconds: How long the run took
        error: Error message if failed
        agent_name: Agent name for display
        message_ids: Dict of destination_type -> message_id for updates

    Returns:
        List of OutputResults
    """
    if not destinations:
        logger.debug("no_output_destinations")
        return []

    registry = get_output_registry()
    results = []
    message_ids = message_ids or {}

    for dest in destinations:
        handler = registry.get(dest.type)
        if not handler:
            logger.warning("unknown_output_destination", type=dest.type)
            results.append(
                OutputResult(
                    success=False,
                    destination_type=dest.type,
                    error=f"Unknown destination type: {dest.type}",
                )
            )
            continue

        try:
            result = await handler.post_final(
                config=dest.config,
                message_id=message_ids.get(dest.type),
                output=output,
                success=success,
                duration_seconds=duration_seconds,
                error=error,
                agent_name=agent_name,
            )
            results.append(result)

            logger.info(
                "output_posted",
                destination_type=dest.type,
                success=result.success,
            )

        except Exception as e:
            logger.error(
                "output_post_failed",
                destination_type=dest.type,
                error=str(e),
            )
            results.append(
                OutputResult(
                    success=False,
                    destination_type=dest.type,
                    error=str(e),
                )
            )

    return results


async def post_initial_to_destinations(
    destinations: list[OutputDestination],
    task_description: str,
    agent_name: str = "IncidentFox",
) -> dict[str, str]:
    """
    Post initial "working" message to all destinations.

    Returns:
        Dict of destination_type -> message_id for later updates
    """
    if not destinations:
        return {}

    registry = get_output_registry()
    message_ids = {}

    for dest in destinations:
        handler = registry.get(dest.type)
        if not handler:
            continue

        try:
            message_id = await handler.post_initial(
                config=dest.config,
                task_description=task_description,
                agent_name=agent_name,
            )
            if message_id:
                message_ids[dest.type] = message_id

        except Exception as e:
            logger.warning(
                "initial_post_failed",
                destination_type=dest.type,
                error=str(e),
            )

    return message_ids


def parse_output_destinations(raw: Any) -> list[OutputDestination]:
    """
    Parse output destinations from request data.

    Accepts:
    - List of dicts: [{"type": "slack", "config": {...}}]
    - Flat format: [{"type": "slack", "channel_id": "...", ...}]
    - Mixed format: [{"type": "slack", "channel_id": "...", "config": {"run_id": "..."}}]
    - List of OutputDestination objects
    - None (returns empty list)

    When both flat keys and a "config" dict exist, they are merged with flat keys
    taking precedence (allowing overrides at top level).
    """
    if not raw:
        return []

    if not isinstance(raw, list):
        raw = [raw]

    destinations = []
    for item in raw:
        if isinstance(item, OutputDestination):
            destinations.append(item)
        elif isinstance(item, dict):
            dest_type = item.get("type", "")

            # Extract flat keys (everything except "type" and "config")
            flat_keys = {k: v for k, v in item.items() if k not in ("type", "config")}

            # Get nested config if it exists
            nested_config = item.get("config", {})

            # Merge: start with nested config, then overlay flat keys
            # This allows flat keys to override nested config values
            config = {**nested_config, **flat_keys}

            destinations.append(OutputDestination(type=dest_type, config=config))

    return destinations
