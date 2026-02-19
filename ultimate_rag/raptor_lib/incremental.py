import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from .tree_structures import Node, Tree
from .utils import get_text_for_summary

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class IncrementalUpdateConfig:
    """
    Settings for approximate incremental updates.

    Notes:
    - This is an ONLINE approximation (local changes) and will drift vs a full rebuild.
    - Recommended to do periodic full rebuilds to correct drift.
    """

    # Which embedding key to use for routing (must exist in node.embeddings for leaves and parents)
    embedding_key: str
    # Cosine similarity threshold for attaching a new leaf to an existing parent cluster.
    # If max similarity < threshold, create a new parent cluster (layer 1).
    similarity_threshold: float = 0.25
    # Cap how many child texts are used when re-summarizing a parent (keeps summarization bounded).
    max_children_for_summary: int = 50
    # Cap the context token budget when collecting child texts for summarization.
    max_summary_context_tokens: int = 12000


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12
    return float(np.dot(a, b) / denom)


def _collect_child_texts_for_summary(
    tree: Tree,
    child_indices: List[int],
    tokenizer,
    max_tokens: int,
    max_children: int,
) -> str:
    """
    Collect up to max_children child texts, stopping once token budget is reached.
    """
    parts: List[str] = []
    total = 0
    for idx in child_indices[:max_children]:
        node = tree.all_nodes.get(idx)
        if node is None:
            continue
        txt = (node.text or "").strip()
        if not txt:
            continue
        toks = len(tokenizer.encode(txt))
        if parts and total + toks > max_tokens:
            break
        parts.append(txt)
        total += toks
    # `parts` already contains child texts (potentially with provenance headers).
    # Strip headers/shortcodes to keep parent summaries clean.
    return get_text_for_summary(
        [type("N", (), {"text": p}) for p in parts]
    )  # lightweight adapter


def incremental_insert_leaf_nodes_layer1(
    *,
    tree: Tree,
    new_leaf_nodes: Dict[int, Node],
    layer1_nodes: List[Node],
    cfg: IncrementalUpdateConfig,
    tokenizer,
    summarizer,
    embedder_map: Dict[str, object],
    summarization_length: int,
) -> Tuple[Set[int], List[int]]:
    """
    Incrementally attach leaf nodes into layer-1 clusters (parent nodes).

    Returns:
    - updated_parent_indices: parent node indices whose summaries/embeddings were updated
    - created_parent_indices: newly created layer-1 parent node indices
    """
    if tree.layer_to_nodes.get(0) is None:
        tree.layer_to_nodes[0] = []
    if tree.layer_to_nodes.get(1) is None:
        tree.layer_to_nodes[1] = []

    # Add leaves to tree structures first.
    for idx, node in new_leaf_nodes.items():
        tree.leaf_nodes[idx] = node
        tree.all_nodes[idx] = node
        tree.layer_to_nodes[0].append(node)

    # Index parents by id for faster updates.
    parent_by_id: Dict[int, Node] = {n.index: n for n in layer1_nodes}

    updated_parents: Set[int] = set()
    created_parents: List[int] = []

    for leaf_idx, leaf_node in new_leaf_nodes.items():
        leaf_emb = leaf_node.embeddings.get(cfg.embedding_key)
        if leaf_emb is None:
            raise ValueError(
                f"Leaf node {leaf_idx} missing embeddings['{cfg.embedding_key}']"
            )

        # Find best existing parent by cosine similarity (using parent node's embedding as proxy).
        best_parent: Optional[int] = None
        best_sim: float = -1.0

        for pid, parent in parent_by_id.items():
            p_emb = parent.embeddings.get(cfg.embedding_key)
            if p_emb is None:
                continue
            sim = _cosine_similarity(leaf_emb, p_emb)
            if sim > best_sim:
                best_sim = sim
                best_parent = pid

        if best_parent is None or best_sim < cfg.similarity_threshold:
            # Create a new parent cluster node (layer 1) that contains just this leaf.
            new_parent_idx = max(tree.all_nodes.keys()) + 1

            # Summarize just the leaf (or a short version). This keeps behavior consistent across models.
            child_text = (leaf_node.text or "").strip()
            if hasattr(summarizer, "summarize_layer"):
                summary = summarizer.summarize_layer(  # type: ignore[attr-defined]
                    child_text, layer=1, max_tokens=summarization_length
                )
            else:
                summary = summarizer.summarize(
                    child_text, max_tokens=summarization_length
                )

            embeddings = {
                model_name: model.create_embedding(summary)
                for model_name, model in embedder_map.items()
            }
            new_parent = Node(
                text=summary,
                index=new_parent_idx,
                children={leaf_idx},
                embeddings=embeddings,
            )

            tree.all_nodes[new_parent_idx] = new_parent
            tree.layer_to_nodes[1].append(new_parent)
            parent_by_id[new_parent_idx] = new_parent
            created_parents.append(new_parent_idx)
            continue

        # Attach to existing parent and update its summary/embeddings (expensive part).
        parent = parent_by_id[best_parent]
        parent.children.add(leaf_idx)
        updated_parents.add(best_parent)

        # Re-summarize parent using a bounded set of its child texts.
        child_list = sorted(list(parent.children))
        context = _collect_child_texts_for_summary(
            tree,
            child_list,
            tokenizer=tokenizer,
            max_tokens=cfg.max_summary_context_tokens,
            max_children=cfg.max_children_for_summary,
        )
        if hasattr(summarizer, "summarize_layer"):
            parent_summary = summarizer.summarize_layer(  # type: ignore[attr-defined]
                context, layer=1, max_tokens=summarization_length
            )
        else:
            parent_summary = summarizer.summarize(
                context, max_tokens=summarization_length
            )
        parent.text = parent_summary

        # Refresh embeddings for the parent text so retrieval remains consistent.
        parent.embeddings = {
            model_name: model.create_embedding(parent_summary)
            for model_name, model in embedder_map.items()
        }

    # If this is a 2-level tree (num_layers==1), keep root_nodes aligned to layer 1.
    if getattr(tree, "num_layers", None) == 1:
        tree.root_nodes = tree.layer_to_nodes[1]

    return updated_parents, created_parents


