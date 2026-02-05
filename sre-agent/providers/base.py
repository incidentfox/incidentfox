"""
Base LLM Provider abstraction for SRE Agent.

This module defines the abstract interface for LLM providers, allowing
the agent to work with different backends (Claude SDK, OpenHands, etc.)
without changing the core agent logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Optional


@dataclass
class SubagentConfig:
    """Configuration for a specialized subagent."""

    name: str
    description: str
    prompt: str
    tools: list[str]
    model: str = "sonnet"  # Default model for subagents


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""

    # Working directory for file operations
    cwd: str

    # Thread ID for session tracking
    thread_id: str

    # List of allowed tool names
    allowed_tools: list[str]

    # Subagent configurations
    subagents: dict[str, SubagentConfig]

    # Permission mode (e.g., "acceptEdits")
    permission_mode: str = "acceptEdits"

    # Whether to include partial messages (for subagent tracking)
    include_partial_messages: bool = True

    # Skill loading sources
    setting_sources: list[str] = None

    def __post_init__(self):
        if self.setting_sources is None:
            self.setting_sources = ["user", "project"]


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Each provider implements the same interface, allowing the agent to
    swap between different LLM backends without code changes.
    """

    def __init__(self, config: ProviderConfig):
        """
        Initialize the provider with configuration.

        Args:
            config: Provider configuration including tools, subagents, etc.
        """
        self.config = config
        self.thread_id = config.thread_id
        self.is_running: bool = False
        self._was_interrupted: bool = False

    @abstractmethod
    async def start(self) -> None:
        """
        Initialize the LLM client session.

        This should be called before execute() to set up the connection.
        """
        pass

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        images: Optional[list[dict]] = None,
    ) -> AsyncIterator[Any]:
        """
        Execute a query and stream events.

        Args:
            prompt: User prompt to send
            images: Optional list of image dicts with {type, media_type, data}

        Yields:
            StreamEvent objects for each agent action
        """
        pass

    @abstractmethod
    async def interrupt(self) -> AsyncIterator[Any]:
        """
        Interrupt the current execution.

        Yields:
            StreamEvent objects for interrupt status
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up the client session."""
        pass

    @abstractmethod
    def set_answer_callback(
        self,
        callback: Callable[[dict], None],
    ) -> None:
        """
        Set callback for receiving user answers to AskUserQuestion.

        Args:
            callback: Function to call when user provides answer
        """
        pass

    @abstractmethod
    async def provide_answer(self, answers: dict) -> None:
        """
        Provide an answer to a pending AskUserQuestion.

        Args:
            answers: Dict of question -> answer mappings
        """
        pass


def get_provider_class(provider_name: str) -> type[LLMProvider]:
    """
    Get the provider class by name.

    Args:
        provider_name: Name of the provider ("claude" or "openhands")

    Returns:
        The provider class

    Raises:
        ValueError: If provider name is not recognized
    """
    if provider_name == "claude":
        from providers.claude_provider import ClaudeProvider

        return ClaudeProvider
    elif provider_name == "openhands":
        from providers.openhands_provider import OpenHandsProvider

        return OpenHandsProvider
    else:
        raise ValueError(
            f"Unknown provider: {provider_name}. Use 'claude' or 'openhands'."
        )


def create_provider(
    provider_name: str,
    config: ProviderConfig,
) -> LLMProvider:
    """
    Factory function to create an LLM provider.

    Args:
        provider_name: Name of the provider ("claude" or "openhands")
        config: Provider configuration

    Returns:
        Configured LLM provider instance
    """
    provider_class = get_provider_class(provider_name)
    return provider_class(config)
