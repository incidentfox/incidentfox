"""
Teaching Interface

Allows agents to teach the knowledge base new information
learned during their work.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ..core.node import KnowledgeNode, KnowledgeTree
    from ..graph.graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class TeachStatus(str, Enum):
    """Status of a teaching request."""

    CREATED = "created"  # New knowledge created
    MERGED = "merged"  # Merged with existing similar knowledge
    DUPLICATE = "duplicate"  # Exact duplicate, skipped
    CONTRADICTION = "contradiction"  # Conflicts with existing, needs review
    PENDING_REVIEW = "pending_review"  # Queued for human review
    REJECTED = "rejected"  # Rejected by quality check


@dataclass
class TeachResult:
    """Result of a teaching request."""

    status: TeachStatus
    node_id: Optional[int] = None  # Created/affected node ID
    existing_nodes: List[int] = field(default_factory=list)  # Related existing nodes
    action: str = ""  # Description of action taken
    confidence: float = 0.5  # Confidence in the teaching
    needs_review: bool = False
    review_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "node_id": self.node_id,
            "existing_nodes": self.existing_nodes,
            "action": self.action,
            "confidence": self.confidence,
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
        }


@dataclass
class PendingTeaching:
    """A teaching request pending human review."""

    teaching_id: str
    content: str
    knowledge_type: str
    source: str
    confidence: float
    learned_from: str
    related_entities: List[str]
    submitted_at: datetime
    submitted_by: str  # Agent ID
    task_context: Optional[str] = None  # What task led to this learning
    review_notes: Optional[str] = None


class TeachingInterface:
    """
    Interface for agents to teach the knowledge base.

    Handles:
    - Duplicate detection
    - Contradiction detection
    - Quality gating
    - Entity extraction and linking
    """

    def __init__(
        self,
        tree: "KnowledgeTree",
        graph: Optional["KnowledgeGraph"] = None,
        embedder=None,
        similarity_threshold: float = 0.85,
        auto_approve_threshold: float = 0.9,
    ):
        self.tree = tree
        self.graph = graph
        self.embedder = embedder
        self.similarity_threshold = similarity_threshold
        self.auto_approve_threshold = auto_approve_threshold

        # Pending teachings queue
        self._pending: Dict[str, PendingTeaching] = {}

        # Stats
        self._stats = {
            "total_teachings": 0,
            "created": 0,
            "merged": 0,
            "duplicates": 0,
            "contradictions": 0,
            "pending_review": 0,
            "rejected": 0,
        }

    async def teach(
        self,
        content: str,
        knowledge_type: str,
        source: str,
        confidence: float = 0.5,
        related_entities: Optional[List[str]] = None,
        learned_from: str = "agent",
        agent_id: Optional[str] = None,
        task_context: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TeachResult:
        """
        Agent teaches the KB new knowledge.

        Args:
            content: The new knowledge content
            knowledge_type: Type of knowledge (procedural, factual, etc.)
            source: Where this knowledge came from
            confidence: How confident the agent is (0-1)
            related_entities: Entity IDs this relates to
            learned_from: Context of learning (incident_resolution, user_correction, etc.)
            agent_id: Which agent is teaching
            task_context: Description of what task led to this learning
            metadata: Additional metadata

        Returns:
            TeachResult with status and details
        """
        self._stats["total_teachings"] += 1
        related_entities = related_entities or []

        # 1. Content validation
        content = content.strip()
        if not content or len(content) < 20:
            self._stats["rejected"] += 1
            return TeachResult(
                status=TeachStatus.REJECTED,
                action="Content too short or empty",
                confidence=0.0,
            )

        # 2. Check for duplicates
        content_hash = self._compute_hash(content)
        similar_nodes = self.tree.find_similar_nodes(content_hash)

        if similar_nodes:
            # Exact duplicate
            self._stats["duplicates"] += 1
            return TeachResult(
                status=TeachStatus.DUPLICATE,
                existing_nodes=[n.index for n in similar_nodes],
                action="Exact duplicate found",
                confidence=confidence,
            )

        # 3. Check for semantic similarity (if embedder available)
        if self.embedder:
            similar = await self._find_semantically_similar(content)
            if similar:
                similarity_score, similar_node = similar[0]

                if similarity_score >= 0.95:
                    # Near-duplicate
                    self._stats["duplicates"] += 1
                    return TeachResult(
                        status=TeachStatus.DUPLICATE,
                        existing_nodes=[similar_node.index],
                        action=f"Near-duplicate found (similarity: {similarity_score:.2f})",
                        confidence=confidence,
                    )

                if similarity_score >= self.similarity_threshold:
                    # Check for contradiction
                    is_contradiction = await self._check_contradiction(
                        content, similar_node
                    )

                    if is_contradiction:
                        self._stats["contradictions"] += 1
                        await self._queue_for_review(
                            content=content,
                            knowledge_type=knowledge_type,
                            source=source,
                            confidence=confidence,
                            learned_from=learned_from,
                            related_entities=related_entities,
                            agent_id=agent_id,
                            task_context=task_context,
                            review_reason=f"Contradicts node {similar_node.index}",
                        )
                        return TeachResult(
                            status=TeachStatus.CONTRADICTION,
                            existing_nodes=[similar_node.index],
                            action="Queued for review due to potential contradiction",
                            needs_review=True,
                            review_reason="May contradict existing knowledge",
                            confidence=confidence,
                        )

                    # Merge opportunity
                    merge_result = await self._merge_with_existing(
                        content, similar_node, metadata
                    )
                    if merge_result:
                        self._stats["merged"] += 1
                        return TeachResult(
                            status=TeachStatus.MERGED,
                            node_id=similar_node.index,
                            existing_nodes=[similar_node.index],
                            action="Merged with existing similar knowledge",
                            confidence=confidence,
                        )

        # 4. Quality check
        if confidence < self.auto_approve_threshold:
            # Queue for human review
            self._stats["pending_review"] += 1
            teaching_id = await self._queue_for_review(
                content=content,
                knowledge_type=knowledge_type,
                source=source,
                confidence=confidence,
                learned_from=learned_from,
                related_entities=related_entities,
                agent_id=agent_id,
                task_context=task_context,
                review_reason="Confidence below auto-approve threshold",
            )
            return TeachResult(
                status=TeachStatus.PENDING_REVIEW,
                action=f"Queued for review (teaching_id: {teaching_id})",
                needs_review=True,
                review_reason=f"Confidence ({confidence:.2f}) below threshold",
                confidence=confidence,
            )

        # 5. Create new node
        node = await self._create_node(
            content=content,
            knowledge_type=knowledge_type,
            source=source,
            confidence=confidence,
            learned_from=learned_from,
            related_entities=related_entities,
            metadata=metadata,
        )

        self._stats["created"] += 1
        logger.info(
            f"Created new knowledge node {node.index} from agent teaching "
            f"(type={knowledge_type}, confidence={confidence:.2f})"
        )

        return TeachResult(
            status=TeachStatus.CREATED,
            node_id=node.index,
            action="Created new knowledge node",
            confidence=confidence,
        )

    async def teach_from_correction(
        self,
        original_query: str,
        original_answer: str,
        correct_answer: str,
        corrected_by: str = "user",
        related_nodes: Optional[List[int]] = None,
    ) -> TeachResult:
        """
        Learn from a user correction.

        This is a high-confidence learning opportunity since
        we have direct user feedback.
        """
        # Build content from correction
        content = f"Correction: For the question '{original_query}', "
        content += f"the correct answer is: {correct_answer}"

        # Demote nodes that gave wrong answer
        if related_nodes:
            for node_id in related_nodes:
                node = self.tree.get_node(node_id)
                if node:
                    node.importance.record_feedback(positive=False)

        return await self.teach(
            content=correct_answer,
            knowledge_type="factual",
            source=f"user_correction:{corrected_by}",
            confidence=0.85,  # High confidence from user correction
            learned_from="user_correction",
            task_context=f"Corrected answer for: {original_query}",
        )

    async def teach_from_incident(
        self,
        incident_id: str,
        symptoms: str,
        root_cause: str,
        resolution: str,
        services_affected: Optional[List[str]] = None,
    ) -> TeachResult:
        """
        Learn from incident resolution.

        Creates knowledge about symptoms, causes, and resolutions.
        """
        content = f"""
