"""HTTP client wrapper for injecting per-agent headers into Claude SDK requests.

The Claude SDK doesn't provide a direct way to inject custom headers per request.
This module provides a monkey-patch solution that intercepts HTTP requests and
injects per-agent model configuration headers.
"""

import contextvars
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Context variable to store current agent's model config
_current_agent_context: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar("current_agent_context", default=None)
)


def set_agent_context(agent_name: str, model_config: dict[str, Any]):
    """Set the current agent context for the next API call.

    Args:
        agent_name: Name of the agent making the request
        model_config: Dict with temperature, max_tokens, top_p (all optional)
    """
    context = {"name": agent_name, **model_config}
    _current_agent_context.set(context)
    logger.debug(f"Set agent context: {context}")


def clear_agent_context():
    """Clear the agent context after an API call."""
    _current_agent_context.set(None)


def get_agent_headers() -> dict[str, str]:
    """Get headers for the current agent context.

    Returns:
        Dict of X-Agent-* headers to inject into the request
    """
    context = _current_agent_context.get()
    if not context:
        return {}

    headers = {}

    # Agent name (for logging/debugging)
    if "name" in context:
        headers["X-Agent-Name"] = context["name"]

    # Model settings
    if "temperature" in context and context["temperature"] is not None:
        headers["X-Agent-Temperature"] = str(context["temperature"])

    if "max_tokens" in context and context["max_tokens"] is not None:
        headers["X-Agent-Max-Tokens"] = str(context["max_tokens"])

    if "top_p" in context and context["top_p"] is not None:
        headers["X-Agent-Top-P"] = str(context["top_p"])

    return headers


def patch_anthropic_client():
    """Monkey-patch the Anthropic HTTP client to inject agent headers.

    This patches the httpx client used by the Anthropic SDK to automatically
    inject X-Agent-* headers from the current agent context.
    """
    try:
        import httpx
        from anthropic import AsyncAnthropic

        # Store original httpx.AsyncClient
        original_client_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            """Patched __init__ that injects agent headers."""
            # Get default headers or create empty dict
            default_headers = kwargs.get("headers", {})
            if default_headers is None:
                default_headers = {}
            elif isinstance(default_headers, httpx.Headers):
                default_headers = dict(default_headers)

            # Add agent headers
            agent_headers = get_agent_headers()
            if agent_headers:
                logger.debug(f"Injecting agent headers: {agent_headers}")
                default_headers.update(agent_headers)

            kwargs["headers"] = default_headers

            # Call original init
            return original_client_init(self, *args, **kwargs)

        # Apply patch
        httpx.AsyncClient.__init__ = patched_init
        logger.info("Successfully patched httpx.AsyncClient for agent header injection")

    except ImportError as e:
        logger.warning(f"Could not patch Anthropic client: {e}")
    except Exception as e:
        logger.error(f"Error patching Anthropic client: {e}", exc_info=True)
