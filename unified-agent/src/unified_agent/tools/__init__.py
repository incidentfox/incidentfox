"""
Unified Agent Tools Package.

Provides a registry of 300+ tools for incident investigation.
Tools are organized by category:
- kubernetes: Pod, deployment, service operations
- aws: EC2, ECS, CloudWatch, Lambda
- github: Code search, PRs, issues
- grafana: Dashboards, metrics, alerts
- datadog: Logs, APM, metrics
- remediation: Safe system changes
- coding: File operations, git, testing
"""

from collections.abc import Callable
from typing import Dict

# Tool registry - populated by tool modules
_TOOL_REGISTRY: Dict[str, Callable] = {}


def register_tool(name: str, func: Callable) -> Callable:
    """Register a tool in the global registry."""
    _TOOL_REGISTRY[name] = func
    return func


def get_tool_registry() -> Dict[str, Callable]:
    """Get all registered tools."""
    # Lazy load tool modules to populate registry
    _load_all_tools()
    return _TOOL_REGISTRY.copy()


def get_tool(name: str) -> Callable | None:
    """Get a specific tool by name."""
    _load_all_tools()
    return _TOOL_REGISTRY.get(name)


def _load_all_tools():
    """Lazy load all tool modules."""
    # Only load once
    if _TOOL_REGISTRY:
        return

    # Import tool modules - they register themselves
    # Infrastructure
    try:
        from . import kubernetes
    except ImportError:
        pass

    try:
        from . import aws
    except ImportError:
        pass

    try:
        from . import docker
    except ImportError:
        pass

    # Version control
    try:
        from . import git
    except ImportError:
        pass

    try:
        from . import github
    except ImportError:
        pass

    # Observability
    try:
        from . import grafana
    except ImportError:
        pass

    try:
        from . import datadog
    except ImportError:
        pass

    try:
        from . import sentry
    except ImportError:
        pass

    # Incident management
    try:
        from . import pagerduty
    except ImportError:
        pass

    try:
        from . import slack
    except ImportError:
        pass

    # Operations
    try:
        from . import remediation
    except ImportError:
        pass

    try:
        from . import coding
    except ImportError:
        pass

    try:
        from . import meta
    except ImportError:
        pass


# Export registry functions
__all__ = [
    "register_tool",
    "get_tool_registry",
    "get_tool",
]
