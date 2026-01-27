"""
Advanced Retrieval Module for Ultimate RAG.

Implements sophisticated retrieval strategies:
- Multi-query expansion
- HyDE (Hypothetical Document Embeddings)
- Adaptive depth traversal
- Graph + Tree hybrid retrieval
- Importance-weighted ranking
"""

from .strategies import (
    RetrievalStrategy,
    MultiQueryStrategy,
    HyDEStrategy,
    AdaptiveDepthStrategy,
    HybridGraphTreeStrategy,
)
from .retriever import UltimateRetriever, RetrievalResult, RetrievalConfig
from .reranker import Reranker, ImportanceReranker, CrossEncoderReranker

__all__ = [
    # Strategies
    "RetrievalStrategy",
    "MultiQueryStrategy",
    "HyDEStrategy",
    "AdaptiveDepthStrategy",
    "HybridGraphTreeStrategy",
    # Main retriever
    "UltimateRetriever",
    "RetrievalResult",
    "RetrievalConfig",
    # Rerankers
    "Reranker",
    "ImportanceReranker",
    "CrossEncoderReranker",
]
