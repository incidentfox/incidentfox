import logging
import random
import time
from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np
import tiktoken
import umap
from sklearn.mixture import GaussianMixture

# Initialize logging
logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)

from .tree_structures import Node

# Import necessary methods from other modules


def _seed() -> int:
    import os

    raw = os.environ.get("RAPTOR_RANDOM_SEED", "").strip()
    if raw:
        try:
            return int(raw)
        except Exception:
            pass
    return 224


def _set_global_seeds(seed: int) -> None:
    # Best-effort determinism:
    # - python random
    # - numpy
    # (Other libs may have additional sources of nondeterminism.)
    random.seed(int(seed))
    try:
        np.random.seed(int(seed))
    except Exception:
        pass


def _progress_enabled() -> bool:
    import os

    return os.environ.get("RAPTOR_PROGRESS", "").strip() not in (
        "",
        "0",
        "false",
        "False",
    )


def global_cluster_embeddings(
    embeddings: np.ndarray,
    dim: int,
    n_neighbors: Optional[int] = None,
    metric: str = "cosine",
    random_state: Optional[int] = None,
) -> np.ndarray:
    n = len(embeddings)
    # Need at least 4 points for UMAP with n_neighbors >= 2
    if n <= 3:
        if _progress_enabled():
            logging.info(f"[clustering] UMAP global skip: n={n} too small")
        return embeddings[:, : min(dim, embeddings.shape[1])]

    if n_neighbors is None:
        n_neighbors = int((n - 1) ** 0.5)
    # Clamp n_neighbors to valid range
    n_neighbors = max(2, min(n_neighbors, n - 1))

    if _progress_enabled():
        logging.info(
            f"[clustering] UMAP global start: n={n} n_neighbors={n_neighbors} dim={dim} metric={metric}"
        )
        t0 = time.time()
    rs = _seed() if random_state is None else int(random_state)
    _set_global_seeds(rs)
    reduced_embeddings = umap.UMAP(
        n_neighbors=n_neighbors, n_components=dim, metric=metric, random_state=rs
    ).fit_transform(embeddings)
    if _progress_enabled():
        logging.info(f"[clustering] UMAP global done in {time.time() - t0:.2f}s")
    return reduced_embeddings


def local_cluster_embeddings(
    embeddings: np.ndarray,
    dim: int,
    num_neighbors: int = 10,
    metric: str = "cosine",
    random_state: Optional[int] = None,
) -> np.ndarray:
    n = len(embeddings)
    # n_neighbors must be >= 2 and < n
    # If cluster is too small, skip UMAP and return identity (no dimensionality reduction)
    if n <= 3:
        if _progress_enabled():
            logging.info(f"[clustering] UMAP local skip: n={n} too small")
        return embeddings[:, : min(dim, embeddings.shape[1])]

    # Clamp n_neighbors to valid range
    actual_neighbors = max(2, min(num_neighbors, n - 1))

    if _progress_enabled():
        logging.info(
            f"[clustering] UMAP local start: n={n} n_neighbors={actual_neighbors} dim={dim} metric={metric}"
        )
        t0 = time.time()
    rs = _seed() if random_state is None else int(random_state)
    _set_global_seeds(rs)
    reduced_embeddings = umap.UMAP(
        n_neighbors=actual_neighbors, n_components=dim, metric=metric, random_state=rs
    ).fit_transform(embeddings)
    if _progress_enabled():
        logging.info(f"[clustering] UMAP local done in {time.time() - t0:.2f}s")
    return reduced_embeddings


def get_optimal_clusters(
    embeddings: np.ndarray, max_clusters: int = 50, random_state: Optional[int] = None
) -> int:
    rs = _seed() if random_state is None else int(random_state)
    _set_global_seeds(rs)
    max_clusters = min(max_clusters, len(embeddings))
    n_clusters = np.arange(1, max_clusters)
    bics = []
    use_progress = _progress_enabled()
    t0 = time.time()
    for n in n_clusters:
        gm = GaussianMixture(n_components=n, random_state=rs)
        gm.fit(embeddings)
        bics.append(gm.bic(embeddings))
        if use_progress and (n in (1, 2, 5, 10, 20, 30, 40) or (n == max_clusters - 1)):
            logging.info(f"[clustering] GMM BIC sweep progress: {n}/{max_clusters - 1}")
    optimal_clusters = n_clusters[np.argmin(bics)]
    if use_progress:
        logging.info(
            f"[clustering] GMM BIC sweep done in {time.time() - t0:.2f}s; optimal_clusters={optimal_clusters}"
        )
    return optimal_clusters


