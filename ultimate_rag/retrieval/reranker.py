"""
Reranking module for Ultimate RAG.

Rerankers improve retrieval quality by:
- Re-scoring results with more sophisticated models
- Incorporating importance and freshness signals
- Applying diversity constraints
- Filtering low-quality results
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .strategies import RetrievedChunk

if TYPE_CHECKING:
    from ..core.node import KnowledgeNode, TreeForest
    from ..graph.graph import KnowledgeGraph

logger = logging.getLogger(__name__)


@dataclass
class RerankConfig:
    """Configuration for reranking."""

    # Score weights
    similarity_weight: float = 0.4
    importance_weight: float = 0.3
    freshness_weight: float = 0.15
    diversity_weight: float = 0.15

    # Thresholds
    min_score: float = 0.1  # Filter out below this
    freshness_decay_days: int = 90  # After this, freshness drops

    # Diversity
    max_same_source: int = 3  # Max results from same source
    min_diversity_distance: float = 0.3  # Min embedding distance between results


class Reranker(ABC):
    """Base class for rerankers."""

    name: str = "base"

    @abstractmethod
    async def rerank(
        self,
        chunks: List[RetrievedChunk],
        query: str,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """
        Rerank retrieved chunks.

        Args:
            chunks: Initial retrieved chunks
            query: Original query
            top_k: Number of results to return
            **kwargs: Reranker-specific parameters

        Returns:
            Reranked list of chunks
        """
        pass


class ImportanceReranker(Reranker):
    """
    Reranker that incorporates importance scores.

    Combines semantic similarity with multi-signal importance:
    - Explicit priority
    - Usage patterns
    - Content quality
    - Freshness
    """

    name = "importance"

    def __init__(self, config: Optional[RerankConfig] = None):
        self.config = config or RerankConfig()

    async def rerank(
        self,
        chunks: List[RetrievedChunk],
        query: str,
        top_k: int = 10,
        forest: Optional["TreeForest"] = None,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Rerank with importance weighting."""
        scored_chunks = []

        for chunk in chunks:
            # Get enhanced importance if we have access to the node
            importance = chunk.importance
            freshness = 1.0

            if forest:
                node = self._find_node(chunk.node_id, forest)
                if node:
                    importance = node.get_importance()
                    freshness = self._compute_freshness(node)

            # Compute final score
            final_score = (
                self.config.similarity_weight * chunk.score
                + self.config.importance_weight * importance
                + self.config.freshness_weight * freshness
            )

            chunk.score = final_score
            scored_chunks.append(chunk)

        # Filter low scores
        filtered = [c for c in scored_chunks if c.score >= self.config.min_score]

        # Sort by score
        sorted_chunks = sorted(filtered, key=lambda c: c.score, reverse=True)

        # Apply diversity constraint
        diverse_chunks = self._apply_diversity(sorted_chunks, top_k)

        return diverse_chunks

    def _compute_freshness(self, node: "KnowledgeNode") -> float:
        """Compute freshness score based on last validation/update."""
        now = datetime.utcnow()

        # Get most recent relevant date
        last_date = None
        if node.metadata and node.metadata.validated_at:
            last_date = node.metadata.validated_at
        elif node.importance.last_accessed:
            last_date = node.importance.last_accessed
        elif node.importance.created_at:
            last_date = node.importance.created_at

        if not last_date:
            return 0.5  # Unknown freshness

        # Compute decay
        age_days = (now - last_date).days
        if age_days <= 7:
            return 1.0
        elif age_days <= 30:
            return 0.9
        elif age_days <= self.config.freshness_decay_days:
            # Linear decay from 0.8 to 0.3
            progress = (age_days - 30) / (self.config.freshness_decay_days - 30)
            return 0.8 - (0.5 * progress)
        else:
            return 0.3  # Stale content

    def _apply_diversity(
        self,
        chunks: List[RetrievedChunk],
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Apply diversity constraints to avoid redundant results."""
        selected = []
        source_counts: Dict[str, int] = {}

        for chunk in chunks:
            if len(selected) >= top_k:
                break

            # Check source limit
            source = chunk.metadata.get("source", "unknown")
            if source_counts.get(source, 0) >= self.config.max_same_source:
                continue

            # Add to selection
            selected.append(chunk)
            source_counts[source] = source_counts.get(source, 0) + 1

        return selected

    def _find_node(
        self,
        node_id: int,
        forest: "TreeForest",
    ) -> Optional["KnowledgeNode"]:
        """Find node in forest."""
        for tree in forest.trees.values():
            if node_id in tree.all_nodes:
                return tree.all_nodes[node_id]
        return None


class CrossEncoderReranker(Reranker):
    """
    Cross-encoder reranker for high-precision reranking.

    Uses a cross-encoder model to jointly encode query and document
    for more accurate relevance scoring.
    """

    name = "cross_encoder"

    def __init__(
        self,
        model: Optional[Any] = None,  # Cross-encoder model
        batch_size: int = 16,
    ):
        self.model = model
        self.batch_size = batch_size

    async def rerank(
        self,
        chunks: List[RetrievedChunk],
        query: str,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Rerank using cross-encoder."""
        if not self.model:
            # No model available, return as-is
            return chunks[:top_k]

        # Prepare pairs for cross-encoder
        pairs = [(query, chunk.text) for chunk in chunks]

        # Score in batches
        scores = []
        for i in range(0, len(pairs), self.batch_size):
            batch = pairs[i : i + self.batch_size]
            # In production: batch_scores = self.model.predict(batch)
            batch_scores = [0.5] * len(batch)  # Placeholder
            scores.extend(batch_scores)

        # Update chunk scores
        for chunk, score in zip(chunks, scores):
            # Combine cross-encoder score with original
            chunk.score = 0.7 * score + 0.3 * chunk.score

        # Sort and return
        return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_k]


