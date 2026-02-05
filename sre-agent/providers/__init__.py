"""
LLM Provider abstraction for SRE Agent.

This package provides a unified interface for different LLM backends:
- Claude SDK (default, production-tested)
- OpenHands SDK (multi-LLM support: Claude, Gemini, OpenAI)

Usage:
    from providers import create_provider, ProviderConfig, SubagentConfig

    config = ProviderConfig(
        cwd="/app",
        thread_id="thread-123",
        allowed_tools=["Bash", "Read", "Write"],
        subagents={...},
    )

    # Use environment variable LLM_PROVIDER to select
    provider = create_provider(os.getenv("LLM_PROVIDER", "claude"), config)
    await provider.start()

    async for event in provider.execute("Investigate the pod crash"):
        print(event)

    await provider.close()
"""

from providers.base import (
    LLMProvider,
    ProviderConfig,
    SubagentConfig,
    create_provider,
    get_provider_class,
)

__all__ = [
    "LLMProvider",
    "ProviderConfig",
    "SubagentConfig",
    "create_provider",
    "get_provider_class",
]
