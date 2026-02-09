"""
A2A (Agent-to-Agent) Protocol Integration

Enables IncidentFox to integrate with remote A2A-compatible agents.
"""

from .agent_wrapper import create_a2a_agent_tool
from .auth import APIKeyAuth, BearerAuth, OAuth2Auth
from .client import A2AClient

__all__ = [
    "A2AClient",
    "create_a2a_agent_tool",
    "BearerAuth",
    "APIKeyAuth",
    "OAuth2Auth",
]
