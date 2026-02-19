from typing import Any, Dict, List, Optional, Set


class Node:
    """
    Represents a node in the hierarchical tree structure.
    """

    def __init__(
        self,
        text: str,
        index: int,
        children: Set[int],
        embeddings,
        keywords: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        original_content_ref: Optional[str] = None,
    ) -> None:
        self.text = text
        self.index = index
        self.children = children
        self.embeddings = embeddings
        # Optional keyword/keyphrase list for browsing / keyword search / graph relationships.
        # Backward-compatible: older pickles will simply not have this attr.
        self.keywords = keywords or []
        # Optional metadata from ingestion pipeline (SourceMetadata serialized as dict)
        # Backward-compatible: older pickles will simply not have this attr.
        self.metadata = metadata or {}
        # Optional reference to original content file/URL
        self.original_content_ref = original_content_ref


class Tree:
    """
    Represents the entire hierarchical tree structure.
    """

    def __init__(
        self, all_nodes, root_nodes, leaf_nodes, num_layers, layer_to_nodes
    ) -> None:
        self.all_nodes = all_nodes
        self.root_nodes = root_nodes
        self.leaf_nodes = leaf_nodes
        self.num_layers = num_layers
        self.layer_to_nodes = layer_to_nodes