class ContextualReranker(Reranker):
    """
    Contextual reranker that considers conversation history.

    Useful for multi-turn conversations where context matters.
    """

    name = "contextual"

    def __init__(
        self,
        context_weight: float = 0.3,
        max_context_turns: int = 5,
    ):
        self.context_weight = context_weight
        self.max_context_turns = max_context_turns
        self._conversation_context: List[str] = []

    def add_context(self, text: str) -> None:
        """Add a turn to the conversation context."""
        self._conversation_context.append(text)
        if len(self._conversation_context) > self.max_context_turns:
            self._conversation_context.pop(0)

    def clear_context(self) -> None:
        """Clear conversation context."""
        self._conversation_context = []

    async def rerank(
        self,
        chunks: List[RetrievedChunk],
        query: str,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Rerank considering conversation context."""
        if not self._conversation_context:
            # No context, return as-is
            return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_k]

        # Combine context with query
        context_text = " ".join(self._conversation_context)
        context_words = set(context_text.lower().split())

        for chunk in chunks:
            # Boost chunks that relate to context
            chunk_words = set(chunk.text.lower().split())
            context_overlap = len(context_words & chunk_words)

            if context_overlap > 0:
                context_boost = min(0.2, context_overlap * 0.05)
                chunk.score += context_boost * self.context_weight

        return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_k]


class EnsembleReranker(Reranker):
    """
    Ensemble multiple rerankers for robust results.

    Combines scores from multiple rerankers using weighted voting.
    """

    name = "ensemble"

    def __init__(
        self,
        rerankers: Optional[List[Reranker]] = None,
        weights: Optional[List[float]] = None,
    ):
        self.rerankers = rerankers or [
            ImportanceReranker(),
        ]
        self.weights = weights or [1.0 / len(self.rerankers)] * len(self.rerankers)

        if len(self.weights) != len(self.rerankers):
            raise ValueError("Number of weights must match number of rerankers")

    async def rerank(
        self,
        chunks: List[RetrievedChunk],
        query: str,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Rerank using ensemble of rerankers."""
        # Get scores from each reranker
        all_scores: Dict[int, List[float]] = {c.node_id: [] for c in chunks}

        for reranker, weight in zip(self.rerankers, self.weights):
            # Create copies to avoid modifying original
            chunk_copies = [
                RetrievedChunk(
                    node_id=c.node_id,
                    text=c.text,
                    score=c.score,
                    importance=c.importance,
                    strategy=c.strategy,
                    tree_level=c.tree_level,
                    path=c.path.copy(),
                    metadata=c.metadata.copy(),
                )
                for c in chunks
            ]

            reranked = await reranker.rerank(chunk_copies, query, len(chunks), **kwargs)

            # Record scores
            for i, chunk in enumerate(reranked):
                # Score based on rank position
                rank_score = 1.0 - (i / len(reranked))
                all_scores[chunk.node_id].append(rank_score * weight)

        # Compute final scores
        for chunk in chunks:
            scores = all_scores[chunk.node_id]
            chunk.score = sum(scores) / len(self.rerankers) if scores else 0

        return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_k]


class RecencyBoostReranker(Reranker):
    """
    Reranker that boosts recent content.

    Useful when freshness is critical (e.g., during incidents).
    """

    name = "recency_boost"

    def __init__(
        self,
        boost_window_hours: int = 24,
        max_boost: float = 0.3,
    ):
        self.boost_window_hours = boost_window_hours
        self.max_boost = max_boost

    async def rerank(
        self,
        chunks: List[RetrievedChunk],
        query: str,
        top_k: int = 10,
        forest: Optional["TreeForest"] = None,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Rerank with recency boost."""
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=self.boost_window_hours)

        for chunk in chunks:
            # Check if recently updated
            updated_at = chunk.metadata.get("updated_at")
            if updated_at:
                if isinstance(updated_at, str):
                    updated_at = datetime.fromisoformat(updated_at)

                if updated_at > cutoff:
                    # Apply boost based on how recent
                    hours_ago = (now - updated_at).total_seconds() / 3600
                    boost = self.max_boost * (1 - hours_ago / self.boost_window_hours)
                    chunk.score += boost

        return sorted(chunks, key=lambda c: c.score, reverse=True)[:top_k]
