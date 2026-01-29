import copy
import logging
import os
from abc import abstractclassmethod
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import tiktoken

from .EmbeddingModels import BaseEmbeddingModel, OpenAIEmbeddingModel
from .SummarizationModels import BaseSummarizationModel, GPT3TurboSummarizationModel
from .tree_structures import Node, Tree
from .utils import (
    distances_from_embeddings,
    get_embeddings,
    indices_of_nearest_neighbors_from_distances,
    split_text,
)

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


def _progress_enabled() -> bool:
    # Enable progress bars/logging by setting RAPTOR_PROGRESS=1
    return os.environ.get("RAPTOR_PROGRESS", "").strip() not in (
        "",
        "0",
        "false",
        "False",
    )


def _summary_max_workers() -> int:
    """
    Control concurrency for cluster summarization (chat completions).
    Set RAPTOR_SUMMARY_MAX_WORKERS (e.g. 2, 4, 8). Default is conservative.
    """
    raw = os.environ.get("RAPTOR_SUMMARY_MAX_WORKERS", "").strip()
    if raw:
        try:
            v = int(raw)
            if v >= 1:
                return v
        except Exception:
            pass
    # Chat completions are easier to rate-limit than embeddings; keep this conservative by default.
    return 2


class TreeBuilderConfig:
    def __init__(
        self,
        tokenizer=None,
        max_tokens=None,
        num_layers=None,
        threshold=None,
        top_k=None,
        selection_mode=None,
        summarization_length=None,
        summarization_model=None,
        embedding_models=None,
        cluster_embedding_model=None,
        # Optional chunker for build_from_text; defaults to utils.split_text
        chunker=None,
        # Optional per-layer summary controls
        summarization_length_by_layer=None,  # Dict[int,int]
    ):
        if tokenizer is None:
            tokenizer = tiktoken.get_encoding("cl100k_base")
        self.tokenizer = tokenizer

        if max_tokens is None:
            max_tokens = 100
        if not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("max_tokens must be an integer and at least 1")
        self.max_tokens = max_tokens

        if num_layers is None:
            num_layers = 5
        if not isinstance(num_layers, int) or num_layers < 1:
            raise ValueError("num_layers must be an integer and at least 1")
        self.num_layers = num_layers

        if threshold is None:
            threshold = 0.5
        if not isinstance(threshold, (int, float)) or not (0 <= threshold <= 1):
            raise ValueError("threshold must be a number between 0 and 1")
        self.threshold = threshold

        if top_k is None:
            top_k = 5
        if not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be an integer and at least 1")
        self.top_k = top_k

        if selection_mode is None:
            selection_mode = "top_k"
        if selection_mode not in ["top_k", "threshold"]:
            raise ValueError("selection_mode must be either 'top_k' or 'threshold'")
        self.selection_mode = selection_mode

        if summarization_length is None:
            summarization_length = 100
        self.summarization_length = summarization_length
        self.summarization_length_by_layer = dict(summarization_length_by_layer or {})

        if summarization_model is None:
            summarization_model = GPT3TurboSummarizationModel()
        if not isinstance(summarization_model, BaseSummarizationModel):
            raise ValueError(
                "summarization_model must be an instance of BaseSummarizationModel"
            )
        self.summarization_model = summarization_model

        if embedding_models is None:
            embedding_models = {"OpenAI": OpenAIEmbeddingModel()}
        if not isinstance(embedding_models, dict):
            raise ValueError(
                "embedding_models must be a dictionary of model_name: instance pairs"
            )
        for model in embedding_models.values():
            if not isinstance(model, BaseEmbeddingModel):
                raise ValueError(
                    "All embedding models must be an instance of BaseEmbeddingModel"
                )
        self.embedding_models = embedding_models

        if cluster_embedding_model is None:
            cluster_embedding_model = "OpenAI"
        if cluster_embedding_model not in self.embedding_models:
            raise ValueError(
                "cluster_embedding_model must be a key in the embedding_models dictionary"
            )
        self.cluster_embedding_model = cluster_embedding_model

        # Allow callers (e.g. ingest scripts) to choose a semantic/structure-aware chunker.
        # Must have signature: (text, tokenizer, max_tokens) -> List[str]
        self.chunker = chunker or split_text

    def log_config(self):
        config_log = """
        TreeBuilderConfig:
            Tokenizer: {tokenizer}
            Max Tokens: {max_tokens}
            Num Layers: {num_layers}
            Threshold: {threshold}
            Top K: {top_k}
            Selection Mode: {selection_mode}
            Summarization Length: {summarization_length}
            Summarization Model: {summarization_model}
            Embedding Models: {embedding_models}
            Cluster Embedding Model: {cluster_embedding_model}
        """.format(
            tokenizer=self.tokenizer,
            max_tokens=self.max_tokens,
            num_layers=self.num_layers,
            threshold=self.threshold,
            top_k=self.top_k,
            selection_mode=self.selection_mode,
            summarization_length=self.summarization_length,
            summarization_model=self.summarization_model,
            embedding_models=self.embedding_models,
            cluster_embedding_model=self.cluster_embedding_model,
        )
        return config_log


