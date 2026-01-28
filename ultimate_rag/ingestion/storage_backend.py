"""
Storage backend implementations for the Intelligent Ingestion Pipeline.

This module provides storage backends that bridge the IntelligentIngestionPipeline
to the existing ultimate_rag components (TreeForest, KnowledgeGraph, TeachingInterface).
"""

import hashlib
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..intelligence.models import ContentAnalysisResult, PendingKnowledgeChange

if TYPE_CHECKING:
    from ..agents.teaching import TeachingInterface
    from ..core.node import TreeForest
    from ..graph.graph import KnowledgeGraph
    from ..retrieval.retriever import UltimateRetriever

logger = logging.getLogger(__name__)


class UltimateRAGStorageBackend:
    """
    Storage backend that bridges to the ultimate_rag components.

    This backend:
    - Stores content via the TeachingInterface (which handles RAPTOR tree building)
    - Registers entities/relationships in the KnowledgeGraph
    - Uses the UltimateRetriever for similarity search
    - Submits pending changes to the Proposed Changes API
    """

    def __init__(
        self,
        forest: "TreeForest",
        graph: "KnowledgeGraph",
        teaching: "TeachingInterface",
        retriever: "UltimateRetriever",
        proposed_changes_api_url: Optional[str] = None,
        proposed_changes_api_token: Optional[str] = None,
        org_id: Optional[str] = None,
        team_node_id: Optional[str] = None,
    ):
        """
        Initialize the storage backend.

        Args:
            forest: TreeForest for RAPTOR tree storage.
            graph: KnowledgeGraph for entity/relationship storage.
            teaching: TeachingInterface for content ingestion.
            retriever: UltimateRetriever for similarity search.
            proposed_changes_api_url: Base URL for config_service internal API.
            proposed_changes_api_token: Auth token for internal API.
            org_id: Organization ID for API calls.
            team_node_id: Team node ID for associating changes with teams.
        """
        self.forest = forest
        self.graph = graph
        self.teaching = teaching
        self.retriever = retriever

        self.proposed_changes_api_url = proposed_changes_api_url
        self.proposed_changes_api_token = proposed_changes_api_token
        self.org_id = org_id
        self.team_node_id = team_node_id

        # Local cache of pending changes (if API not configured)
        self._local_pending_changes: Dict[str, PendingKnowledgeChange] = {}

        # Stats
        self._stored_count = 0
        self._updated_count = 0
        self._pending_count = 0

    async def store_content(
        self,
        content: str,
        source: str,
        analysis: ContentAnalysisResult,
        related_node_ids: Optional[List[str]] = None,
    ) -> str:
        """
        Store content in the knowledge base.

        This uses the TeachingInterface to:
        1. Add content to the RAPTOR tree
        2. Update graph with extracted entities/relationships
        3. Index for retrieval

        Args:
            content: The text content to store.
            source: Source attribution.
            analysis: LLM-powered analysis results.
            related_node_ids: Optional related node IDs for linking.

        Returns:
            Node ID of stored content.
        """
        from ..core.types import KnowledgeType

        # Map our knowledge type to core types
        knowledge_type_map = {
            "procedural": KnowledgeType.PROCEDURAL,
            "factual": KnowledgeType.FACTUAL,
            "relational": KnowledgeType.RELATIONAL,
            "temporal": KnowledgeType.TEMPORAL,
            "social": KnowledgeType.SOCIAL,
            "contextual": KnowledgeType.CONTEXTUAL,
            "policy": KnowledgeType.POLICY,
            "meta": KnowledgeType.META,
        }

        kt = knowledge_type_map.get(
            analysis.knowledge_type.knowledge_type.value,
            KnowledgeType.FACTUAL,
        )

        # Build metadata from analysis
        metadata = {
            "source": source,
            "chunk_id": analysis.chunk_id,
            "knowledge_type": analysis.knowledge_type.knowledge_type.value,
            "knowledge_type_confidence": analysis.knowledge_type.confidence,
            "importance": analysis.importance.overall_importance,
            "authority_score": analysis.importance.authority_score,
            "criticality_score": analysis.importance.criticality_score,
            "summary": analysis.summary,
            "keywords": analysis.keywords,
            "entity_count": len(analysis.entities),
            "relationship_count": len(analysis.relationships),
            "processed_at": datetime.utcnow().isoformat(),
        }

        # Extract entity IDs for linking
        entity_ids = [e.canonical_name for e in analysis.entities]

        # Teach the content
        try:
            result = await self.teaching.teach(
                knowledge=content,
                knowledge_type=kt,
                source=source,
                entity_ids=entity_ids,
                importance=analysis.importance.overall_importance,
            )

            node_id = str(result.node_id) if result.node_id else analysis.chunk_id

            # Register entities in graph
            await self._register_entities(analysis)

            # Register relationships in graph
            await self._register_relationships(analysis)

            self._stored_count += 1

            logger.info(
                f"Stored content {node_id}: type={kt.value}, "
                f"importance={analysis.importance.overall_importance:.2f}"
            )

            return node_id

        except Exception as e:
            logger.error(f"Failed to store content: {e}")
            # Return a generated ID on failure
            return analysis.chunk_id

    async def update_content(
        self,
        node_id: str,
        content: str,
        source: str,
        analysis: ContentAnalysisResult,
        importance_multiplier: float = 1.0,
    ) -> None:
        """
        Update existing content in the knowledge base.

        Args:
            node_id: ID of the node to update.
            content: New content.
            source: Source attribution.
            analysis: LLM-powered analysis results.
            importance_multiplier: Multiplier for importance score.
        """
        from ..core.types import KnowledgeType

        # Map knowledge type
        knowledge_type_map = {
            "procedural": KnowledgeType.PROCEDURAL,
            "factual": KnowledgeType.FACTUAL,
            "relational": KnowledgeType.RELATIONAL,
            "temporal": KnowledgeType.TEMPORAL,
            "social": KnowledgeType.SOCIAL,
            "contextual": KnowledgeType.CONTEXTUAL,
            "policy": KnowledgeType.POLICY,
            "meta": KnowledgeType.META,
        }

        kt = knowledge_type_map.get(
            analysis.knowledge_type.knowledge_type.value,
            KnowledgeType.FACTUAL,
        )

        # Adjust importance
        adjusted_importance = min(
            1.0,
            analysis.importance.overall_importance * importance_multiplier
        )

        # Re-teach with updated content (teaching interface handles updates)
        try:
            result = await self.teaching.teach(
                knowledge=content,
                knowledge_type=kt,
                source=f"{source} (updated)",
                entity_ids=[e.canonical_name for e in analysis.entities],
                importance=adjusted_importance,
            )

            # Update graph entities/relationships
            await self._register_entities(analysis)
            await self._register_relationships(analysis)

            self._updated_count += 1

            logger.info(f"Updated content {node_id}")

        except Exception as e:
            logger.error(f"Failed to update content {node_id}: {e}")

    async def find_similar(
        self,
        content: str,
        limit: int = 5,
        threshold: float = 0.75,
    ) -> List[Dict[str, Any]]:
        """
        Find similar existing content using vector similarity.

        Args:
            content: Content to search for.
            limit: Maximum results.
            threshold: Minimum similarity threshold.

        Returns:
            List of similar content with similarity scores.
        """
        try:
            # Use the retriever to find similar content
            result = await self.retriever.retrieve(
                query=content,
                top_k=limit * 2,  # Get more, filter by threshold
            )

            similar = []
            for chunk in result.chunks:
                # Filter by threshold
                if chunk.score >= threshold:
                    similar.append({
                        "id": chunk.metadata.get("node_id", chunk.metadata.get("chunk_id", "")),
                        "content": chunk.text,
                        "source": chunk.metadata.get("source", "unknown"),
                        "updated_at": chunk.metadata.get("processed_at", "unknown"),
                        "similarity_score": chunk.score,
                    })

                if len(similar) >= limit:
                    break

            return similar

        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            return []

    async def store_pending_change(
        self,
        change: PendingKnowledgeChange,
    ) -> str:
        """
        Store a pending change for human review.

        If the Proposed Changes API is configured, submits there.
        Otherwise, stores locally.

        Args:
            change: The pending change to store.

        Returns:
            ID of the stored change.
        """
        if self.proposed_changes_api_url and self.proposed_changes_api_token:
            try:
                change_id = await self._submit_to_api(change)
                logger.info(f"Submitted pending change to API: {change_id}")
                self._pending_count += 1
                return change_id
            except Exception as e:
                logger.warning(f"Failed to submit to API, storing locally: {e}")

        # Store locally
        self._local_pending_changes[change.id] = change
        self._pending_count += 1

        logger.info(f"Stored pending change locally: {change.id}")
        return change.id

    async def _submit_to_api(self, change: PendingKnowledgeChange) -> str:
        """Submit a pending change to the config_service internal API.

        This creates a pending knowledge change that appears in the team's
        Proposed Changes UI at /team/pending-changes for human review.
        """
        import httpx

        url = f"{self.proposed_changes_api_url}/api/v1/internal/pending-changes"

        # Build the proposed_value dict that team.py expects for knowledge changes
        # See config_service/src/api/routes/team.py:list_proposed_kb_changes
        proposed_value = {
            "title": change.title,
            "summary": change.new_content,  # The actual content to be added
            "learned_from": change.source,
            # Include additional context for reviewers
            "conflict_type": change.conflict_relationship.value,
            "existing_content": change.existing_content,
            "existing_node_id": change.existing_node_id,
            "ai_reasoning": change.conflict_reasoning,
            "ai_confidence": change.confidence,
            "evidence": change.evidence,
        }

        # Build the reason string with context about why this needs review
        reason = (
            f"{change.conflict_reasoning}\n\n"
            f"Conflict type: {change.conflict_relationship.value}\n"
            f"AI confidence: {change.confidence:.2f}"
        )

        payload = {
            "id": change.id,
            "org_id": self.org_id,
            "node_id": self.team_node_id,
            "change_type": "knowledge",
            "proposed_value": proposed_value,
            "previous_value": (
                {"content": change.existing_content, "node_id": change.existing_node_id}
                if change.existing_content else None
            ),
            "requested_by": change.proposed_by or "content_analyzer",
            "reason": reason,
            "status": "pending",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.proposed_changes_api_token}",
                    "Content-Type": "application/json",
                    "X-Internal-Service": "ai_pipeline",  # Required by internal API
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("id", change.id)

    async def _register_entities(self, analysis: ContentAnalysisResult) -> None:
        """Register extracted entities in the knowledge graph."""
        from ..graph.entities import Entity, EntityType

        entity_type_map = {
            "service": EntityType.SERVICE,
            "team": EntityType.TEAM,
            "person": EntityType.PERSON,
            "technology": EntityType.TECHNOLOGY,
            "metric": EntityType.METRIC,
            "runbook": EntityType.RUNBOOK,
            "environment": EntityType.ENVIRONMENT,
            "alert": EntityType.ALERT,
            "incident": EntityType.INCIDENT,
            "namespace": EntityType.NAMESPACE,
        }

        for extracted_entity in analysis.entities:
            try:
                entity_type = entity_type_map.get(
                    extracted_entity.entity_type.value,
                    EntityType.SERVICE,  # Default
                )

                entity = Entity(
                    entity_id=extracted_entity.canonical_name,
                    entity_type=entity_type,
                    name=extracted_entity.name,
                    description=extracted_entity.context,
                    properties={
                        "confidence": extracted_entity.confidence,
                        "source_chunk": analysis.chunk_id,
                    },
                )

                self.graph.add_entity(entity)

            except Exception as e:
                logger.debug(f"Failed to register entity {extracted_entity.name}: {e}")

    async def _register_relationships(self, analysis: ContentAnalysisResult) -> None:
        """Register extracted relationships in the knowledge graph."""
        from ..graph.entities import Relationship, RelationshipType

        rel_type_map = {
            "depends_on": RelationshipType.DEPENDS_ON,
            "calls": RelationshipType.CALLS,
            "owns": RelationshipType.OWNED_BY,  # Note: mapping owns -> owned_by
            "member_of": RelationshipType.MEMBER_OF,
            "monitors": RelationshipType.MONITORS,
            "documents": RelationshipType.DOCUMENTS,
            "triggers": RelationshipType.TRIGGERS,
            "supersedes": RelationshipType.SUPERSEDES,
            "related_to": RelationshipType.RELATED_TO,
            "deployed_to": RelationshipType.DEPLOYED_TO,
            "uses": RelationshipType.USES,
        }

        for extracted_rel in analysis.relationships:
            try:
                rel_type = rel_type_map.get(
                    extracted_rel.relationship.value,
                    RelationshipType.RELATED_TO,  # Default
                )

                # Generate relationship ID
                rel_id = hashlib.md5(
                    f"{extracted_rel.source}:{rel_type.value}:{extracted_rel.target}".encode()
                ).hexdigest()[:12]

                relationship = Relationship(
                    relationship_id=rel_id,
                    source_id=extracted_rel.source.lower().replace(" ", "-"),
                    target_id=extracted_rel.target.lower().replace(" ", "-"),
                    relationship_type=rel_type,
                    properties={
                        "confidence": extracted_rel.confidence,
                        "evidence": extracted_rel.evidence,
                        "source_chunk": analysis.chunk_id,
                    },
                )

                self.graph.add_relationship(relationship)

            except Exception as e:
                logger.debug(
                    f"Failed to register relationship "
                    f"{extracted_rel.source}->{extracted_rel.target}: {e}"
                )

    def get_local_pending_changes(self) -> List[PendingKnowledgeChange]:
        """Get locally stored pending changes."""
        return list(self._local_pending_changes.values())

    def get_stats(self) -> Dict[str, Any]:
        """Get storage backend statistics."""
        return {
            "stored_count": self._stored_count,
            "updated_count": self._updated_count,
            "pending_count": self._pending_count,
            "local_pending_changes": len(self._local_pending_changes),
        }
