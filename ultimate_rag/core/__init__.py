"""
Ultimate RAG Core Module

The core data structures and types for the ultimate enterprise knowledge base.
"""

from .types import (
    KnowledgeType,
    ImportanceScore,
    ImportanceWeights,
    DEFAULT_IMPORTANCE_WEIGHTS,
)
from .node import (
    KnowledgeNode,
    KnowledgeTree,
    TreeForest,
)
from .metadata import (
    NodeMetadata,
    SourceInfo,
    ValidationStatus,
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
