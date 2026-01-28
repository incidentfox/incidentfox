"""
Ingestion Module for Ultimate RAG.

Handles processing various content types into the knowledge base:
- Documents (Markdown, PDF, HTML)
- Runbooks and procedures
- Service documentation
- Incident reports
- Slack/chat conversations
- API documentation

The main entry point is IntelligentIngestionPipeline which orchestrates:
1. Document Processing (parsing, chunking)
2. LLM-Powered Analysis (knowledge type, entities, relationships, importance)
3. Conflict Resolution (duplicate detection, supersession, merging)
4. Storage (RAPTOR tree, vector embeddings, graph)
5. Human Review Integration (FLAG_REVIEW to Proposed Changes)
"""

from .extractors import (
    EntityExtractor,
    MetadataExtractor,
    RelationshipExtractor,
)
from .pipeline import (
    BatchIngestionResult,
    InMemoryStorageBackend,
    IngestionResult,
    IntelligentIngestionPipeline,
    PipelineConfig,
    ProposedChangesAPIClient,
    StorageBackend,
)
from .storage_backend import UltimateRAGStorageBackend
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
    # Intelligent Pipeline (recommended entry point)
    "IntelligentIngestionPipeline",
    "PipelineConfig",
    "IngestionResult",
    "BatchIngestionResult",
    "StorageBackend",
    "InMemoryStorageBackend",
    "UltimateRAGStorageBackend",
    "ProposedChangesAPIClient",
    # Legacy processor
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
