"""
Enhanced Tree Builder - Extends RAPTOR with Ultimate RAG features.

Adds to standard RAPTOR tree building:
- Knowledge type inference
- Importance scoring during build
- Entity extraction for graph integration
- Quality validation
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set

if TYPE_CHECKING:
    from knowledge_base.raptor.cluster_tree_builder import (
        ClusterTreeBuilder,
        ClusterTreeConfig,
    )

from ..core.metadata import NodeMetadata, SourceInfo, ValidationStatus
from ..core.node import KnowledgeNode, KnowledgeTree
from ..core.types import ImportanceScore, KnowledgeType
from ..graph.entities import Entity, EntityType
from ..graph.graph import KnowledgeGraph

logger = logging.getLogger(__name__)


@dataclass
class EnhancedTreeConfig:
    """Configuration for enhanced tree building."""

    # Knowledge type inference
    infer_knowledge_types: bool = True
    type_inference_model: Optional[Any] = None  # Optional LLM for better inference

    # Importance scoring
    compute_importance: bool = True
    layer_importance_boost: float = 0.1  # Boost per layer

    # Entity extraction
    extract_entities: bool = True
    entity_extractor: Optional[Any] = None  # Optional NER model

    # Quality validation
    validate_quality: bool = True
    min_summary_ratio: float = 0.3  # Min compression ratio for summaries
    max_summary_ratio: float = 0.9  # Max compression ratio (avoid near-duplicates)

    # Graph integration
    build_graph: bool = True


class EnhancedTreeBuilder:
    """
    Enhanced tree builder that wraps RAPTOR with Ultimate RAG features.

    Usage:
        from knowledge_base.raptor.cluster_tree_builder import ClusterTreeBuilder, ClusterTreeConfig

        # Create standard RAPTOR builder
        raptor_config = ClusterTreeConfig(...)
        raptor_builder = ClusterTreeBuilder(raptor_config)

        # Enhance it
        enhanced_config = EnhancedTreeConfig(...)
        enhanced_builder = EnhancedTreeBuilder(raptor_builder, enhanced_config)

        # Build with enhancements
        knowledge_tree = enhanced_builder.build(texts)
    """

    def __init__(
        self,
        raptor_builder: "ClusterTreeBuilder",
        config: Optional[EnhancedTreeConfig] = None,
    ):
        self.raptor_builder = raptor_builder
        self.config = config or EnhancedTreeConfig()

        # Knowledge graph (built during tree construction if enabled)
        self.graph: Optional[KnowledgeGraph] = None
        if self.config.build_graph:
            self.graph = KnowledgeGraph()

        # Callbacks for customization
        self._post_node_hooks: List[Callable[[KnowledgeNode], None]] = []
        self._post_layer_hooks: List[Callable[[int, List[KnowledgeNode]], None]] = []

    def build(
        self,
        texts: List[str],
        metadata_list: Optional[List[Dict[str, Any]]] = None,
    ) -> KnowledgeTree:
        """
        Build an enhanced knowledge tree from texts.

        Args:
            texts: List of text documents
            metadata_list: Optional metadata for each text

        Returns:
            KnowledgeTree with enhanced features
        """
        logger.info(f"Building enhanced tree from {len(texts)} documents")

        # Step 1: Build standard RAPTOR tree
        raptor_tree = self.raptor_builder.build_tree_from_text(texts)

        # Step 2: Convert to KnowledgeTree with enhancements
        knowledge_tree = self._enhance_tree(raptor_tree, metadata_list)

        # Step 3: Build knowledge graph if enabled
        if self.config.build_graph and self.graph:
            self._build_graph_from_tree(knowledge_tree)

        logger.info(
            f"Built enhanced tree: {len(knowledge_tree.all_nodes)} nodes, "
            f"{knowledge_tree.num_layers} layers"
        )

        return knowledge_tree

    def _enhance_tree(
        self,
        raptor_tree: Any,
        metadata_list: Optional[List[Dict[str, Any]]],
    ) -> KnowledgeTree:
        """Convert and enhance a RAPTOR tree."""
        from .bridge import RaptorBridge

        bridge = RaptorBridge()
        knowledge_tree = bridge.import_tree(
            raptor_tree,
            tree_name="enhanced",
            infer_types=False,  # We'll do our own inference
        )

        # Enhance each node
        for layer in range(knowledge_tree.num_layers + 1):
            layer_nodes = knowledge_tree.layer_to_nodes.get(layer, [])

            for node in layer_nodes:
                self._enhance_node(node, layer, knowledge_tree.num_layers)

                # Run post-node hooks
                for hook in self._post_node_hooks:
                    hook(node)

            # Run post-layer hooks
            for hook in self._post_layer_hooks:
                hook(layer, layer_nodes)

        # Apply metadata to leaf nodes if provided
        if metadata_list:
            for i, node in enumerate(knowledge_tree.leaf_nodes):
                if i < len(metadata_list):
                    self._apply_metadata(node, metadata_list[i])

        return knowledge_tree

    def _enhance_node(
        self,
        node: KnowledgeNode,
        layer: int,
        max_layer: int,
    ) -> None:
        """Apply enhancements to a single node."""
        # 1. Infer knowledge type
        if self.config.infer_knowledge_types:
            node.knowledge_type = self._infer_type(node.text, layer)

        # 2. Compute importance
        if self.config.compute_importance:
            self._compute_importance(node, layer, max_layer)

        # 3. Extract entities
        if self.config.extract_entities:
            entities = self._extract_entities(node.text)
            node.entity_ids = set(e.entity_id for e in entities)

        # 4. Validate quality
        if self.config.validate_quality:
            self._validate_quality(node, layer)

        # 5. Compute content hash
        node.content_hash = hashlib.md5(node.text.encode()).hexdigest()

    def _infer_type(self, text: str, layer: int) -> KnowledgeType:
        """Infer knowledge type from text content."""
        if self.config.type_inference_model:
            # Use LLM for inference
            # return self.config.type_inference_model.classify(text)
            pass

        # Heuristic-based inference
        text_lower = text.lower()

        # Higher layers (summaries) are often more factual/contextual
        if layer > 0:
            # Check for procedural summaries
            if any(
                kw in text_lower for kw in ["steps", "procedure", "process", "workflow"]
            ):
                return KnowledgeType.PROCEDURAL

            # Check for relational summaries
            if any(
                kw in text_lower
                for kw in ["architecture", "system", "components", "services"]
            ):
                return KnowledgeType.RELATIONAL

            return KnowledgeType.CONTEXTUAL

        # Leaf-level type inference
        if any(
            kw in text_lower
            for kw in ["step 1", "first,", "then,", "how to", "procedure"]
        ):
            return KnowledgeType.PROCEDURAL

        if any(kw in text_lower for kw in ["depends on", "calls", "owns", "manages"]):
            return KnowledgeType.RELATIONAL

        if any(kw in text_lower for kw in ["on january", "in 2023", "last week"]):
            return KnowledgeType.TEMPORAL

        if any(kw in text_lower for kw in ["must", "required", "policy", "should not"]):
            return KnowledgeType.POLICY

        if any(kw in text_lower for kw in ["@", "email", "slack", "contact"]):
            return KnowledgeType.SOCIAL

        return KnowledgeType.FACTUAL

    def _compute_importance(
        self,
        node: KnowledgeNode,
        layer: int,
        max_layer: int,
    ) -> None:
        """Compute importance score for a node."""
        # Base importance
        base = 0.5

        # Layer boost (higher layers are more important)
        layer_boost = (
            self.config.layer_importance_boost * (layer / max_layer)
            if max_layer > 0
            else 0
        )

        # Content-based signals
        text_length = len(node.text)
        length_factor = min(1.0, text_length / 500)  # Favor substantial content

        # Keyword density (if keywords extracted)
        keyword_factor = 0.0
        if node.keywords:
            keyword_factor = min(0.2, len(node.keywords) * 0.02)

        # Update importance score
        node.importance.explicit_priority = base + layer_boost
        node.importance.authority_score = 0.5 + layer_boost + length_factor * 0.1

        # Add contextual boost
        if keyword_factor > 0:
            node.importance.add_contextual_boost("keyword_rich", keyword_factor)

    def _extract_entities(self, text: str) -> List[Entity]:
        """Extract entities from text."""
        if not self.graph:
            return []

        entities = []

        if self.config.entity_extractor:
            # Use NER model
            # raw_entities = self.config.entity_extractor.extract(text)
            pass
        else:
            # Simple pattern-based extraction
            entities = self._simple_entity_extraction(text)

        return entities

    def _simple_entity_extraction(self, text: str) -> List[Entity]:
        """Simple heuristic-based entity extraction."""
        if not self.graph:
            return []

        entities = []

        # Look for service-like patterns
        import re

        service_pattern = r"\b([a-z]+-service|[a-z]+-api)\b"
        for match in re.finditer(service_pattern, text.lower()):
            service_name = match.group(1)
            entity = self.graph.get_or_create_entity(
                entity_type=EntityType.SERVICE,
                name=service_name,
                description="Service mentioned in document",
            )
            entities.append(entity)

        # Look for team patterns
        team_pattern = r"\b(team [a-z]+|[a-z]+ team)\b"
        for match in re.finditer(team_pattern, text.lower()):
            team_name = match.group(1)
            entity = self.graph.get_or_create_entity(
                entity_type=EntityType.TEAM,
                name=team_name,
                description="Team mentioned in document",
            )
            entities.append(entity)

        return entities

    def _validate_quality(self, node: KnowledgeNode, layer: int) -> None:
        """Validate node quality and set appropriate status."""
        if not node.metadata:
            node.metadata = NodeMetadata()

        # For summary nodes (layer > 0), check compression ratio
        if layer > 0 and node.children_ids:
            # This would need access to children texts for proper validation
            # For now, just mark as provisional
            node.metadata.validation_status = ValidationStatus.PROVISIONAL
        else:
            node.metadata.validation_status = ValidationStatus.VALIDATED

    def _apply_metadata(
        self,
        node: KnowledgeNode,
        metadata: Dict[str, Any],
    ) -> None:
        """Apply external metadata to a node."""
        if not node.metadata:
            node.metadata = NodeMetadata()

        if "source_url" in metadata:
            node.metadata.source = SourceInfo(
                source_type=metadata.get("source_type", "document"),
                source_id=metadata.get("doc_id", ""),
                url=metadata.get("source_url"),
                title=metadata.get("title", ""),
            )

        if "tags" in metadata:
            node.metadata.tags = metadata["tags"]

        if "domain" in metadata:
            node.metadata.domain = metadata["domain"]

        if "subject" in metadata:
            node.metadata.subject = metadata["subject"]

        if "owner" in metadata:
            node.metadata.owner = metadata["owner"]

    def _build_graph_from_tree(self, tree: KnowledgeTree) -> None:
        """Build knowledge graph relationships from tree structure."""
        if not self.graph:
            return

        logger.info("Building knowledge graph from tree")

        # Link entities to their RAPTOR nodes
        for node in tree.all_nodes.values():
            for entity_id in node.entity_ids:
                entity = self.graph.get_entity(entity_id)
                if entity:
                    entity.raptor_node_ids.add(node.index)

        # Infer relationships from co-occurrence
        for node in tree.all_nodes.values():
            if len(node.entity_ids) > 1:
                entity_list = list(node.entity_ids)
                for i, eid1 in enumerate(entity_list):
                    for eid2 in entity_list[i + 1 :]:
                        # Create RELATED_TO relationship for co-occurring entities
                        from ..graph.relationships import Relationship, RelationshipType

                        rel = Relationship.create(
                            RelationshipType.RELATED_TO,
                            eid1,
                            eid2,
                            confidence=0.6,
                            source_node=node.index,
                        )
                        self.graph.add_relationship(rel)

        logger.info(
            f"Graph built: {len(self.graph.entities)} entities, "
            f"{len(self.graph.relationships)} relationships"
        )

    # ==================== Customization ====================

    def add_post_node_hook(
        self,
        hook: Callable[[KnowledgeNode], None],
    ) -> None:
        """Add a hook to run after each node is enhanced."""
        self._post_node_hooks.append(hook)

    def add_post_layer_hook(
        self,
        hook: Callable[[int, List[KnowledgeNode]], None],
    ) -> None:
        """Add a hook to run after each layer is processed."""
        self._post_layer_hooks.append(hook)

    def get_graph(self) -> Optional[KnowledgeGraph]:
        """Get the knowledge graph built during tree construction."""
        return self.graph


def create_enhanced_builder(
    embedding_model: Any,
    summarization_model: Any,
    config: Optional[EnhancedTreeConfig] = None,
    **raptor_kwargs,
) -> EnhancedTreeBuilder:
    """
    Factory function to create an enhanced builder with sensible defaults.

    Args:
        embedding_model: Model for embeddings
        summarization_model: Model for summarization
        config: EnhancedTreeConfig (uses defaults if not provided)
        **raptor_kwargs: Additional kwargs for ClusterTreeConfig

    Returns:
        EnhancedTreeBuilder ready to use
    """
    # Import RAPTOR components
    from knowledge_base.raptor.cluster_tree_builder import (
        ClusterTreeBuilder,
        ClusterTreeConfig,
    )

    # Create RAPTOR config
    raptor_config = ClusterTreeConfig(
        embedding_model=embedding_model,
        summary_model=summarization_model,
        auto_depth=True,
        target_top_nodes=75,
        **raptor_kwargs,
    )

    # Create RAPTOR builder
    raptor_builder = ClusterTreeBuilder(raptor_config)

    # Create enhanced builder
    enhanced_config = config or EnhancedTreeConfig()
    enhanced_builder = EnhancedTreeBuilder(raptor_builder, enhanced_config)

    return enhanced_builder
