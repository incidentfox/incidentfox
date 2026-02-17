import logging
import os
import pickle
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Dict, List

from .cluster_utils import RAPTOR_Clustering
from .tree_builder import TreeBuilder, TreeBuilderConfig, _summary_max_workers
from .tree_structures import Node, Tree
from .utils import (
    get_node_list,
    get_text_for_summary,
)

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


def _progress_enabled() -> bool:
    return os.environ.get("RAPTOR_PROGRESS", "").strip() not in (
        "",
        "0",
        "false",
        "False",
    )


class ClusterTreeConfig(TreeBuilderConfig):
    def __init__(
        self,
        reduction_dimension=10,
        clustering_algorithm=RAPTOR_Clustering,  # Default to RAPTOR clustering
        clustering_params={},  # Pass additional params as a dict
        # Auto-depth controls
        auto_depth: bool = False,
        target_top_nodes: int = 75,
        max_layers: int = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.reduction_dimension = reduction_dimension
        self.clustering_algorithm = clustering_algorithm
        self.clustering_params = clustering_params
        self.auto_depth = auto_depth
        self.target_top_nodes = target_top_nodes
        self.max_layers = max_layers

    def log_config(self):
        base_summary = super().log_config()
        cluster_tree_summary = f"""
        Reduction Dimension: {self.reduction_dimension}
        Clustering Algorithm: {self.clustering_algorithm.__name__}
        Clustering Parameters: {self.clustering_params}
        Auto Depth: {self.auto_depth}
        Target Top Nodes: {self.target_top_nodes}
        Max Layers (auto): {self.max_layers}
        """
        return base_summary + cluster_tree_summary


class ClusterTreeBuilder(TreeBuilder):
    def __init__(self, config) -> None:
        super().__init__(config)

        if not isinstance(config, ClusterTreeConfig):
            raise ValueError("config must be an instance of ClusterTreeConfig")
        self.reduction_dimension = config.reduction_dimension
        self.clustering_algorithm = config.clustering_algorithm
        self.clustering_params = config.clustering_params
        self.auto_depth = getattr(config, "auto_depth", False)
        self.target_top_nodes = getattr(config, "target_top_nodes", 75)
        self.max_layers_auto = getattr(config, "max_layers", None)

        logging.info(
            f"Successfully initialized ClusterTreeBuilder with Config {config.log_config()}"
        )

    def construct_tree(
        self,
        current_level_nodes: Dict[int, Node],
        all_tree_nodes: Dict[int, Node],
        layer_to_nodes: Dict[int, List[Node]],
        use_multithreading: bool = False,
    ) -> Dict[int, Node]:
        logging.info("Using Cluster TreeBuilder")

        next_node_index = len(all_tree_nodes)
        checkpoint_dir = os.environ.get("RAPTOR_TREE_CHECKPOINT_DIR", "").strip()

        def _aggregate_provenance(cluster_nodes) -> Dict[str, Any]:
            """
            Best-effort provenance aggregation.

            Leaves may have:
            - node.original_content_ref (e.g. source URL)
            - node.metadata (dict) containing source_url/rel_path/doc_id/etc

            Parents will store:
            - metadata["citations"]: top unique sources with counts
            - metadata["citation_total"]: total child references considered
            """
            counts: Dict[str, int] = {}
            details: Dict[str, Dict[str, Any]] = {}
            total = 0
            for n in cluster_nodes:
                ref = getattr(n, "original_content_ref", None) or None
                md = getattr(n, "metadata", None)
                if isinstance(md, dict):
                    ref = (
                        ref
                        or md.get("source_url")
                        or md.get("original_content_ref")
                        or None
                    )
                if not ref:
                    continue
                ref_s = str(ref)
                counts[ref_s] = counts.get(ref_s, 0) + 1
                total += 1
                if ref_s not in details:
                    details[ref_s] = {}
                    if isinstance(md, dict):
                        # Keep a few useful fields if present
                        for k in ("rel_path", "doc_id", "domain", "subject"):
                            if k in md:
                                details[ref_s][k] = md.get(k)

            # Top-N citations for UI/answers
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
            citations = []
            for ref_s, c in top:
                item = {"ref": ref_s, "count": int(c)}
                item.update(details.get(ref_s, {}))
                citations.append(item)

            return {"citations": citations, "citation_total": int(total)}

        def process_cluster(
            cluster, new_level_nodes, next_node_index, summarization_length, lock
        ):
            node_texts = get_text_for_summary(cluster)

            summarized_text = self.summarize(
                context=node_texts,
                max_tokens=summarization_length,
                layer=layer + 1,
            )

            logging.info(
                f"Node Texts Length: {len(self.tokenizer.encode(node_texts))}, Summarized Text Length: {len(self.tokenizer.encode(summarized_text))}"
            )

            __, new_parent_node = self.create_node(
                next_node_index,
                summarized_text,
                {node.index for node in cluster},
                metadata=_aggregate_provenance(cluster),
            )

            with lock:
                new_level_nodes[next_node_index] = new_parent_node

        max_layers = (
            self.max_layers_auto
            if self.max_layers_auto is not None
            else self.num_layers
        )

        layer = 0
        # If auto_depth is enabled, keep building until top layer is small enough (or we hit limits).
        # Otherwise build exactly `self.num_layers` layers (unless early stop triggers).
        while layer < max_layers:

            new_level_nodes = {}

            logging.info(f"Constructing Layer {layer}")

            node_list_current_layer = get_node_list(current_level_nodes)
            if _progress_enabled():
                logging.info(
                    f"Layer {layer}: current_nodes={len(node_list_current_layer)} next_node_index={next_node_index}"
                )

            if (
                self.auto_depth
                and layer > 0
                and len(node_list_current_layer) <= self.target_top_nodes
            ):
                logging.info(
                    f"Auto-depth stop: top layer size {len(node_list_current_layer)} <= target_top_nodes {self.target_top_nodes}"
                )
                self.num_layers = layer
                break

            if len(node_list_current_layer) <= self.reduction_dimension + 1:
                self.num_layers = layer
                logging.info(
                    f"Stopping Layer construction: Cannot Create More Layers. Total Layers in tree: {layer}"
                )
                break

            clusters = self.clustering_algorithm.perform_clustering(
                node_list_current_layer,
                self.cluster_embedding_model,
                reduction_dimension=self.reduction_dimension,
                **self.clustering_params,
            )
            if _progress_enabled():
                logging.info(f"Layer {layer}: clusters={len(clusters)}")

            lock = Lock()

            target_layer = layer + 1
            summarization_length = self.summarization_length_for_layer(
                target_layer, default=self.summarization_length
            )
            logging.info(
                f"Summarization Length (target_layer={target_layer}): {summarization_length}"
            )

            use_progress = _progress_enabled()
            pbar = None
            if use_progress:
                try:
                    from tqdm.auto import tqdm  # type: ignore

                    pbar = tqdm(
                        total=len(clusters),
                        desc=f"RAPTOR layer {layer} summaries",
                        unit="cluster",
                    )
                except Exception:
                    pbar = None

            if use_multithreading:
                max_workers = _summary_max_workers()
                if _progress_enabled():
                    logging.info(
                        f"Layer {layer} summarization concurrency: max_workers={max_workers}"
                    )
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = []
                    for cluster in clusters:
                        futures.append(
                            executor.submit(
                                process_cluster,
                                cluster,
                                new_level_nodes,
                                next_node_index,
                                summarization_length,
                                lock,
                            )
                        )
                        next_node_index += 1
                    for i, f in enumerate(futures, start=1):
                        f.result()
                        if pbar is not None:
                            pbar.update(1)
                        elif use_progress and i % 250 == 0:
                            logging.info(
                                f"Layer {layer} summaries progress: {i}/{len(clusters)}"
                            )
                    executor.shutdown(wait=True)

            else:
                for i, cluster in enumerate(clusters, start=1):
                    process_cluster(
                        cluster,
                        new_level_nodes,
                        next_node_index,
                        summarization_length,
                        lock,
                    )
                    next_node_index += 1
                    if pbar is not None:
                        pbar.update(1)
                    elif use_progress and i % 250 == 0:
                        logging.info(
                            f"Layer {layer} summaries progress: {i}/{len(clusters)}"
                        )

            if pbar is not None:
                pbar.close()

            layer_to_nodes[layer + 1] = list(new_level_nodes.values())
            current_level_nodes = new_level_nodes
            all_tree_nodes.update(new_level_nodes)

            tree = Tree(
                all_tree_nodes,
                layer_to_nodes[layer + 1],
                layer_to_nodes[0],
                layer + 1,
                layer_to_nodes,
            )

            # Optional per-layer checkpoint for true resume artifacts.
            # This does NOT (yet) resume mid-build automatically, but it preserves work so you
            # can at least recover a valid tree snapshot up to the last completed layer.
            if checkpoint_dir:
                try:
                    os.makedirs(checkpoint_dir, exist_ok=True)
                    ckpt_path = os.path.join(
                        checkpoint_dir, f"tree_layer_{layer+1}.pkl"
                    )
                    with open(ckpt_path, "wb") as f:
                        pickle.dump(tree, f)
                    if _progress_enabled():
                        logging.info(f"[checkpoint] wrote {ckpt_path}")
                except Exception as e:
                    logging.warning(
                        f"[checkpoint] failed to write layer checkpoint: {e}"
                    )

            layer += 1

        # If we finished all layers without early stop, ensure num_layers reflects actual built depth.
        if layer == max_layers:
            self.num_layers = max_layers

        return current_level_nodes