def rebuild_upper_layers_from(
    *,
    tree: Tree,
    start_layer: int,
    builder,
    target_top_nodes: int = 75,
    max_layers: int = 5,
    hard_max_children_per_parent: int = 300,
) -> None:
    """
    Rebuild layers (start_layer+1 ..) from the nodes in `start_layer` upward until:
    - top layer size <= target_top_nodes, or
    - we hit max_layers, or
    - builder stop condition triggers.

    This is the "objective" way to keep upper abstractions consistent after daily incremental updates,
    without touching leaf or layer-1 membership logic.
    """
    if start_layer not in tree.layer_to_nodes:
        raise ValueError(f"Tree missing start_layer {start_layer}")

    # Remove existing upper layers from all_nodes to prevent unbounded growth.
    layers_to_remove = [l for l in tree.layer_to_nodes.keys() if l > start_layer]
    remove_indices: Set[int] = set()
    for l in layers_to_remove:
        for n in tree.layer_to_nodes.get(l, []):
            remove_indices.add(n.index)
    for idx in remove_indices:
        tree.all_nodes.pop(idx, None)

    # Reset layer_to_nodes to only <= start_layer
    tree.layer_to_nodes = {
        l: tree.layer_to_nodes[l]
        for l in sorted(tree.layer_to_nodes.keys())
        if l <= start_layer
    }
    tree.num_layers = start_layer
    tree.root_nodes = tree.layer_to_nodes[start_layer]

    current_nodes: List[Node] = list(tree.root_nodes)
    layer = start_layer

    while layer < max_layers and len(current_nodes) > target_top_nodes:
        # Builder stop condition
        if len(current_nodes) <= builder.reduction_dimension + 1:
            break

        clusters = builder.clustering_algorithm.perform_clustering(
            current_nodes,
            builder.cluster_embedding_model,
            reduction_dimension=builder.reduction_dimension,
            **builder.clustering_params,
        )

        next_layer_nodes: List[Node] = []
        next_idx = max(tree.all_nodes.keys()) + 1 if tree.all_nodes else 0

        for cluster in clusters:
            # Hard cap on children per parent to avoid pathological parents.
            if (
                hard_max_children_per_parent is not None
                and len(cluster) > hard_max_children_per_parent
            ):
                # Split deterministically into chunks. This is a fallback, not a perfect clustering.
                for i in range(0, len(cluster), hard_max_children_per_parent):
                    sub = cluster[i : i + hard_max_children_per_parent]
                    node_texts = get_text_for_summary(sub)
                    target_layer = layer + 1
                    summary = builder.summarize(
                        node_texts,
                        max_tokens=builder.summarization_length_for_layer(
                            target_layer, default=builder.summarization_length
                        ),
                        layer=target_layer,
                    )
                    __, new_parent = builder.create_node(
                        next_idx, summary, {n.index for n in sub}
                    )
                    tree.all_nodes[next_idx] = new_parent
                    next_layer_nodes.append(new_parent)
                    next_idx += 1
                continue

            node_texts = get_text_for_summary(cluster)
            target_layer = layer + 1
            summary = builder.summarize(
                node_texts,
                max_tokens=builder.summarization_length_for_layer(
                    target_layer, default=builder.summarization_length
                ),
                layer=target_layer,
            )
            __, new_parent = builder.create_node(
                next_idx, summary, {n.index for n in cluster}
            )
            tree.all_nodes[next_idx] = new_parent
            next_layer_nodes.append(new_parent)
            next_idx += 1

        layer += 1
        tree.layer_to_nodes[layer] = next_layer_nodes
        tree.num_layers = layer
        tree.root_nodes = next_layer_nodes
        current_nodes = next_layer_nodes


