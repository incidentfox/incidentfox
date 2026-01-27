"""
Ultimate Retriever - Main orchestration for retrieval.

Combines multiple strategies and rerankers for optimal retrieval:
1. Analyzes query to select appropriate strategy
2. Executes retrieval (potentially multiple strategies)
3. Reranks results
4. Records observations for learning
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from .reranker import (
    EnsembleReranker,
    ImportanceReranker,
    RerankConfig,
    Reranker,
)
from .strategies import (
    AdaptiveDepthStrategy,
    HybridGraphTreeStrategy,
    HyDEStrategy,
    IncidentAwareStrategy,
    MultiQueryStrategy,
    QueryAnalysis,
    QueryIntent,
    RetrievalStrategy,
    RetrievedChunk,
)

if TYPE_CHECKING:
    from ..agents.observations import ObservationCollector
    from ..core.node import KnowledgeNode, TreeForest
    from ..graph.graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class RetrievalMode(str, Enum):
    """Retrieval modes based on use case."""

    STANDARD = "standard"  # Balanced retrieval
    FAST = "fast"  # Speed over quality
    THOROUGH = "thorough"  # Quality over speed
    INCIDENT = "incident"  # Incident response mode


@dataclass
class RetrievalConfig:
    """Configuration for the retriever."""

    # Strategy selection
    default_mode: RetrievalMode = RetrievalMode.STANDARD
    enable_multi_strategy: bool = True  # Run multiple strategies

    # Result settings
    default_top_k: int = 10
    max_top_k: int = 50

    # Reranking
    enable_reranking: bool = True
    rerank_config: RerankConfig = field(default_factory=RerankConfig)

    # Observability
    record_observations: bool = True
    trace_retrieval: bool = False  # Detailed tracing for debugging

    # Performance
    parallel_strategies: bool = True  # Run strategies in parallel
    timeout_seconds: float = 10.0


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""

    # Query info
    query: str
    query_analysis: QueryAnalysis

    # Results
    chunks: List[RetrievedChunk]

    # Metadata
    mode: RetrievalMode
    strategies_used: List[str]
    total_candidates: int  # Before reranking
    retrieval_time_ms: float

    # Optional trace
    trace: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "query_analysis": self.query_analysis.to_dict(),
            "chunks": [c.to_dict() for c in self.chunks],
            "mode": self.mode.value,
            "strategies_used": self.strategies_used,
            "total_candidates": self.total_candidates,
            "retrieval_time_ms": self.retrieval_time_ms,
        }

    @property
    def texts(self) -> List[str]:
        """Get just the text from results."""
        return [c.text for c in self.chunks]

    @property
    def top_text(self) -> Optional[str]:
        """Get the best matching text."""
        return self.chunks[0].text if self.chunks else None


class UltimateRetriever:
    """
    Main retriever that orchestrates all retrieval components.

    Features:
    - Automatic strategy selection based on query
    - Multi-strategy retrieval with result fusion
    - Sophisticated reranking
    - Observation recording for continuous learning
    """

    def __init__(
        self,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        observation_collector: Optional["ObservationCollector"] = None,
        config: Optional[RetrievalConfig] = None,
    ):
        self.forest = forest
        self.graph = graph
        self.observations = observation_collector
        self.config = config or RetrievalConfig()

        # Initialize strategies
        self._strategies: Dict[str, RetrievalStrategy] = {
            "multi_query": MultiQueryStrategy(),
            "hyde": HyDEStrategy(),
            "adaptive_depth": AdaptiveDepthStrategy(),
            "hybrid": HybridGraphTreeStrategy(),
            "incident": IncidentAwareStrategy(),
        }

        # Initialize rerankers
        self._reranker = EnsembleReranker(
            rerankers=[
                ImportanceReranker(self.config.rerank_config),
            ]
        )

        # Stats
        self._query_count = 0
        self._total_retrieval_time = 0.0

    async def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        mode: Optional[RetrievalMode] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> RetrievalResult:
        """
        Retrieve relevant knowledge for a query.

        Args:
            query: User query
            top_k: Number of results to return
            mode: Retrieval mode (affects strategy selection)
            filters: Optional filters (e.g., {"source": "runbooks"})

        Returns:
            RetrievalResult with ranked chunks
        """
        start_time = datetime.utcnow()
        self._query_count += 1

        top_k = min(top_k or self.config.default_top_k, self.config.max_top_k)
        mode = mode or self.config.default_mode

        # 1. Analyze query
        strategy = self._strategies.get("hybrid", HybridGraphTreeStrategy())
        analysis = strategy.analyze_query(query)

        # Override mode for incident-like queries
        if analysis.intent == QueryIntent.TROUBLESHOOTING and analysis.urgency > 0.7:
            mode = RetrievalMode.INCIDENT

        # 2. Select strategies based on mode
        selected_strategies = self._select_strategies(mode, analysis)

        # 3. Execute retrieval
        if self.config.parallel_strategies and len(selected_strategies) > 1:
            all_chunks = await self._parallel_retrieve(
                query, selected_strategies, top_k * 2
            )
        else:
            all_chunks = await self._sequential_retrieve(
                query, selected_strategies, top_k * 2
            )

        # 4. Apply filters
        if filters:
            all_chunks = self._apply_filters(all_chunks, filters)

        total_candidates = len(all_chunks)

        # 5. Rerank
        if self.config.enable_reranking and all_chunks:
            reranked = await self._reranker.rerank(
                all_chunks,
                query,
                top_k=top_k,
                forest=self.forest,
            )
        else:
            reranked = sorted(all_chunks, key=lambda c: c.combined_score, reverse=True)[
                :top_k
            ]

        # 6. Calculate timing
        end_time = datetime.utcnow()
        retrieval_time_ms = (end_time - start_time).total_seconds() * 1000
        self._total_retrieval_time += retrieval_time_ms

        # 7. Create result
        result = RetrievalResult(
            query=query,
            query_analysis=analysis,
            chunks=reranked,
            mode=mode,
            strategies_used=[s.name for s in selected_strategies],
            total_candidates=total_candidates,
            retrieval_time_ms=retrieval_time_ms,
        )

        # 8. Record observation
        if self.config.record_observations and self.observations:
            await self._record_retrieval(result)

        logger.info(
            f"Retrieved {len(reranked)} chunks for '{query[:50]}...' "
            f"in {retrieval_time_ms:.1f}ms (mode={mode.value})"
        )

        return result

    def _select_strategies(
        self,
        mode: RetrievalMode,
        analysis: QueryAnalysis,
    ) -> List[RetrievalStrategy]:
        """Select retrieval strategies based on mode and query analysis."""
        strategies = []

        if mode == RetrievalMode.FAST:
            # Single fast strategy
            strategies.append(self._strategies["adaptive_depth"])

        elif mode == RetrievalMode.INCIDENT:
            # Incident-specific strategy
            strategies.append(self._strategies["incident"])

        elif mode == RetrievalMode.THOROUGH:
            # Use all strategies
            strategies.extend(
                [
                    self._strategies["multi_query"],
                    self._strategies["hyde"],
                    self._strategies["hybrid"],
                ]
            )

        else:  # STANDARD
            # Select based on query intent
            if analysis.intent == QueryIntent.PROCEDURAL:
                strategies.append(self._strategies["hybrid"])
                strategies.append(self._strategies["adaptive_depth"])
            elif analysis.intent == QueryIntent.RELATIONAL:
                strategies.append(self._strategies["hybrid"])
            elif analysis.intent == QueryIntent.TROUBLESHOOTING:
                strategies.append(self._strategies["incident"])
            else:
                strategies.append(self._strategies["multi_query"])
                strategies.append(self._strategies["hybrid"])

        return strategies

    async def _parallel_retrieve(
        self,
        query: str,
        strategies: List[RetrievalStrategy],
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Run multiple strategies in parallel."""
        tasks = [
            strategy.retrieve(query, self.forest, self.graph, top_k)
            for strategy in strategies
        ]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.config.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("Retrieval timeout, using partial results")
            results = []

        # Merge results
        all_chunks: Dict[int, RetrievedChunk] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Strategy failed: {result}")
                continue
            for chunk in result:
                if chunk.node_id not in all_chunks:
                    all_chunks[chunk.node_id] = chunk
                elif chunk.score > all_chunks[chunk.node_id].score:
                    all_chunks[chunk.node_id].score = chunk.score

        return list(all_chunks.values())

    async def _sequential_retrieve(
        self,
        query: str,
        strategies: List[RetrievalStrategy],
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Run strategies sequentially."""
        all_chunks: Dict[int, RetrievedChunk] = {}

        for strategy in strategies:
            try:
                chunks = await strategy.retrieve(query, self.forest, self.graph, top_k)
                for chunk in chunks:
                    if chunk.node_id not in all_chunks:
                        all_chunks[chunk.node_id] = chunk
                    elif chunk.score > all_chunks[chunk.node_id].score:
                        all_chunks[chunk.node_id].score = chunk.score
            except Exception as e:
                logger.error(f"Strategy {strategy.name} failed: {e}")

        return list(all_chunks.values())

    def _apply_filters(
        self,
        chunks: List[RetrievedChunk],
        filters: Dict[str, Any],
    ) -> List[RetrievedChunk]:
        """Apply filters to retrieved chunks."""
        filtered = chunks

        # Filter by source
        if "source" in filters:
            target_source = filters["source"]
            filtered = [
                c for c in filtered if c.metadata.get("source") == target_source
            ]

        # Filter by tree level
        if "max_level" in filters:
            max_level = filters["max_level"]
            filtered = [c for c in filtered if c.tree_level <= max_level]

        # Filter by minimum score
        if "min_score" in filters:
            min_score = filters["min_score"]
            filtered = [c for c in filtered if c.score >= min_score]

        return filtered

    async def _record_retrieval(self, result: RetrievalResult) -> None:
        """Record retrieval observation for learning."""
        if not self.observations:
            return

        # Record as query observation
        success = len(result.chunks) > 0 and result.chunks[0].score > 0.5

        if success:
            self.observations.record_query_success(
                query=result.query,
                node_ids=[c.node_id for c in result.chunks],
                top_score=result.chunks[0].score if result.chunks else 0,
            )
        else:
            self.observations.record_query_failure(
                query=result.query,
                partial_matches=[c.node_id for c in result.chunks],
            )

    # ==================== Specialized Retrieval Methods ====================

    async def retrieve_for_incident(
        self,
        symptoms: str,
        affected_services: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> RetrievalResult:
        """
        Specialized retrieval for incident response.

        Prioritizes:
        - Runbooks matching symptoms
        - Similar past incidents
        - Service documentation
        """
        # Build enhanced query
        enhanced_query = symptoms
        if affected_services:
            enhanced_query += f" services: {', '.join(affected_services)}"

        return await self.retrieve(
            query=enhanced_query,
            top_k=top_k,
            mode=RetrievalMode.INCIDENT,
        )

    async def retrieve_procedure(
        self,
        task_description: str,
        context: Optional[str] = None,
        top_k: int = 5,
    ) -> RetrievalResult:
        """
        Retrieve procedures/runbooks for a task.
        """
        query = f"procedure how to {task_description}"
        if context:
            query += f" context: {context}"

        result = await self.retrieve(
            query=query,
            top_k=top_k,
            filters={"max_level": 1},  # Prefer detailed content
        )

        return result

    async def retrieve_entity_knowledge(
        self,
        entity_name: str,
        knowledge_type: Optional[str] = None,
        top_k: int = 10,
    ) -> RetrievalResult:
        """
        Retrieve all knowledge about a specific entity.
        """
        query = f"information about {entity_name}"
        if knowledge_type:
            query += f" {knowledge_type}"

        # Use graph-heavy strategy for entity queries
        return await self.retrieve(
            query=query,
            top_k=top_k,
            mode=RetrievalMode.THOROUGH,
        )

    async def retrieve_with_context(
        self,
        query: str,
        context_chunks: List[RetrievedChunk],
        top_k: int = 10,
    ) -> RetrievalResult:
        """
        Retrieve while considering already-retrieved context.

        Useful for follow-up questions in a conversation.
        """
        # Extract keywords from context
        context_text = " ".join(c.text[:100] for c in context_chunks)
        enhanced_query = f"{query} context: {context_text[:200]}"

        return await self.retrieve(
            query=enhanced_query,
            top_k=top_k,
        )

    # ==================== Admin Methods ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get retriever statistics."""
        avg_time = (
            self._total_retrieval_time / self._query_count
            if self._query_count > 0
            else 0
        )

        return {
            "query_count": self._query_count,
            "total_retrieval_time_ms": self._total_retrieval_time,
            "average_retrieval_time_ms": avg_time,
            "strategies_available": list(self._strategies.keys()),
            "config": {
                "default_mode": self.config.default_mode.value,
                "default_top_k": self.config.default_top_k,
                "enable_reranking": self.config.enable_reranking,
            },
        }

    def add_strategy(self, name: str, strategy: RetrievalStrategy) -> None:
        """Add a custom retrieval strategy."""
        self._strategies[name] = strategy
        logger.info(f"Added custom strategy: {name}")

    def set_reranker(self, reranker: Reranker) -> None:
        """Set a custom reranker."""
        self._reranker = reranker
        logger.info(f"Set reranker: {reranker.name}")
