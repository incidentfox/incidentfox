import logging
import pickle

from ultimate_rag.core.persistence import safe_pickle_load

from .cluster_tree_builder import ClusterTreeBuilder, ClusterTreeConfig
from .EmbeddingModels import BaseEmbeddingModel
from .incremental import IncrementalUpdateConfig, incremental_insert_leaf_nodes_layer1
from .QAModels import BaseQAModel, GPT3TurboQAModel
from .SummarizationModels import BaseSummarizationModel
from .tree_retriever import TreeRetriever, TreeRetrieverConfig
from .tree_structures import Tree
from .utils import split_text

# Define a dictionary to map supported tree builders to their respective configs
supported_tree_builders = {"cluster": (ClusterTreeBuilder, ClusterTreeConfig)}

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)

# Sentinel used to distinguish "not provided" from "explicitly None".
_QA_DEFAULT = object()


class RetrievalAugmentationConfig:
    def __init__(
        self,
        tree_builder_config=None,
        tree_retriever_config=None,  # Change from default instantiation
        qa_model=_QA_DEFAULT,
        embedding_model=None,
        summarization_model=None,
        tree_builder_type="cluster",
        # New parameters for TreeRetrieverConfig and TreeBuilderConfig
        # TreeRetrieverConfig arguments
        tr_tokenizer=None,
        tr_threshold=0.5,
        tr_top_k=5,
        tr_selection_mode="top_k",
        tr_context_embedding_model="OpenAI",
        tr_embedding_model=None,
        tr_num_layers=None,
        tr_start_layer=None,
        # TreeBuilderConfig arguments
        tb_tokenizer=None,
        tb_max_tokens=100,
        tb_num_layers=5,
        tb_threshold=0.5,
        tb_top_k=5,
        tb_selection_mode="top_k",
        tb_summarization_length=100,
        tb_summarization_model=None,
        tb_embedding_models=None,
        tb_cluster_embedding_model="OpenAI",
        # Auto-depth (initial build)
        tb_auto_depth: bool = False,
        tb_target_top_nodes: int = 75,
        tb_max_layers: int = None,
    ):
        # Validate tree_builder_type
        if tree_builder_type not in supported_tree_builders:
            raise ValueError(
                f"tree_builder_type must be one of {list(supported_tree_builders.keys())}"
            )

        # Validate qa_model
        if (
            qa_model is not _QA_DEFAULT
            and qa_model is not None
            and not isinstance(qa_model, BaseQAModel)
        ):
            raise ValueError(
                "qa_model must be an instance of BaseQAModel (or None to disable QA)"
            )

        if embedding_model is not None and not isinstance(
            embedding_model, BaseEmbeddingModel
        ):
            raise ValueError(
                "embedding_model must be an instance of BaseEmbeddingModel"
            )
        elif embedding_model is not None:
            if tb_embedding_models is not None:
                raise ValueError(
                    "Only one of 'tb_embedding_models' or 'embedding_model' should be provided, not both."
                )
            tb_embedding_models = {"EMB": embedding_model}
            tr_embedding_model = embedding_model
            tb_cluster_embedding_model = "EMB"
            tr_context_embedding_model = "EMB"

        if summarization_model is not None and not isinstance(
            summarization_model, BaseSummarizationModel
        ):
            raise ValueError(
                "summarization_model must be an instance of BaseSummarizationModel"
            )

        elif summarization_model is not None:
            if tb_summarization_model is not None:
                raise ValueError(
                    "Only one of 'tb_summarization_model' or 'summarization_model' should be provided, not both."
                )
            tb_summarization_model = summarization_model

        # Set TreeBuilderConfig
        tree_builder_class, tree_builder_config_class = supported_tree_builders[
            tree_builder_type
        ]
        if tree_builder_config is None:
            tree_builder_config = tree_builder_config_class(
                tokenizer=tb_tokenizer,
                max_tokens=tb_max_tokens,
                num_layers=tb_num_layers,
                threshold=tb_threshold,
                top_k=tb_top_k,
                selection_mode=tb_selection_mode,
                summarization_length=tb_summarization_length,
                summarization_model=tb_summarization_model,
                embedding_models=tb_embedding_models,
                cluster_embedding_model=tb_cluster_embedding_model,
                auto_depth=tb_auto_depth,
                target_top_nodes=tb_target_top_nodes,
                max_layers=tb_max_layers,
            )

        elif not isinstance(tree_builder_config, tree_builder_config_class):
            raise ValueError(
                f"tree_builder_config must be a direct instance of {tree_builder_config_class} for tree_builder_type '{tree_builder_type}'"
            )

        # Set TreeRetrieverConfig
        if tree_retriever_config is None:
            tree_retriever_config = TreeRetrieverConfig(
                tokenizer=tr_tokenizer,
                threshold=tr_threshold,
                top_k=tr_top_k,
                selection_mode=tr_selection_mode,
                context_embedding_model=tr_context_embedding_model,
                embedding_model=tr_embedding_model,
                num_layers=tr_num_layers,
                start_layer=tr_start_layer,
            )
        elif not isinstance(tree_retriever_config, TreeRetrieverConfig):
            raise ValueError(
                "tree_retriever_config must be an instance of TreeRetrieverConfig"
            )

        # Assign the created configurations to the instance
        self.tree_builder_config = tree_builder_config
        self.tree_retriever_config = tree_retriever_config
        # Default QA model only when not explicitly provided.
        self.qa_model = GPT3TurboQAModel() if qa_model is _QA_DEFAULT else qa_model
        self.tree_builder_type = tree_builder_type

    def log_config(self):
        config_summary = """
        RetrievalAugmentationConfig:
            {tree_builder_config}
            
            {tree_retriever_config}
            
            QA Model: {qa_model}
            Tree Builder Type: {tree_builder_type}
        """.format(
            tree_builder_config=self.tree_builder_config.log_config(),
            tree_retriever_config=self.tree_retriever_config.log_config(),
            qa_model=self.qa_model,
            tree_builder_type=self.tree_builder_type,
        )
        return config_summary


