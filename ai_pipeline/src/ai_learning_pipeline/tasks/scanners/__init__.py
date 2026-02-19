"""
Integration scanners for onboarding knowledge ingestion.

Provides the Document dataclass used for passing documents through
the knowledge extraction pipeline.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Document:
    """A document discovered by a scanner, ready for RAG ingestion."""

    content: str
    source_url: str
    content_type: str  # "markdown", "html", "plain_text", "slack_thread"
    metadata: Dict[str, Any] = field(default_factory=dict)
    knowledge_type: Optional[str] = None  # "procedural", "factual", etc.
