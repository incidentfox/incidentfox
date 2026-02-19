"""
Tree merging utilities for combining multiple RAPTOR trees.

Use cases:
1. Merge trees built from different subject domains
2. Combine incrementally-built trees periodically
3. Federated builds where different teams build trees separately
"""

import copy
import logging
from typing import Dict, List

from .tree_structures import Node, Tree

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


def merge_trees(
    trees: List[Tree],
    *,
    rebuild_upper_layers: bool = True,
    builder=None,
    target_top_nodes: int = 75,
    max_layers: int = 5,
) -> Tree:
    """
    Merge multiple RAPTOR trees into a single tree.

    This performs a "leaf-level merge" - all leaf nodes from all trees are combined,
    and upper layers are optionally rebuilt to create a unified hierarchy.

    Args:
        trees: List of Tree objects to merge
        rebuild_upper_layers: If True, rebuild layers 1+ from merged leaves.
                              If False, keep original layer-1 nodes but reindex.
        builder: ClusterTreeBuilder instance (required if rebuild_upper_layers=True)
        target_top_nodes: Target number of root nodes after rebuild
        max_layers: Maximum number of layers to build

    Returns:
        A new merged Tree

    Notes:
        - All node indices are remapped to avoid collisions
        - Metadata and provenance are preserved
        - If rebuild_upper_layers=False, layer-1+ nodes are simply concatenated
          (this is faster but may have redundant/overlapping clusters)
    """
    if not trees:
        raise ValueError("At least one tree is required")

    if len(trees) == 1:
        return copy.deepcopy(trees[0])

    if rebuild_upper_layers and builder is None:
        raise ValueError("builder is required when rebuild_upper_layers=True")

    logging.info(f"[merge_trees] Merging {len(trees)} trees...")

    # Phase 1: Collect all leaf nodes with remapped indices
    merged_leaves: Dict[int, Node] = {}
    merged_all_nodes: Dict[int, Node] = {}
    next_idx = 0

    # Track original -> new index mapping for each tree
    index_maps: List[Dict[int, int]] = []

    for tree_i, tree in enumerate(trees):
        idx_map: Dict[int, int] = {}
        leaf_count = 0

        for old_idx, node in tree.leaf_nodes.items():
            new_idx = next_idx
            idx_map[old_idx] = new_idx

            # Create new node with remapped index
            new_node = Node(
                text=node.text,
                index=new_idx,
                children=set(),  # Leaves have no children
                embeddings=copy.deepcopy(node.embeddings),
                keywords=copy.copy(node.keywords) if node.keywords else None,
                metadata=copy.deepcopy(node.metadata) if node.metadata else None,
                original_content_ref=node.original_content_ref,
            )

            merged_leaves[new_idx] = new_node
            merged_all_nodes[new_idx] = new_node
            next_idx += 1
            leaf_count += 1

        index_maps.append(idx_map)
        logging.info(
            f"[merge_trees] Tree {tree_i}: merged {leaf_count} leaves (indices {next_idx - leaf_count} - {next_idx - 1})"
        )

    total_leaves = len(merged_leaves)
    logging.info(f"[merge_trees] Total merged leaves: {total_leaves}")

    if rebuild_upper_layers:
        # Phase 2a: Rebuild upper layers using the builder
        logging.info("[merge_trees] Rebuilding upper layers...")

        layer_to_nodes = {0: list(merged_leaves.values())}

        root_nodes = builder.construct_tree(
            copy.deepcopy(merged_all_nodes),
            merged_all_nodes,
            layer_to_nodes,
            use_multithreading=True,
        )

        merged_tree = Tree(
            merged_all_nodes,
            root_nodes,
            merged_leaves,
            len(layer_to_nodes) - 1,
            layer_to_nodes,
        )
    else:
        # Phase 2b: Simple concatenation of layer-1+ nodes (faster, less optimal)
        logging.info("[merge_trees] Concatenating upper layers (no rebuild)...")

        layer_to_nodes: Dict[int, List[Node]] = {0: list(merged_leaves.values())}

        for tree_i, tree in enumerate(trees):
            idx_map = index_maps[tree_i]

            for layer_num in sorted(tree.layer_to_nodes.keys()):
                if layer_num == 0:
                    continue  # Already handled leaves

                if layer_num not in layer_to_nodes:
                    layer_to_nodes[layer_num] = []

                for node in tree.layer_to_nodes[layer_num]:
                    new_idx = next_idx
                    idx_map[node.index] = new_idx

                    # Remap children indices
                    new_children = {idx_map.get(c, c) for c in node.children}

                    new_node = Node(
                        text=node.text,
                        index=new_idx,
                        children=new_children,
                        embeddings=copy.deepcopy(node.embeddings),
                        keywords=copy.copy(node.keywords) if node.keywords else None,
                        metadata=(
                            copy.deepcopy(node.metadata) if node.metadata else None
                        ),
                        original_content_ref=node.original_content_ref,
                    )

                    merged_all_nodes[new_idx] = new_node
                    layer_to_nodes[layer_num].append(new_node)
                    next_idx += 1

        # Determine root nodes (highest layer)
        max_layer = max(layer_to_nodes.keys())
        root_nodes = {n.index: n for n in layer_to_nodes[max_layer]}

        merged_tree = Tree(
            merged_all_nodes,
            root_nodes,
            merged_leaves,
            max_layer,
            layer_to_nodes,
        )

    logging.info(
        f"[merge_trees] Merge complete: {len(merged_tree.all_nodes)} total nodes, {len(merged_tree.root_nodes)} roots"
    )

    return merged_tree


