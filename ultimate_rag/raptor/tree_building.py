"""
RAPTOR Tree Building Integration for Ultimate RAG.

This module provides the bridge between ultimate_rag's flat ingestion
and the full RAPTOR hierarchical tree building with clustering and summarization.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..core.node import KnowledgeTree


@dataclass
class TreeBuildConfig:
    """Configuration for RAPTOR tree building."""

    # Chunking
    max_tokens: int = 500  # Max tokens per leaf chunk

    # Tree structure
    num_layers: int = 5  # Max number of layers
    auto_depth: bool = True  # Auto-stop when top layer is small enough
    target_top_nodes: int = 50  # Target size for top layer

    # Summarization
    summarization_length: int = 200  # Max tokens for summaries
    summarization_model: str = "gpt-4o-mini"  # Model for summarization

    # Clustering
    cluster_threshold: float = 0.1  # GMM membership threshold
    max_clusters: int = 20  # Max clusters per layer
    reduction_dimension: int = 6  # UMAP output dimension

    # Embedding
    embedding_model: str = "text-embedding-3-large"

    # Caching (recommended for large corpora)
    cache_embeddings: bool = True
    cache_summaries: bool = True
    cache_path: str = ".cache"


class RaptorTreeBuilder:
    """
    Builds proper RAPTOR hierarchical trees from flat chunks.

    This wraps the knowledge_base RAPTOR implementation to provide
    full clustering and summarization capabilities.
    """

    def __init__(self, config: Optional[TreeBuildConfig] = None):
        self.config = config or TreeBuildConfig()
        self._raptor_builder = None
        self._embedding_model = None
        self._summarization_model = None

    def _init_models(self):
        """Initialize embedding and summarization models."""
        if self._embedding_model is not None:
            return

        try:
            from knowledge_base.raptor.embedding_cache import (
                CachedEmbeddingModel,
                EmbeddingCache,
            )
            from knowledge_base.raptor.EmbeddingModels import OpenAIEmbeddingModel
            from knowledge_base.raptor.SummarizationModels import (
                CachedSummarizationModel,
                GPT3TurboSummarizationModel,
            )
            from knowledge_base.raptor.summary_cache import SummaryCache

            # Embedding model
            self._embedding_model = OpenAIEmbeddingModel(
                model=self.config.embedding_model
            )

            if self.config.cache_embeddings:
                cache = EmbeddingCache(f"{self.config.cache_path}/embeddings.sqlite")
                self._embedding_model = CachedEmbeddingModel(
                    self._embedding_model,
                    cache=cache,
                    model_id=self.config.embedding_model,
                )

            # Summarization model
            self._summarization_model = GPT3TurboSummarizationModel(
                model=self.config.summarization_model
            )

            if self.config.cache_summaries:
                cache = SummaryCache(f"{self.config.cache_path}/summaries.sqlite")
                self._summarization_model = CachedSummarizationModel(
                    self._summarization_model,
                    cache=cache,
                    model_id=self.config.summarization_model,
                )

            logger.info(
                f"Initialized RAPTOR models: embed={self.config.embedding_model}, "
                f"summarize={self.config.summarization_model}"
            )

        except ImportError as e:
            logger.error(f"Failed to import RAPTOR components: {e}")
            raise RuntimeError(
                "knowledge_base.raptor module not available. "
                "Ensure PYTHONPATH includes knowledge_base directory."
            ) from e

    def _init_builder(self):
        """Initialize the ClusterTreeBuilder."""
        if self._raptor_builder is not None:
            return

        self._init_models()

        try:
            from knowledge_base.raptor.cluster_tree_builder import (
                ClusterTreeBuilder,
                ClusterTreeConfig,
            )

            config = ClusterTreeConfig(
                max_tokens=self.config.max_tokens,
                num_layers=self.config.num_layers,
                summarization_length=self.config.summarization_length,
                summarization_model=self._summarization_model,
                embedding_models={"OpenAI": self._embedding_model},
                cluster_embedding_model="OpenAI",
                clustering_params={
                    "threshold": self.config.cluster_threshold,
                    "max_clusters": self.config.max_clusters,
                },
                auto_depth=self.config.auto_depth,
                target_top_nodes=self.config.target_top_nodes,
                max_layers=self.config.num_layers,
                reduction_dimension=self.config.reduction_dimension,
            )

            self._raptor_builder = ClusterTreeBuilder(config)
            logger.info(
                f"Initialized ClusterTreeBuilder: auto_depth={self.config.auto_depth}, "
                f"target_top={self.config.target_top_nodes}, max_layers={self.config.num_layers}"
            )

        except ImportError as e:
            logger.error(f"Failed to import ClusterTreeBuilder: {e}")
            raise RuntimeError(
                "ClusterTreeBuilder not available in knowledge_base.raptor"
            ) from e

    def build_from_texts(
        self,
        texts: List[str],
        tree_name: str = "default",
    ) -> "KnowledgeTree":
        """
        Build a hierarchical RAPTOR tree from a list of texts.

        Args:
            texts: List of text documents to build tree from
            tree_name: Name for the resulting tree

        Returns:
            KnowledgeTree with full RAPTOR hierarchy
        """
        self._init_builder()

        logger.info(f"Building RAPTOR tree from {len(texts)} documents...")

        # RAPTOR's build_from_text expects a single string
        # Join documents with clear separators for proper chunking
        combined_text = "\n\n---DOCUMENT_SEPARATOR---\n\n".join(texts)
        logger.info(
            f"Combined {len(texts)} documents into {len(combined_text)} characters"
        )

        # Build RAPTOR tree
        raptor_tree = self._raptor_builder.build_from_text(combined_text)

        # Convert to KnowledgeTree
        from .bridge import RaptorBridge

        bridge = RaptorBridge()
        knowledge_tree = bridge.import_tree(
            raptor_tree,
            tree_name=tree_name,
            infer_types=True,
        )

        logger.info(
            f"Built RAPTOR tree: {len(knowledge_tree.all_nodes)} nodes, "
            f"{knowledge_tree.num_layers} layers"
        )

        return knowledge_tree

    def build_hierarchy_from_leaves(
        self,
        tree: "KnowledgeTree",
    ) -> "KnowledgeTree":
        """
        Take an existing tree with only leaf nodes and build the RAPTOR hierarchy.

        This is used to upgrade a flat-ingested tree to a proper RAPTOR tree.

        Args:
            tree: Existing KnowledgeTree with leaf nodes at layer 0

        Returns:
            New KnowledgeTree with full hierarchy
        """
        # Extract texts from existing leaf nodes
        leaf_nodes = [n for n in tree.all_nodes.values() if n.layer == 0]

        if not leaf_nodes:
            raise ValueError("Tree has no leaf nodes to build hierarchy from")

        texts = [node.text for node in leaf_nodes]

        logger.info(f"Building hierarchy from {len(texts)} existing leaf nodes...")

        # Build new tree with hierarchy
        new_tree = self.build_from_texts(texts, tree_name=tree.tree_id)

        # Preserve metadata from original nodes where possible
        # (matching by text hash)
        text_to_metadata = {hash(node.text): node.metadata for node in leaf_nodes}

        for node in new_tree.all_nodes.values():
            if node.layer == 0:
                text_hash = hash(node.text)
                if text_hash in text_to_metadata:
                    # Merge metadata
                    original_meta = text_to_metadata[text_hash]
                    if original_meta:
                        node.metadata.update(original_meta)

        return new_tree


def build_raptor_tree(
    texts: List[str],
    tree_name: str = "default",
    config: Optional[TreeBuildConfig] = None,
) -> "KnowledgeTree":
    """
    Convenience function to build a RAPTOR tree.

    Args:
        texts: List of text documents
        tree_name: Name for the tree
        config: Optional configuration

    Returns:
        KnowledgeTree with full RAPTOR hierarchy
    """
    builder = RaptorTreeBuilder(config)
    return builder.build_from_texts(texts, tree_name)
