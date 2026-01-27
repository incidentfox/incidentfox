"""
Ingestion Module for Ultimate RAG.

Handles processing various content types into the knowledge base:
- Documents (Markdown, PDF, HTML)
- Runbooks and procedures
- Service documentation
- Incident reports
- Slack/chat conversations
- API documentation
"""

from .extractors import (
    EntityExtractor,
    MetadataExtractor,
    RelationshipExtractor,
)
from .processor import (
    DocumentProcessor,
    ProcessingConfig,
    ProcessingResult,
)
from .sources import (
    ConfluenceSource,
    ContentSource,
    FileSource,
    GitRepoSource,
    SlackSource,
)

__all__ = [
    # Main processor
    "DocumentProcessor",
    "ProcessingResult",
    "ProcessingConfig",
    # Sources
    "ContentSource",
    "FileSource",
    "GitRepoSource",
    "ConfluenceSource",
    "SlackSource",
    # Extractors
    "EntityExtractor",
    "RelationshipExtractor",
    "MetadataExtractor",
]