class TreeBuilder:
    """
    The TreeBuilder class is responsible for building a hierarchical text abstraction
    structure, known as a "tree," using summarization models and
    embedding models.
    """

    def __init__(self, config) -> None:
        """Initializes the tokenizer, maximum tokens, number of layers, top-k value, threshold, and selection mode."""

        self.tokenizer = config.tokenizer
        self.max_tokens = config.max_tokens
        self.num_layers = config.num_layers
        self.top_k = config.top_k
        self.threshold = config.threshold
        self.selection_mode = config.selection_mode
        self.summarization_length = config.summarization_length
        self.summarization_length_by_layer = (
            getattr(config, "summarization_length_by_layer", {}) or {}
        )
        self.summarization_model = config.summarization_model
        self.embedding_models = config.embedding_models
        self.cluster_embedding_model = config.cluster_embedding_model
        self.chunker = getattr(config, "chunker", split_text)

        logging.info(
            f"Successfully initialized TreeBuilder with Config {config.log_config()}"
        )

    def create_node(
        self,
        index: int,
        text: str,
        children_indices: Optional[Set[int]] = None,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        original_content_ref: Optional[str] = None,
    ) -> Tuple[int, Node]:
        """Creates a new node with the given index, text, and (optionally) children indices.

        Args:
            index (int): The index of the new node.
            text (str): The text associated with the new node.
            children_indices (Optional[Set[int]]): A set of indices representing the children of the new node.
                If not provided, an empty set will be used.

        Returns:
            Tuple[int, Node]: A tuple containing the index and the newly created node.
        """
        if children_indices is None:
            children_indices = set()

        embeddings = {
            model_name: model.create_embedding(text)
            for model_name, model in self.embedding_models.items()
        }
        return (
            index,
            Node(
                text,
                index,
                children_indices,
                embeddings,
                metadata=metadata,
                original_content_ref=original_content_ref,
            ),
        )

    def create_embedding(self, text) -> List[float]:
        """
        Generates embeddings for the given text using the specified embedding model.

        Args:
            text (str): The text for which to generate embeddings.

        Returns:
            List[float]: The generated embeddings.
        """
        return self.embedding_models[self.cluster_embedding_model].create_embedding(
            text
        )

    def summarization_length_for_layer(self, layer: int, default: int) -> int:
        try:
            layer_i = int(layer)
        except Exception:
            layer_i = -1
        v = self.summarization_length_by_layer.get(layer_i)
        if isinstance(v, int) and v > 0:
            return v
        return int(default)

    def summarize(self, context, max_tokens=150, *, layer: int = None) -> str:
        """
        Generates a summary of the input context using the specified summarization model.

        Args:
            context (str, optional): The context to summarize.
            max_tokens (int, optional): The maximum number of tokens in the generated summary. Defaults to 150.o

        Returns:
            str: The generated summary.
        """
        # Layer-aware summarizers can vary prompt/behavior by layer.
        if layer is not None and hasattr(self.summarization_model, "summarize_layer"):
            summary = self.summarization_model.summarize_layer(  # type: ignore[attr-defined]
                context, layer=int(layer), max_tokens=int(max_tokens)
            )
        else:
            summary = self.summarization_model.summarize(context, max_tokens)
        # Defensive: ensure we always return a non-empty string so downstream embedding calls don't fail.
        if not isinstance(summary, str):
            summary = "" if summary is None else str(summary)
        summary = summary.strip()
        if summary:
            return summary

        # Fallback: if model returns empty output, use a truncated version of the context.
        # This keeps the build progressing (and is preferable to crashing).
        try:
            toks = self.tokenizer.encode(context or "")
            toks = toks[: max(1, int(max_tokens))]
            fallback = self.tokenizer.decode(toks).strip()
            return fallback or " "
        except Exception:
            return (context or " ").strip() or " "

    def get_relevant_nodes(self, current_node, list_nodes) -> List[Node]:
        """
        Retrieves the top-k most relevant nodes to the current node from the list of nodes
        based on cosine distance in the embedding space.

        Args:
            current_node (Node): The current node.
            list_nodes (List[Node]): The list of nodes.

        Returns:
            List[Node]: The top-k most relevant nodes.
        """
        embeddings = get_embeddings(list_nodes, self.cluster_embedding_model)
        distances = distances_from_embeddings(
            current_node.embeddings[self.cluster_embedding_model], embeddings
        )
        indices = indices_of_nearest_neighbors_from_distances(distances)

        if self.selection_mode == "threshold":
            best_indices = [
                index for index in indices if distances[index] > self.threshold
            ]

        elif self.selection_mode == "top_k":
            best_indices = indices[: self.top_k]

        nodes_to_add = [list_nodes[idx] for idx in best_indices]

        return nodes_to_add

    def multithreaded_create_leaf_nodes(
        self, chunks: List[Union[str, dict]]
    ) -> Dict[int, Node]:
        """Creates leaf nodes using batch embedding from the given list of text chunks.

        Uses batch embedding API for efficiency (single API call for multiple texts)
        instead of individual calls per chunk.

        Args:
            chunks (List[str]): A list of text chunks to be turned into leaf nodes.

        Returns:
            Dict[int, Node]: A dictionary mapping node indices to the corresponding leaf nodes.
        """
        total = len(chunks)
        use_progress = _progress_enabled()

        def _coerce_leaf_chunk(
            item: Union[str, dict],
        ) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
            # Accept either plain string chunks (legacy) or structured chunks:
            # { "text": "...", "metadata": {...}, "original_content_ref": "..." }
            if isinstance(item, dict):
                text = str(item.get("text", "") or "")
                meta = item.get("metadata")
                meta = meta if isinstance(meta, dict) else None
                ref = item.get("original_content_ref")
                ref = str(ref) if ref else None
                return text, meta, ref
            return str(item), None, None

        # Extract texts and metadata from chunks
        chunk_data = [_coerce_leaf_chunk(item) for item in chunks]
        texts = [cd[0] for cd in chunk_data]

        if use_progress:
            logging.info(f"Creating batch embeddings for {total} chunks...")

        # Batch embed all texts for each embedding model
        all_model_embeddings: Dict[str, List] = {}
        for model_name, model in self.embedding_models.items():
            if use_progress:
                logging.info(f"  Embedding with model: {model_name}")
            # Use batch embedding if available
            if hasattr(model, "create_embeddings_batch"):
                all_model_embeddings[model_name] = model.create_embeddings_batch(texts)
            else:
                # Fallback to individual calls for models without batch support
                all_model_embeddings[model_name] = [
                    model.create_embedding(t) for t in texts
                ]

        if use_progress:
            logging.info(f"Batch embedding complete. Creating {total} nodes...")

        # Create nodes with pre-computed embeddings
        leaf_nodes = {}
        for index, (text, meta, ref) in enumerate(chunk_data):
            embeddings = {
                model_name: all_model_embeddings[model_name][index]
                for model_name in self.embedding_models
            }
            node = Node(
                text,
                index,
                set(),  # children_indices
                embeddings,
                metadata=meta,
                original_content_ref=ref,
            )
            leaf_nodes[index] = node

        if use_progress:
            logging.info(f"Created {len(leaf_nodes)} leaf nodes")

        return leaf_nodes

    def build_from_text(self, text: str, use_multithreading: bool = True) -> Tree:
        """Builds a golden tree from the input text, optionally using multithreading.

        Args:
            text (str): The input text.
            use_multithreading (bool, optional): Whether to use multithreading when creating leaf nodes.
                Default: True.

        Returns:
            Tree: The golden tree structure.
        """
        chunks = self.chunker(text, self.tokenizer, self.max_tokens)
        if _progress_enabled():
            logging.info(
                f"Split input into {len(chunks)} chunks (tb_max_tokens={self.max_tokens})"
            )

        return self.build_from_chunks(
            chunks=chunks, use_multithreading=use_multithreading
        )

    def build_from_chunks(
        self, chunks: List[Union[str, dict]], use_multithreading: bool = True
    ) -> Tree:
        """
        Builds a tree from pre-chunked text.

        This is useful for smoke tests / sampling where you want a deterministic number of leaf nodes
        without relying on `split_text()` on a large concatenated corpus.
        """
        if not isinstance(chunks, list):
            raise ValueError("chunks must be a list")
        if len(chunks) == 0:
            raise ValueError("chunks must be non-empty")
        if _progress_enabled():
            logging.info(f"Building tree from {len(chunks)} pre-chunked leaves")

        logging.info("Creating Leaf Nodes")

        if use_multithreading:
            leaf_nodes = self.multithreaded_create_leaf_nodes(chunks)
        else:
            leaf_nodes = {}
            total = len(chunks)
            use_progress = _progress_enabled()
            pbar = None
            if use_progress:
                try:
                    from tqdm.auto import tqdm  # type: ignore

                    pbar = tqdm(
                        total=total, desc="RAPTOR leaf embeddings", unit="chunk"
                    )
                except Exception:
                    pbar = None

            def _coerce_leaf_chunk(
                item: Union[str, dict],
            ) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
                if isinstance(item, dict):
                    text = str(item.get("text", "") or "")
                    meta = item.get("metadata")
                    meta = meta if isinstance(meta, dict) else None
                    ref = item.get("original_content_ref")
                    ref = str(ref) if ref else None
                    return text, meta, ref
                return str(item), None, None

            for index, item in enumerate(chunks):
                text, meta, ref = _coerce_leaf_chunk(item)
                __, node = self.create_node(
                    index, text, metadata=meta, original_content_ref=ref
                )
                leaf_nodes[index] = node
                if pbar is not None:
                    pbar.update(1)
                elif use_progress and (index + 1) % 250 == 0:
                    logging.info(f"Leaf embeddings progress: {index + 1}/{total}")

            if pbar is not None:
                pbar.close()

        layer_to_nodes = {0: list(leaf_nodes.values())}

        logging.info(f"Created {len(leaf_nodes)} Leaf Embeddings")

        logging.info("Building All Nodes")

        all_nodes = copy.deepcopy(leaf_nodes)

        root_nodes = self.construct_tree(
            all_nodes,
            all_nodes,
            layer_to_nodes,
            use_multithreading=use_multithreading,
        )

        tree = Tree(all_nodes, root_nodes, leaf_nodes, self.num_layers, layer_to_nodes)

        return tree

    @abstractclassmethod
    def construct_tree(
        self,
        current_level_nodes: Dict[int, Node],
        all_tree_nodes: Dict[int, Node],
        layer_to_nodes: Dict[int, List[Node]],
        use_multithreading: bool = True,
    ) -> Dict[int, Node]:
        """
        Constructs the hierarchical tree structure layer by layer by iteratively summarizing groups
        of relevant nodes and updating the current_level_nodes and all_tree_nodes dictionaries at each step.

        Args:
            current_level_nodes (Dict[int, Node]): The current set of nodes.
            all_tree_nodes (Dict[int, Node]): The dictionary of all nodes.
            use_multithreading (bool): Whether to use multithreading to speed up the process.

        Returns:
            Dict[int, Node]: The final set of root nodes.
        """
        pass

        # logging.info("Using Transformer-like TreeBuilder")

        # def process_node(idx, current_level_nodes, new_level_nodes, all_tree_nodes, next_node_index, lock):
        #     relevant_nodes_chunk = self.get_relevant_nodes(
        #         current_level_nodes[idx], current_level_nodes
        #     )

        #     node_texts = get_text(relevant_nodes_chunk)

        #     summarized_text = self.summarize(
        #         context=node_texts,
        #         max_tokens=self.summarization_length,
        #     )

        #     logging.info(
        #         f"Node Texts Length: {len(self.tokenizer.encode(node_texts))}, Summarized Text Length: {len(self.tokenizer.encode(summarized_text))}"
        #     )

        #     next_node_index, new_parent_node = self.create_node(
        #         next_node_index,
        #         summarized_text,
        #         {node.index for node in relevant_nodes_chunk}
        #     )

        #     with lock:
        #         new_level_nodes[next_node_index] = new_parent_node

        # for layer in range(self.num_layers):
        #     logging.info(f"Constructing Layer {layer}: ")

        #     node_list_current_layer = get_node_list(current_level_nodes)
        #     next_node_index = len(all_tree_nodes)

        #     new_level_nodes = {}
        #     lock = Lock()

        #     if use_multithreading:
        #         with ThreadPoolExecutor() as executor:
        #             for idx in range(0, len(node_list_current_layer)):
        #                 executor.submit(process_node, idx, node_list_current_layer, new_level_nodes, all_tree_nodes, next_node_index, lock)
        #                 next_node_index += 1
        #             executor.shutdown(wait=True)
        #     else:
        #         for idx in range(0, len(node_list_current_layer)):
        #             process_node(idx, node_list_current_layer, new_level_nodes, all_tree_nodes, next_node_index, lock)

        #     layer_to_nodes[layer + 1] = list(new_level_nodes.values())
        #     current_level_nodes = new_level_nodes
        #     all_tree_nodes.update(new_level_nodes)

        # return new_level_nodes
