"""
IncidentFox Unified Agent

Multi-model AI agent for incident investigation with:
- Config-driven agent hierarchy (from agent/)
- OpenHands/LiteLLM for multi-model support (Claude, Gemini, OpenAI)
- gVisor sandbox isolation (from sre-agent/)
- 300+ tools + Skills system
"""

__version__ = "0.1.0"

# Core exports
from .core import (
    # Agent
    Agent,
    # Config
    AgentConfig,
    AgentDefinition,
    AgentResult,
    MaxTurnsExceeded,
    ModelSettings,
    ProviderConfig,
    # Runner
    Runner,
    RunResult,
    build_agent_from_config,
    # Builder
    build_agent_hierarchy,
    create_generic_agent_from_config,
    function_tool,
    get_planner_agent,
    validate_agent_config,
)

# Provider exports
from .providers import (
    LLMProvider,
    SubagentConfig,
    create_provider,
)

__all__ = [
    # Version
    "__version__",
    # Agent
    "Agent",
    "AgentDefinition",
    "ModelSettings",
    "function_tool",
    # Runner
    "Runner",
    "RunResult",
    "MaxTurnsExceeded",
    # Config
    "AgentConfig",
    "ProviderConfig",
    # Builder
    "build_agent_hierarchy",
    "build_agent_from_config",
    "get_planner_agent",
    "create_generic_agent_from_config",
    "validate_agent_config",
    "AgentResult",
    # Providers
    "LLMProvider",
    "SubagentConfig",
    "create_provider",
]
