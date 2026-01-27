"""
RAPTOR Bridge Module.

Provides integration with the existing RAPTOR implementation:
- Import existing RAPTOR trees
- Export to RAPTOR format
- Bridge for using RAPTOR's embedding and clustering
"""

from .bridge import (
    RaptorBridge,
    import_raptor_tree,
    export_to_raptor,
)
from .enhanced_builder import (
    EnhancedTreeBuilder,
    EnhancedTreeConfig,
)

__all__ = [
    "RaptorBridge",
    "import_raptor_tree",
    "export_to_raptor",
    "EnhancedTreeBuilder",
    "EnhancedTreeConfig",
]