def GMM_cluster(
    embeddings: np.ndarray,
    threshold: float,
    random_state: Optional[int] = None,
    max_clusters: int = 50,
):
    if _progress_enabled():
        logging.info(
            f"[clustering] GMM_cluster start: n={len(embeddings)} threshold={threshold}"
        )
        t0 = time.time()
    rs = _seed() if random_state is None else int(random_state)
    _set_global_seeds(rs)
    n_clusters = get_optimal_clusters(
        embeddings, max_clusters=max_clusters, random_state=rs
    )
    gm = GaussianMixture(n_components=n_clusters, random_state=rs)
    gm.fit(embeddings)
    probs = gm.predict_proba(embeddings)
    labels = [np.where(prob > threshold)[0] for prob in probs]
    if _progress_enabled():
        logging.info(
            f"[clustering] GMM_cluster done in {time.time() - t0:.2f}s; n_clusters={n_clusters}"
        )
    return labels, n_clusters


def perform_clustering(
    embeddings: np.ndarray,
    dim: int,
    threshold: float,
    verbose: bool = False,
    max_clusters: int = 50,
    random_state: Optional[int] = None,
) -> List[np.ndarray]:
    """
    Cluster embeddings using global UMAP + GMM, then local UMAP + GMM per global cluster.

    MEMORY FIX: We track original indices throughout instead of doing expensive
    broadcast comparisons like (embeddings == subset[:, None]).all(-1) which
    creates O(n * m * d) intermediate arrays and causes OOM on large datasets.
    """
    rs = _seed() if random_state is None else int(random_state)
    _set_global_seeds(rs)

    n = len(embeddings)

    # Cannot cluster fewer than 4 points meaningfully
    if n <= 3:
        if verbose:
            logging.info(f"[clustering] Skip: only {n} points, returning single cluster")
        # Return all points in a single cluster
        return [np.array([0]) for _ in range(n)]

    # Ensure dimension is at least 1
    effective_dim = max(1, min(dim, n - 2))
    reduced_embeddings_global = global_cluster_embeddings(
        embeddings, effective_dim, random_state=rs
    )
    global_clusters, n_global_clusters = GMM_cluster(
        reduced_embeddings_global, threshold, max_clusters=max_clusters, random_state=rs
    )

    if verbose:
        logging.info(f"Global Clusters: {n_global_clusters}")

    all_local_clusters = [np.array([]) for _ in range(n)]
    total_clusters = 0

    for i in range(n_global_clusters):
        # Get indices of points in this global cluster
        global_mask = np.array([i in gc for gc in global_clusters])
        global_indices = np.where(global_mask)[0]

        if verbose:
            logging.info(f"Nodes in Global Cluster {i}: {len(global_indices)}")
        if len(global_indices) == 0:
            continue

        global_cluster_embeddings_ = embeddings[global_indices]

        if len(global_indices) <= dim + 1:
            local_clusters = [np.array([0]) for _ in global_indices]
            n_local_clusters = 1
        else:
            reduced_embeddings_local = local_cluster_embeddings(
                global_cluster_embeddings_, dim, random_state=rs
            )
            local_clusters, n_local_clusters = GMM_cluster(
                reduced_embeddings_local,
                threshold,
                max_clusters=max_clusters,
                random_state=rs,
            )

        if verbose:
            logging.info(f"Local Clusters in Global Cluster {i}: {n_local_clusters}")

        # Assign local cluster labels - track indices directly, no broadcast comparison
        for j in range(n_local_clusters):
            # Find which points within this global cluster belong to local cluster j
            local_mask = np.array([j in lc for lc in local_clusters])
            local_subset_indices = np.where(local_mask)[0]

            # Map back to original indices
            original_indices = global_indices[local_subset_indices]

            for idx in original_indices:
                all_local_clusters[idx] = np.append(
                    all_local_clusters[idx], j + total_clusters
                )

        total_clusters += n_local_clusters

    if verbose:
        logging.info(f"Total Clusters: {total_clusters}")
    return all_local_clusters


