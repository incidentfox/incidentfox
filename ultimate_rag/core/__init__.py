"""
Ultimate RAG Core Module

The core data structures and types for the ultimate enterprise knowledge base.
"""

from .metadata import (
    NodeMetadata,
    SourceInfo,
    ValidationStatus,
)
from .node import (
    KnowledgeNode,
    KnowledgeTree,
    TreeForest,
)
from .types import (
    DEFAULT_IMPORTANCE_WEIGHTS,
    ImportanceScore,
    ImportanceWeights,
    KnowledgeType,
)

__all__ = [
    # Types
    "KnowledgeType",
    "ImportanceScore",
    "ImportanceWeights",
    "DEFAULT_IMPORTANCE_WEIGHTS",
    # Node structures
    "KnowledgeNode",
    "KnowledgeTree",
    "TreeForest",
    # Metadata
    "NodeMetadata",
    "SourceInfo",
    "ValidationStatus",
]