def merge_trees_incremental(
    base_tree: Tree,
    new_tree: Tree,
    *,
    builder=None,
    similarity_threshold: float = 0.25,
    embedding_key: str = "EMB",
) -> Tree:
    """
    Incrementally merge a new tree into an existing base tree.

    This is more efficient than full merge + rebuild for adding small amounts
    of new content to a large existing tree.

    Strategy:
    1. For each leaf in new_tree, find the most similar layer-1 cluster in base_tree
    2. If similarity > threshold, attach to that cluster and update its summary
    3. If similarity < threshold, create a new cluster
    4. Optionally rebuild upper layers

    Args:
        base_tree: The existing tree to merge into (modified in place)
        new_tree: The new tree whose leaves will be merged in
        builder: TreeBuilder for creating summaries/embeddings
        similarity_threshold: Minimum similarity to attach to existing cluster
        embedding_key: Which embedding to use for similarity computation

    Returns:
        The modified base_tree
    """
    from .incremental import (
        IncrementalUpdateConfig,
        incremental_insert_leaf_nodes_layer1,
    )

    if builder is None:
        raise ValueError("builder is required for incremental merge")

    # Remap new tree leaf indices to avoid collision
    next_idx = max(base_tree.all_nodes.keys()) + 1 if base_tree.all_nodes else 0
    new_leaves: Dict[int, Node] = {}

    for old_idx, node in new_tree.leaf_nodes.items():
        new_node = Node(
            text=node.text,
            index=next_idx,
            children=set(),
            embeddings=copy.deepcopy(node.embeddings),
            keywords=copy.copy(node.keywords) if node.keywords else None,
            metadata=copy.deepcopy(node.metadata) if node.metadata else None,
            original_content_ref=node.original_content_ref,
        )
        new_leaves[next_idx] = new_node
        next_idx += 1

    logging.info(
        f"[merge_trees_incremental] Adding {len(new_leaves)} leaves to base tree ({len(base_tree.leaf_nodes)} existing leaves)"
    )

    # Get layer-1 nodes from base tree
    layer1_nodes = list(base_tree.layer_to_nodes.get(1, []))

    cfg = IncrementalUpdateConfig(
        embedding_key=embedding_key,
        similarity_threshold=similarity_threshold,
    )

    # Use incremental insert logic
    updated, created = incremental_insert_leaf_nodes_layer1(
        tree=base_tree,
        new_leaf_nodes=new_leaves,
        layer1_nodes=layer1_nodes,
        cfg=cfg,
        tokenizer=builder.tokenizer,
        summarizer=builder.summarization_model,
        embedder_map=builder.embedding_models,
        summarization_length=builder.summarization_length,
    )

    logging.info(
        f"[merge_trees_incremental] Updated {len(updated)} clusters, created {len(created)} new clusters"
    )

    return base_tree


# Convenience function for CLI usage
def merge_tree_files(
    tree_paths: List[str],
    output_path: str,
    *,
    rebuild: bool = True,
    builder_config=None,
) -> Tree:
    """
    Load multiple tree pickle files and merge them.

    Args:
        tree_paths: Paths to .pkl tree files
        output_path: Where to save the merged tree
        rebuild: Whether to rebuild upper layers
        builder_config: Configuration for the tree builder (if rebuild=True)

    Returns:
        The merged Tree
    """
    import pickle

    trees = []
    for path in tree_paths:
        with open(path, "rb") as f:
            tree = pickle.load(f)
            if not isinstance(tree, Tree):
                raise ValueError(f"{path} does not contain a Tree object")
            trees.append(tree)
            logging.info(
                f"[merge_tree_files] Loaded {path}: {len(tree.all_nodes)} nodes"
            )

    builder = None
    if rebuild and builder_config is not None:
        from .cluster_tree_builder import ClusterTreeBuilder

        builder = ClusterTreeBuilder(builder_config)

    merged = merge_trees(trees, rebuild_upper_layers=rebuild, builder=builder)

    with open(output_path, "wb") as f:
        pickle.dump(merged, f)
    logging.info(f"[merge_tree_files] Saved merged tree to {output_path}")

    return merged
