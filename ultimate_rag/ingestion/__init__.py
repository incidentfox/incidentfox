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

from .processor import (
    DocumentProcessor,
    ProcessingResult,
    ProcessingConfig,
)
from .sources import (
    ContentSource,
    FileSource,
    GitRepoSource,
    ConfluenceSource,
    SlackSource,
)
from .extractors import (
    EntityExtractor,
    RelationshipExtractor,
    MetadataExtractor,
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
