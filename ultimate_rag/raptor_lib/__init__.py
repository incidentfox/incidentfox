# raptor/__init__.py
from .cluster_tree_builder import ClusterTreeBuilder, ClusterTreeConfig
from .EmbeddingModels import (
    BaseEmbeddingModel,
    OpenAIEmbeddingModel,
    SBertEmbeddingModel,
)

# FAISS is optional in many environments (it can require native deps like swig).
# Keep RAPTOR usable without FAISS by making this import best-effort.
try:
    from .FaissRetriever import FaissRetriever, FaissRetrieverConfig
except Exception:  # pragma: no cover
    FaissRetriever = None
    FaissRetrieverConfig = None
from .QAModels import (
    BaseQAModel,
    GPT3QAModel,
    GPT3TurboQAModel,
    GPT4QAModel,
    UnifiedQAModel,
)
from .RetrievalAugmentation import RetrievalAugmentation, RetrievalAugmentationConfig
from .Retrievers import BaseRetriever
from .SummarizationModels import (
    BaseSummarizationModel,
    CachedSummarizationModel,
    GPT3SummarizationModel,
    GPT3TurboSummarizationModel,
    OpenAILayeredSummarizationModel,
)
from .summary_cache import SummaryCache
from .tree_builder import TreeBuilder, TreeBuilderConfig
from .tree_retriever import TreeRetriever, TreeRetrieverConfig
from .tree_structures import Node, Tree

# Enhanced keyword models (optional)
try:
    from .EnhancedKeywordModels import (
        EnhancedKeywordModel,
        propagate_keywords_hierarchically,
    )
    from .keyword_index import KeywordIndex, build_keyword_index
except ImportError:
    EnhancedKeywordModel = None
    propagate_keywords_hierarchically = None
    KeywordIndex = None
    build_keyword_index = None

# Tree merging utilities
try:
    from .tree_merge import merge_tree_files, merge_trees, merge_trees_incremental
except ImportError:
    merge_trees = None
    merge_trees_incremental = None
    merge_tree_files = None

# Incremental update utilities
try:
    from .incremental import (
        IncrementalUpdateConfig,
        incremental_insert_leaf_nodes_layer1,
        rebuild_upper_layers_from,
    )
except ImportError:
    IncrementalUpdateConfig = None
    incremental_insert_leaf_nodes_layer1 = None
    rebuild_upper_layers_from = None
