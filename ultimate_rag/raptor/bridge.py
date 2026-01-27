"""
RAPTOR Bridge - Connect existing RAPTOR trees to Ultimate RAG.

Provides bidirectional conversion between:
- RAPTOR's Node/Tree classes
- Ultimate RAG's KnowledgeNode/KnowledgeTree classes
"""

import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Union

if TYPE_CHECKING:
    # Import RAPTOR types for type hints only
    from knowledge_base.raptor.tree_structures import Node as RaptorNode
    from knowledge_base.raptor.tree_structures import Tree as RaptorTree

from ..core.metadata import NodeMetadata, SourceInfo, ValidationStatus
from ..core.node import KnowledgeNode, KnowledgeTree, TreeForest
from ..core.types import ImportanceScore, KnowledgeType

logger = logging.getLogger(__name__)


class RaptorBridge:
    """
    Bridge between RAPTOR and Ultimate RAG.

    Handles:
    - Importing existing RAPTOR trees
    - Exporting Ultimate RAG trees to RAPTOR format
    - Maintaining bidirectional mapping
    """

    def __init__(self):
        # Mapping from RAPTOR node index to KnowledgeNode index
        self._raptor_to_knowledge: Dict[int, int] = {}
        # Mapping from KnowledgeNode index to RAPTOR node index
        self._knowledge_to_raptor: Dict[int, int] = {}
        # Store for imported RAPTOR trees
        self._raptor_trees: Dict[str, "RaptorTree"] = {}

    def import_tree(
        self,
        raptor_tree: "RaptorTree",
        tree_name: str = "imported",
        infer_types: bool = True,
    ) -> KnowledgeTree:
        """
        Import a RAPTOR tree into the Ultimate RAG format.

        Args:
            raptor_tree: RAPTOR Tree object
            tree_name: Name for the imported tree
            infer_types: Whether to infer knowledge types from content

        Returns:
            KnowledgeTree with enhanced nodes
        """
        logger.info(f"Importing RAPTOR tree with {len(raptor_tree.all_nodes)} nodes")

        # Store reference
        self._raptor_trees[tree_name] = raptor_tree

        # Create KnowledgeTree
        knowledge_tree = KnowledgeTree(name=tree_name)

        # Track layer info for importance scoring
        max_layer = raptor_tree.num_layers

        # Convert all nodes
        for raptor_node in raptor_tree.all_nodes.values():
            knowledge_node = self._convert_raptor_node(
                raptor_node,
                raptor_tree,
                max_layer,
                infer_types,
            )

            # Add to tree
            knowledge_tree.all_nodes[knowledge_node.index] = knowledge_node

            # Track mapping
            self._raptor_to_knowledge[raptor_node.index] = knowledge_node.index
            self._knowledge_to_raptor[knowledge_node.index] = raptor_node.index

        # Set root and leaf nodes
        knowledge_tree.root_nodes = [
            knowledge_tree.all_nodes[self._raptor_to_knowledge[n.index]]
            for n in raptor_tree.root_nodes
        ]
        knowledge_tree.leaf_nodes = [
            knowledge_tree.all_nodes[self._raptor_to_knowledge[n.index]]
            for n in raptor_tree.leaf_nodes
        ]

        # Set layer mapping
        knowledge_tree.layer_to_nodes = {}
        for layer, nodes in raptor_tree.layer_to_nodes.items():
            knowledge_tree.layer_to_nodes[layer] = [
                knowledge_tree.all_nodes[self._raptor_to_knowledge[n.index]]
                for n in nodes
            ]

        knowledge_tree.num_layers = raptor_tree.num_layers

        logger.info(
            f"Imported tree '{tree_name}': "
            f"{len(knowledge_tree.all_nodes)} nodes, "
            f"{knowledge_tree.num_layers} layers"
        )

        return knowledge_tree

    def _convert_raptor_node(
        self,
        raptor_node: "RaptorNode",
        raptor_tree: "RaptorTree",
        max_layer: int,
        infer_types: bool,
    ) -> KnowledgeNode:
        """Convert a single RAPTOR node to KnowledgeNode."""
        # Determine layer for this node
        node_layer = self._get_node_layer(raptor_node, raptor_tree)

        # Infer knowledge type from content
        knowledge_type = KnowledgeType.FACTUAL  # Default
        if infer_types:
            knowledge_type = self._infer_knowledge_type(raptor_node.text)

        # Create importance score
        # Higher layers (summaries) get slightly higher base importance
        layer_boost = 0.1 * (node_layer / max_layer) if max_layer > 0 else 0
        importance = ImportanceScore(
            explicit_priority=0.5 + layer_boost,
            authority_score=0.5 + layer_boost,
        )

        # Extract metadata from RAPTOR node
        metadata = self._extract_metadata(raptor_node)

        # Get parent IDs (RAPTOR stores children, we need to invert)
        parent_ids = self._find_parents(raptor_node.index, raptor_tree)

        # Create KnowledgeNode
        knowledge_node = KnowledgeNode(
            text=raptor_node.text,
            index=raptor_node.index,  # Preserve original index
            children_ids=raptor_node.children,
            parent_ids=parent_ids,
            embeddings=raptor_node.embeddings,
            knowledge_type=knowledge_type,
            importance=importance,
            metadata=metadata,
            keywords=raptor_node.keywords if hasattr(raptor_node, "keywords") else [],
        )

        return knowledge_node

    def _get_node_layer(
        self,
        node: "RaptorNode",
        tree: "RaptorTree",
    ) -> int:
        """Determine which layer a node belongs to."""
        for layer, nodes in tree.layer_to_nodes.items():
            for n in nodes:
                if n.index == node.index:
                    return layer
        return 0

    def _find_parents(
        self,
        node_index: int,
        tree: "RaptorTree",
    ) -> Set[int]:
        """Find parent nodes (nodes that have this node as a child)."""
        parents = set()
        for node in tree.all_nodes.values():
            if node_index in node.children:
                parents.add(node.index)
        return parents

    def _infer_knowledge_type(self, text: str) -> KnowledgeType:
        """Infer knowledge type from text content."""
        text_lower = text.lower()

        # Check for procedural content
        if any(
            kw in text_lower
            for kw in [
                "step 1",
                "first,",
                "then,",
                "how to",
                "procedure",
                "instructions",
            ]
        ):
            return KnowledgeType.PROCEDURAL

        # Check for relational content
        if any(
            kw in text_lower
            for kw in ["depends on", "connected to", "owns", "manages", "part of"]
        ):
            return KnowledgeType.RELATIONAL

        # Check for temporal content
        if any(
            kw in text_lower
            for kw in ["on january", "in 2023", "last week", "yesterday", "when"]
        ):
            return KnowledgeType.TEMPORAL

        # Check for policy content
        if any(
            kw in text_lower
            for kw in ["must", "required", "policy", "compliance", "rule", "should not"]
        ):
            return KnowledgeType.POLICY

        # Check for contextual content
        if any(
            kw in text_lower
            for kw in ["in production", "during peak", "when traffic", "context"]
        ):
            return KnowledgeType.CONTEXTUAL

        # Default to factual
        return KnowledgeType.FACTUAL

    def _extract_metadata(self, raptor_node: "RaptorNode") -> Optional[NodeMetadata]:
        """Extract metadata from RAPTOR node."""
        raptor_meta = getattr(raptor_node, "metadata", {}) or {}

        if not raptor_meta:
            return None

        # Extract source info
        source_info = None
        source_url = raptor_meta.get("source_url") or getattr(
            raptor_node, "original_content_ref", None
        )
        if source_url:
            source_info = SourceInfo(
                source_type="document",
                source_id=raptor_meta.get("doc_id", ""),
                url=source_url,
                title=raptor_meta.get("rel_path", ""),
            )

        # Create metadata
        metadata = NodeMetadata(
            source=source_info,
            validation_status=ValidationStatus.PROVISIONAL,
            tags=raptor_meta.get("tags", []),
            domain=raptor_meta.get("domain"),
            subject=raptor_meta.get("subject"),
        )

        # Extract citations if present
        citations = raptor_meta.get("citations", [])
        if citations:
            metadata.related_urls = [c.get("ref") for c in citations if c.get("ref")]

        return metadata

    def export_tree(
        self,
        knowledge_tree: KnowledgeTree,
    ) -> "RaptorTree":
        """
        Export a KnowledgeTree back to RAPTOR format.

        Useful for using RAPTOR's retrieval or updating an existing tree.
        """
        # Import RAPTOR types
        from knowledge_base.raptor.tree_structures import Node as RaptorNode
        from knowledge_base.raptor.tree_structures import Tree as RaptorTree

        all_nodes = {}
        layer_to_nodes = {}

        # Convert all nodes
        for knowledge_node in knowledge_tree.all_nodes.values():
            raptor_node = RaptorNode(
                text=knowledge_node.text,
                index=knowledge_node.index,
                children=knowledge_node.children_ids,
                embeddings=knowledge_node.embeddings,
                keywords=knowledge_node.keywords,
                metadata=self._export_metadata(knowledge_node),
            )
            all_nodes[raptor_node.index] = raptor_node

        # Convert layer mapping
        for layer, nodes in knowledge_tree.layer_to_nodes.items():
            layer_to_nodes[layer] = [all_nodes[n.index] for n in nodes]

        # Create RAPTOR tree
        raptor_tree = RaptorTree(
            all_nodes=all_nodes,
            root_nodes=[all_nodes[n.index] for n in knowledge_tree.root_nodes],
            leaf_nodes=[all_nodes[n.index] for n in knowledge_tree.leaf_nodes],
            num_layers=knowledge_tree.num_layers,
            layer_to_nodes=layer_to_nodes,
        )

        return raptor_tree

    def _export_metadata(self, node: KnowledgeNode) -> Dict[str, Any]:
        """Convert KnowledgeNode metadata to RAPTOR format."""
        metadata = {}

        if node.metadata:
            if node.metadata.source:
                metadata["source_url"] = node.metadata.source.url
                metadata["doc_id"] = node.metadata.source.source_id

            metadata["domain"] = node.metadata.domain
            metadata["subject"] = node.metadata.subject
            metadata["tags"] = node.metadata.tags

        # Add knowledge type info
        metadata["knowledge_type"] = node.knowledge_type.value
        metadata["importance"] = node.get_importance()

        return metadata

    def get_raptor_index(self, knowledge_index: int) -> Optional[int]:
        """Get RAPTOR node index from KnowledgeNode index."""
        return self._knowledge_to_raptor.get(knowledge_index)

    def get_knowledge_index(self, raptor_index: int) -> Optional[int]:
        """Get KnowledgeNode index from RAPTOR node index."""
        return self._raptor_to_knowledge.get(raptor_index)