def _find_best_parent_in_layer(
    node: Node,
    layer_nodes: List[Node],
    embedding_key: str,
    threshold: float,
) -> Tuple[Optional[Node], float]:
    """
    Find the best matching parent node in a layer by cosine similarity.
    Returns (best_parent, similarity) or (None, -1) if no good match.
    """
    node_emb = node.embeddings.get(embedding_key)
    if node_emb is None:
        return None, -1.0

    best_parent: Optional[Node] = None
    best_sim: float = -1.0

    for parent in layer_nodes:
        p_emb = parent.embeddings.get(embedding_key)
        if p_emb is None:
            continue
        sim = _cosine_similarity(node_emb, p_emb)
        if sim > best_sim:
            best_sim = sim
            best_parent = parent

    if best_sim < threshold:
        return None, best_sim

    return best_parent, best_sim


def propagate_changes_upward(
    *,
    tree: Tree,
    affected_nodes: List[Node],
    start_layer: int,
    cfg: IncrementalUpdateConfig,
    tokenizer,
    summarizer,
    embedder_map: Dict[str, object],
    summarization_length: int,
) -> Tuple[Set[int], List[int]]:
    """
    Propagate changes from affected nodes upward through the tree, layer by layer.

    This is the SAFE incremental update that never deletes existing structure.
    For each affected node at layer N:
    1. Find best parent at layer N+1 by similarity
    2. If good match: attach and update parent's summary/embedding
    3. If no match: create new parent node at layer N+1
    4. Repeat for layer N+1 until reaching top layer

    Returns:
        updated_indices: Set of node indices that were updated
        created_indices: List of newly created node indices
    """
    updated_indices: Set[int] = set()
    created_indices: List[int] = []

    current_affected = affected_nodes
    current_layer = start_layer

    while current_affected and current_layer < tree.num_layers:
        next_layer = current_layer + 1
        next_affected: List[Node] = []

        # Get nodes at next layer
        if next_layer not in tree.layer_to_nodes:
            # No more layers - affected nodes become new roots
            # We need to create a new layer or extend the top
            logger.info(
                f"Creating new layer {next_layer} for {len(current_affected)} nodes"
            )
            tree.layer_to_nodes[next_layer] = []
            tree.num_layers = next_layer

        layer_nodes = tree.layer_to_nodes[next_layer]
        layer_node_map = {n.index: n for n in layer_nodes}

        for node in current_affected:
            best_parent, sim = _find_best_parent_in_layer(
                node, layer_nodes, cfg.embedding_key, cfg.similarity_threshold
            )

            if best_parent is not None:
                # Attach to existing parent
                if node.index not in best_parent.children:
                    best_parent.children.add(node.index)
                    updated_indices.add(best_parent.index)

                    # Update parent's summary and embedding
                    child_list = sorted(list(best_parent.children))
                    context = _collect_child_texts_for_summary(
                        tree,
                        child_list,
                        tokenizer=tokenizer,
                        max_tokens=cfg.max_summary_context_tokens,
                        max_children=cfg.max_children_for_summary,
                    )
                    if hasattr(summarizer, "summarize_layer"):
                        summary = summarizer.summarize_layer(
                            context, layer=next_layer, max_tokens=summarization_length
                        )
                    else:
                        summary = summarizer.summarize(
                            context, max_tokens=summarization_length
                        )
                    best_parent.text = summary
                    best_parent.embeddings = {
                        model_name: model.create_embedding(summary)
                        for model_name, model in embedder_map.items()
                    }

                    # This parent is now affected and needs to propagate
                    if best_parent not in next_affected:
                        next_affected.append(best_parent)
            else:
                # Create new parent node
                new_parent_idx = max(tree.all_nodes.keys()) + 1

                child_text = (node.text or "").strip()
                if hasattr(summarizer, "summarize_layer"):
                    summary = summarizer.summarize_layer(
                        child_text, layer=next_layer, max_tokens=summarization_length
                    )
                else:
                    summary = summarizer.summarize(
                        child_text, max_tokens=summarization_length
                    )

                embeddings = {
                    model_name: model.create_embedding(summary)
                    for model_name, model in embedder_map.items()
                }

                new_parent = Node(
                    text=summary,
                    index=new_parent_idx,
                    children={node.index},
                    embeddings=embeddings,
                )

                tree.all_nodes[new_parent_idx] = new_parent
                tree.layer_to_nodes[next_layer].append(new_parent)
                layer_node_map[new_parent_idx] = new_parent
                created_indices.append(new_parent_idx)

                # New parent needs to propagate upward
                next_affected.append(new_parent)

        current_affected = next_affected
        current_layer = next_layer

    # Update root_nodes to point to the top layer
    tree.root_nodes = tree.layer_to_nodes[tree.num_layers]

    return updated_indices, created_indices


