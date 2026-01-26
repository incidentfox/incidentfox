"""
Execution Context for Thread-Safe Multi-Tenant Agent Runs

Provides request-scoped context for team configuration and integrations,
ensuring proper isolation between concurrent agent executions.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Thread-safe per-request storage
_execution_context: ContextVar[ExecutionContext | None] = ContextVar(
    "execution_context", default=None
)


@dataclass
class ExecutionContext:
    """
    Execution context for a single agent run.

    Contains team-specific configuration including integrations,
    ensuring proper multi-tenant isolation.
    """

    org_id: str
    team_node_id: str
    team_config: dict[str, Any]

    @property
    def integrations(self) -> dict[str, Any]:
        """Get integrations configuration for this execution."""
        return self.team_config.get("integrations", {})

    # Metadata keys that are NOT actual configuration values.
    # These are structural/schema keys from the config system's default structure.
    _INTEGRATION_METADATA_KEYS = frozenset(
        {
            "level",  # org/team level indicator
            "locked",  # whether integration is locked at org level
            "config_schema",  # schema for org-level fields (for UI display)
            "team_config_schema",  # schema for team-level fields (for UI display)
            "name",  # display name
        }
    )

    def get_integration_config(self, integration_id: str) -> dict[str, Any]:
        """
        Get configuration for a specific integration.

        Integration values are stored at the top level of the integration object,
        alongside metadata keys. This method extracts only the actual config values.

        Example input:
            {
                "level": "org",           # metadata - skip
                "config_schema": {...},   # metadata - skip
                "token": "ghp_xxx",       # actual value - include
                "org": "my-org",          # actual value - include
            }

        Returns:
            {"token": "ghp_xxx", "org": "my-org"}

        Args:
            integration_id: Integration identifier (e.g., "github", "slack")

        Returns:
            Dict of actual config values, or empty dict if not configured
        """
        integration = self.integrations.get(integration_id, {})

        if not integration:
            logger.warning(
                "integration_not_configured",
                integration_id=integration_id,
                org_id=self.org_id,
                team_node_id=self.team_node_id,
            )
            return {}

        # Extract actual config values (everything except metadata keys)
        return {
            key: value
            for key, value in integration.items()
            if key not in self._INTEGRATION_METADATA_KEYS
        }

    def is_integration_configured(
        self, integration_id: str, required_fields: list[str] = None
    ) -> bool:
        """
        Check if an integration is properly configured.

        Args:
            integration_id: Integration identifier
            required_fields: Optional list of required fields to check

        Returns:
            True if integration has all required fields
        """
        config = self.get_integration_config(integration_id)

        if not config:
            return False

        if required_fields:
            return all(config.get(field) for field in required_fields)

        return True


def set_execution_context(
    org_id: str, team_node_id: str, team_config: dict[str, Any]
) -> ExecutionContext:
    """
    Set execution context for current request/task.

    This should be called at the start of each agent execution.

    Args:
        org_id: Organization ID
        team_node_id: Team node ID
        team_config: Full team configuration including integrations

    Returns:
        The created ExecutionContext
    """
    context = ExecutionContext(
        org_id=org_id, team_node_id=team_node_id, team_config=team_config
    )

    _execution_context.set(context)

    logger.info(
        "execution_context_set",
        org_id=org_id,
        team_node_id=team_node_id,
        integrations=list(context.integrations.keys()),
    )

    return context


def get_execution_context() -> ExecutionContext | None:
    """
    Get execution context for current request/task.

    Returns:
        ExecutionContext if set, None otherwise
    """
    return _execution_context.get()


def clear_execution_context():
    """
    Clear execution context after request/task completion.

    This should be called in a finally block to ensure cleanup.
    """
    context = _execution_context.get()
    if context:
        logger.debug(
            "execution_context_cleared",
            org_id=context.org_id,
            team_node_id=context.team_node_id,
        )

    _execution_context.set(None)


def propagate_context_to_thread(parent_context: ExecutionContext | None) -> None:
    """
    Propagate execution context from parent thread to current thread.

    Python's ContextVar does NOT automatically propagate to new threads.
    Call this at the start of a new thread to restore the parent's context.

    Usage in sub-agent threads:
        # In parent thread:
        parent_ctx = get_execution_context()

        def run_in_new_thread():
            # At start of new thread:
            propagate_context_to_thread(parent_ctx)
            # Now tools can access the context
            ...

    Args:
        parent_context: ExecutionContext captured from parent thread
    """
    if parent_context:
        _execution_context.set(parent_context)
        logger.debug(
            "execution_context_propagated_to_thread",
            org_id=parent_context.org_id,
            team_node_id=parent_context.team_node_id,
        )


def require_execution_context() -> ExecutionContext:
    """
    Get execution context, raising error if not set.

    Use this in tools that require context to be set.

    Returns:
        ExecutionContext

    Raises:
        RuntimeError: If context not set
    """
    context = get_execution_context()

    if context is None:
        raise RuntimeError(
            "No execution context set. "
            "Tools must be called within an agent execution context. "
            "Use set_execution_context() before running agents."
        )

    return context


class ExecutionContextManager:
    """
    Context manager for execution context.

    Usage:
        async with ExecutionContextManager(org_id, team_node_id, team_config):
            result = await agent.run(query)
    """

    def __init__(self, org_id: str, team_node_id: str, team_config: dict[str, Any]):
        self.org_id = org_id
        self.team_node_id = team_node_id
        self.team_config = team_config
        self.context: ExecutionContext | None = None

    def __enter__(self) -> ExecutionContext:
        self.context = set_execution_context(
            self.org_id, self.team_node_id, self.team_config
        )
        return self.context

    def __exit__(self, exc_type, exc_val, exc_tb):
        clear_execution_context()

    async def __aenter__(self) -> ExecutionContext:
        self.context = set_execution_context(
            self.org_id, self.team_node_id, self.team_config
        )
        return self.context

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        clear_execution_context()