def import_raptor_tree(
    source: Union[str, Path, "RaptorTree"],
    tree_name: str = "imported",
    infer_types: bool = True,
) -> KnowledgeTree:
    """
    Convenience function to import a RAPTOR tree.

    Args:
        source: Path to pickle file, or RaptorTree object
        tree_name: Name for the imported tree
        infer_types: Whether to infer knowledge types

    Returns:
        KnowledgeTree
    """
    bridge = RaptorBridge()

    if isinstance(source, (str, Path)):
        # Load from pickle
        with open(source, "rb") as f:
            raptor_tree = pickle.load(f)
    else:
        raptor_tree = source

    return bridge.import_tree(raptor_tree, tree_name, infer_types)


def export_to_raptor(
    knowledge_tree: KnowledgeTree,
    output_path: Optional[Union[str, Path]] = None,
) -> "RaptorTree":
    """
    Export a KnowledgeTree to RAPTOR format.

    Args:
        knowledge_tree: Tree to export
        output_path: Optional path to save pickle

    Returns:
        RaptorTree object
    """
    bridge = RaptorBridge()
    raptor_tree = bridge.export_tree(knowledge_tree)

    if output_path:
        with open(output_path, "wb") as f:
            pickle.dump(raptor_tree, f)
        logger.info(f"Exported tree to {output_path}")

    return raptor_tree


def import_forest_from_directory(
    directory: Union[str, Path],
    pattern: str = "*.pkl",
) -> TreeForest:
    """
    Import multiple RAPTOR trees from a directory into a TreeForest.

    Args:
        directory: Directory containing pickle files
        pattern: Glob pattern for pickle files

    Returns:
        TreeForest containing all imported trees
    """
    directory = Path(directory)
    forest = TreeForest()
    bridge = RaptorBridge()

    for pkl_file in directory.glob(pattern):
        try:
            with open(pkl_file, "rb") as f:
                raptor_tree = pickle.load(f)

            tree_name = pkl_file.stem
            knowledge_tree = bridge.import_tree(raptor_tree, tree_name)
            forest.add_tree(tree_name, knowledge_tree)

            logger.info(f"Imported tree '{tree_name}' from {pkl_file}")

        except Exception as e:
            logger.error(f"Failed to import {pkl_file}: {e}")

    return forest
