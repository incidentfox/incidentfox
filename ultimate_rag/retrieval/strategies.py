"""
Retrieval Strategies for Ultimate RAG.

Each strategy provides a different approach to finding relevant knowledge:
- MultiQueryStrategy: Expands query into multiple perspectives
- HyDEStrategy: Generates hypothetical documents to improve matching
- AdaptiveDepthStrategy: Dynamically adjusts tree traversal depth
- HybridGraphTreeStrategy: Combines graph traversal with tree search
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from ..core.node import KnowledgeNode, KnowledgeTree, TreeForest
    from ..graph.entities import Entity
    from ..graph.graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class QueryIntent(str, Enum):
    """Detected intent of a query."""

    FACTUAL = "factual"  # Looking for specific facts
    PROCEDURAL = "procedural"  # Looking for how-to
    TROUBLESHOOTING = "troubleshooting"  # Debugging an issue
    EXPLORATORY = "exploratory"  # General exploration
    COMPARATIVE = "comparative"  # Comparing options
    RELATIONAL = "relational"  # Finding relationships
    TEMPORAL = "temporal"  # Time-based queries


@dataclass
class QueryAnalysis:
    """Analysis of a user query."""

    original_query: str
    intent: QueryIntent
    entities_mentioned: List[str]
    keywords: List[str]
    time_constraints: Optional[Tuple[datetime, datetime]] = None
    scope_hints: List[str] = field(
        default_factory=list
    )  # e.g., ["payment-service", "production"]
    urgency: float = 0.5  # 0-1, higher = more urgent (affects retrieval strategy)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_query": self.original_query,
            "intent": self.intent.value,
            "entities_mentioned": self.entities_mentioned,
            "keywords": self.keywords,
            "scope_hints": self.scope_hints,
            "urgency": self.urgency,
        }


@dataclass
class RetrievedChunk:
    """A chunk retrieved by a strategy."""

    node_id: int
    text: str
    score: float  # Base similarity score
    importance: float  # Importance score from node
    strategy: str  # Which strategy found this
    tree_level: int = 0  # Level in RAPTOR tree (0 = leaf)
    path: List[int] = field(default_factory=list)  # Path from root to this node
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def combined_score(self) -> float:
        """Combine similarity and importance scores."""
        # Weight importance at 30% of final score
        return 0.7 * self.score + 0.3 * self.importance

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "text": self.text[:200] + "..." if len(self.text) > 200 else self.text,
            "score": self.score,
            "importance": self.importance,
            "combined_score": self.combined_score,
            "strategy": self.strategy,
            "tree_level": self.tree_level,
        }


class RetrievalStrategy(ABC):
    """Base class for retrieval strategies."""

    name: str = "base"

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """
        Retrieve relevant chunks for a query.

        Args:
            query: User query
            forest: Knowledge tree forest
            graph: Optional knowledge graph
            top_k: Number of results to return
            **kwargs: Strategy-specific parameters

        Returns:
            List of retrieved chunks
        """
        pass

    def analyze_query(self, query: str) -> QueryAnalysis:
        """
        Analyze a query to understand intent and extract entities.

        In production, use an LLM or NER model for better analysis.
        """
        query_lower = query.lower()

        # Detect intent based on keywords
        intent = QueryIntent.FACTUAL
        if any(
            kw in query_lower for kw in ["how to", "how do", "steps to", "procedure"]
        ):
            intent = QueryIntent.PROCEDURAL
        elif any(
            kw in query_lower
            for kw in ["error", "fail", "issue", "debug", "fix", "broken"]
        ):
            intent = QueryIntent.TROUBLESHOOTING
        elif any(kw in query_lower for kw in ["compare", "difference", "vs", "better"]):
            intent = QueryIntent.COMPARATIVE
        elif any(
            kw in query_lower
            for kw in ["who", "owns", "responsible", "team", "contact"]
        ):
            intent = QueryIntent.RELATIONAL
        elif any(kw in query_lower for kw in ["when", "last", "history", "changed"]):
            intent = QueryIntent.TEMPORAL

        # Extract keywords (simple approach)
        stop_words = {
            "how",
            "do",
            "i",
            "the",
            "a",
            "an",
            "to",
            "for",
            "in",
            "is",
            "what",
            "why",
            "where",
            "when",
        }
        words = query_lower.split()
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        # Detect urgency
        urgency = 0.5
        if any(
            kw in query_lower for kw in ["urgent", "asap", "critical", "down", "outage"]
        ):
            urgency = 0.9
        elif any(kw in query_lower for kw in ["important", "production", "customer"]):
            urgency = 0.7

        return QueryAnalysis(
            original_query=query,
            intent=intent,
            entities_mentioned=[],  # Would use NER in production
            keywords=keywords,
            urgency=urgency,
        )


class MultiQueryStrategy(RetrievalStrategy):
    """
    Expand a single query into multiple perspectives.

    Generates query variations to capture different aspects of what
    the user might be looking for, then combines results.
    """

    name = "multi_query"

    def __init__(
        self,
        num_variations: int = 3,
        llm_expander: Optional[Any] = None,  # LLM for query expansion
    ):
        self.num_variations = num_variations
        self.llm_expander = llm_expander

    async def retrieve(
        self,
        query: str,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Retrieve using multiple query variations."""
        # Generate query variations
        variations = await self._expand_query(query)

        all_chunks: Dict[int, RetrievedChunk] = {}

        # Search with each variation
        for variation in variations:
            chunks = await self._search_trees(variation, forest, top_k)

            # Merge results, keeping best score for duplicates
            for chunk in chunks:
                if chunk.node_id not in all_chunks:
                    all_chunks[chunk.node_id] = chunk
                elif chunk.score > all_chunks[chunk.node_id].score:
                    all_chunks[chunk.node_id].score = chunk.score

        # Sort by combined score and return top_k
        results = sorted(
            all_chunks.values(), key=lambda c: c.combined_score, reverse=True
        )[:top_k]

        return results

    async def _expand_query(self, query: str) -> List[str]:
        """
        Expand query into variations.

        If LLM available, use it for intelligent expansion.
        Otherwise, use simple heuristics.
        """
        variations = [query]  # Always include original

        if self.llm_expander:
            # Use LLM for expansion (implementation depends on LLM interface)
            # prompt = f"Generate {self.num_variations} different ways to ask: {query}"
            # expanded = await self.llm_expander.generate(prompt)
            pass
        else:
            # Simple heuristic expansion
            analysis = self.analyze_query(query)

            # Add keyword-focused version
            if analysis.keywords:
                variations.append(" ".join(analysis.keywords))

            # Add intent-specific reformulation
            if analysis.intent == QueryIntent.PROCEDURAL:
                variations.append(
                    f"steps procedure guide {' '.join(analysis.keywords)}"
                )
            elif analysis.intent == QueryIntent.TROUBLESHOOTING:
                variations.append(f"error fix solution {' '.join(analysis.keywords)}")
            elif analysis.intent == QueryIntent.RELATIONAL:
                variations.append(
                    f"owner team responsible {' '.join(analysis.keywords)}"
                )

        return variations[: self.num_variations + 1]

    async def _search_trees(
        self,
        query: str,
        forest: "TreeForest",
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Search across all trees in the forest."""
        results = []

        # This would use the actual embedding search
        # For now, return placeholder
        for tree in forest.trees.values():
            # In production: use tree's vector index for similarity search
            # tree_results = await tree.search(query, top_k=top_k)
            pass

        return results


class HyDEStrategy(RetrievalStrategy):
    """
    Hypothetical Document Embeddings (HyDE).

    Instead of searching directly with the query, generate a hypothetical
    answer document and search with its embedding. This bridges the gap
    between question embeddings and document embeddings.
    """

    name = "hyde"

    def __init__(
        self,
        llm: Optional[Any] = None,  # LLM for generating hypothetical documents
        num_hypotheses: int = 1,
    ):
        self.llm = llm
        self.num_hypotheses = num_hypotheses

    async def retrieve(
        self,
        query: str,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Retrieve using hypothetical document embeddings."""
        # Generate hypothetical answer document
        hypotheses = await self._generate_hypotheses(query)

        all_chunks: Dict[int, RetrievedChunk] = {}

        # Search with each hypothesis
        for hypothesis in hypotheses:
            # In production: embed hypothesis and search
            # chunks = await self._search_with_embedding(hypothesis, forest, top_k)
            pass

        # Also search with original query
        original_chunks = await self._search_original(query, forest, top_k)
        for chunk in original_chunks:
            if chunk.node_id not in all_chunks:
                all_chunks[chunk.node_id] = chunk

        return sorted(
            all_chunks.values(), key=lambda c: c.combined_score, reverse=True
        )[:top_k]

    async def _generate_hypotheses(self, query: str) -> List[str]:
        """
        Generate hypothetical answer documents.

        The hypothesis should look like an ideal document that would
        answer the query.
        """
        if not self.llm:
            # Return simple template-based hypothesis
            analysis = self.analyze_query(query)

            if analysis.intent == QueryIntent.PROCEDURAL:
                template = f"""
                Procedure for {' '.join(analysis.keywords)}:
                1. First, you need to...
                2. Then, perform...
                3. Finally, verify...
                This procedure is used when you need to accomplish the task.
                """
            elif analysis.intent == QueryIntent.TROUBLESHOOTING:
                template = f"""
                Troubleshooting {' '.join(analysis.keywords)}:
                Common causes include configuration issues and resource constraints.
                To resolve this issue:
                1. Check the logs for specific errors
                2. Verify the configuration
                3. Restart the affected service
                """
            else:
                template = f"""
                Information about {' '.join(analysis.keywords)}:
                This describes the relevant details and context.
                Key points include the main concepts and their relationships.
                """

            return [template.strip()]

        # Use LLM for better hypothesis generation
        # prompt = f"Write a document that would answer this question: {query}"
        # return await self.llm.generate(prompt, n=self.num_hypotheses)
        return []

    async def _search_original(
        self,
        query: str,
        forest: "TreeForest",
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Fallback search with original query."""
        # Implementation would use actual embedding search
        return []


class AdaptiveDepthStrategy(RetrievalStrategy):
    """
    Adaptive Depth Traversal.

    Dynamically adjusts how deep to traverse the RAPTOR tree based on:
    - Query complexity
    - Initial results quality
    - Retrieved chunk coherence
    """

    name = "adaptive_depth"

    def __init__(
        self,
        min_depth: int = 0,  # Leaf level
        max_depth: int = 5,  # Maximum tree height
        quality_threshold: float = 0.7,  # When to stop going deeper
    ):
        self.min_depth = min_depth
        self.max_depth = max_depth
        self.quality_threshold = quality_threshold

    async def retrieve(
        self,
        query: str,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Retrieve with adaptive depth traversal."""
        analysis = self.analyze_query(query)

        # Determine starting depth based on query complexity
        start_depth = self._determine_start_depth(analysis)

        all_chunks: List[RetrievedChunk] = []
        current_depth = start_depth

        while current_depth >= self.min_depth and current_depth <= self.max_depth:
            # Retrieve at current depth
            chunks = await self._retrieve_at_depth(query, forest, current_depth, top_k)

            # Evaluate quality
            avg_score = sum(c.score for c in chunks) / len(chunks) if chunks else 0

            if avg_score >= self.quality_threshold:
                # Good quality, add these results
                all_chunks.extend(chunks)
                break
            elif avg_score < 0.3:
                # Poor quality, go higher (more abstract)
                current_depth += 1
            else:
                # Medium quality, go lower (more specific)
                all_chunks.extend(chunks)
                current_depth -= 1

        # Deduplicate and return
        seen = set()
        unique_chunks = []
        for chunk in all_chunks:
            if chunk.node_id not in seen:
                seen.add(chunk.node_id)
                unique_chunks.append(chunk)

        return sorted(unique_chunks, key=lambda c: c.combined_score, reverse=True)[
            :top_k
        ]

    def _determine_start_depth(self, analysis: QueryAnalysis) -> int:
        """
        Determine which tree depth to start searching.

        - Specific/factual queries → start at leaves (depth 0)
        - Broad/exploratory queries → start higher (depth 2-3)
        """
        if analysis.intent in [QueryIntent.FACTUAL, QueryIntent.TROUBLESHOOTING]:
            # Specific queries start at leaves
            return 0
        elif analysis.intent == QueryIntent.EXPLORATORY:
            # Broad queries start at summaries
            return 2
        elif analysis.intent == QueryIntent.COMPARATIVE:
            # Comparative needs both specific and summary
            return 1
        else:
            return 1

    async def _retrieve_at_depth(
        self,
        query: str,
        forest: "TreeForest",
        depth: int,
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Retrieve nodes at a specific tree depth."""
        chunks = []

        for tree in forest.trees.values():
            # Filter nodes at target depth
            nodes_at_depth = [
                node
                for node in tree.all_nodes.values()
                if node.is_active and self._get_node_depth(node, tree) == depth
            ]

            # In production: embed query and compute similarity with filtered nodes
            # For now, return placeholder
            for node in nodes_at_depth[:top_k]:
                chunks.append(
                    RetrievedChunk(
                        node_id=node.index,
                        text=node.text,
                        score=0.5,  # Would be actual similarity
                        importance=node.get_importance(),
                        strategy=self.name,
                        tree_level=depth,
                    )
                )

        return chunks

    def _get_node_depth(self, node: "KnowledgeNode", tree: "KnowledgeTree") -> int:
        """Get the depth of a node in the tree."""
        # Count levels to root
        depth = 0
        current = node
        while current.parent_ids:
            depth += 1
            # Get first parent (arbitrary for multi-parent cases)
            parent_id = current.parent_ids[0]
            if parent_id in tree.all_nodes:
                current = tree.all_nodes[parent_id]
            else:
                break
        return depth


class HybridGraphTreeStrategy(RetrievalStrategy):
    """
    Hybrid Graph + Tree Retrieval.

    Combines knowledge graph traversal with RAPTOR tree search:
    1. Use graph to find relevant entities
    2. Expand to related entities via relationships
    3. Get RAPTOR nodes linked to those entities
    4. Supplement with direct tree search
    """

    name = "hybrid_graph_tree"

    def __init__(
        self,
        graph_weight: float = 0.4,  # Weight for graph-derived results
        tree_weight: float = 0.6,  # Weight for tree search results
        expansion_hops: int = 2,  # How many hops to traverse in graph
    ):
        self.graph_weight = graph_weight
        self.tree_weight = tree_weight
        self.expansion_hops = expansion_hops

    async def retrieve(
        self,
        query: str,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Retrieve using hybrid graph + tree approach."""
        all_chunks: Dict[int, RetrievedChunk] = {}

        # Step 1: Graph-based retrieval
        if graph:
            graph_chunks = await self._retrieve_via_graph(query, forest, graph, top_k)
            for chunk in graph_chunks:
                chunk.score *= self.graph_weight
                all_chunks[chunk.node_id] = chunk

        # Step 2: Tree-based retrieval
        tree_chunks = await self._retrieve_via_tree(query, forest, top_k)
        for chunk in tree_chunks:
            if chunk.node_id in all_chunks:
                # Combine scores
                existing = all_chunks[chunk.node_id]
                existing.score += chunk.score * self.tree_weight
            else:
                chunk.score *= self.tree_weight
                all_chunks[chunk.node_id] = chunk

        # Sort and return
        return sorted(
            all_chunks.values(), key=lambda c: c.combined_score, reverse=True
        )[:top_k]

    async def _retrieve_via_graph(
        self,
        query: str,
        forest: "TreeForest",
        graph: "KnowledgeGraph",
        top_k: int,
    ) -> List[RetrievedChunk]:
        """
        Retrieve by traversing the knowledge graph.

        1. Find entities mentioned in query
        2. Traverse relationships to find related entities
        3. Get RAPTOR nodes linked to those entities
        """
        chunks = []
        analysis = self.analyze_query(query)

        # Find starting entities (in production, use NER or entity linking)
        starting_entities = self._find_entities_in_query(query, graph)

        if not starting_entities:
            return []

        # Traverse graph to find related entities
        related_entity_ids: Set[str] = set()
        for entity_id in starting_entities:
            # Get neighborhood
            traversal = graph.traverse(
                start_entity_id=entity_id,
                max_hops=self.expansion_hops,
            )
            for hop_entities in traversal.entities_by_hop.values():
                related_entity_ids.update(hop_entities)

        # Get RAPTOR nodes for these entities
        for entity_id in related_entity_ids:
            entity = graph.get_entity(entity_id)
            if entity and entity.raptor_node_ids:
                for node_id in entity.raptor_node_ids:
                    # Find node in forest
                    node = self._find_node_in_forest(node_id, forest)
                    if node:
                        chunks.append(
                            RetrievedChunk(
                                node_id=node_id,
                                text=node.text,
                                score=0.8,  # Graph-derived gets high base score
                                importance=node.get_importance(),
                                strategy=f"{self.name}_graph",
                                metadata={"source_entity": entity_id},
                            )
                        )

        return chunks[:top_k]

    async def _retrieve_via_tree(
        self,
        query: str,
        forest: "TreeForest",
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Direct tree-based semantic search."""
        # In production: use embedding similarity search
        # This would call the RAPTOR tree's search method
        chunks = []

        for tree in forest.trees.values():
            # Would use actual embedding search
            # tree_results = await tree.similarity_search(query, top_k)
            pass

        return chunks

    def _find_entities_in_query(
        self,
        query: str,
        graph: "KnowledgeGraph",
    ) -> List[str]:
        """
        Find entities mentioned in the query.

        Simple implementation: check if entity names appear in query.
        Production: use NER + entity linking.
        """
        found = []
        query_lower = query.lower()

        for entity_id, entity in graph.entities.items():
            if entity.name.lower() in query_lower:
                found.append(entity_id)
            # Also check aliases
            for alias in entity.aliases:
                if alias.lower() in query_lower:
                    found.append(entity_id)
                    break

        return found

    def _find_node_in_forest(
        self,
        node_id: int,
        forest: "TreeForest",
    ) -> Optional["KnowledgeNode"]:
        """Find a node by ID across all trees."""
        for tree in forest.trees.values():
            if node_id in tree.all_nodes:
                return tree.all_nodes[node_id]
        return None


class IncidentAwareStrategy(RetrievalStrategy):
    """
    Incident-aware retrieval strategy.

    When handling incidents, prioritizes:
    - Runbooks for similar symptoms
    - Recent incident resolutions
    - Service dependency information
    - On-call contacts
    """

    name = "incident_aware"

    def __init__(
        self,
        symptom_weight: float = 0.4,
        recency_weight: float = 0.3,
        success_weight: float = 0.3,
    ):
        self.symptom_weight = symptom_weight
        self.recency_weight = recency_weight
        self.success_weight = success_weight

    async def retrieve(
        self,
        query: str,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Retrieve with incident awareness."""
        analysis = self.analyze_query(query)

        if analysis.intent != QueryIntent.TROUBLESHOOTING:
            # Fall back to standard hybrid search
            hybrid = HybridGraphTreeStrategy()
            return await hybrid.retrieve(query, forest, graph, top_k, **kwargs)

        chunks: List[RetrievedChunk] = []

        if graph:
            # 1. Find runbooks matching symptoms
            runbook_chunks = await self._find_runbooks(query, forest, graph)
            chunks.extend(runbook_chunks)

            # 2. Find similar past incidents
            incident_chunks = await self._find_similar_incidents(query, forest, graph)
            chunks.extend(incident_chunks)

            # 3. Get service context
            service_chunks = await self._get_service_context(query, forest, graph)
            chunks.extend(service_chunks)

        # 4. Supplement with tree search
        tree_chunks = await self._tree_search(query, forest, top_k)
        chunks.extend(tree_chunks)

        # Deduplicate and rank
        seen = set()
        unique = []
        for chunk in chunks:
            if chunk.node_id not in seen:
                seen.add(chunk.node_id)
                unique.append(chunk)

        return sorted(unique, key=lambda c: c.combined_score, reverse=True)[:top_k]

    async def _find_runbooks(
        self,
        query: str,
        forest: "TreeForest",
        graph: "KnowledgeGraph",
    ) -> List[RetrievedChunk]:
        """Find runbooks matching the symptoms in the query."""
        from ..graph.entities import EntityType

        chunks = []

        # Find all runbook entities
        runbooks = graph.get_entities_by_type(EntityType.RUNBOOK)

        for runbook in runbooks:
            # Check if symptoms match (simple keyword matching)
            # In production: use embedding similarity
            symptoms = runbook.properties.get("symptoms", [])
            query_lower = query.lower()

            match_score = 0
            for symptom in symptoms:
                if any(word in query_lower for word in symptom.lower().split()):
                    match_score += 1

            if match_score > 0:
                # Get linked RAPTOR nodes
                for node_id in runbook.raptor_node_ids:
                    node = self._find_node_in_forest(node_id, forest)
                    if node:
                        chunks.append(
                            RetrievedChunk(
                                node_id=node_id,
                                text=node.text,
                                score=min(1.0, match_score * 0.3),
                                importance=node.get_importance(),
                                strategy=f"{self.name}_runbook",
                                metadata={
                                    "runbook_id": runbook.entity_id,
                                    "runbook_name": runbook.name,
                                },
                            )
                        )

        return chunks

    async def _find_similar_incidents(
        self,
        query: str,
        forest: "TreeForest",
        graph: "KnowledgeGraph",
    ) -> List[RetrievedChunk]:
        """Find similar past incidents."""
        from ..graph.entities import EntityType
        from ..graph.relationships import RelationshipType

        chunks = []

        # Find resolved incidents with SIMILAR_TO relationships
        incidents = graph.get_entities_by_type(EntityType.INCIDENT)

        for incident in incidents:
            if incident.properties.get("status") != "resolved":
                continue

            # Check for keyword overlap
            incident_text = f"{incident.name} {incident.description}"
            query_words = set(query.lower().split())
            incident_words = set(incident_text.lower().split())

            overlap = len(query_words & incident_words)
            if overlap >= 2:
                for node_id in incident.raptor_node_ids:
                    node = self._find_node_in_forest(node_id, forest)
                    if node:
                        chunks.append(
                            RetrievedChunk(
                                node_id=node_id,
                                text=node.text,
                                score=min(1.0, overlap * 0.2),
                                importance=node.get_importance(),
                                strategy=f"{self.name}_incident",
                                metadata={
                                    "incident_id": incident.entity_id,
                                    "resolution": incident.properties.get("resolution"),
                                },
                            )
                        )

        return chunks

    async def _get_service_context(
        self,
        query: str,
        forest: "TreeForest",
        graph: "KnowledgeGraph",
    ) -> List[RetrievedChunk]:
        """Get context about affected services."""
        # Would use entity linking to find services mentioned
        # Then get their dependencies, owners, etc.
        return []

    async def _tree_search(
        self,
        query: str,
        forest: "TreeForest",
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Standard tree-based search."""
        return []

    def _find_node_in_forest(
        self,
        node_id: int,
        forest: "TreeForest",
    ) -> Optional["KnowledgeNode"]:
        """Find a node by ID across all trees."""
        for tree in forest.trees.values():
            if node_id in tree.all_nodes:
                return tree.all_nodes[node_id]
        return None
