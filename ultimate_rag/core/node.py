"""
Knowledge node and tree structures.

Enhanced version of RAPTOR nodes with importance scoring,
metadata, and knowledge graph integration.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set

from .metadata import NodeMetadata, SourceInfo, ValidationStatus
from .types import ImportanceScore, ImportanceWeights, KnowledgeType


@dataclass
class KnowledgeNode:
    """
    A node in the knowledge tree.

    Enhanced version of RAPTOR Node with:
    - Multi-signal importance scoring
    - Rich metadata and provenance
    - Knowledge graph entity references
    - Validation status tracking
    """

    # Core content
    text: str
    index: int

    # Tree structure
    children: Set[int] = field(default_factory=set)
    layer: int = 0

    # Embeddings (multiple models supported)
    embeddings: Dict[str, List[float]] = field(default_factory=dict)

    # Classification
    knowledge_type: KnowledgeType = KnowledgeType.FACTUAL

    # Importance scoring
    importance: ImportanceScore = field(default_factory=ImportanceScore)

    # Metadata
    metadata: Optional[NodeMetadata] = None

    # Keywords for hybrid search
    keywords: List[str] = field(default_factory=list)

    # Quick access fields (denormalized from metadata)
    source_url: Optional[str] = None
    tree_id: Optional[str] = None

    # Content hash for deduplication
    _content_hash: Optional[str] = field(default=None, repr=False)

    def __post_init__(self):
        """Initialize computed fields."""
        if self._content_hash is None:
            self._content_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute content hash for deduplication."""
        content = self.text.strip().lower()
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @property
    def content_hash(self) -> str:
        """Get content hash."""
        if self._content_hash is None:
            self._content_hash = self._compute_hash()
        return self._content_hash

    @property
    def is_leaf(self) -> bool:
        """Check if this is a leaf node (no children)."""
        return len(self.children) == 0

    @property
    def is_summary(self) -> bool:
        """Check if this is a summary node (has children)."""
        return len(self.children) > 0

    @property
    def is_active(self) -> bool:
        """Check if this node is active (not archived/deprecated)."""
        if self.metadata:
            return self.metadata.is_active()
        return True

    @property
    def validation_status(self) -> ValidationStatus:
        """Get validation status."""
        if self.metadata:
            return self.metadata.validation_status
        return ValidationStatus.PROVISIONAL

    @property
    def confidence(self) -> float:
        """Get confidence score."""
        if self.metadata:
            return self.metadata.confidence
        return 0.5

    def get_importance(
        self,
        weights: Optional[ImportanceWeights] = None,
    ) -> float:
        """
        Compute final importance score.

        Args:
            weights: Custom weights for importance calculation

        Returns:
            Importance score in [0, 1]
        """
        ttl_days = self.knowledge_type.default_ttl_days
        return self.importance.compute_final(
            weights=weights,
            content_ttl_days=ttl_days,
        )

    def record_access(self) -> None:
        """Record an access to this node."""
        self.importance.record_access()

    def record_feedback(self, positive: bool) -> None:
        """Record user feedback on this node."""
        self.importance.record_feedback(positive)

    def record_task_outcome(self, success: bool) -> None:
        """Record task outcome when this node was used."""
        self.importance.record_task_outcome(success)

    def add_contextual_boost(self, reason: str, amount: float) -> None:
        """Add a temporary importance boost."""
        self.importance.add_contextual_boost(reason, amount)

    def get_embedding(self, model_name: str = "OpenAI") -> Optional[List[float]]:
        """Get embedding for a specific model."""
        return self.embeddings.get(model_name)

    def set_embedding(self, model_name: str, embedding: List[float]) -> None:
        """Set embedding for a specific model."""
        self.embeddings[model_name] = embedding

    def add_keyword(self, keyword: str) -> None:
        """Add a keyword."""
        if keyword and keyword not in self.keywords:
            self.keywords.append(keyword)

    def matches_keywords(
        self, query_keywords: List[str], match_all: bool = False
    ) -> bool:
        """Check if node matches given keywords."""
        if not query_keywords:
            return True
        if not self.keywords:
            return False

        node_kw_lower = {k.lower() for k in self.keywords}
        query_kw_lower = {k.lower() for k in query_keywords}

        if match_all:
            return query_kw_lower.issubset(node_kw_lower)
        else:
            return bool(query_kw_lower & node_kw_lower)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "text": self.text,
            "index": self.index,
            "children": list(self.children),
            "layer": self.layer,
            "embeddings": self.embeddings,
            "knowledge_type": self.knowledge_type.value,
            "importance": self.importance.to_dict(),
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "keywords": self.keywords,
            "source_url": self.source_url,
            "tree_id": self.tree_id,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeNode":
        """Deserialize from dictionary."""
        return cls(
            text=data.get("text", ""),
            index=data.get("index", 0),
            children=set(data.get("children", [])),
            layer=data.get("layer", 0),
            embeddings=data.get("embeddings", {}),
            knowledge_type=KnowledgeType(data.get("knowledge_type", "factual")),
            importance=ImportanceScore.from_dict(data.get("importance", {})),
            metadata=(
                NodeMetadata.from_dict(data["metadata"])
                if data.get("metadata")
                else None
            ),
            keywords=data.get("keywords", []),
            source_url=data.get("source_url"),
            tree_id=data.get("tree_id"),
            _content_hash=data.get("content_hash"),
        )

    @classmethod
    def from_raptor_node(cls, raptor_node, tree_id: str = None) -> "KnowledgeNode":
        """
        Create KnowledgeNode from a RAPTOR Node.

        Preserves all RAPTOR fields and adds Ultimate RAG enhancements.
        """
        # Extract metadata from RAPTOR node
        raptor_metadata = getattr(raptor_node, "metadata", {}) or {}
        source_url = raptor_metadata.get("source_url") or getattr(
            raptor_node, "original_content_ref", None
        )

        # Create source info
        source_info = None
        if source_url:
            source_info = SourceInfo(
                source_type="raptor_import",
                source_url=source_url,
            )

        # Determine layer (RAPTOR doesn't store this directly on nodes)
        layer = getattr(raptor_node, "layer", 0)

        # Create metadata
        metadata = NodeMetadata(
            node_id=raptor_node.index,
            tree_id=tree_id or "",
            layer=layer,
            knowledge_type="factual",
            source=source_info,
            citations=raptor_metadata.get("citations", []),
            citation_total=raptor_metadata.get("citation_total", 0),
        )

        return cls(
            text=raptor_node.text,
            index=raptor_node.index,
            children=set(raptor_node.children) if raptor_node.children else set(),
            layer=layer,
            embeddings=dict(raptor_node.embeddings) if raptor_node.embeddings else {},
            knowledge_type=KnowledgeType.FACTUAL,
            metadata=metadata,
            keywords=(
                list(raptor_node.keywords)
                if getattr(raptor_node, "keywords", None)
                else []
            ),
            source_url=source_url,
            tree_id=tree_id,
        )


