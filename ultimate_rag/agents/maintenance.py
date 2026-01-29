"""
Knowledge Base Maintenance Agent

Proactively maintains the knowledge base:
- Detects stale content
- Identifies knowledge gaps
- Finds contradictions
- Suggests improvements
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..core.node import KnowledgeNode, KnowledgeTree, TreeForest
    from ..graph.graph import KnowledgeGraph
    from .observations import ObservationCollector

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeGap:
    """A detected gap in the knowledge base."""

    gap_id: str
    description: str
    frequency: int  # How many times this gap was hit
    example_queries: List[str]
    suggested_sources: List[str]
    affected_topics: List[str]
    detected_at: datetime
    priority: float  # 0-1, based on frequency and impact

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "description": self.description,
            "frequency": self.frequency,
            "example_queries": self.example_queries,
            "suggested_sources": self.suggested_sources,
            "affected_topics": self.affected_topics,
            "detected_at": self.detected_at.isoformat(),
            "priority": self.priority,
        }


@dataclass
class Contradiction:
    """A detected contradiction between knowledge nodes."""

    contradiction_id: str
    node_ids: List[int]
    description: str
    field: Optional[str]  # Which aspect contradicts
    detected_at: datetime
    severity: str  # low, medium, high
    suggested_resolution: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "node_ids": self.node_ids,
            "description": self.description,
            "field": self.field,
            "detected_at": self.detected_at.isoformat(),
            "severity": self.severity,
            "suggested_resolution": self.suggested_resolution,
        }


class MaintenanceTaskType(str, Enum):
    """Types of maintenance tasks."""

    REFRESH_STALE = "refresh_stale"
    FILL_GAP = "fill_gap"
    RESOLVE_CONTRADICTION = "resolve_contradiction"
    MERGE_DUPLICATES = "merge_duplicates"
    UPDATE_IMPORTANCE = "update_importance"
    ARCHIVE_LOW_VALUE = "archive_low_value"
    VALIDATE_SOURCES = "validate_sources"
    EXTRACT_ENTITIES = "extract_entities"


@dataclass
class MaintenanceTask:
    """A maintenance task for the knowledge base."""

    task_id: str
    task_type: MaintenanceTaskType
    description: str
    priority: float  # 0-1
    target_nodes: List[int]
    target_entities: List[str]
    created_at: datetime
    status: str = "pending"  # pending, in_progress, completed, failed
    completed_at: Optional[datetime] = None
    result: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "description": self.description,
            "priority": self.priority,
            "target_nodes": self.target_nodes,
            "target_entities": self.target_entities,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "result": self.result,
        }


class MaintenanceAgent:
    """
    Background agent that keeps the knowledge base healthy.

    Runs periodic maintenance cycles to:
    - Detect and flag stale content
    - Identify knowledge gaps from failed queries
    - Find contradictions between nodes
    - Suggest node merges for duplicates
    - Update importance scores
    - Archive low-value content
    """

    def __init__(
        self,
        forest: "TreeForest",
        graph: Optional["KnowledgeGraph"] = None,
        observation_collector: Optional["ObservationCollector"] = None,
        stale_threshold_days: int = 90,
        low_value_threshold: float = 0.1,
        gap_detection_min_frequency: int = 3,
    ):
        self.forest = forest
        self.graph = graph
        self.observations = observation_collector

        # Configuration
        self.stale_threshold_days = stale_threshold_days
        self.low_value_threshold = low_value_threshold
        self.gap_detection_min_frequency = gap_detection_min_frequency

        # Task queue
        self._tasks: List[MaintenanceTask] = []
        self._completed_tasks: List[MaintenanceTask] = []

        # Detected issues
        self._gaps: Dict[str, KnowledgeGap] = {}
        self._contradictions: Dict[str, Contradiction] = {}

        # Stats
        self._last_run: Optional[datetime] = None
        self._run_count = 0

    async def run_maintenance_cycle(self) -> Dict[str, Any]:
        """
        Run a full maintenance cycle.

        Returns summary of actions taken.
        """
        self._run_count += 1
        self._last_run = datetime.utcnow()

        logger.info(f"Starting maintenance cycle #{self._run_count}")

        results = {
            "cycle": self._run_count,
            "started_at": self._last_run.isoformat(),
            "stale_detected": 0,
            "gaps_detected": 0,
            "contradictions_detected": 0,
            "duplicates_detected": 0,
            "tasks_created": 0,
        }

        # 1. Detect stale content
        stale_nodes = await self.detect_stale_content()
        results["stale_detected"] = len(stale_nodes)
        for node in stale_nodes:
            await self._create_refresh_task(node)

        # 2. Analyze query logs for gaps
        if self.observations:
            gaps = await self.analyze_query_logs_for_gaps()
            results["gaps_detected"] = len(gaps)
            for gap in gaps:
                await self._create_gap_task(gap)

        # 3. Detect contradictions
        contradictions = await self.find_contradictions()
        results["contradictions_detected"] = len(contradictions)

        # 4. Find near-duplicates
        duplicates = await self.find_near_duplicates()
        results["duplicates_detected"] = len(duplicates)

        # 5. Update importance scores
        await self.recalculate_importance_scores()

        # 6. Archive low-value content
        archived = await self.archive_low_value_nodes()
        results["archived"] = len(archived)

        results["tasks_created"] = len(self._tasks)
        results["completed_at"] = datetime.utcnow().isoformat()

        logger.info(
            f"Maintenance cycle #{self._run_count} complete: "
            f"stale={results['stale_detected']}, gaps={results['gaps_detected']}, "
            f"contradictions={results['contradictions_detected']}"
        )

        return results

    # ==================== Detection Methods ====================

    async def detect_stale_content(self) -> List["KnowledgeNode"]:
        """
        Find nodes that haven't been validated recently.
        """
        stale_nodes = []
        cutoff = datetime.utcnow() - timedelta(days=self.stale_threshold_days)

        for tree in self.forest.trees.values():
            for node in tree.all_nodes.values():
                if not node.is_active:
                    continue

                # Check validation date
                if node.metadata and node.metadata.validated_at:
                    if node.metadata.validated_at < cutoff:
                        stale_nodes.append(node)
                elif node.importance.last_validated:
                    if node.importance.last_validated < cutoff:
                        stale_nodes.append(node)
                else:
                    # Never validated
                    if node.importance.created_at < cutoff:
                        stale_nodes.append(node)

        logger.info(f"Detected {len(stale_nodes)} stale nodes")
        return stale_nodes

    async def analyze_query_logs_for_gaps(
        self,
        days: int = 7,
    ) -> List[KnowledgeGap]:
        """
        Analyze failed queries to identify knowledge gaps.

        Uses semantic clustering with embeddings to find patterns.
        """
        if not self.observations:
            return []

        failed_queries = self.observations.get_recent_failures(days=days)

        if len(failed_queries) < self.gap_detection_min_frequency:
            return []

        # Use semantic clustering with embeddings
        clusters = await self._cluster_queries_by_embedding(failed_queries)

        # Convert clusters to gaps
        gaps = []
        import uuid

        for cluster_queries in clusters:
            if len(cluster_queries) >= self.gap_detection_min_frequency:
                # Extract common topics from the cluster
                all_words: Dict[str, int] = {}
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
                    "when",
                    "where",
                    "can",
                    "could",
                    "would",
                    "should",
                    "does",
                    "did",
                    "are",
                    "was",
                    "were",
                    "be",
                    "been",
                    "being",
                }
                for obs in cluster_queries:
                    words = set(obs.query.lower().split()) - stop_words
                    for word in words:
                        all_words[word] = all_words.get(word, 0) + 1

                # Get top keywords that appear in most queries
                sorted_words = sorted(
                    all_words.items(), key=lambda x: x[1], reverse=True
                )
                top_topics = [w[0] for w in sorted_words[:5] if w[1] >= 2]

                if not top_topics:
                    top_topics = [w[0] for w in sorted_words[:3]]

                description = f"Missing knowledge about: {', '.join(top_topics)}"

                gap = KnowledgeGap(
                    gap_id=str(uuid.uuid4()),
                    description=description,
                    frequency=len(cluster_queries),
                    example_queries=[obs.query for obs in cluster_queries[:5]],
                    suggested_sources=[],
                    affected_topics=top_topics,
                    detected_at=datetime.utcnow(),
                    priority=min(1.0, len(cluster_queries) / 10),
                )
                gaps.append(gap)
                self._gaps[gap.gap_id] = gap

        logger.info(f"Detected {len(gaps)} knowledge gaps")
        return gaps

    async def _cluster_queries_by_embedding(
        self,
        failed_queries: List[Any],
        similarity_threshold: float = 0.7,
    ) -> List[List[Any]]:
        """
        Cluster failed queries using embedding similarity.

        Uses agglomerative clustering based on cosine similarity.
        """
        if not failed_queries:
            return []

        try:
            from knowledge_base.raptor.EmbeddingModels import OpenAIEmbeddingModel
            from knowledge_base.raptor.utils import distances_from_embeddings
        except ImportError as e:
            logger.warning(
                f"RAPTOR imports failed, falling back to keyword clustering: {e}"
            )
            return self._fallback_keyword_clustering(failed_queries)

        # Get embeddings for all queries
        embedding_model = OpenAIEmbeddingModel()
        queries = [obs.query for obs in failed_queries]

        try:
            embeddings = [embedding_model.create_embedding(q) for q in queries]
        except Exception as e:
            logger.warning(f"Embedding failed, falling back to keyword clustering: {e}")
            return self._fallback_keyword_clustering(failed_queries)

        # Simple agglomerative clustering
        clusters: List[List[int]] = []  # List of query indices per cluster
        assigned = set()

        for i in range(len(failed_queries)):
            if i in assigned:
                continue

            # Start a new cluster with this query
            cluster = [i]
            assigned.add(i)

            # Find similar queries
            query_embedding = embeddings[i]
            other_embeddings = []
            other_indices = []

            for j in range(len(failed_queries)):
                if j not in assigned:
                    other_embeddings.append(embeddings[j])
                    other_indices.append(j)

            if other_embeddings:
                distances = distances_from_embeddings(
                    query_embedding, other_embeddings, distance_metric="cosine"
                )

                for idx, distance in enumerate(distances):
                    similarity = 1.0 - distance
                    if similarity >= similarity_threshold:
                        j = other_indices[idx]
                        cluster.append(j)
                        assigned.add(j)

            clusters.append(cluster)

        # Convert indices back to observation objects
        return [[failed_queries[i] for i in cluster] for cluster in clusters]

    def _fallback_keyword_clustering(
        self,
        failed_queries: List[Any],
    ) -> List[List[Any]]:
        """
        Fallback clustering using keyword overlap when embeddings unavailable.
        """
        clusters: Dict[str, List] = {}
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
            "when",
            "where",
            "can",
            "could",
            "would",
            "should",
        }

        for obs in failed_queries:
            words = set(obs.query.lower().split()) - stop_words
            cluster_key = "_".join(sorted(list(words)[:3]))
            if cluster_key not in clusters:
                clusters[cluster_key] = []
            clusters[cluster_key].append(obs)

        return list(clusters.values())

    async def find_contradictions(self) -> List[Contradiction]:
        """
        Find potential contradictions between nodes.

        Uses multiple approaches:
        1. Observation-reported contradictions
        2. LLM-based semantic contradiction detection on similar nodes
        """
        contradictions = []
        import uuid

        # 1. Check observation-reported contradictions
        if self.observations:
            quality_issues = self.observations.get_quality_issues()
            for obs in quality_issues:
                if obs.contradicting_nodes and len(obs.contradicting_nodes) >= 2:
                    contradiction = Contradiction(
                        contradiction_id=str(uuid.uuid4()),
                        node_ids=obs.contradicting_nodes,
                        description=obs.contradiction_description
                        or "Reported by agent",
                        field=None,
                        detected_at=datetime.utcnow(),
                        severity="medium",
                    )
                    contradictions.append(contradiction)
                    self._contradictions[contradiction.contradiction_id] = contradiction

        # 2. Active LLM-based contradiction detection on similar nodes
        similar_pairs = await self._find_similar_node_pairs(similarity_threshold=0.7)

        for node1, node2, similarity in similar_pairs[:20]:  # Limit LLM calls
            is_contradiction, description = await self._llm_check_contradiction(
                node1.text, node2.text
            )
            if is_contradiction:
                contradiction = Contradiction(
                    contradiction_id=str(uuid.uuid4()),
                    node_ids=[node1.index, node2.index],
                    description=description,
                    field=None,
                    detected_at=datetime.utcnow(),
                    severity="medium" if similarity < 0.85 else "high",
                    suggested_resolution="Review both nodes and determine which is correct",
                )
                contradictions.append(contradiction)
                self._contradictions[contradiction.contradiction_id] = contradiction

        logger.info(f"Detected {len(contradictions)} contradictions")
        return contradictions

    async def _find_similar_node_pairs(
        self,
        similarity_threshold: float = 0.7,
    ) -> List[tuple]:
        """Find pairs of nodes with high semantic similarity that might contradict."""
        try:
            from knowledge_base.raptor.EmbeddingModels import OpenAIEmbeddingModel
            from knowledge_base.raptor.utils import distances_from_embeddings
        except ImportError:
            logger.warning("RAPTOR not available for similarity detection")
            return []

        pairs = []

        for tree in self.forest.trees.values():
            nodes = [n for n in tree.all_nodes.values() if n.is_active]
            if len(nodes) < 2:
                continue

            # Get embeddings
            embedding_key = getattr(tree, "embedding_model", "OpenAI") or "OpenAI"
            embeddings = []
            valid_nodes = []

            for node in nodes:
                emb = node.embeddings.get(embedding_key)
                if emb:
                    embeddings.append(emb)
                    valid_nodes.append(node)

            if len(embeddings) < 2:
                continue

            # Find similar pairs
            for i in range(len(valid_nodes)):
                if len(pairs) >= 50:  # Limit total pairs
                    break

                other_embeddings = embeddings[i + 1 :]
                if not other_embeddings:
                    continue

                try:
                    distances = distances_from_embeddings(
                        embeddings[i], other_embeddings, distance_metric="cosine"
                    )

                    for j, dist in enumerate(distances):
                        similarity = 1.0 - dist
                        # Look for nodes that are similar but not identical
                        if similarity_threshold <= similarity < 0.95:
                            pairs.append(
                                (valid_nodes[i], valid_nodes[i + 1 + j], similarity)
                            )
                except Exception as e:
                    logger.debug(f"Similarity calculation failed: {e}")

        # Sort by similarity descending
        pairs.sort(key=lambda x: x[2], reverse=True)
        return pairs

    async def _llm_check_contradiction(
        self,
        text1: str,
        text2: str,
    ) -> tuple:
        """
        Use LLM to check if two texts contradict each other.

        Returns (is_contradiction: bool, description: str)
        """
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI()

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.0,
                max_tokens=150,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert at detecting contradictions in technical documentation.

Analyze whether two pieces of text make contradictory claims.

Respond with JSON:
{
  "contradicts": true or false,
  "description": "brief description of the contradiction if found"
}

Examples of contradictions:
- Different values for same configuration
- Opposite instructions for same procedure
- Conflicting requirements or constraints
- One says "always" while other says "never"

NOT contradictions:
- Different topics entirely
- Complementary information
- Different levels of detail""",
                    },
                    {
                        "role": "user",
                        "content": f"Text 1:\n{text1[:500]}\n\nText 2:\n{text2[:500]}",
                    },
                ],
            )

            import json

            content = response.choices[0].message.content.strip()
            data = json.loads(content)

            return (
                data.get("contradicts", False),
                data.get("description", "Potential contradiction detected"),
            )

        except Exception as e:
            logger.debug(f"LLM contradiction check failed: {e}")
            return (False, "")

    async def find_near_duplicates(
        self,
        similarity_threshold: float = 0.9,
    ) -> List[List[int]]:
        """
        Find groups of near-duplicate nodes.
        """
        # Group by content hash first
        duplicates = []

        for tree in self.forest.trees.values():
            hash_groups: Dict[str, List[int]] = {}

            for node in tree.all_nodes.values():
                if not node.is_active:
                    continue

                h = node.content_hash
                if h not in hash_groups:
                    hash_groups[h] = []
                hash_groups[h].append(node.index)

            # Report groups with more than one node
            for node_ids in hash_groups.values():
                if len(node_ids) > 1:
                    duplicates.append(node_ids)

        logger.info(f"Detected {len(duplicates)} duplicate groups")
        return duplicates

    async def recalculate_importance_scores(self) -> None:
        """
        Recalculate importance scores for all nodes.

        Uses observation data to adjust scores.
        """
        if not self.observations:
            return

        for tree in self.forest.trees.values():
            for node in tree.all_nodes.values():
                if not node.is_active:
                    continue

                # Get observation-based success rate
                success_rate = self.observations.get_node_success_rate(node.index)

                # Adjust importance based on observations
                if success_rate > 0.8:
                    node.importance.add_contextual_boost("high_success_rate", 0.1)
                elif success_rate < 0.3:
                    node.importance.add_contextual_boost("low_success_rate", -0.1)

        logger.info("Recalculated importance scores")

    async def archive_low_value_nodes(self) -> List[int]:
        """
        Archive nodes with very low importance and no recent activity.
        """
        archived = []
        cutoff = datetime.utcnow() - timedelta(days=180)

        for tree in self.forest.trees.values():
            for node in tree.all_nodes.values():
                if not node.is_active:
                    continue

                importance = node.get_importance()

                # Check if low value and not accessed recently
                if importance < self.low_value_threshold:
                    last_access = node.importance.last_accessed
                    if not last_access or last_access < cutoff:
                        # Archive (don't delete, just mark)
                        if node.metadata:
                            node.metadata.archived_at = datetime.utcnow()
                        archived.append(node.index)

        if archived:
            logger.info(f"Archived {len(archived)} low-value nodes")

        return archived

    # ==================== Task Management ====================

    async def _create_refresh_task(self, node: "KnowledgeNode") -> MaintenanceTask:
        """Create a task to refresh stale content."""
        import uuid

        task = MaintenanceTask(
            task_id=str(uuid.uuid4()),
            task_type=MaintenanceTaskType.REFRESH_STALE,
            description=f"Refresh stale node {node.index}: {node.text[:50]}...",
            priority=node.get_importance(),
            target_nodes=[node.index],
            target_entities=[],
            created_at=datetime.utcnow(),
        )
        self._tasks.append(task)
        return task

    async def _create_gap_task(self, gap: KnowledgeGap) -> MaintenanceTask:
        """Create a task to fill a knowledge gap."""
        import uuid

        task = MaintenanceTask(
            task_id=str(uuid.uuid4()),
            task_type=MaintenanceTaskType.FILL_GAP,
            description=gap.description,
            priority=gap.priority,
            target_nodes=[],
            target_entities=gap.affected_topics,
            created_at=datetime.utcnow(),
        )
        self._tasks.append(task)
        return task

    def get_pending_tasks(
        self,
        task_type: Optional[MaintenanceTaskType] = None,
    ) -> List[MaintenanceTask]:
        """Get pending maintenance tasks."""
        tasks = [t for t in self._tasks if t.status == "pending"]
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        return sorted(tasks, key=lambda t: t.priority, reverse=True)

    async def complete_task(
        self,
        task_id: str,
        success: bool,
        result: str,
    ) -> None:
        """Mark a task as completed."""
        for task in self._tasks:
            if task.task_id == task_id:
                task.status = "completed" if success else "failed"
                task.completed_at = datetime.utcnow()
                task.result = result
                self._completed_tasks.append(task)
                self._tasks.remove(task)
                break

    # ==================== Reporting ====================

    def get_health_report(self) -> Dict[str, Any]:
        """Get a health report of the knowledge base."""
        total_nodes = sum(len(t.all_nodes) for t in self.forest.trees.values())
        active_nodes = sum(
            len([n for n in t.all_nodes.values() if n.is_active])
            for t in self.forest.trees.values()
        )

        return {
            "total_nodes": total_nodes,
            "active_nodes": active_nodes,
            "stale_count": len([g for g in self._gaps.values()]),
            "gap_count": len(self._gaps),
            "contradiction_count": len(self._contradictions),
            "pending_tasks": len([t for t in self._tasks if t.status == "pending"]),
            "completed_tasks": len(self._completed_tasks),
            "last_maintenance_run": (
                self._last_run.isoformat() if self._last_run else None
            ),
            "maintenance_runs": self._run_count,
        }

    def get_gaps(self) -> List[KnowledgeGap]:
        """Get all detected knowledge gaps."""
        return list(self._gaps.values())

    def get_contradictions(self) -> List[Contradiction]:
        """Get all detected contradictions."""
        return list(self._contradictions.values())

    def get_stats(self) -> Dict[str, Any]:
        """Get maintenance agent statistics."""
        return {
            "run_count": self._run_count,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "gaps_detected": len(self._gaps),
            "contradictions_detected": len(self._contradictions),
            "pending_tasks": len([t for t in self._tasks if t.status == "pending"]),
            "completed_tasks": len(self._completed_tasks),
        }