class RetrievalAugmentation:
    """
    A Retrieval Augmentation class that combines the TreeBuilder and TreeRetriever classes.
    Enables adding documents to the tree, retrieving information, and answering questions.
    """

    def __init__(self, config=None, tree=None):
        """
        Initializes a RetrievalAugmentation instance with the specified configuration.
        Args:
            config (RetrievalAugmentationConfig): The configuration for the RetrievalAugmentation instance.
            tree: The tree instance or the path to a pickled tree file.
        """
        if config is None:
            config = RetrievalAugmentationConfig()
        if not isinstance(config, RetrievalAugmentationConfig):
            raise ValueError(
                "config must be an instance of RetrievalAugmentationConfig"
            )

        # Check if tree is a string (indicating a path to a pickled tree)
        if isinstance(tree, str):
            try:
                with open(tree, "rb") as file:
                    self.tree = safe_pickle_load(file)
                if not isinstance(self.tree, Tree):
                    raise ValueError("The loaded object is not an instance of Tree")
            except Exception as e:
                raise ValueError(f"Failed to load tree from {tree}: {e}")
        elif isinstance(tree, Tree) or tree is None:
            self.tree = tree
        else:
            raise ValueError(
                "tree must be an instance of Tree, a path to a pickled Tree, or None"
            )

        tree_builder_class = supported_tree_builders[config.tree_builder_type][0]
        self.tree_builder = tree_builder_class(config.tree_builder_config)

        self.tree_retriever_config = config.tree_retriever_config
        self.qa_model = config.qa_model

        if self.tree is not None:
            self.retriever = TreeRetriever(self.tree_retriever_config, self.tree)
        else:
            self.retriever = None

        logging.info(
            f"Successfully initialized RetrievalAugmentation with Config {config.log_config()}"
        )

    def add_documents(self, docs):
        """
        Adds documents to the tree and creates a TreeRetriever instance.

        Args:
            docs (str): The input text to add to the tree.
        """
        if self.tree is not None:
            user_input = input(
                "Warning: Overwriting existing tree. Did you mean to call 'add_to_existing' instead? (y/n): "
            )
            if user_input.lower() == "y":
                # self.add_to_existing(docs)
                return

        self.tree = self.tree_builder.build_from_text(text=docs)
        self.retriever = TreeRetriever(self.tree_retriever_config, self.tree)

    def add_chunks(self, chunks):
        """
        Adds pre-chunked leaf texts (bypasses `split_text()`).

        Primarily intended for smoke tests / sampling runs where you want a predictable number of
        leaf nodes to validate the pipeline quickly.

        Supported formats:
        - List[str] (legacy)
        - List[dict] where each dict is {"text": str, "metadata": dict, "original_content_ref": str}
        """
        if self.tree is not None:
            user_input = input(
                "Warning: Overwriting existing tree. Did you mean to call 'add_to_existing' instead? (y/n): "
            )
            if user_input.lower() == "y":
                return

        self.tree = self.tree_builder.build_from_chunks(chunks=chunks)
        self.retriever = TreeRetriever(self.tree_retriever_config, self.tree)

    def add_to_existing(
        self,
        docs: str,
        *,
        similarity_threshold: float = 0.25,
        max_children_for_summary: int = 50,
        max_summary_context_tokens: int = 12000,
        use_safe_propagation: bool = True,
    ):
        """
        Incremental update that adds new documents and propagates changes through the tree.

        The SAFE mode (use_safe_propagation=True, default) uses layer-by-layer propagation:
        - Adds leaves to layer 0
        - For each leaf, finds/creates parent at layer 1
        - Propagates changes upward through ALL existing layers
        - NEVER deletes existing structure

        Important:
        - This is an approximation and will drift vs a full rebuild over time.
        - Best practice: incremental updates daily + periodic full rebuilds (weekly/monthly).
        """
        if self.tree is None:
            # No existing tree; fall back to full build.
            self.add_documents(docs)
            return

        # Today we support incremental updates for trees with at least one parent layer.
        if 1 not in self.tree.layer_to_nodes:
            raise ValueError(
                "Tree has no layer 1 nodes; cannot perform incremental update. Rebuild with tb_num_layers>=1."
            )

        # Chunk input the same way the builder does.
        chunks = split_text(
            docs, self.tree_builder.tokenizer, self.tree_builder.max_tokens
        )

        # Create new leaf nodes with fresh indices.
        next_idx = max(self.tree.all_nodes.keys()) + 1 if self.tree.all_nodes else 0
        new_leaf_nodes = {}
        for chunk in chunks:
            __, node = self.tree_builder.create_node(next_idx, chunk, set())
            new_leaf_nodes[next_idx] = node
            next_idx += 1

        # Determine which embedding key to use for routing.
        embed_key = self.tree_builder.cluster_embedding_model

        cfg = IncrementalUpdateConfig(
            embedding_key=embed_key,
            similarity_threshold=similarity_threshold,
            max_children_for_summary=max_children_for_summary,
            max_summary_context_tokens=max_summary_context_tokens,
        )

        if use_safe_propagation:
            # Use the SAFE layer-by-layer propagation (recommended)
            from .incremental import incremental_add_with_propagation

            updated, created = incremental_add_with_propagation(
                tree=self.tree,
                new_leaf_nodes=new_leaf_nodes,
                cfg=cfg,
                tokenizer=self.tree_builder.tokenizer,
                summarizer=self.tree_builder.summarization_model,
                embedder_map=self.tree_builder.embedding_models,
                summarization_length=self.tree_builder.summarization_length,
            )

            logging.info(
                f"Incremental update (safe propagation): new_leaves={len(new_leaf_nodes)} "
                f"updated={len(updated)} created={len(created)} "
                f"final_layers={self.tree.num_layers + 1}"
            )
        else:
            # Legacy: only update layer 0 and 1, no upper layer propagation
            updated, created = incremental_insert_leaf_nodes_layer1(
                tree=self.tree,
                new_leaf_nodes=new_leaf_nodes,
                layer1_nodes=self.tree.layer_to_nodes[1],
                cfg=cfg,
                tokenizer=self.tree_builder.tokenizer,
                summarizer=self.tree_builder.summarization_model,
                embedder_map=self.tree_builder.embedding_models,
                summarization_length=self.tree_builder.summarization_length,
            )

            logging.info(
                f"Incremental update (layer 1 only): new_leaves={len(new_leaf_nodes)} "
                f"updated_parents={len(updated)} created_parents={len(created)}"
            )

        # Refresh retriever to include new nodes and updated embeddings.
        self.retriever = TreeRetriever(self.tree_retriever_config, self.tree)

    def merge_tree(
        self,
        source_tree,
        *,
        similarity_threshold: float = 0.25,
        max_children_for_summary: int = 50,
        max_summary_context_tokens: int = 12000,
    ):
        """
        Merge another tree into this tree.

        Takes all leaf nodes from source_tree and integrates them into this tree
        using layer-by-layer propagation. The source tree's non-leaf nodes are NOT
        copied - instead, new parent relationships are formed based on similarity
        to existing nodes in this tree.

        Args:
            source_tree: The tree to merge FROM (will not be modified)
            similarity_threshold: Min similarity to attach to existing parent
            max_children_for_summary: Max children to use for re-summarization
            max_summary_context_tokens: Max tokens for summary context

        Returns:
            Tuple of (updated_indices, created_indices)
        """
        if self.tree is None:
            raise ValueError("Cannot merge into empty tree. Call add_documents first.")

        from .incremental import merge_trees

        embed_key = self.tree_builder.cluster_embedding_model

        cfg = IncrementalUpdateConfig(
            embedding_key=embed_key,
            similarity_threshold=similarity_threshold,
            max_children_for_summary=max_children_for_summary,
            max_summary_context_tokens=max_summary_context_tokens,
        )

        updated, created = merge_trees(
            target_tree=self.tree,
            source_tree=source_tree,
            cfg=cfg,
            tokenizer=self.tree_builder.tokenizer,
            summarizer=self.tree_builder.summarization_model,
            embedder_map=self.tree_builder.embedding_models,
            summarization_length=self.tree_builder.summarization_length,
        )

        logging.info(
            f"Tree merge complete: source_leaves={len(source_tree.leaf_nodes)} "
            f"updated={len(updated)} created={len(created)} "
            f"final_leaves={len(self.tree.leaf_nodes)} final_layers={self.tree.num_layers + 1}"
        )

        # Refresh retriever
        self.retriever = TreeRetriever(self.tree_retriever_config, self.tree)

        return updated, created

    def retrieve(
        self,
        question,
        start_layer: int = None,
        num_layers: int = None,
        top_k: int = 10,
        max_tokens: int = 3500,
        collapse_tree: bool = True,
        return_layer_information: bool = True,
    ):
        """
        Retrieves information and answers a question using the TreeRetriever instance.

        Args:
            question (str): The question to answer.
            start_layer (int): The layer to start from. Defaults to self.start_layer.
            num_layers (int): The number of layers to traverse. Defaults to self.num_layers.
            max_tokens (int): The maximum number of tokens. Defaults to 3500.
            use_all_information (bool): Whether to retrieve information from all nodes. Defaults to False.

        Returns:
            str: The context from which the answer can be found.

        Raises:
            ValueError: If the TreeRetriever instance has not been initialized.
        """
        if self.retriever is None:
            raise ValueError(
                "The TreeRetriever instance has not been initialized. Call 'add_documents' first."
            )

        return self.retriever.retrieve(
            question,
            start_layer,
            num_layers,
            top_k,
            max_tokens,
            collapse_tree,
            return_layer_information,
        )

    def answer_question(
        self,
        question,
        top_k: int = 10,
        start_layer: int = None,
        num_layers: int = None,
        max_tokens: int = 3500,
        collapse_tree: bool = True,
        return_layer_information: bool = False,
        use_citations: bool = True,
    ):
        """
        Retrieves information and answers a question using the TreeRetriever instance.

        Args:
            question (str): The question to answer.
            start_layer (int): The layer to start from. Defaults to self.start_layer.
            num_layers (int): The number of layers to traverse. Defaults to self.num_layers.
            max_tokens (int): The maximum number of tokens. Defaults to 3500.
            collapse_tree (bool): Whether to use collapsed tree retrieval. Defaults to True.
            return_layer_information (bool): Whether to return layer info. Defaults to False.
            use_citations (bool): Whether to format context with [N] citation labels. Defaults to True.

        Returns:
            str: The answer to the question (with inline [N] citations if use_citations=True).
            If return_layer_information=True, returns (answer, layer_information).

        Raises:
            ValueError: If the TreeRetriever instance has not been initialized.
        """
        from .utils import get_text_with_citations

        # Retrieve context and layer information
        context, layer_information = self.retrieve(
            question, start_layer, num_layers, top_k, max_tokens, collapse_tree, True
        )

        citations = []
        if use_citations and layer_information:
            # Get the actual nodes from layer_information
            nodes = []
            for info in layer_information:
                node_idx = int(info["node_index"])
                node = self.tree.all_nodes.get(node_idx)
                if node:
                    nodes.append(node)

            # Build citation-labeled context
            if nodes:
                context, citations = get_text_with_citations(nodes)

        answer = self.qa_model.answer_question(context, question)

        if return_layer_information:
            return answer, layer_information, citations

        return answer

    def answer_question_with_citations(
        self,
        question,
        top_k: int = 10,
        max_tokens: int = 3500,
    ):
        """
        Answer a question and return structured citations.

        Args:
            question (str): The question to answer.
            top_k (int): Number of nodes to retrieve.
            max_tokens (int): Maximum context tokens.

        Returns:
            dict: {
                "answer": str (with inline [N] citations),
                "citations": list of {"index": N, "source": URL, ...},
                "layer_info": list of node info dicts
            }
        """
        answer, layer_info, citations = self.answer_question(
            question,
            top_k=top_k,
            max_tokens=max_tokens,
            return_layer_information=True,
            use_citations=True,
        )

        return {
            "answer": answer,
            "citations": citations,
            "layer_info": layer_info,
        }

    def answer_question_with_citations(
        self,
        question,
        top_k: int = 10,
        max_tokens: int = 3500,
    ):
        """
        Answer a question and return structured citations.

        Args:
            question (str): The question to answer.
            top_k (int): Number of nodes to retrieve.
            max_tokens (int): Maximum context tokens.

        Returns:
            dict: {
                "answer": str (with inline [N] citations),
                "citations": list of {"index": N, "source": URL, ...},
                "layer_info": list of node info dicts
            }
        """
        answer, layer_info, citations = self.answer_question(
            question,
            top_k=top_k,
            max_tokens=max_tokens,
            return_layer_information=True,
            use_citations=True,
        )

        return {
            "answer": answer,
            "citations": citations,
            "layer_info": layer_info,
        }

    def save(self, path):
        if self.tree is None:
            raise ValueError("There is no tree to save.")
        with open(path, "wb") as file:
            pickle.dump(self.tree, file)
        logging.info(f"Tree successfully saved to {path}")