@dataclass
class KnowledgeTree:
    """
    A knowledge tree containing nodes organized hierarchically.

    Enhanced version of RAPTOR Tree with importance-aware operations.
    """

    # Identity
    tree_id: str
    name: str
    description: str = ""

    # Classification
    knowledge_type: KnowledgeType = KnowledgeType.FACTUAL
    tags: List[str] = field(default_factory=list)

    # Nodes
    all_nodes: Dict[int, KnowledgeNode] = field(default_factory=dict)
    root_nodes: Dict[int, KnowledgeNode] = field(default_factory=dict)
    leaf_nodes: Dict[int, KnowledgeNode] = field(default_factory=dict)

    # Structure
    num_layers: int = 0
    layer_to_nodes: Dict[int, List[KnowledgeNode]] = field(default_factory=dict)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    version: str = "1.0.0"

    # Configuration
    embedding_model: str = "OpenAI"
    embedding_dimension: int = 1536

    def add_node(self, node: KnowledgeNode) -> None:
        """Add a node to the tree."""
        node.tree_id = self.tree_id
        self.all_nodes[node.index] = node

        # Update layer mapping
        if node.layer not in self.layer_to_nodes:
            self.layer_to_nodes[node.layer] = []
        if node not in self.layer_to_nodes[node.layer]:
            self.layer_to_nodes[node.layer].append(node)

        # Update leaf/root tracking
        if node.is_leaf:
            self.leaf_nodes[node.index] = node
        if node.layer == self.num_layers:
            self.root_nodes[node.index] = node

        self.updated_at = datetime.utcnow()

    def get_node(self, index: int) -> Optional[KnowledgeNode]:
        """Get a node by index."""
        return self.all_nodes.get(index)

    def get_nodes_by_layer(self, layer: int) -> List[KnowledgeNode]:
        """Get all nodes at a specific layer."""
        return self.layer_to_nodes.get(layer, [])

    def get_active_nodes(self) -> List[KnowledgeNode]:
        """Get all active (non-archived) nodes."""
        return [n for n in self.all_nodes.values() if n.is_active]

    def get_nodes_by_importance(
        self,
        min_importance: float = 0.0,
        weights: Optional[ImportanceWeights] = None,
        limit: int = None,
    ) -> List[KnowledgeNode]:
        """Get nodes sorted by importance."""
        scored = [
            (n, n.get_importance(weights))
            for n in self.all_nodes.values()
            if n.is_active
        ]
        filtered = [(n, s) for n, s in scored if s >= min_importance]
        sorted_nodes = sorted(filtered, key=lambda x: x[1], reverse=True)

        if limit:
            sorted_nodes = sorted_nodes[:limit]

        return [n for n, _ in sorted_nodes]

    def get_stale_nodes(self) -> List[KnowledgeNode]:
        """Get nodes that are stale and need refresh."""
        stale = []
        for node in self.all_nodes.values():
            ttl = node.knowledge_type.default_ttl_days
            if node.importance.is_stale(ttl):
                stale.append(node)
        return stale

    def get_nodes_needing_validation(self) -> List[KnowledgeNode]:
        """Get nodes that need human validation."""
        return [
            n
            for n in self.all_nodes.values()
            if n.is_active and n.importance.needs_validation()
        ]

    def find_similar_nodes(
        self,
        content_hash: str,
        threshold: float = 0.0,
    ) -> List[KnowledgeNode]:
        """Find nodes with same or similar content hash."""
        return [n for n in self.all_nodes.values() if n.content_hash == content_hash]

    def get_stats(self) -> Dict[str, Any]:
        """Get tree statistics."""
        active_nodes = [n for n in self.all_nodes.values() if n.is_active]
        importance_scores = [n.get_importance() for n in active_nodes]

        return {
            "tree_id": self.tree_id,
            "name": self.name,
            "total_nodes": len(self.all_nodes),
            "active_nodes": len(active_nodes),
            "leaf_nodes": len(self.leaf_nodes),
            "root_nodes": len(self.root_nodes),
            "num_layers": self.num_layers,
            "layer_counts": {l: len(nodes) for l, nodes in self.layer_to_nodes.items()},
            "avg_importance": (
                sum(importance_scores) / len(importance_scores)
                if importance_scores
                else 0
            ),
            "stale_nodes": len(self.get_stale_nodes()),
            "needs_validation": len(self.get_nodes_needing_validation()),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    def to_raptor_tree(self):
        """
        Convert to RAPTOR Tree for compatibility.

        Returns a tree object compatible with existing RAPTOR retriever.
        """
        # Import here to avoid circular deps
        from dataclasses import dataclass as dc

        @dc
        class RaptorNode:
            text: str
            index: int
            children: Set[int]
            embeddings: Dict[str, List[float]]
            keywords: List[str]
            metadata: Dict[str, Any]
            original_content_ref: Optional[str]

        @dc
        class RaptorTree:
            all_nodes: Dict[int, Any]
            root_nodes: Dict[int, Any]
            leaf_nodes: Dict[int, Any]
            num_layers: int
            layer_to_nodes: Dict[int, List[Any]]

        # Convert nodes
        raptor_nodes = {}
        for idx, node in self.all_nodes.items():
            raptor_nodes[idx] = RaptorNode(
                text=node.text,
                index=node.index,
                children=node.children,
                embeddings=node.embeddings,
                keywords=node.keywords,
                metadata=node.metadata.to_dict() if node.metadata else {},
                original_content_ref=node.source_url,
            )

        # Convert layer mapping
        raptor_layer_to_nodes = {}
        for layer, nodes in self.layer_to_nodes.items():
            raptor_layer_to_nodes[layer] = [raptor_nodes[n.index] for n in nodes]

        return RaptorTree(
            all_nodes=raptor_nodes,
            root_nodes={idx: raptor_nodes[idx] for idx in self.root_nodes},
            leaf_nodes={idx: raptor_nodes[idx] for idx in self.leaf_nodes},
            num_layers=self.num_layers,
            layer_to_nodes=raptor_layer_to_nodes,
        )

    @classmethod
    def from_raptor_tree(cls, raptor_tree, tree_id: str, name: str) -> "KnowledgeTree":
        """
        Create KnowledgeTree from a RAPTOR Tree.

        Preserves all RAPTOR structure and adds Ultimate RAG enhancements.
        """
        tree = cls(
            tree_id=tree_id,
            name=name,
            num_layers=raptor_tree.num_layers,
        )

        # Build layer mapping for node layer lookup
        node_to_layer = {}
        if hasattr(raptor_tree, "layer_to_nodes"):
            for layer, nodes in raptor_tree.layer_to_nodes.items():
                for node in nodes:
                    node_to_layer[node.index] = layer

        # Convert nodes
        for idx, raptor_node in raptor_tree.all_nodes.items():
            # Determine layer
            layer = node_to_layer.get(idx, 0)

            # Create KnowledgeNode
            knode = KnowledgeNode.from_raptor_node(raptor_node, tree_id)
            knode.layer = layer

            if knode.metadata:
                knode.metadata.layer = layer

            tree.all_nodes[idx] = knode

        # Set up leaf and root nodes
        for idx in raptor_tree.leaf_nodes:
            if idx in tree.all_nodes:
                tree.leaf_nodes[idx] = tree.all_nodes[idx]

        for idx in raptor_tree.root_nodes:
            if idx in tree.all_nodes:
                tree.root_nodes[idx] = tree.all_nodes[idx]

        # Set up layer mapping
        for layer, nodes in raptor_tree.layer_to_nodes.items():
            tree.layer_to_nodes[layer] = [
                tree.all_nodes[n.index] for n in nodes if n.index in tree.all_nodes
            ]

        # Detect embedding model from first node
        for node in tree.all_nodes.values():
            if node.embeddings:
                tree.embedding_model = list(node.embeddings.keys())[0]
                first_emb = list(node.embeddings.values())[0]
                tree.embedding_dimension = len(first_emb) if first_emb else 1536
                break

        return tree


@dataclass
class TreeForest:
    """
    A collection of knowledge trees.

    Supports federated search across multiple trees.
    """

    # Identity
    forest_id: str
    name: str
    description: str = ""

    # Trees
    trees: Dict[str, KnowledgeTree] = field(default_factory=dict)

    # Default tree for single-tree queries
    default_tree: Optional[str] = None

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_tree(self, tree: KnowledgeTree) -> None:
        """Add a tree to the forest."""
        self.trees[tree.tree_id] = tree
        if self.default_tree is None:
            self.default_tree = tree.tree_id
        self.updated_at = datetime.utcnow()

    def get_tree(self, tree_id: str) -> Optional[KnowledgeTree]:
        """Get a tree by ID."""
        return self.trees.get(tree_id)

    def remove_tree(self, tree_id: str) -> bool:
        """Remove a tree from the forest."""
        if tree_id in self.trees:
            del self.trees[tree_id]
            if self.default_tree == tree_id:
                self.default_tree = next(iter(self.trees), None)
            self.updated_at = datetime.utcnow()
            return True
        return False

    def get_all_nodes(self) -> List[KnowledgeNode]:
        """Get all nodes across all trees."""
        nodes = []
        for tree in self.trees.values():
            nodes.extend(tree.all_nodes.values())
        return nodes

    def get_trees_by_type(self, knowledge_type: KnowledgeType) -> List[KnowledgeTree]:
        """Get trees of a specific knowledge type."""
        return [t for t in self.trees.values() if t.knowledge_type == knowledge_type]

    def get_stats(self) -> Dict[str, Any]:
        """Get forest statistics."""
        total_nodes = sum(len(t.all_nodes) for t in self.trees.values())
        total_leaves = sum(len(t.leaf_nodes) for t in self.trees.values())

        return {
            "forest_id": self.forest_id,
            "name": self.name,
            "num_trees": len(self.trees),
            "total_nodes": total_nodes,
            "total_leaves": total_leaves,
            "trees": {tid: t.get_stats() for tid, t in self.trees.items()},
            "default_tree": self.default_tree,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