def incremental_add_with_propagation(
    *,
    tree: Tree,
    new_leaf_nodes: Dict[int, Node],
    cfg: IncrementalUpdateConfig,
    tokenizer,
    summarizer,
    embedder_map: Dict[str, object],
    summarization_length: int,
) -> Tuple[Set[int], List[int]]:
    """
    Add new leaf nodes and propagate changes through ALL layers of the tree.

    This is the improved incremental update that:
    1. Adds leaves to layer 0
    2. For each leaf, finds/creates parent at layer 1
    3. Propagates changes upward through layers 2, 3, ... N
    4. NEVER deletes existing structure

    Returns:
        updated_indices: Set of node indices that were updated
        created_indices: List of newly created node indices
    """
    # Ensure layer structures exist
    if tree.layer_to_nodes.get(0) is None:
        tree.layer_to_nodes[0] = []
    if tree.layer_to_nodes.get(1) is None:
        tree.layer_to_nodes[1] = []

    # Add leaves to layer 0
    for idx, node in new_leaf_nodes.items():
        tree.leaf_nodes[idx] = node
        tree.all_nodes[idx] = node
        tree.layer_to_nodes[0].append(node)

    logger.info(f"Added {len(new_leaf_nodes)} new leaf nodes to layer 0")

    # First pass: attach leaves to layer 1 parents
    layer1_nodes = tree.layer_to_nodes[1]
    layer1_map = {n.index: n for n in layer1_nodes}

    updated_indices: Set[int] = set()
    created_indices: List[int] = []
    affected_layer1: List[Node] = []

    for leaf_idx, leaf_node in new_leaf_nodes.items():
        best_parent, sim = _find_best_parent_in_layer(
            leaf_node, layer1_nodes, cfg.embedding_key, cfg.similarity_threshold
        )

        if best_parent is not None:
            # Attach to existing parent
            best_parent.children.add(leaf_idx)
            updated_indices.add(best_parent.index)

            # Update parent's summary
            child_list = sorted(list(best_parent.children))
            context = _collect_child_texts_for_summary(
                tree,
                child_list,
                tokenizer=tokenizer,
                max_tokens=cfg.max_summary_context_tokens,
                max_children=cfg.max_children_for_summary,
            )
            if hasattr(summarizer, "summarize_layer"):
                summary = summarizer.summarize_layer(
                    context, layer=1, max_tokens=summarization_length
                )
            else:
                summary = summarizer.summarize(context, max_tokens=summarization_length)
            best_parent.text = summary
            best_parent.embeddings = {
                model_name: model.create_embedding(summary)
                for model_name, model in embedder_map.items()
            }

            if best_parent not in affected_layer1:
                affected_layer1.append(best_parent)
        else:
            # Create new layer 1 parent
            new_parent_idx = max(tree.all_nodes.keys()) + 1

            child_text = (leaf_node.text or "").strip()
            if hasattr(summarizer, "summarize_layer"):
                summary = summarizer.summarize_layer(
                    child_text, layer=1, max_tokens=summarization_length
                )
            else:
                summary = summarizer.summarize(
                    child_text, max_tokens=summarization_length
                )

            embeddings = {
                model_name: model.create_embedding(summary)
                for model_name, model in embedder_map.items()
            }

            new_parent = Node(
                text=summary,
                index=new_parent_idx,
                children={leaf_idx},
                embeddings=embeddings,
            )

            tree.all_nodes[new_parent_idx] = new_parent
            tree.layer_to_nodes[1].append(new_parent)
            layer1_map[new_parent_idx] = new_parent
            layer1_nodes.append(new_parent)  # Add to list for future lookups
            created_indices.append(new_parent_idx)
            affected_layer1.append(new_parent)

    logger.info(
        f"Layer 1: updated {len(updated_indices)} parents, created {len(created_indices)} new parents"
    )

    # Propagate changes upward through remaining layers
    if tree.num_layers > 1 and affected_layer1:
        logger.info(f"Propagating changes through layers 2-{tree.num_layers}")
        upper_updated, upper_created = propagate_changes_upward(
            tree=tree,
            affected_nodes=affected_layer1,
            start_layer=1,
            cfg=cfg,
            tokenizer=tokenizer,
            summarizer=summarizer,
            embedder_map=embedder_map,
            summarization_length=summarization_length,
        )
        updated_indices.update(upper_updated)
        created_indices.extend(upper_created)

    logger.info(
        f"Incremental update complete: {len(updated_indices)} updated, {len(created_indices)} created"
    )

    return updated_indices, created_indices


