"""
Advanced Retrieval Module for Ultimate RAG.

Implements sophisticated retrieval strategies:
- Multi-query expansion
- HyDE (Hypothetical Document Embeddings)
- Adaptive depth traversal
- Graph + Tree hybrid retrieval
- Importance-weighted ranking
"""

from .reranker import CrossEncoderReranker, ImportanceReranker, Reranker
from .retriever import RetrievalConfig, RetrievalResult, UltimateRetriever
from .strategies import (
    AdaptiveDepthStrategy,
    HybridGraphTreeStrategy,
    HyDEStrategy,
    MultiQueryStrategy,
    RetrievalStrategy,
)

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
