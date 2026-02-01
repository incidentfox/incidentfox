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
    tree_id: str = ""  # Tree this chunk came from
    tree_level: int = 0  # Level in RAPTOR tree (0 = leaf)
    layer: int = 0  # Alias for tree_level (used by RAPTOR)
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

        Uses LLM for sophisticated analysis with heuristic fallback.
        """
        # Try LLM-based analysis first
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, use heuristics
                return self._analyze_query_heuristic(query)
            else:
                return loop.run_until_complete(self._analyze_query_llm(query))
        except RuntimeError:
            # No event loop, try to create one
            try:
                return asyncio.run(self._analyze_query_llm(query))
            except Exception:
                return self._analyze_query_heuristic(query)

    async def _analyze_query_llm(self, query: str) -> QueryAnalysis:
        """LLM-based query analysis for intent and entity extraction."""
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI()

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.0,
                max_tokens=200,
                messages=[
                    {
                        "role": "system",
                        "content": """Analyze this search query and return JSON with:
{
  "intent": one of ["factual", "procedural", "troubleshooting", "comparative", "relational", "temporal"],
  "entities": list of service/system/team names mentioned,
  "keywords": list of important search terms,
  "urgency": number 0.0-1.0 (1.0 = critical incident)
}

Intent definitions:
- factual: Looking for facts or information
- procedural: How to do something, steps, procedures
- troubleshooting: Fixing errors, debugging, resolving issues
- comparative: Comparing options
- relational: Who owns/manages something
- temporal: When something happened or changed""",
                    },
                    {"role": "user", "content": query},
                ],
            )

            content = response.choices[0].message.content.strip()
            import json

            # Parse JSON response
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                import re

                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    return self._analyze_query_heuristic(query)

            # Map intent string to enum
            intent_map = {
                "factual": QueryIntent.FACTUAL,
                "procedural": QueryIntent.PROCEDURAL,
                "troubleshooting": QueryIntent.TROUBLESHOOTING,
                "comparative": QueryIntent.COMPARATIVE,
                "relational": QueryIntent.RELATIONAL,
                "temporal": QueryIntent.TEMPORAL,
            }
            intent = intent_map.get(data.get("intent", "factual"), QueryIntent.FACTUAL)

            return QueryAnalysis(
                original_query=query,
                intent=intent,
                entities_mentioned=data.get("entities", []),
                keywords=data.get("keywords", []),
                urgency=float(data.get("urgency", 0.5)),
            )

        except Exception as e:
            logger.debug(f"LLM query analysis failed, using heuristics: {e}")
            return self._analyze_query_heuristic(query)

    def _analyze_query_heuristic(self, query: str) -> QueryAnalysis:
        """Fallback heuristic-based query analysis."""
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
            "can",
            "could",
            "would",
            "should",
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
            entities_mentioned=[],
            keywords=keywords,
            urgency=urgency,
        )

    async def search_trees(
        self,
        query: str,
        forest: "TreeForest",
        top_k: int = 10,
    ) -> List[RetrievedChunk]:
        """
        Shared tree search implementation using RAPTOR's similarity functions.

        This is the core semantic search that all strategies can use.
        """
        try:
            from knowledge_base.raptor.EmbeddingModels import OpenAIEmbeddingModel
            from knowledge_base.raptor.utils import distances_from_embeddings
        except ImportError as e:
            logger.error(f"Failed to import RAPTOR modules: {e}")
            logger.error(
                "Ensure knowledge_base is in PYTHONPATH and dependencies are installed"
            )
            return []

        chunks = []
        embedding_model = OpenAIEmbeddingModel()

        try:
            query_embedding = embedding_model.create_embedding(query)
        except Exception as e:
            logger.error(f"Failed to create query embedding: {e}")
            return []

        for tree in forest.trees.values():
            node_list = list(tree.all_nodes.values())
            if not node_list:
                continue

            # Extract embeddings
            embeddings = []
            valid_nodes = []
            embedding_key = getattr(tree, "embedding_model", "OpenAI") or "OpenAI"

            for node in node_list:
                node_embedding = node.embeddings.get(embedding_key)
                # Use 'is not None' to handle numpy arrays correctly
                if node_embedding is not None:
                    embeddings.append(node_embedding)
                    valid_nodes.append(node)

            if not embeddings:
                continue

            try:
                distances = distances_from_embeddings(
                    query_embedding, embeddings, distance_metric="cosine"
                )
                scores = [1.0 - d for d in distances]
                sorted_indices = sorted(
                    range(len(scores)), key=lambda i: scores[i], reverse=True
                )

                for idx in sorted_indices[:top_k]:
                    node = valid_nodes[idx]
                    chunks.append(
                        RetrievedChunk(
                            text=node.text,
                            node_id=node.index,
                            tree_id=tree.tree_id,
                            score=scores[idx],
                            importance=node.get_importance(),
                            layer=getattr(node, "layer", 0),
                            strategy=self.name,
                            metadata={
                                "source_url": getattr(node, "source_url", None),
                                "knowledge_type": (
                                    node.knowledge_type.value
                                    if hasattr(node, "knowledge_type")
                                    else "factual"
                                ),
                            },
                        )
                    )
            except Exception as e:
                logger.error(f"Search failed for tree {tree.tree_id}: {e}")
                continue

        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks[:top_k]


class MultiQueryStrategy(RetrievalStrategy):
    """
    Expand a single query into multiple perspectives using LLM.

    Generates query variations to capture different aspects of what
    the user might be looking for, then combines results.
    """

    name = "multi_query"

    def __init__(
        self,
        num_variations: int = 3,
        model: str = "gpt-4o-mini",
    ):
        self.num_variations = num_variations
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI()
            except ImportError:
                logger.warning("OpenAI not available for multi-query expansion")
        return self._client

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
        Expand query into variations using LLM.

        Uses GPT to generate semantically diverse reformulations
        that capture different aspects of the user's intent.
        """
        variations = [query]  # Always include original

        client = self._get_client()
        if client:
            try:
                response = await client.chat.completions.create(
                    model=self.model,
                    temperature=0.7,
                    max_tokens=300,
                    messages=[
                        {
                            "role": "system",
                            "content": """You are a search query expansion expert. Generate alternative search queries that capture different aspects of the user's information need.

Rules:
- Generate exactly the requested number of variations
- Each variation should approach the topic from a different angle
- Keep variations concise (under 20 words each)
- Output ONLY the variations, one per line, no numbering or prefixes
- Variations should be natural language queries, not keywords""",
                        },
                        {
                            "role": "user",
                            "content": f"Generate {self.num_variations} different ways to search for information about:\n\n{query}",
                        },
                    ],
                )

                content = response.choices[0].message.content
                if content:
                    # Parse variations from response
                    llm_variations = [
                        line.strip()
                        for line in content.strip().split("\n")
                        if line.strip() and len(line.strip()) > 5
                    ]
                    variations.extend(llm_variations[: self.num_variations])
                    logger.debug(
                        f"LLM expanded query into {len(variations)} variations"
                    )

            except Exception as e:
                logger.warning(f"LLM query expansion failed, using heuristics: {e}")
                # Fall back to heuristic expansion
                variations.extend(self._heuristic_expansion(query))
        else:
            # No LLM available, use heuristics
            variations.extend(self._heuristic_expansion(query))

        return variations[: self.num_variations + 1]

    def _heuristic_expansion(self, query: str) -> List[str]:
        """Fallback heuristic-based query expansion."""
        expansions = []
        analysis = self.analyze_query(query)

        # Add keyword-focused version
        if analysis.keywords:
            expansions.append(" ".join(analysis.keywords))

        # Add intent-specific reformulation
        if analysis.intent == QueryIntent.PROCEDURAL:
            expansions.append(f"steps procedure guide {' '.join(analysis.keywords)}")
        elif analysis.intent == QueryIntent.TROUBLESHOOTING:
            expansions.append(f"error fix solution {' '.join(analysis.keywords)}")
        elif analysis.intent == QueryIntent.RELATIONAL:
            expansions.append(f"owner team responsible {' '.join(analysis.keywords)}")

        return expansions

    async def _search_trees(
        self,
        query: str,
        forest: "TreeForest",
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Search across all trees in the forest using shared semantic search."""
        return await self.search_trees(query, forest, top_k)


class QueryDecompositionStrategy(RetrievalStrategy):
    """
    Decompose complex multi-hop queries into simpler sub-queries.

    For questions requiring information from multiple sources, this strategy:
    1. Uses LLM to identify distinct sub-questions
    2. Retrieves for each sub-question independently
    3. Merges results with score boosting for chunks found by multiple sub-queries
    """

    name = "query_decomposition"

    DECOMPOSITION_PROMPT = """Analyze this question and break it into simpler sub-questions.

Question: {query}

Instructions:
- Identify distinct pieces of information needed
- Each sub-question should be answerable by a single document
- Output 2-4 focused sub-questions, one per line
- No numbering or bullets"""

    def __init__(self, model: str = "gpt-4o-mini", max_sub_queries: int = 4):
        self.model = model
        self.max_sub_queries = max_sub_queries
        self._client = None

    def _get_client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI()
            except ImportError:
                logger.warning("OpenAI not available for query decomposition")
        return self._client

    async def _decompose_query(self, query: str) -> List[str]:
        """Use LLM to break query into sub-questions."""
        sub_queries = [query]
        client = self._get_client()
        if not client:
            return sub_queries

        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.DECOMPOSITION_PROMPT.format(query=query),
                    }
                ],
                temperature=0.3,
                max_tokens=200,
            )
            content = response.choices[0].message.content
            if content:
                llm_sub_queries = [
                    line.strip().rstrip("?") + "?"
                    for line in content.strip().split("\n")
                    if line.strip() and len(line.strip()) > 10
                ]
                sub_queries.extend(llm_sub_queries[: self.max_sub_queries])
                logger.info(f"Query decomposed into {len(sub_queries)} sub-queries")
        except Exception as e:
            logger.warning(f"Query decomposition failed: {e}")

        return sub_queries

    async def retrieve(
        self,
        query: str,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Retrieve using decomposed sub-queries."""
        sub_queries = await self._decompose_query(query)

        all_chunks: Dict[int, RetrievedChunk] = {}
        chunk_hit_count: Dict[int, int] = {}

        for sub_q in sub_queries:
            chunks = await self.search_trees(sub_q, forest, top_k)
            for chunk in chunks:
                chunk_hit_count[chunk.node_id] = (
                    chunk_hit_count.get(chunk.node_id, 0) + 1
                )
                if chunk.node_id not in all_chunks:
                    all_chunks[chunk.node_id] = chunk
                elif chunk.score > all_chunks[chunk.node_id].score:
                    all_chunks[chunk.node_id].score = chunk.score

        # Boost chunks found by multiple sub-queries
        for node_id, chunk in all_chunks.items():
            hit_count = chunk_hit_count[node_id]
            if hit_count > 1:
                boost_factor = 1.0 + (0.2 * (hit_count - 1))
                chunk.score = min(1.0, chunk.score * boost_factor)

        results = sorted(all_chunks.values(), key=lambda c: c.score, reverse=True)[
            :top_k
        ]
        return results


class HyDEStrategy(RetrievalStrategy):
    """
    Hypothetical Document Embeddings (HyDE) with LLM generation.

    Instead of searching directly with the query, generate a hypothetical
    answer document using LLM and search with its embedding. This bridges
    the gap between question embeddings and document embeddings.
    """

    name = "hyde"

    def __init__(
        self,
        num_hypotheses: int = 2,
        model: str = "gpt-4o-mini",
    ):
        self.num_hypotheses = num_hypotheses
        self.model = model
        self._client = None

    def _get_client(self):
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI()
            except ImportError:
                logger.warning("OpenAI not available for HyDE")
        return self._client

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

        # Search with each hypothesis (they act as expanded queries)
        for hypothesis in hypotheses:
            chunks = await self.search_trees(hypothesis, forest, top_k)
            for chunk in chunks:
                if chunk.node_id not in all_chunks:
                    # Slightly reduce score for hypothesis-based results
                    chunk.score *= 0.9
                    all_chunks[chunk.node_id] = chunk
                else:
                    # Boost score if found by multiple hypotheses
                    all_chunks[chunk.node_id].score = min(
                        1.0, all_chunks[chunk.node_id].score + 0.1
                    )

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
        Generate hypothetical answer documents using LLM.

        The hypothesis should look like an ideal document that would
        answer the query - written as if it's documentation, not a response.
        """
        client = self._get_client()
        if client:
            try:
                # Analyze query to customize the prompt
                analysis = self.analyze_query(query)

                if analysis.intent == QueryIntent.PROCEDURAL:
                    doc_type = "a step-by-step procedure or runbook"
                elif analysis.intent == QueryIntent.TROUBLESHOOTING:
                    doc_type = "a troubleshooting guide with root causes and solutions"
                elif analysis.intent == QueryIntent.RELATIONAL:
                    doc_type = (
                        "documentation about ownership, dependencies, or relationships"
                    )
                else:
                    doc_type = "technical documentation or reference material"

                response = await client.chat.completions.create(
                    model=self.model,
                    temperature=0.7,
                    max_tokens=500,
                    messages=[
                        {
                            "role": "system",
                            "content": f"""You are a technical documentation writer. Generate {self.num_hypotheses} hypothetical documentation excerpts that would perfectly answer the user's question.

Rules:
- Write as if you're creating {doc_type}
- Each excerpt should be 50-100 words
- Use technical language appropriate for infrastructure/DevOps documentation
- Include specific details, steps, or explanations that would be in real docs
- Do NOT write a conversational answer - write as documentation
- Separate each excerpt with "---" on its own line
- Include relevant technical terms, service names, and concepts""",
                        },
                        {
                            "role": "user",
                            "content": f"Write hypothetical documentation excerpts that would answer:\n\n{query}",
                        },
                    ],
                )

                content = response.choices[0].message.content
                if content:
                    # Parse hypotheses from response
                    hypotheses = [
                        h.strip()
                        for h in content.split("---")
                        if h.strip() and len(h.strip()) > 20
                    ]
                    if hypotheses:
                        logger.debug(
                            f"LLM generated {len(hypotheses)} hypotheses for HyDE"
                        )
                        return hypotheses[: self.num_hypotheses]

            except Exception as e:
                logger.warning(
                    f"LLM hypothesis generation failed, using templates: {e}"
                )

        # Fall back to template-based hypothesis
        return self._template_hypothesis(query)

    def _template_hypothesis(self, query: str) -> List[str]:
        """Fallback template-based hypothesis generation."""
        analysis = self.analyze_query(query)
        keywords = " ".join(analysis.keywords) if analysis.keywords else query

        hypotheses = []

        if analysis.intent == QueryIntent.PROCEDURAL:
            hypotheses.append(f"""
## Procedure: {keywords}

### Prerequisites
- Access to the relevant system
- Required permissions configured

### Steps
1. First, verify the current state of {keywords}
2. Make the necessary configuration changes
3. Apply and validate the changes
4. Monitor for any issues

### Troubleshooting
If issues occur, check the logs and rollback if necessary.
            """.strip())
        elif analysis.intent == QueryIntent.TROUBLESHOOTING:
            hypotheses.append(f"""
## Troubleshooting: {keywords}

### Symptoms
- Service degradation or errors related to {keywords}
- Alert triggered from monitoring

### Root Causes
1. Configuration drift or misconfiguration
2. Resource exhaustion (CPU, memory, disk)
3. Network connectivity issues
4. Dependency service failures

### Resolution Steps
1. Check service logs: `kubectl logs` or CloudWatch
2. Verify configuration matches expected state
3. Check resource utilization metrics
4. Restart affected components if needed

### Prevention
Set up monitoring and alerting for early detection.
            """.strip())
        else:
            hypotheses.append(f"""
## {keywords}

### Overview
This documentation covers {keywords} and related concepts.

### Key Information
- Primary purpose and functionality
- Integration points with other systems
- Configuration options and best practices

### Related Topics
- Dependencies and requirements
- Monitoring and observability
- Common operations and maintenance tasks
            """.strip())

        return hypotheses

    async def _search_original(
        self,
        query: str,
        forest: "TreeForest",
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Fallback search with original query."""
        return await self.search_trees(query, forest, top_k)


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
        """Retrieve nodes at a specific tree depth using semantic search."""
        try:
            from knowledge_base.raptor.EmbeddingModels import OpenAIEmbeddingModel
            from knowledge_base.raptor.utils import distances_from_embeddings
        except ImportError as e:
            logger.error(f"Failed to import RAPTOR modules: {e}")
            return []

        chunks = []
        embedding_model = OpenAIEmbeddingModel()

        try:
            query_embedding = embedding_model.create_embedding(query)
        except Exception as e:
            logger.error(f"Failed to create query embedding: {e}")
            return []

        for tree in forest.trees.values():
            # Filter nodes at target depth (using layer as proxy for depth)
            nodes_at_depth = [
                node
                for node in tree.all_nodes.values()
                if getattr(node, "is_active", True)
                and getattr(node, "layer", 0) == depth
            ]

            if not nodes_at_depth:
                continue

            # Extract embeddings for filtered nodes
            embeddings = []
            valid_nodes = []
            embedding_key = getattr(tree, "embedding_model", "OpenAI") or "OpenAI"

            for node in nodes_at_depth:
                node_embedding = node.embeddings.get(embedding_key)
                # Use 'is not None' to handle numpy arrays correctly
                if node_embedding is not None:
                    embeddings.append(node_embedding)
                    valid_nodes.append(node)

            if not embeddings:
                continue

            try:
                # Compute similarity scores
                distances = distances_from_embeddings(
                    query_embedding, embeddings, distance_metric="cosine"
                )
                scores = [1.0 - d for d in distances]
                sorted_indices = sorted(
                    range(len(scores)), key=lambda i: scores[i], reverse=True
                )

                for idx in sorted_indices[:top_k]:
                    node = valid_nodes[idx]
                    chunks.append(
                        RetrievedChunk(
                            node_id=node.index,
                            text=node.text,
                            tree_id=tree.tree_id,
                            score=scores[idx],
                            importance=node.get_importance(),
                            strategy=self.name,
                            layer=depth,
                            metadata={
                                "source_url": getattr(node, "source_url", None),
                                "depth": depth,
                            },
                        )
                    )
            except Exception as e:
                logger.error(f"Depth search failed for tree {tree.tree_id}: {e}")
                continue

        # Sort by score and return top_k
        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks[:top_k]

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

        # Step 1: Graph-based retrieval (with error handling)
        if graph:
            try:
                graph_chunks = await self._retrieve_via_graph(
                    query, forest, graph, top_k
                )
                for chunk in graph_chunks:
                    chunk.score *= self.graph_weight
                    all_chunks[chunk.node_id] = chunk
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    f"Graph retrieval failed, falling back to tree: {e}"
                )

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
        """
        Direct tree-based semantic search using shared helper.

        Uses cosine similarity between query embedding and node embeddings
        to find the most relevant nodes across all trees in the forest.
        """
        chunks = await self.search_trees(query, forest, top_k)
        # Update strategy name to indicate tree source
        for chunk in chunks:
            chunk.strategy = f"{self.name}_tree"
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
        """Find runbooks matching the symptoms in the query using semantic similarity."""
        from ..graph.entities import EntityType

        try:
            from knowledge_base.raptor.EmbeddingModels import OpenAIEmbeddingModel
            from knowledge_base.raptor.utils import distances_from_embeddings
        except ImportError:
            logger.warning("RAPTOR not available, falling back to keyword matching")
            return await self._find_runbooks_keyword(query, forest, graph)

        chunks = []
        embedding_model = OpenAIEmbeddingModel()

        try:
            query_embedding = embedding_model.create_embedding(query)
        except Exception as e:
            logger.error(f"Failed to embed query: {e}")
            return await self._find_runbooks_keyword(query, forest, graph)

        # Find all runbook entities
        runbooks = graph.get_entities_by_type(EntityType.RUNBOOK)

        for runbook in runbooks:
            # Compute semantic similarity with runbook content
            runbook_text = f"{runbook.name} {runbook.description}"
            symptoms = runbook.properties.get("symptoms", [])
            if symptoms:
                runbook_text += " " + " ".join(symptoms)

            try:
                runbook_embedding = embedding_model.create_embedding(runbook_text)
                distances = distances_from_embeddings(
                    query_embedding, [runbook_embedding], distance_metric="cosine"
                )
                similarity_score = 1.0 - distances[0]

                if similarity_score > 0.4:  # Threshold for relevance
                    # Get linked RAPTOR nodes
                    for node_id in runbook.raptor_node_ids:
                        node = self._find_node_in_forest(node_id, forest)
                        if node:
                            chunks.append(
                                RetrievedChunk(
                                    node_id=node_id,
                                    text=node.text,
                                    tree_id=getattr(node, "tree_id", None),
                                    score=similarity_score,
                                    importance=node.get_importance(),
                                    strategy=f"{self.name}_runbook",
                                    metadata={
                                        "runbook_id": runbook.entity_id,
                                        "runbook_name": runbook.name,
                                    },
                                )
                            )
            except Exception as e:
                logger.warning(f"Failed to embed runbook {runbook.name}: {e}")
                continue

        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks

    async def _find_runbooks_keyword(
        self,
        query: str,
        forest: "TreeForest",
        graph: "KnowledgeGraph",
    ) -> List[RetrievedChunk]:
        """Fallback keyword-based runbook search."""
        from ..graph.entities import EntityType

        chunks = []
        runbooks = graph.get_entities_by_type(EntityType.RUNBOOK)

        for runbook in runbooks:
            symptoms = runbook.properties.get("symptoms", [])
            query_lower = query.lower()

            match_score = 0
            for symptom in symptoms:
                if any(word in query_lower for word in symptom.lower().split()):
                    match_score += 1

            if match_score > 0:
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
        """Find similar past incidents using semantic similarity."""
        from ..graph.entities import EntityType

        try:
            from knowledge_base.raptor.EmbeddingModels import OpenAIEmbeddingModel
            from knowledge_base.raptor.utils import distances_from_embeddings
        except ImportError:
            logger.warning("RAPTOR not available, falling back to keyword matching")
            return await self._find_similar_incidents_keyword(query, forest, graph)

        chunks = []
        embedding_model = OpenAIEmbeddingModel()

        try:
            query_embedding = embedding_model.create_embedding(query)
        except Exception as e:
            logger.error(f"Failed to embed query: {e}")
            return await self._find_similar_incidents_keyword(query, forest, graph)

        # Find resolved incidents
        incidents = graph.get_entities_by_type(EntityType.INCIDENT)

        for incident in incidents:
            if incident.properties.get("status") != "resolved":
                continue

            # Compute semantic similarity
            incident_text = f"{incident.name} {incident.description}"

            try:
                incident_embedding = embedding_model.create_embedding(incident_text)
                distances = distances_from_embeddings(
                    query_embedding, [incident_embedding], distance_metric="cosine"
                )
                similarity_score = 1.0 - distances[0]

                if similarity_score > 0.5:  # Threshold for relevance
                    for node_id in incident.raptor_node_ids:
                        node = self._find_node_in_forest(node_id, forest)
                        if node:
                            chunks.append(
                                RetrievedChunk(
                                    node_id=node_id,
                                    text=node.text,
                                    tree_id=getattr(node, "tree_id", None),
                                    score=similarity_score,
                                    importance=node.get_importance(),
                                    strategy=f"{self.name}_incident",
                                    metadata={
                                        "incident_id": incident.entity_id,
                                        "resolution": incident.properties.get(
                                            "resolution"
                                        ),
                                    },
                                )
                            )
            except Exception as e:
                logger.warning(f"Failed to embed incident {incident.name}: {e}")
                continue

        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks

    async def _find_similar_incidents_keyword(
        self,
        query: str,
        forest: "TreeForest",
        graph: "KnowledgeGraph",
    ) -> List[RetrievedChunk]:
        """Fallback keyword-based incident search."""
        from ..graph.entities import EntityType

        chunks = []
        incidents = graph.get_entities_by_type(EntityType.INCIDENT)

        for incident in incidents:
            if incident.properties.get("status") != "resolved":
                continue

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
        """
        Get context about affected services using LLM-based entity extraction
        and graph traversal for dependencies.
        """
        from ..graph.entities import EntityType

        chunks = []

        # Extract service names from query using LLM
        service_names = await self._extract_services_from_query(query)

        if not service_names:
            # Fall back to keyword matching against known services
            services = graph.get_entities_by_type(EntityType.SERVICE)
            query_lower = query.lower()
            for service in services:
                if service.name.lower() in query_lower or any(
                    alias.lower() in query_lower for alias in service.aliases
                ):
                    service_names.append(service.name)

        # Get context for each identified service
        for service_name in service_names:
            service = graph.get_entity_by_name(service_name)
            if not service:
                continue

            # Get service's RAPTOR nodes
            for node_id in service.raptor_node_ids:
                node = self._find_node_in_forest(node_id, forest)
                if node:
                    chunks.append(
                        RetrievedChunk(
                            node_id=node_id,
                            text=node.text,
                            tree_id=getattr(node, "tree_id", None),
                            score=0.7,  # Base score for direct service match
                            importance=node.get_importance(),
                            strategy=f"{self.name}_service",
                            metadata={
                                "service_id": service.entity_id,
                                "service_name": service.name,
                            },
                        )
                    )

            # Get dependencies and their context
            dependencies = graph.get_related_entities(
                service.entity_id, relationship_type="depends_on"
            )
            for dep in dependencies[:3]:  # Limit to top 3 dependencies
                for node_id in dep.raptor_node_ids:
                    node = self._find_node_in_forest(node_id, forest)
                    if node:
                        chunks.append(
                            RetrievedChunk(
                                node_id=node_id,
                                text=node.text,
                                tree_id=getattr(node, "tree_id", None),
                                score=0.5,  # Lower score for dependency context
                                importance=node.get_importance(),
                                strategy=f"{self.name}_dependency",
                                metadata={
                                    "dependency_of": service.name,
                                    "dependency_name": dep.name,
                                },
                            )
                        )

        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks

    async def _extract_services_from_query(self, query: str) -> List[str]:
        """Extract service names from query using LLM."""
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI()

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.0,
                max_tokens=100,
                messages=[
                    {
                        "role": "system",
                        "content": """Extract service/system names mentioned in the query.
Return ONLY a JSON array of service names, e.g. ["api-gateway", "postgres", "redis"]
If no services are mentioned, return an empty array: []
Focus on infrastructure components, databases, APIs, microservices, etc.""",
                    },
                    {"role": "user", "content": query},
                ],
            )

            content = response.choices[0].message.content.strip()
            import json

            return json.loads(content)
        except Exception as e:
            logger.warning(f"LLM service extraction failed: {e}")
            return []

    async def _tree_search(
        self,
        query: str,
        forest: "TreeForest",
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Standard tree-based semantic search using shared helper."""
        return await self.search_trees(query, forest, top_k)

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


class BM25HybridStrategy(RetrievalStrategy):
    """
    Hybrid BM25 + Dense retrieval strategy.

    Combines sparse (BM25 keyword) and dense (embedding) retrieval for
    better coverage. This is the standard approach for SOTA retrieval.

    BM25 excels at:
    - Exact keyword matching
    - Rare/specific terms
    - Named entities (person names, service names)

    Dense excels at:
    - Semantic similarity
    - Paraphrases
    - Conceptual matching

    Combining both gives the best of both worlds.
    """

    name = "bm25_hybrid"

    def __init__(self, bm25_weight: float = 0.4, dense_weight: float = 0.6):
        """
        Args:
            bm25_weight: Weight for BM25 scores (default 0.4)
            dense_weight: Weight for dense scores (default 0.6)
        """
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight
        self._bm25_index = None
        self._node_texts: Dict[int, str] = {}
        self._node_ids: List[int] = []
        self._tokenized_corpus: List[List[str]] = []
        self._forest_hash: Optional[int] = None

    async def retrieve(
        self,
        query: str,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        top_k: int = 10,
        **kwargs,
    ) -> List[RetrievedChunk]:
        """Retrieve using BM25 + dense hybrid."""
        # Ensure BM25 index is built (rebuild if forest changed)
        self._ensure_bm25_index(forest)

        if not self._bm25_index:
            # Fall back to dense only if BM25 not available
            return await self.search_trees(query, forest, top_k)

        # Get BM25 results
        bm25_results = self._bm25_search(query, forest, top_k * 2)

        # Get dense results
        dense_results = await self.search_trees(query, forest, top_k * 2)

        # Combine results with reciprocal rank fusion
        combined = self._reciprocal_rank_fusion(
            bm25_results,
            dense_results,
        )

        return combined[:top_k]

    def _get_forest_hash(self, forest: "TreeForest") -> int:
        """Get a hash to detect if forest has changed."""
        total_nodes = sum(
            len(tree.all_nodes)
            for tree in forest.trees.values()
            if hasattr(tree, "all_nodes")
        )
        return hash((tuple(forest.trees.keys()), total_nodes))

    def _ensure_bm25_index(self, forest: "TreeForest") -> None:
        """Build BM25 index if not already built or if forest changed."""
        current_hash = self._get_forest_hash(forest)
        if self._bm25_index is not None and self._forest_hash == current_hash:
            return

        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.warning("rank_bm25 not installed, BM25 hybrid disabled")
            return

        # Collect all node texts
        self._node_texts = {}
        self._node_ids = []
        self._tokenized_corpus = []

        for tree in forest.trees.values():
            if not hasattr(tree, "all_nodes"):
                continue
            for node_id, node in tree.all_nodes.items():
                text = getattr(node, "text", "") or getattr(node, "content", "")
                if text:
                    self._node_texts[node_id] = text
                    self._node_ids.append(node_id)
                    # Simple tokenization
                    tokens = text.lower().split()
                    self._tokenized_corpus.append(tokens)

        if self._tokenized_corpus:
            self._bm25_index = BM25Okapi(self._tokenized_corpus)
            self._forest_hash = current_hash
            logger.info(f"BM25 index built with {len(self._tokenized_corpus)} documents")
        else:
            logger.warning("No documents found for BM25 index")

    def _bm25_search(
        self, query: str, forest: "TreeForest", top_k: int
    ) -> List[RetrievedChunk]:
        """Search using BM25."""
        if not self._bm25_index:
            return []

        # Tokenize query
        query_tokens = query.lower().split()

        # Get BM25 scores
        scores = self._bm25_index.get_scores(query_tokens)

        # Get top-k indices
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
            :top_k
        ]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue

            node_id = self._node_ids[idx]
            text = self._node_texts[node_id]

            # Normalize BM25 score to [0, 1]
            max_score = max(scores) if max(scores) > 0 else 1
            normalized_score = scores[idx] / max_score

            results.append(
                RetrievedChunk(
                    node_id=node_id,
                    text=text,
                    score=normalized_score,
                    importance=0.5,
                    strategy=self.name,
                )
            )

        return results

    def _reciprocal_rank_fusion(
        self,
        bm25_results: List[RetrievedChunk],
        dense_results: List[RetrievedChunk],
        k: int = 60,
    ) -> List[RetrievedChunk]:
        """
        Combine results using Reciprocal Rank Fusion.

        RRF score = sum(1 / (k + rank)) for each result list
        """
        scores: Dict[int, float] = {}
        chunks: Dict[int, RetrievedChunk] = {}

        # Score BM25 results
        for rank, chunk in enumerate(bm25_results):
            rrf_score = self.bm25_weight / (k + rank + 1)
            scores[chunk.node_id] = scores.get(chunk.node_id, 0) + rrf_score
            if chunk.node_id not in chunks:
                chunks[chunk.node_id] = chunk

        # Score dense results
        for rank, chunk in enumerate(dense_results):
            rrf_score = self.dense_weight / (k + rank + 1)
            scores[chunk.node_id] = scores.get(chunk.node_id, 0) + rrf_score
            if chunk.node_id not in chunks:
                chunks[chunk.node_id] = chunk

        # Update chunk scores and sort
        for node_id, chunk in chunks.items():
            chunk.score = scores[node_id]

        return sorted(chunks.values(), key=lambda c: c.score, reverse=True)
