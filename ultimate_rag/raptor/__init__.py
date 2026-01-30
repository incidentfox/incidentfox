"""
RAPTOR Bridge Module.

Provides integration with the existing RAPTOR implementation:
- Import existing RAPTOR trees
- Export to RAPTOR format
- Bridge for using RAPTOR's embedding and clustering
- Build full RAPTOR hierarchies with clustering and summarization
"""

from .bridge import (
    RaptorBridge,
    export_to_raptor,
    import_raptor_tree,
)
from .enhanced_builder import (
    EnhancedTreeBuilder,
    EnhancedTreeConfig,
)
from .tree_building import (
    RaptorTreeBuilder,
    TreeBuildConfig,
    build_raptor_tree,
)

__all__ = [
    "RaptorBridge",
    "import_raptor_tree",
    "export_to_raptor",
    "EnhancedTreeBuilder",
    "EnhancedTreeConfig",
    "RaptorTreeBuilder",
    "TreeBuildConfig",
    "build_raptor_tree",
]