Incident Resolution:

Symptoms: {symptoms}

Root Cause: {root_cause}

Resolution: {resolution}
"""
        if services_affected:
            content += f"\nServices Affected: {', '.join(services_affected)}"

        return await self.teach(
            content=content.strip(),
            knowledge_type="temporal",  # Incident knowledge
            source=f"incident:{incident_id}",
            confidence=0.9,  # High confidence from actual resolution
            related_entities=services_affected or [],
            learned_from="incident_resolution",
            task_context=f"Resolution of incident {incident_id}",
        )

    # ==================== Internal Methods ====================

    def _compute_hash(self, content: str) -> str:
        """Compute content hash for deduplication."""
        normalized = content.strip().lower()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    async def _find_semantically_similar(
        self,
        content: str,
        top_k: int = 5,
    ) -> List[tuple]:
        """Find semantically similar nodes using embeddings."""
        if not self.embedder:
            return []

        # Embed the content
        content_embedding = self.embedder.create_embedding(content)

        # Search tree
        # This is a simplified version - in production, use vector DB
        import numpy as np

        results = []
        for node in self.tree.all_nodes.values():
            node_emb = node.get_embedding()
            if node_emb:
                # Cosine similarity
                sim = np.dot(content_embedding, node_emb) / (
                    np.linalg.norm(content_embedding) * np.linalg.norm(node_emb) + 1e-9
                )
                if sim >= self.similarity_threshold:
                    results.append((float(sim), node))

        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]

    async def _check_contradiction(
        self,
        content: str,
        existing_node: "KnowledgeNode",
    ) -> bool:
        """
        Check if new content contradicts existing knowledge.

        This is a simplified check - in production, use NLI model
        or LLM to detect contradictions.
        """
        # Simple heuristic: check for negation words near similar content
        negation_indicators = [
            "not",
            "don't",
            "doesn't",
            "shouldn't",
            "never",
            "incorrect",
            "wrong",
            "false",
            "outdated",
            "deprecated",
        ]

        content_lower = content.lower()
        existing_lower = existing_node.text.lower()

        # If content has negations about similar topics, might be contradiction
        for neg in negation_indicators:
            if neg in content_lower:
                # Very basic check - in production use proper NLI
                return True

        return False

    async def _merge_with_existing(
        self,
        content: str,
        existing_node: "KnowledgeNode",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Attempt to merge new content with existing node.

        Returns True if merged, False if should create new.
        """
        # For now, just boost the existing node's importance
        # In production, could merge text or add as child node
        existing_node.importance.record_feedback(positive=True)
        existing_node.importance.citation_count += 1

        logger.info(
            f"Merged teaching with existing node {existing_node.index} "
            f"(boosted importance)"
        )

        return True

    async def _queue_for_review(
        self,
        content: str,
        knowledge_type: str,
        source: str,
        confidence: float,
        learned_from: str,
        related_entities: List[str],
        agent_id: Optional[str],
        task_context: Optional[str],
        review_reason: str,
    ) -> str:
        """Queue a teaching request for human review."""
        teaching_id = str(uuid.uuid4())

        pending = PendingTeaching(
            teaching_id=teaching_id,
            content=content,
            knowledge_type=knowledge_type,
            source=source,
            confidence=confidence,
            learned_from=learned_from,
            related_entities=related_entities,
            submitted_at=datetime.utcnow(),
            submitted_by=agent_id or "unknown",
            task_context=task_context,
            review_notes=review_reason,
        )

        self._pending[teaching_id] = pending

        logger.info(f"Queued teaching {teaching_id} for review: {review_reason}")

        return teaching_id

    async def _create_node(
        self,
        content: str,
        knowledge_type: str,
        source: str,
        confidence: float,
        learned_from: str,
        related_entities: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "KnowledgeNode":
        """Create a new knowledge node."""
        # Import here to avoid circular deps
        from ..core.metadata import NodeMetadata, SourceInfo, ValidationStatus
        from ..core.node import KnowledgeNode
        from ..core.types import ImportanceScore, KnowledgeType

        # Generate new index
        max_index = max(self.tree.all_nodes.keys()) if self.tree.all_nodes else -1
        new_index = max_index + 1

        # Create source info
        source_info = SourceInfo(
            source_type="agent_teaching",
            source_url=source if source.startswith("http") else None,
            source_id=source,
        )

        # Create metadata
        node_metadata = NodeMetadata(
            node_id=new_index,
            tree_id=self.tree.tree_id,
            layer=0,  # Leaf node
            knowledge_type=knowledge_type,
            source=source_info,
            validation_status=ValidationStatus.PROVISIONAL,
            confidence=confidence,
            learned_from=learned_from,
            learning_context={
                "related_entities": related_entities,
                **(metadata or {}),
            },
        )

        # Create importance score
        importance = ImportanceScore(
            explicit_priority=confidence * 0.5,  # Start lower, let it prove itself
            authority_score=0.3,  # Agent-learned starts with lower authority
        )

        # Create node
        node = KnowledgeNode(
            text=content,
            index=new_index,
            layer=0,
            knowledge_type=KnowledgeType.from_string(knowledge_type),
            importance=importance,
            metadata=node_metadata,
            source_url=source if source.startswith("http") else None,
            tree_id=self.tree.tree_id,
        )

        # Create embedding if embedder available
        if self.embedder:
            embedding = self.embedder.create_embedding(content)
            node.set_embedding("OpenAI", embedding)

        # Add to tree
        self.tree.add_node(node)

        # Link to graph entities
        if self.graph and related_entities:
            for entity_id in related_entities:
                entity = self.graph.get_entity(entity_id)
                if entity:
                    entity.add_node_reference(new_index, self.tree.tree_id)

        return node

    # ==================== Review Management ====================

    def get_pending_reviews(self) -> List[PendingTeaching]:
        """Get all pending teaching reviews."""
        return list(self._pending.values())

    async def approve_teaching(
        self,
        teaching_id: str,
        reviewer: str,
        notes: Optional[str] = None,
    ) -> TeachResult:
        """Approve a pending teaching."""
        if teaching_id not in self._pending:
            return TeachResult(
                status=TeachStatus.REJECTED,
                action="Teaching not found",
            )

        pending = self._pending.pop(teaching_id)

        # Create the node with high confidence since human-approved
        node = await self._create_node(
            content=pending.content,
            knowledge_type=pending.knowledge_type,
            source=pending.source,
            confidence=0.9,  # High confidence after approval
            learned_from=pending.learned_from,
            related_entities=pending.related_entities,
            metadata={
                "approved_by": reviewer,
                "approved_at": datetime.utcnow().isoformat(),
                "review_notes": notes,
            },
        )

        # Update metadata
        node.metadata.mark_validated(by=reviewer, notes=notes)

        self._stats["created"] += 1
        self._stats["pending_review"] -= 1

        return TeachResult(
            status=TeachStatus.CREATED,
            node_id=node.index,
            action=f"Approved and created by {reviewer}",
            confidence=0.9,
        )

    async def reject_teaching(
        self,
        teaching_id: str,
        reviewer: str,
        reason: str,
    ) -> TeachResult:
        """Reject a pending teaching."""
        if teaching_id not in self._pending:
            return TeachResult(
                status=TeachStatus.REJECTED,
                action="Teaching not found",
            )

        pending = self._pending.pop(teaching_id)

        self._stats["rejected"] += 1
        self._stats["pending_review"] -= 1

        logger.info(f"Teaching {teaching_id} rejected by {reviewer}: {reason}")

        return TeachResult(
            status=TeachStatus.REJECTED,
            action=f"Rejected by {reviewer}: {reason}",
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get teaching statistics."""
        return {
            **self._stats,
            "pending_count": len(self._pending),
        }