def merge_trees(
    *,
    target_tree: Tree,
    source_tree: Tree,
    cfg: IncrementalUpdateConfig,
    tokenizer,
    summarizer,
    embedder_map: Dict[str, object],
    summarization_length: int,
) -> Tuple[Set[int], List[int]]:
    """
    Merge a source tree into a target tree.

    This function takes all leaf nodes from source_tree and integrates them
    into target_tree using the layer-by-layer propagation approach.

    The source tree's non-leaf nodes are NOT copied - instead, new parent
    relationships are formed based on similarity to existing target tree nodes.

    Args:
        target_tree: The tree to merge INTO (will be modified)
        source_tree: The tree to merge FROM (will not be modified)
        cfg: Configuration for the merge
        tokenizer: Tokenizer for text processing
        summarizer: Summarization model
        embedder_map: Embedding models
        summarization_length: Max tokens for summaries

    Returns:
        updated_indices: Set of node indices that were updated in target_tree
        created_indices: List of newly created node indices in target_tree
    """
    logger.info(
        f"Merging source tree ({len(source_tree.leaf_nodes)} leaves) into target tree ({len(target_tree.leaf_nodes)} leaves)"
    )

    # Re-index source leaf nodes to avoid conflicts
    next_idx = max(target_tree.all_nodes.keys()) + 1
    new_leaf_nodes: Dict[int, Node] = {}

    for old_idx, node in source_tree.leaf_nodes.items():
        # Create new node with new index but same content
        new_node = Node(
            text=node.text,
            index=next_idx,
            children=set(),  # Leaf nodes have no children
            embeddings=dict(node.embeddings),  # Copy embeddings
            keywords=list(node.keywords) if node.keywords else [],
            metadata=dict(node.metadata) if node.metadata else {},
            original_content_ref=node.original_content_ref,
        )
        new_leaf_nodes[next_idx] = new_node
        next_idx += 1

    logger.info(f"Re-indexed {len(new_leaf_nodes)} source leaf nodes")

    # Use the improved incremental add to merge
    return incremental_add_with_propagation(
        tree=target_tree,
        new_leaf_nodes=new_leaf_nodes,
        cfg=cfg,
        tokenizer=tokenizer,
        summarizer=summarizer,
        embedder_map=embedder_map,
        summarization_length=summarization_length,
    )
