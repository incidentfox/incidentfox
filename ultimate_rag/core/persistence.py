"""
Tree persistence module for Ultimate RAG.

Supports saving and loading KnowledgeTree/TreeForest to:
- Local disk (pickle or JSON format)
- AWS S3

For development, use local disk storage.
For production, use S3 for durability and sharing across instances.
"""

import io
import json
import logging
import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that only allows safe built-in types.

    Prevents arbitrary code execution via crafted pickle payloads.
    Our trees are serialized as plain dicts (via _tree_to_dict), so only
    built-in types should ever appear in the pickle stream.
    """

    _SAFE_BUILTINS = frozenset(
        {
            "dict",
            "list",
            "tuple",
            "set",
            "frozenset",
            "str",
            "bytes",
            "int",
            "float",
            "bool",
            "complex",
            "type",
        }
    )
    _SAFE_MODULES = frozenset(
        {
            "builtins",
            "datetime",
            "collections",
            # RAPTOR compatibility: trees may contain raptor Node/Tree objects
            "raptor.tree_structures",
            "raptor.tree_builder",
        }
    )

    def find_class(self, module: str, name: str):
        if module == "builtins" and name in self._SAFE_BUILTINS:
            return super().find_class(module, name)
        if module in self._SAFE_MODULES:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"Blocked unpickling of {module}.{name} — " f"only safe types are allowed"
        )


def safe_pickle_load(f) -> Any:
    """Load a pickle file using restricted unpickler."""
    return _RestrictedUnpickler(f).load()


def safe_pickle_loads(data: bytes) -> Any:
    """Load pickle bytes using restricted unpickler."""
    return _RestrictedUnpickler(io.BytesIO(data)).load()


from .node import KnowledgeNode, KnowledgeTree, TreeForest
from .types import KnowledgeType

logger = logging.getLogger(__name__)


class TreePersistence:
    """
    Handles saving and loading trees to various backends.

    Supports:
    - Local filesystem (pickle format for speed, JSON for debugging)
    - AWS S3 (pickle format)
    """

    def __init__(
        self,
        local_dir: Optional[str] = None,
        s3_bucket: Optional[str] = None,
        s3_prefix: str = "trees/",
    ):
        """
        Initialize persistence layer.

        Args:
            local_dir: Local directory for tree storage (default: ./trees)
            s3_bucket: S3 bucket name for cloud storage
            s3_prefix: Prefix within S3 bucket (default: trees/)
        """
        self.local_dir = Path(local_dir) if local_dir else Path("./trees")
        self.s3_bucket = s3_bucket or os.environ.get("TREES_S3_BUCKET")
        self.s3_prefix = s3_prefix
        self._s3_client = None

        # Ensure local directory exists
        self.local_dir.mkdir(parents=True, exist_ok=True)

    @property
    def s3_client(self):
        """Lazy initialization of S3 client."""
        if self._s3_client is None and self.s3_bucket:
            try:
                import boto3

                self._s3_client = boto3.client("s3")
            except ImportError:
                logger.warning("boto3 not available, S3 persistence disabled")
        return self._s3_client

    # ==================== Local Storage ====================

    def save_tree_local(
        self,
        tree: KnowledgeTree,
        path: Optional[str] = None,
        format: str = "pickle",
    ) -> str:
        """
        Save a tree to local disk.

        Args:
            tree: KnowledgeTree to save
            path: Optional explicit path (default: local_dir/tree_id.pkl)
            format: "pickle" (fast, binary) or "json" (human-readable)

        Returns:
            Path where tree was saved
        """
        if path:
            save_path = Path(path)
        else:
            ext = ".pkl" if format == "pickle" else ".json"
            save_path = self.local_dir / f"{tree.tree_id}{ext}"

        save_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "pickle":
            with open(save_path, "wb") as f:
                pickle.dump(self._tree_to_dict(tree), f)
        else:
            with open(save_path, "w") as f:
                json.dump(self._tree_to_dict(tree), f, indent=2, default=str)

        logger.info(f"Saved tree '{tree.tree_id}' to {save_path}")
        return str(save_path)

    def load_tree_local(
        self,
        tree_id: str,
        path: Optional[str] = None,
    ) -> Optional[KnowledgeTree]:
        """
        Load a tree from local disk.

        Args:
            tree_id: Tree ID to load
            path: Optional explicit path

        Returns:
            KnowledgeTree or None if not found
        """
        if path:
            load_path = Path(path)
        else:
            # Try pickle first, then JSON
            pkl_path = self.local_dir / f"{tree_id}.pkl"
            json_path = self.local_dir / f"{tree_id}.json"

            if pkl_path.exists():
                load_path = pkl_path
            elif json_path.exists():
                load_path = json_path
            else:
                # Check in subdirectory
                subdir_pkl = self.local_dir / tree_id / f"{tree_id}.pkl"
                if subdir_pkl.exists():
                    load_path = subdir_pkl
                else:
                    logger.warning(f"Tree '{tree_id}' not found locally")
                    return None

        try:
            if load_path.suffix == ".pkl":
                with open(load_path, "rb") as f:
                    data = safe_pickle_load(f)
            else:
                with open(load_path, "r") as f:
                    data = json.load(f)

            tree = self._dict_to_tree(data)
            logger.info(f"Loaded tree '{tree_id}' from {load_path}")
            return tree

        except Exception as e:
            logger.error(f"Failed to load tree '{tree_id}': {e}")
            return None

    def list_local_trees(self) -> List[str]:
        """List all trees available locally."""
        trees = set()

        # Find .pkl files
        for pkl_file in self.local_dir.glob("*.pkl"):
            trees.add(pkl_file.stem)

        # Find .json files
        for json_file in self.local_dir.glob("*.json"):
            trees.add(json_file.stem)

        # Find subdirectories with .pkl files
        for subdir in self.local_dir.iterdir():
            if subdir.is_dir():
                pkl_file = subdir / f"{subdir.name}.pkl"
                if pkl_file.exists():
                    trees.add(subdir.name)

        return sorted(trees)

    # ==================== S3 Storage ====================

    def save_tree_s3(
        self,
        tree: KnowledgeTree,
        key: Optional[str] = None,
    ) -> str:
        """
        Save a tree to S3.

        Args:
            tree: KnowledgeTree to save
            key: Optional S3 key (default: prefix/tree_id/tree_id.pkl)

        Returns:
            S3 URI where tree was saved
        """
        if not self.s3_client or not self.s3_bucket:
            raise RuntimeError("S3 not configured")

        if key:
            s3_key = key
        else:
            s3_key = f"{self.s3_prefix}{tree.tree_id}/{tree.tree_id}.pkl"

        # Serialize to pickle bytes
        data = pickle.dumps(self._tree_to_dict(tree))

        self.s3_client.put_object(
            Bucket=self.s3_bucket,
            Key=s3_key,
            Body=data,
        )

        s3_uri = f"s3://{self.s3_bucket}/{s3_key}"
        logger.info(f"Saved tree '{tree.tree_id}' to {s3_uri}")
        return s3_uri

    def load_tree_s3(
        self,
        tree_id: str,
        key: Optional[str] = None,
    ) -> Optional[KnowledgeTree]:
        """
        Load a tree from S3.

        Args:
            tree_id: Tree ID to load
            key: Optional explicit S3 key

        Returns:
            KnowledgeTree or None if not found
        """
        if not self.s3_client or not self.s3_bucket:
            logger.warning("S3 not configured")
            return None

        if key:
            s3_key = key
        else:
            # Try both patterns: trees/tree_id/tree_id.pkl and trees/tree_id.pkl
            s3_key = f"{self.s3_prefix}{tree_id}/{tree_id}.pkl"

        try:
            response = self.s3_client.get_object(
                Bucket=self.s3_bucket,
                Key=s3_key,
            )
            data = safe_pickle_loads(response["Body"].read())
            tree = self._dict_to_tree(data)
            logger.info(f"Loaded tree '{tree_id}' from s3://{self.s3_bucket}/{s3_key}")
            return tree

        except self.s3_client.exceptions.NoSuchKey:
            # Try alternate path
            alt_key = f"{self.s3_prefix}{tree_id}.pkl"
            try:
                response = self.s3_client.get_object(
                    Bucket=self.s3_bucket,
                    Key=alt_key,
                )
                data = safe_pickle_loads(response["Body"].read())
                tree = self._dict_to_tree(data)
                logger.info(
                    f"Loaded tree '{tree_id}' from s3://{self.s3_bucket}/{alt_key}"
                )
                return tree
            except Exception:
                pass

            logger.warning(f"Tree '{tree_id}' not found in S3")
            return None

        except Exception as e:
            logger.error(f"Failed to load tree '{tree_id}' from S3: {e}")
            return None

    def list_s3_trees(self) -> List[str]:
        """List all trees available in S3."""
        if not self.s3_client or not self.s3_bucket:
            return []

        trees = set()

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=self.s3_bucket, Prefix=self.s3_prefix
            ):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith(".pkl"):
                        # Extract tree name from key
                        # Pattern: trees/tree_id/tree_id.pkl or trees/tree_id.pkl
                        rel_path = key[len(self.s3_prefix) :]
                        if "/" in rel_path:
                            tree_id = rel_path.split("/")[0]
                        else:
                            tree_id = rel_path.replace(".pkl", "")
                        trees.add(tree_id)

        except Exception as e:
            logger.error(f"Failed to list S3 trees: {e}")

        return sorted(trees)

    # ==================== High-Level API ====================

    def save_tree(
        self,
        tree: KnowledgeTree,
        to_s3: bool = False,
        to_local: bool = True,
    ) -> Dict[str, str]:
        """
        Save a tree to configured backends.

        Args:
            tree: KnowledgeTree to save
            to_s3: Whether to save to S3
            to_local: Whether to save locally

        Returns:
            Dict with paths where tree was saved
        """
        result = {}

        if to_local:
            result["local"] = self.save_tree_local(tree)

        if to_s3 and self.s3_bucket:
            result["s3"] = self.save_tree_s3(tree)

        return result

    def load_tree(
        self,
        tree_id: str,
        prefer_s3: bool = False,
    ) -> Optional[KnowledgeTree]:
        """
        Load a tree from available backends.

        Args:
            tree_id: Tree ID to load
            prefer_s3: If True, try S3 first, then local

        Returns:
            KnowledgeTree or None if not found
        """
        if prefer_s3 and self.s3_bucket:
            tree = self.load_tree_s3(tree_id)
            if tree:
                return tree

        tree = self.load_tree_local(tree_id)
        if tree:
            return tree

        if not prefer_s3 and self.s3_bucket:
            return self.load_tree_s3(tree_id)

        return None

    # ==================== Forest Operations ====================

    def save_forest(
        self,
        forest: TreeForest,
        to_s3: bool = False,
        to_local: bool = True,
    ) -> Dict[str, Dict[str, str]]:
        """
        Save all trees in a forest.

        Args:
            forest: TreeForest to save
            to_s3: Whether to save to S3
            to_local: Whether to save locally

        Returns:
            Dict mapping tree_id to save paths
        """
        result = {}
        for tree_id, tree in forest.trees.items():
            result[tree_id] = self.save_tree(tree, to_s3=to_s3, to_local=to_local)
        return result

    def load_forest(
        self,
        tree_ids: Optional[List[str]] = None,
        prefer_s3: bool = False,
        forest_id: str = "default",
        forest_name: str = "Default Forest",
    ) -> TreeForest:
        """
        Load trees into a forest.

        Args:
            tree_ids: Specific trees to load (None = load all available)
            prefer_s3: If True, prefer S3 over local
            forest_id: ID for the forest
            forest_name: Name for the forest

        Returns:
            TreeForest with loaded trees
        """
        forest = TreeForest(forest_id=forest_id, name=forest_name)

        if tree_ids is None:
            # Discover available trees
            tree_ids = set(self.list_local_trees())
            if self.s3_bucket:
                tree_ids.update(self.list_s3_trees())
            tree_ids = list(tree_ids)

        for tree_id in tree_ids:
            tree = self.load_tree(tree_id, prefer_s3=prefer_s3)
            if tree:
                forest.add_tree(tree)

        return forest

    # ==================== Serialization Helpers ====================

    def _tree_to_dict(self, tree: KnowledgeTree) -> Dict[str, Any]:
        """Serialize a KnowledgeTree to a dictionary."""
        return {
            "tree_id": tree.tree_id,
            "name": tree.name,
            "description": tree.description,
            "knowledge_type": tree.knowledge_type.value,
            "tags": tree.tags,
            "num_layers": tree.num_layers,
            "embedding_model": tree.embedding_model,
            "embedding_dimension": tree.embedding_dimension,
            "created_at": tree.created_at.isoformat(),
            "updated_at": tree.updated_at.isoformat(),
            "version": tree.version,
            "nodes": {str(idx): node.to_dict() for idx, node in tree.all_nodes.items()},
            "root_node_indices": list(tree.root_nodes.keys()),
            "leaf_node_indices": list(tree.leaf_nodes.keys()),
            "layer_to_node_indices": {
                layer: [n.index for n in nodes]
                for layer, nodes in tree.layer_to_nodes.items()
            },
        }

    def _dict_to_tree(self, data: Dict[str, Any]) -> KnowledgeTree:
        """Deserialize a dictionary to a KnowledgeTree."""
        tree = KnowledgeTree(
            tree_id=data["tree_id"],
            name=data["name"],
            description=data.get("description", ""),
            knowledge_type=KnowledgeType(data.get("knowledge_type", "factual")),
            tags=data.get("tags", []),
            num_layers=data.get("num_layers", 0),
            embedding_model=data.get("embedding_model", "OpenAI"),
            embedding_dimension=data.get("embedding_dimension", 1536),
            version=data.get("version", "1.0.0"),
        )

        # Parse timestamps
        if "created_at" in data:
            try:
                tree.created_at = datetime.fromisoformat(data["created_at"])
            except (ValueError, TypeError):
                pass

        if "updated_at" in data:
            try:
                tree.updated_at = datetime.fromisoformat(data["updated_at"])
            except (ValueError, TypeError):
                pass

        # Deserialize nodes
        for idx_str, node_data in data.get("nodes", {}).items():
            node = KnowledgeNode.from_dict(node_data)
            tree.all_nodes[int(idx_str)] = node

        # Restore root/leaf node references
        for idx in data.get("root_node_indices", []):
            if idx in tree.all_nodes:
                tree.root_nodes[idx] = tree.all_nodes[idx]

        for idx in data.get("leaf_node_indices", []):
            if idx in tree.all_nodes:
                tree.leaf_nodes[idx] = tree.all_nodes[idx]

        # Restore layer mapping
        for layer_str, indices in data.get("layer_to_node_indices", {}).items():
            layer = int(layer_str)
            tree.layer_to_nodes[layer] = [
                tree.all_nodes[idx] for idx in indices if idx in tree.all_nodes
            ]

        return tree

    # ==================== RAPTOR Compatibility ====================

    def export_to_raptor_format(
        self,
        tree: KnowledgeTree,
        output_path: str,
    ) -> str:
        """
        Export tree in RAPTOR-compatible pickle format.

        This creates a pickle file that can be loaded by the original
        RAPTOR RetrievalAugmentation class.

        Args:
            tree: KnowledgeTree to export
            output_path: Path for output pickle file

        Returns:
            Path where file was saved
        """
        try:
            from ..raptor.bridge import export_to_raptor

            export_to_raptor(tree, output_path)
            logger.info(f"Exported RAPTOR-compatible tree to {output_path}")
            return output_path
        except ImportError:
            # Fallback: export in our native format
            logger.warning(
                "RAPTOR bridge not available, exporting in native format instead"
            )
            return self.save_tree_local(tree, path=output_path)


# Convenience singleton for simple usage
_default_persistence: Optional[TreePersistence] = None


def get_persistence(
    local_dir: Optional[str] = None,
    s3_bucket: Optional[str] = None,
) -> TreePersistence:
    """Get or create the default persistence instance."""
    global _default_persistence

    if _default_persistence is None:
        _default_persistence = TreePersistence(
            local_dir=local_dir or os.environ.get("TREES_LOCAL_DIR", "./trees"),
            s3_bucket=s3_bucket or os.environ.get("TREES_S3_BUCKET"),
        )

    return _default_persistence
