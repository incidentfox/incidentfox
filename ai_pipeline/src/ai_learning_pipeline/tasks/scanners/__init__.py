"""
Integration scanners for onboarding knowledge ingestion.

Each scanner takes decrypted credentials + config, calls external APIs
directly, and returns a list of Document objects for RAG ingestion.

To add a new integration scanner:
1. Create a new module (e.g., notion_scanner.py)
2. Implement a scan() function matching the IntegrationScanner protocol
3. Register it in SCANNER_REGISTRY below
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Protocol


@dataclass
class Document:
    """A document discovered by a scanner, ready for RAG ingestion."""

    content: str
    source_url: str
    content_type: str  # "markdown", "html", "plain_text", "slack_thread"
    metadata: Dict[str, Any] = field(default_factory=dict)
    knowledge_type: Optional[str] = None  # "procedural", "factual", etc.


class IntegrationScanner(Protocol):
    """Protocol for integration scanners."""

    async def scan(
        self,
        credentials: Dict[str, Any],
        config: Dict[str, Any],
        org_id: str,
    ) -> List[Document]: ...


# Registry: integration_id -> scanner module's scan function
# Populated by importing scanner modules below
SCANNER_REGISTRY: Dict[str, Callable[..., Coroutine[Any, Any, List[Document]]]] = {}


def register_scanner(
    integration_id: str,
) -> Callable:
    """Decorator to register a scanner function."""

    def decorator(
        fn: Callable[..., Coroutine[Any, Any, List[Document]]],
    ) -> Callable[..., Coroutine[Any, Any, List[Document]]]:
        SCANNER_REGISTRY[integration_id] = fn
        return fn

    return decorator


def get_scanner(
    integration_id: str,
) -> Optional[Callable[..., Coroutine[Any, Any, List[Document]]]]:
    """Get the scanner function for an integration, or None."""
    return SCANNER_REGISTRY.get(integration_id)


# Import scanner modules to trigger registration
from . import confluence_scanner, github_scanner  # noqa: E402, F401