class ClusteringAlgorithm(ABC):
    @abstractmethod
    def perform_clustering(self, embeddings: np.ndarray, **kwargs) -> List[List[int]]:
        pass


class RAPTOR_Clustering(ClusteringAlgorithm):
    def perform_clustering(
        nodes: List[Node],
        embedding_model_name: str,
        max_length_in_cluster: int = 3500,
        tokenizer=tiktoken.get_encoding("cl100k_base"),
        reduction_dimension: int = 10,
        threshold: float = 0.1,
        max_clusters: int = 50,
        verbose: bool = False,
        random_state: Optional[int] = None,
    ) -> List[List[Node]]:
        """
        Cluster `nodes` using RAPTOR's global+local UMAP+GMM scheme.

        If `max_length_in_cluster` is set and a cluster exceeds it, attempt to recluster that
        cluster into smaller clusters. Importantly, we must **never** recurse indefinitely:
        if reclustering fails to split the cluster, we keep it as-is.
        """

        def _total_tokens(ns: List[Node]) -> int:
            # Tokenization can be expensive; only called for clusters we might split.
            return int(sum(len(tokenizer.encode(n.text)) for n in ns))

        # Treat non-positive / None-ish values as "disable reclustering".
        try:
            max_len = (
                int(max_length_in_cluster) if max_length_in_cluster is not None else 0
            )
        except Exception:
            max_len = 0

        pending: List[List[Node]] = [nodes]
        out: List[List[Node]] = []
        seen: set = set()

        while pending:
            cur_nodes = pending.pop()

            if len(cur_nodes) <= 1 or max_len <= 0:
                out.append(cur_nodes)
                continue

            key = frozenset(getattr(n, "index", id(n)) for n in cur_nodes)
            if key in seen:
                # We've already tried splitting this exact set; keep it to avoid infinite loops.
                out.append(cur_nodes)
                continue
            seen.add(key)

            total_len = _total_tokens(cur_nodes)
            if total_len <= max_len:
                out.append(cur_nodes)
                continue

            if verbose:
                logging.info(
                    f"[clustering] recluster attempt: nodes={len(cur_nodes)} total_tokens={total_len} max_length_in_cluster={max_len}"
                )

            # Run ONE round of clustering on the current set.
            rs = _seed() if random_state is None else int(random_state)
            _set_global_seeds(rs)

            # Stable ordering reduces nondeterminism across reruns.
            cur_nodes = sorted(cur_nodes, key=lambda n: int(getattr(n, "index", 0)))
            embeddings = np.array(
                [node.embeddings[embedding_model_name] for node in cur_nodes]
            )
            labels_per_point = perform_clustering(
                embeddings,
                dim=reduction_dimension,
                threshold=threshold,
                max_clusters=max_clusters,
                random_state=rs,
            )

            # Guard: if clustering produced no labels (shouldn't happen), keep as-is.
            try:
                all_labels = np.unique(np.concatenate(labels_per_point))
            except Exception:
                all_labels = np.array([])

            if len(all_labels) == 0:
                out.append(cur_nodes)
                continue

            new_clusters: List[List[Node]] = []
            for label in all_labels:
                idxs = [i for i, labs in enumerate(labels_per_point) if label in labs]
                if not idxs:
                    continue
                new_clusters.append([cur_nodes[i] for i in idxs])

            # Critical stop condition: if we didn't actually split, do NOT try again.
            # (This was the source of the infinite recursion / RecursionError.)
            if len(new_clusters) <= 1:
                if verbose:
                    logging.info(
                        f"[clustering] recluster produced <=1 clusters; keeping unsplit cluster (nodes={len(cur_nodes)} total_tokens={total_len})"
                    )
                out.append(cur_nodes)
                continue

            # Otherwise, push subclusters for possible further splitting.
            pending.extend(new_clusters)

        return out
