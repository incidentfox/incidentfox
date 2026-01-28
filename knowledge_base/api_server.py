#!/usr/bin/env python3
"""
RAPTOR Knowledge Base API Server

Provides REST API endpoints for querying RAPTOR trees with dynamic multi-tenant
support. Trees are loaded on-demand from S3 with LRU caching for memory efficiency.

Endpoints:
- GET  /health                    - Health check with cache info
- GET  /api/v1/cache/stats        - Detailed cache statistics
- GET  /api/v1/trees              - List available trees
- POST /api/v1/search             - Search across trees
- POST /api/v1/federated/search   - Search across multiple trees
- POST /api/v1/answer             - Answer question using RAPTOR
- POST /api/v1/retrieve           - Retrieve relevant chunks only
- POST /api/v1/tree/documents     - Incrementally add documents to a tree

Environment Variables:
- RAPTOR_TREES_DIR: Directory containing .pkl tree files (default: ./trees)
- RAPTOR_DEFAULT_TREE: Default tree to use (default: k8s)
- OPENAI_API_KEY: Required for QA and embedding models
- PORT: Server port (default: 8000)

S3 Lazy Loading (for dynamic multi-tenant):
- S3_LAZY_LOAD_ENABLED: Enable S3 lazy loading (default: true)
- S3_TREES_BUCKET: S3 bucket for trees (default: raptor-kb-trees-103002841599)
- S3_TREES_PREFIX: Prefix in bucket (default: trees)
- AWS_REGION: AWS region (default: us-west-2)

LRU Cache Management:
- MAX_TREE_CACHE_SIZE_GB: Max total cache size in GB (default: 16)
- MAX_CACHED_TREES: Max number of trees in memory (default: 5)
"""

import logging
import os
import pickle
import sys
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# RAPTOR imports
from raptor import RetrievalAugmentation, RetrievalAugmentationConfig
from raptor.EmbeddingModels import OpenAIEmbeddingModel
from raptor.tree_structures import Tree

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
TREES_DIR = Path(os.getenv("RAPTOR_TREES_DIR", "./trees"))
DEFAULT_TREE = os.getenv("RAPTOR_DEFAULT_TREE", "k8s")

# S3 Configuration for lazy tree loading
S3_TREES_BUCKET = os.getenv("S3_TREES_BUCKET", "raptor-kb-trees-103002841599")
S3_TREES_PREFIX = os.getenv("S3_TREES_PREFIX", "trees")
S3_ENABLED = os.getenv("S3_LAZY_LOAD_ENABLED", "true").lower() in ("true", "1", "yes")
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")

# LRU Cache Configuration
MAX_CACHE_SIZE_GB = float(os.getenv("MAX_TREE_CACHE_SIZE_GB", "16"))
MAX_CACHED_TREES = int(os.getenv("MAX_CACHED_TREES", "5"))

# Global tree cache with LRU ordering and size tracking
_tree_cache: OrderedDict[str, RetrievalAugmentation] = OrderedDict()
_tree_sizes: Dict[str, int] = {}  # tree_name -> size in bytes
_cache_lock = threading.Lock()
_download_locks: Dict[str, threading.Lock] = {}  # Prevent concurrent downloads of same tree


def _get_download_lock(tree_name: str) -> threading.Lock:
    """Get or create a lock for downloading a specific tree."""
    if tree_name not in _download_locks:
        _download_locks[tree_name] = threading.Lock()
    return _download_locks[tree_name]


def _download_tree_from_s3(tree_name: str) -> Path:
    """
    Download a tree from S3 to local storage.

    Args:
        tree_name: Name of the tree to download

    Returns:
        Path to the downloaded file

    Raises:
        FileNotFoundError: If tree doesn't exist in S3
        RuntimeError: If download fails
    """
    if not S3_ENABLED:
        raise FileNotFoundError(f"S3 lazy loading disabled, tree not found: {tree_name}")

    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        raise RuntimeError("boto3 not installed, cannot download from S3")

    # Ensure trees directory exists
    TREES_DIR.mkdir(parents=True, exist_ok=True)

    # Construct S3 key - try multiple patterns
    # Pattern 1: trees/{tree_name}/{tree_name}.pkl
    # Pattern 2: trees/{tree_name}.pkl
    s3_keys_to_try = [
        f"{S3_TREES_PREFIX}/{tree_name}/{tree_name}.pkl",
        f"{S3_TREES_PREFIX}/{tree_name}.pkl",
    ]

    local_path = TREES_DIR / f"{tree_name}.pkl"

    # Use a lock to prevent concurrent downloads of the same tree
    download_lock = _get_download_lock(tree_name)
    with download_lock:
        # Check again if file exists (another thread may have downloaded it)
        if local_path.exists():
            logger.info(f"Tree already downloaded by another thread: {tree_name}")
            return local_path

        s3_client = boto3.client("s3", region_name=AWS_REGION)

        for s3_key in s3_keys_to_try:
            try:
                logger.info(f"Attempting to download tree from s3://{S3_TREES_BUCKET}/{s3_key}")

                # Get file size first
                head_response = s3_client.head_object(Bucket=S3_TREES_BUCKET, Key=s3_key)
                file_size = head_response["ContentLength"]
                file_size_gb = file_size / (1024**3)

                logger.info(f"Tree {tree_name} size: {file_size_gb:.2f} GB")

                # Download with progress logging
                temp_path = local_path.with_suffix(".downloading")
                start_time = time.time()

                s3_client.download_file(S3_TREES_BUCKET, s3_key, str(temp_path))

                # Rename to final path (atomic on most filesystems)
                temp_path.rename(local_path)

                download_time = time.time() - start_time
                speed_mbps = (file_size / (1024**2)) / download_time if download_time > 0 else 0

                logger.info(
                    f"Downloaded tree {tree_name}: {file_size_gb:.2f} GB in {download_time:.1f}s "
                    f"({speed_mbps:.1f} MB/s)"
                )

                return local_path

            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    logger.debug(f"Tree not found at {s3_key}, trying next pattern")
                    continue
                raise RuntimeError(f"S3 error downloading {tree_name}: {e}")

        # None of the patterns worked
        raise FileNotFoundError(
            f"Tree '{tree_name}' not found in S3 bucket {S3_TREES_BUCKET}. "
            f"Tried: {s3_keys_to_try}"
        )


def _estimate_tree_memory_size(tree: Tree) -> int:
    """Estimate memory size of a loaded tree in bytes."""
    try:
        return sys.getsizeof(pickle.dumps(tree))
    except Exception:
        # Fallback: estimate based on node count
        # Assume ~10KB per node (embedding + text + metadata)
        return len(tree.all_nodes) * 10 * 1024


def _get_total_cache_size() -> int:
    """Get total size of cached trees in bytes."""
    return sum(_tree_sizes.values())


def _evict_lru_trees_if_needed(new_tree_size: int) -> None:
    """
    Evict least recently used trees if adding new tree would exceed limits.

    Eviction triggers:
    1. Total cache size would exceed MAX_CACHE_SIZE_GB
    2. Number of cached trees would exceed MAX_CACHED_TREES
    """
    max_cache_bytes = int(MAX_CACHE_SIZE_GB * 1024**3)

    with _cache_lock:
        # Check tree count limit
        while len(_tree_cache) >= MAX_CACHED_TREES:
            if not _tree_cache:
                break
            oldest_tree = next(iter(_tree_cache))
            logger.info(f"Evicting tree {oldest_tree} (max trees limit: {MAX_CACHED_TREES})")
            del _tree_cache[oldest_tree]
            _tree_sizes.pop(oldest_tree, None)

        # Check memory limit
        while _get_total_cache_size() + new_tree_size > max_cache_bytes:
            if not _tree_cache:
                break
            oldest_tree = next(iter(_tree_cache))
            logger.info(
                f"Evicting tree {oldest_tree} (memory limit: {MAX_CACHE_SIZE_GB} GB, "
                f"current: {_get_total_cache_size() / 1024**3:.2f} GB)"
            )
            del _tree_cache[oldest_tree]
            _tree_sizes.pop(oldest_tree, None)


def _detect_embedding_info(tree: Tree) -> tuple[str, int]:
    """
    Detect the embedding model key and dimension used in the tree.

    Returns:
        tuple of (embedding_key, embedding_dimension)
    """
    for node in tree.all_nodes.values():
        if hasattr(node, "embeddings") and node.embeddings:
            keys = list(node.embeddings.keys())
            if keys:
                key = keys[0]
                embedding = node.embeddings[key]
                dim = len(embedding) if embedding is not None else 1536
                return key, dim
    # Fallback to defaults
    return "OpenAI", 1536


def _get_embedding_model_for_dim(dim: int) -> OpenAIEmbeddingModel:
    """
    Return the appropriate OpenAI embedding model based on dimension.

    - 3072 dim -> text-embedding-3-large
    - 1536 dim -> text-embedding-3-small or ada-002
    """
    if dim == 3072:
        return OpenAIEmbeddingModel(model="text-embedding-3-large")
    else:
        return OpenAIEmbeddingModel(model="text-embedding-3-small")


def load_tree(tree_name: str) -> RetrievalAugmentation:
    """
    Load a RAPTOR tree with caching and lazy S3 loading.

    Load order:
    1. Check in-memory cache (LRU)
    2. Check local disk
    3. Download from S3 (if enabled)

    The cache implements LRU eviction based on:
    - MAX_CACHED_TREES: Maximum number of trees in memory
    - MAX_CACHE_SIZE_GB: Maximum total memory usage
    """
    # 1. Check cache first (move to end for LRU ordering)
    with _cache_lock:
        if tree_name in _tree_cache:
            # Move to end (most recently used)
            _tree_cache.move_to_end(tree_name)
            logger.debug(f"Cache hit for tree: {tree_name}")
            return _tree_cache[tree_name]

    # 2. Try to find file locally
    tree_path = _find_local_tree_path(tree_name)

    # 3. If not found locally, try S3
    if tree_path is None:
        logger.info(f"Tree {tree_name} not found locally, attempting S3 download")
        tree_path = _download_tree_from_s3(tree_name)

    logger.info(f"Loading tree from: {tree_path}")

    # Load the tree pickle
    with open(tree_path, "rb") as f:
        tree = pickle.load(f)

    # Estimate memory size for LRU management
    tree_size = _estimate_tree_memory_size(tree)
    logger.info(f"Tree {tree_name} estimated memory: {tree_size / 1024**3:.2f} GB")

    # Evict old trees if needed before adding new one
    _evict_lru_trees_if_needed(tree_size)

    # Detect embedding configuration
    embedding_key, embedding_dim = _detect_embedding_info(tree)
    logger.info(f"Detected embedding key: {embedding_key}, dimension: {embedding_dim}")

    # Create config with the correct embedding key and model
    embedding_model = _get_embedding_model_for_dim(embedding_dim)
    config = RetrievalAugmentationConfig(
        tr_context_embedding_model=embedding_key,
        tr_embedding_model=embedding_model,
        tb_cluster_embedding_model=embedding_key,
        tb_embedding_models={embedding_key: embedding_model},
    )

    ra = RetrievalAugmentation(config=config, tree=tree)

    # Add to cache with LRU tracking
    with _cache_lock:
        _tree_cache[tree_name] = ra
        _tree_sizes[tree_name] = tree_size

    logger.info(
        f"Tree loaded: {tree_name} "
        f"(cache: {len(_tree_cache)} trees, {_get_total_cache_size() / 1024**3:.2f} GB)"
    )
    return ra


def _find_local_tree_path(tree_name: str) -> Optional[Path]:
    """
    Find a tree file on local disk.

    Returns:
        Path to the tree file, or None if not found
    """
    # Try direct pkl file first: trees/tree_name.pkl
    tree_path = TREES_DIR / f"{tree_name}.pkl"
    if tree_path.exists():
        return tree_path

    # Try as directory with pkl inside: trees/tree_name/tree_name.pkl
    tree_dir = TREES_DIR / tree_name
    if tree_dir.is_dir():
        tree_path = tree_dir / f"{tree_name}.pkl"
        if tree_path.exists():
            return tree_path

        # Also try any .pkl file in the directory
        pkl_files = list(tree_dir.glob("*.pkl"))
        if pkl_files:
            return pkl_files[0]

    return None


def list_available_trees() -> List[str]:
    """List available tree files."""
    if not TREES_DIR.exists():
        return []

    trees = []
    for f in TREES_DIR.iterdir():
        if f.suffix == ".pkl" or f.is_dir():
            trees.append(f.stem if f.suffix == ".pkl" else f.name)
    return trees


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Ensure trees directory exists
    TREES_DIR.mkdir(parents=True, exist_ok=True)

    # Log configuration
    logger.info(
        f"Knowledge Base starting: "
        f"trees_dir={TREES_DIR}, default_tree={DEFAULT_TREE}, "
        f"s3_enabled={S3_ENABLED}, s3_bucket={S3_TREES_BUCKET}, "
        f"max_cache_gb={MAX_CACHE_SIZE_GB}, max_trees={MAX_CACHED_TREES}"
    )

    # Preload default tree (will download from S3 if not local)
    if DEFAULT_TREE:
        try:
            load_tree(DEFAULT_TREE)
            logger.info(f"Preloaded default tree: {DEFAULT_TREE}")
        except FileNotFoundError as e:
            logger.warning(f"Default tree not available: {e}")
        except Exception as e:
            logger.warning(f"Could not preload default tree: {e}")

    yield

    # Cleanup
    with _cache_lock:
        _tree_cache.clear()
        _tree_sizes.clear()


app = FastAPI(
    title="RAPTOR Knowledge Base API",
    description="Tree-organized retrieval for IncidentFox agents",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response Models


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    tree: Optional[str] = Field(None, description="Tree name (default: k8s)")
    top_k: int = Field(5, description="Number of results to return")
    include_summaries: bool = Field(True, description="Include parent summaries")


class SearchResult(BaseModel):
    text: str
    score: float
    layer: int
    node_id: Optional[str] = None
    is_summary: bool = False


class SearchResponse(BaseModel):
    query: str
    tree: str
    results: List[SearchResult]
    total_nodes_searched: int


class AnswerRequest(BaseModel):
    question: str = Field(..., description="Question to answer")
    tree: Optional[str] = Field(None, description="Tree name (default: k8s)")
    top_k: int = Field(5, description="Number of chunks to use as context")


class CitationInfo(BaseModel):
    index: int
    source: str
    rel_path: Optional[str] = None
    node_ids: List[int] = []


class AnswerResponse(BaseModel):
    question: str
    answer: str
    tree: str
    context_chunks: List[str]
    citations: List[CitationInfo] = []
    confidence: Optional[float] = None


class RetrieveRequest(BaseModel):
    query: str = Field(..., description="Query for retrieval")
    tree: Optional[str] = Field(None, description="Tree name")
    top_k: int = Field(10, description="Number of chunks")
    collapse_tree: bool = Field(True, description="Use tree collapse retrieval")


class RetrieveResponse(BaseModel):
    query: str
    tree: str
    chunks: List[Dict[str, Any]]


# --- Tree Explorer Models ---


class TreeStatsResponse(BaseModel):
    tree: str
    total_nodes: int
    layers: int
    leaf_nodes: int
    summary_nodes: int
    layer_counts: Dict[int, int]


class GraphNode(BaseModel):
    id: str
    label: str
    layer: int
    text_preview: str
    has_children: bool
    children_count: int
    source_url: Optional[str] = None
    is_root: bool = False


class GraphEdge(BaseModel):
    source: str
    target: str


class TreeStructureResponse(BaseModel):
    tree: str
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    total_nodes: int
    layers_included: int


class NodeChildrenResponse(BaseModel):
    node_id: str
    children: List[GraphNode]
    edges: List[GraphEdge]


class SearchNodesRequest(BaseModel):
    query: str = Field(..., description="Search query for node content")
    tree: Optional[str] = Field(None, description="Tree name")
    limit: int = Field(50, description="Max nodes to return")


class SearchNodesResult(BaseModel):
    id: str
    label: str
    layer: int
    text_preview: str
    score: float
    source_url: Optional[str] = None


class SearchNodesResponse(BaseModel):
    query: str
    tree: str
    results: List[SearchNodesResult]
    total_matches: int


# --- Incremental Update Models ---


class AddDocumentsRequest(BaseModel):
    content: str = Field(..., description="Text content to add to the tree")
    tree: Optional[str] = Field(None, description="Tree name (default: mega_ultra_v2)")
    similarity_threshold: float = Field(
        0.25, description="Cosine similarity threshold for cluster attachment"
    )
    auto_rebuild_upper: bool = Field(
        True, description="Rebuild upper layers after incremental update"
    )
    save: bool = Field(True, description="Save the updated tree to disk")


class AddDocumentsResponse(BaseModel):
    tree: str
    new_leaves: int
    updated_clusters: int
    created_clusters: int
    total_nodes_after: int
    message: str


# --- Federated Query Models ---


class FederatedSearchRequest(BaseModel):
    query: str = Field(..., description="Search query")
    tree_names: List[str] = Field(..., description="List of tree names to search")
    top_k: int = Field(10, description="Total number of results to return")
    top_k_per_tree: int = Field(5, description="Max results per tree before merging")
    merge_strategy: str = Field(
        "score", description="Merge strategy: 'score', 'round_robin', or 'weighted'"
    )


class FederatedSearchResult(BaseModel):
    text: str
    score: float
    layer: int
    node_id: Optional[str] = None
    is_summary: bool = False
    source_tree: str


class FederatedSearchResponse(BaseModel):
    query: str
    results: List[FederatedSearchResult]
    trees_searched: List[str]
    trees_failed: List[str] = []


class FederatedRetrieveRequest(BaseModel):
    query: str = Field(..., description="Query for retrieval")
    tree_names: List[str] = Field(..., description="List of tree names to query")
    top_k: int = Field(10, description="Number of chunks per tree")
    collapse_tree: bool = Field(True, description="Use tree collapse retrieval")


class TreeContext(BaseModel):
    tree_name: str
    chunks: List[Dict[str, Any]]


class FederatedRetrieveResponse(BaseModel):
    query: str
    contexts: List[TreeContext]
    trees_queried: List[str]
    trees_failed: List[str] = []


# --- Tree Management Models ---


class CreateTreeRequest(BaseModel):
    tree_name: str = Field(
        ..., description="Name for the new tree (alphanumeric, hyphens, underscores)"
    )
    description: Optional[str] = Field(
        None, description="Optional description of the tree"
    )


class CreateTreeResponse(BaseModel):
    tree_name: str
    message: str
    tree_path: str


class DeleteTreeRequest(BaseModel):
    tree_name: str = Field(..., description="Name of the tree to delete")
    confirm: bool = Field(False, description="Must be true to confirm deletion")


# Endpoints


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    with _cache_lock:
        loaded_trees = list(_tree_cache.keys())
        cache_size_gb = _get_total_cache_size() / 1024**3

    return {
        "status": "healthy",
        "trees_dir": str(TREES_DIR),
        "trees_loaded": loaded_trees,
        "cache_size_gb": round(cache_size_gb, 2),
        "available_trees": list_available_trees(),
        "s3_enabled": S3_ENABLED,
        "s3_bucket": S3_TREES_BUCKET if S3_ENABLED else None,
    }


@app.get("/api/v1/cache/stats")
async def get_cache_stats():
    """
    Get detailed cache statistics.

    Useful for monitoring memory usage and understanding cache behavior.
    """
    with _cache_lock:
        tree_details = []
        for tree_name in _tree_cache:
            size_bytes = _tree_sizes.get(tree_name, 0)
            tree_details.append({
                "name": tree_name,
                "size_gb": round(size_bytes / 1024**3, 3),
                "size_bytes": size_bytes,
            })

        total_size = _get_total_cache_size()

    return {
        "trees_cached": len(tree_details),
        "max_trees": MAX_CACHED_TREES,
        "total_size_gb": round(total_size / 1024**3, 3),
        "max_size_gb": MAX_CACHE_SIZE_GB,
        "utilization_percent": round((total_size / (MAX_CACHE_SIZE_GB * 1024**3)) * 100, 1),
        "trees": tree_details,
        "s3_enabled": S3_ENABLED,
        "s3_bucket": S3_TREES_BUCKET,
    }


@app.get("/api/v1/trees")
async def get_trees():
    """List available RAPTOR trees."""
    available = list_available_trees()
    return {
        "trees": available,
        "default": DEFAULT_TREE,
        "loaded": list(_tree_cache.keys()),
    }


@app.post("/api/v1/trees", response_model=CreateTreeResponse)
async def create_tree(request: CreateTreeRequest):
    """
    Create a new empty RAPTOR tree.

    The tree will be initialized with an empty structure and can have
    documents added via the /api/v1/tree/documents endpoint.
    """
    import re

    # Validate tree name
    if not re.match(r"^[a-zA-Z0-9_-]+$", request.tree_name):
        raise HTTPException(
            status_code=400,
            detail="Tree name must contain only alphanumeric characters, hyphens, and underscores",
        )

    # Check if tree already exists
    tree_dir = TREES_DIR / request.tree_name
    tree_path = tree_dir / f"{request.tree_name}.pkl"

    if tree_path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Tree '{request.tree_name}' already exists",
        )

    try:
        # Create tree directory
        tree_dir.mkdir(parents=True, exist_ok=True)

        # Create empty tree with proper embedding model
        embedding_model = OpenAIEmbeddingModel(model="text-embedding-3-small")
        config = RetrievalAugmentationConfig(
            embedding_model=embedding_model,
        )

        # Initialize empty tree structure
        ra = RetrievalAugmentation(config=config)

        # Save the empty tree
        with open(tree_path, "wb") as f:
            pickle.dump(ra.tree, f)

        # Save metadata
        metadata_path = tree_dir / "metadata.json"
        import json
        from datetime import datetime

        metadata = {
            "tree_name": request.tree_name,
            "description": request.description or "",
            "created_at": datetime.utcnow().isoformat(),
            "embedding_model": "text-embedding-3-small",
            "embedding_dim": 1536,
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Created new tree: {request.tree_name}")

        return CreateTreeResponse(
            tree_name=request.tree_name,
            message=f"Tree '{request.tree_name}' created successfully",
            tree_path=str(tree_path),
        )

    except Exception as e:
        logger.error(f"Error creating tree: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create tree: {e}")


@app.delete("/api/v1/trees/{tree_name}")
async def delete_tree(tree_name: str, confirm: bool = False):
    """
    Delete a RAPTOR tree.

    Requires confirm=true query parameter to prevent accidental deletion.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Must pass confirm=true to delete a tree",
        )

    tree_dir = TREES_DIR / tree_name
    tree_path = tree_dir / f"{tree_name}.pkl"

    if not tree_path.exists():
        # Also check for direct pkl file
        direct_path = TREES_DIR / f"{tree_name}.pkl"
        if not direct_path.exists():
            raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")
        tree_path = direct_path
        tree_dir = None

    try:
        # Remove from cache
        if tree_name in _tree_cache:
            del _tree_cache[tree_name]

        # Delete the tree file
        tree_path.unlink()

        # Delete the directory if it exists and is empty
        if tree_dir and tree_dir.exists():
            import shutil

            shutil.rmtree(tree_dir)

        logger.info(f"Deleted tree: {tree_name}")
        return {"message": f"Tree '{tree_name}' deleted successfully"}

    except Exception as e:
        logger.error(f"Error deleting tree: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete tree: {e}")


@app.post("/api/v1/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """
    Search the knowledge base.

    Returns relevant chunks from the RAPTOR tree, including
    both leaf nodes (original content) and summary nodes (parent abstractions).
    """
    tree_name = request.tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading tree: {e}")

    try:
        # Use RAPTOR's retriever
        tree = ra.tree

        # Get relevant context using RAPTOR's retrieve method
        context, layer_info = ra.retrieve(
            question=request.query,
            top_k=request.top_k,
            return_layer_information=True,
        )

        # Build results from layer_info
        retrieved_nodes = []
        for info in layer_info:
            idx = int(info["node_index"])
            node = tree.all_nodes.get(idx)
            if node:
                # Compute a simple score based on layer (lower layer = more specific)
                layer = int(info.get("layer_number", 0))
                score = 1.0 / (1 + layer * 0.2)
                retrieved_nodes.append((node, score, layer))

        results = []
        for node, score, layer in retrieved_nodes:
            results.append(
                SearchResult(
                    text=node.text[:2000],  # Truncate very long texts
                    score=float(score) if score else 0.0,
                    layer=layer,
                    node_id=str(node.index) if hasattr(node, "index") else None,
                    is_summary=layer > 0,
                )
            )

        return SearchResponse(
            query=request.query,
            tree=tree_name,
            results=results,
            total_nodes_searched=(
                len(tree.all_nodes) if hasattr(tree, "all_nodes") else 0
            ),
        )

    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {e}")


@app.post("/api/v1/answer", response_model=AnswerResponse)
async def answer_question(request: AnswerRequest):
    """
    Answer a question using RAPTOR tree-organized retrieval.

    This uses the full RAPTOR pipeline:
    1. Retrieve relevant chunks using tree traversal
    2. Use QA model to generate answer from context
    """
    tree_name = request.tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")

    try:
        # Get answer using RAPTOR with citations
        answer, layer_info, citations = ra.answer_question(
            question=request.question,
            top_k=request.top_k,
            return_layer_information=True,
            use_citations=True,
        )

        # Get the context chunks that were used
        tree = ra.tree
        context_chunks = []
        for info in layer_info:
            idx = int(info["node_index"])
            node = tree.all_nodes.get(idx)
            if node:
                context_chunks.append(node.text[:500])

        # Format citations for response
        citation_infos = [
            CitationInfo(
                index=c.get("index", 0),
                source=c.get("source", ""),
                rel_path=c.get("rel_path"),
                node_ids=c.get("node_ids", []),
            )
            for c in (citations or [])
        ]

        return AnswerResponse(
            question=request.question,
            answer=answer,
            tree=tree_name,
            context_chunks=context_chunks,
            citations=citation_infos,
        )

    except Exception as e:
        logger.error(f"Answer error: {e}")
        raise HTTPException(status_code=500, detail=f"Answer error: {e}")


@app.post("/api/v1/retrieve", response_model=RetrieveResponse)
async def retrieve_chunks(request: RetrieveRequest):
    """
    Retrieve relevant chunks without generating an answer.

    Useful for:
    - Providing context to agents
    - Building custom prompts
    - Inspecting what RAPTOR retrieves
    """
    tree_name = request.tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")

    try:
        tree = ra.tree

        context, layer_info = ra.retrieve(
            question=request.query,
            top_k=request.top_k,
            collapse_tree=request.collapse_tree,
            return_layer_information=True,
        )

        chunks = []
        for info in layer_info:
            idx = int(info["node_index"])
            layer = int(info.get("layer_number", 0))
            node = tree.all_nodes.get(idx)
            if node:
                # Get source metadata if available
                metadata = getattr(node, "metadata", {}) or {}
                source_url = metadata.get("source_url") or getattr(
                    node, "original_content_ref", None
                )

                chunks.append(
                    {
                        "text": node.text,
                        "score": 1.0
                        / (1 + layer * 0.2),  # Approximate score based on layer
                        "layer": layer,
                        "is_summary": layer > 0,
                        "children_count": (
                            len(node.children) if hasattr(node, "children") else 0
                        ),
                        "source_url": source_url,
                        "rel_path": metadata.get("rel_path"),
                    }
                )

        return RetrieveResponse(
            query=request.query,
            tree=tree_name,
            chunks=chunks,
        )

    except Exception as e:
        logger.error(f"Retrieve error: {e}")
        raise HTTPException(status_code=500, detail=f"Retrieve error: {e}")


# --- Federated Query Endpoints ---


def _merge_search_results(
    all_results: List[FederatedSearchResult],
    top_k: int,
    strategy: str,
) -> List[FederatedSearchResult]:
    """Merge results from multiple trees using the specified strategy."""
    if strategy == "round_robin":
        # Interleave results from different trees
        by_tree: Dict[str, List[FederatedSearchResult]] = {}
        for r in all_results:
            by_tree.setdefault(r.source_tree, []).append(r)

        merged = []
        tree_names = list(by_tree.keys())
        idx = 0
        while len(merged) < top_k and any(by_tree.values()):
            tree = tree_names[idx % len(tree_names)]
            if by_tree[tree]:
                merged.append(by_tree[tree].pop(0))
            idx += 1
            # Remove empty trees
            tree_names = [t for t in tree_names if by_tree[t]]
        return merged[:top_k]

    elif strategy == "weighted":
        # Weight by tree order (first tree gets higher weight)
        tree_weights: Dict[str, float] = {}
        for i, r in enumerate(all_results):
            if r.source_tree not in tree_weights:
                tree_weights[r.source_tree] = 1.0 - (len(tree_weights) * 0.1)

        for r in all_results:
            r.score = r.score * tree_weights.get(r.source_tree, 1.0)

        # Fall through to score-based sorting

    # Default: sort by score
    sorted_results = sorted(all_results, key=lambda x: x.score, reverse=True)
    return sorted_results[:top_k]


@app.post("/api/v1/federated/search", response_model=FederatedSearchResponse)
async def federated_search(request: FederatedSearchRequest):
    """
    Search across multiple RAPTOR trees and merge results.

    This enables multi-tenant knowledge base queries where a team
    has access to multiple trees (their own + inherited org trees).
    """
    if not request.tree_names:
        raise HTTPException(status_code=400, detail="tree_names cannot be empty")

    all_results: List[FederatedSearchResult] = []
    trees_searched: List[str] = []
    trees_failed: List[str] = []

    for tree_name in request.tree_names:
        try:
            ra = load_tree(tree_name)
            tree = ra.tree

            # Get relevant context using RAPTOR's retrieve method
            context, layer_info = ra.retrieve(
                question=request.query,
                top_k=request.top_k_per_tree,
                return_layer_information=True,
            )

            # Build results from layer_info
            for info in layer_info:
                idx = int(info["node_index"])
                node = tree.all_nodes.get(idx)
                if node:
                    layer = int(info.get("layer_number", 0))
                    score = 1.0 / (1 + layer * 0.2)
                    all_results.append(
                        FederatedSearchResult(
                            text=node.text[:2000],
                            score=float(score),
                            layer=layer,
                            node_id=str(node.index) if hasattr(node, "index") else None,
                            is_summary=layer > 0,
                            source_tree=tree_name,
                        )
                    )

            trees_searched.append(tree_name)

        except FileNotFoundError:
            logger.warning(f"Tree not found: {tree_name}")
            trees_failed.append(tree_name)
        except Exception as e:
            logger.error(f"Error searching tree {tree_name}: {e}")
            trees_failed.append(tree_name)

    # Merge results
    merged_results = _merge_search_results(
        all_results, request.top_k, request.merge_strategy
    )

    return FederatedSearchResponse(
        query=request.query,
        results=merged_results,
        trees_searched=trees_searched,
        trees_failed=trees_failed,
    )


@app.post("/api/v1/federated/retrieve", response_model=FederatedRetrieveResponse)
async def federated_retrieve(request: FederatedRetrieveRequest):
    """
    Retrieve relevant chunks from multiple RAPTOR trees.

    Returns contexts grouped by tree, useful for:
    - Providing multi-source context to agents
    - Understanding which tree contributed which knowledge
    """
    if not request.tree_names:
        raise HTTPException(status_code=400, detail="tree_names cannot be empty")

    contexts: List[TreeContext] = []
    trees_queried: List[str] = []
    trees_failed: List[str] = []

    for tree_name in request.tree_names:
        try:
            ra = load_tree(tree_name)
            tree = ra.tree

            context, layer_info = ra.retrieve(
                question=request.query,
                top_k=request.top_k,
                collapse_tree=request.collapse_tree,
                return_layer_information=True,
            )

            chunks = []
            for info in layer_info:
                idx = int(info["node_index"])
                layer = int(info.get("layer_number", 0))
                node = tree.all_nodes.get(idx)
                if node:
                    metadata = getattr(node, "metadata", {}) or {}
                    source_url = metadata.get("source_url") or getattr(
                        node, "original_content_ref", None
                    )

                    chunks.append(
                        {
                            "text": node.text,
                            "score": 1.0 / (1 + layer * 0.2),
                            "layer": layer,
                            "is_summary": layer > 0,
                            "children_count": (
                                len(node.children) if hasattr(node, "children") else 0
                            ),
                            "source_url": source_url,
                            "rel_path": metadata.get("rel_path"),
                        }
                    )

            contexts.append(TreeContext(tree_name=tree_name, chunks=chunks))
            trees_queried.append(tree_name)

        except FileNotFoundError:
            logger.warning(f"Tree not found: {tree_name}")
            trees_failed.append(tree_name)
        except Exception as e:
            logger.error(f"Error retrieving from tree {tree_name}: {e}")
            trees_failed.append(tree_name)

    return FederatedRetrieveResponse(
        query=request.query,
        contexts=contexts,
        trees_queried=trees_queried,
        trees_failed=trees_failed,
    )


# --- Tree Explorer Endpoints ---


def _node_to_graph_node(node, node_id: int, layer: int) -> GraphNode:
    """Convert a RAPTOR node to a GraphNode for visualization."""
    text = node.text if hasattr(node, "text") else str(node)
    metadata = getattr(node, "metadata", {}) or {}
    source_url = metadata.get("source_url") or getattr(
        node, "original_content_ref", None
    )
    # children can be a set of node IDs or a list of Node objects
    children = getattr(node, "children", set()) or set()

    # Create a short label
    label_text = text[:60].replace("\n", " ")
    if len(text) > 60:
        label_text += "..."

    return GraphNode(
        id=str(node_id),
        label=f"L{layer}: {label_text}",
        layer=layer,
        text_preview=text[:500],
        has_children=len(children) > 0,
        children_count=len(children),
        source_url=source_url,
        is_root=False,
    )


def _build_node_to_layer_map(raptor_tree) -> Dict[Any, int]:
    """
    Build a mapping from node (or node id) to its layer.
    The tree.layer_to_nodes contains actual Node objects, not IDs.
    We use id(node) as key since nodes may not be hashable by content.
    """
    node_to_layer: Dict[int, int] = {}  # id(node) -> layer

    if hasattr(raptor_tree, "layer_to_nodes"):
        for layer, nodes in raptor_tree.layer_to_nodes.items():
            if nodes:
                for node in nodes:
                    # Use object id as key
                    node_to_layer[id(node)] = layer

    return node_to_layer


def _get_node_layer(raptor_tree, node) -> int:
    """Get the layer for a given node using layer_to_nodes mapping."""
    # First check if the node has a layer attribute
    node_layer = getattr(node, "layer", None)
    if node_layer is not None:
        return node_layer

    # Fall back to searching layer_to_nodes
    if hasattr(raptor_tree, "layer_to_nodes"):
        for layer, nodes in raptor_tree.layer_to_nodes.items():
            if nodes:
                for n in nodes:
                    if id(n) == id(node):
                        return layer
                    # Also try matching by index
                    if getattr(n, "index", None) == getattr(node, "index", -1):
                        return layer

    return 0


def _build_node_index_to_layer_map(raptor_tree) -> Dict[int, int]:
    """Build a mapping from node index to layer."""
    index_to_layer: Dict[int, int] = {}

    if hasattr(raptor_tree, "layer_to_nodes"):
        for layer, nodes in raptor_tree.layer_to_nodes.items():
            if nodes:
                for node in nodes:
                    node_idx = getattr(node, "index", None)
                    if node_idx is not None:
                        index_to_layer[node_idx] = layer

    return index_to_layer


@app.get("/api/v1/tree/stats", response_model=TreeStatsResponse)
async def get_tree_stats(tree: Optional[str] = None):
    """Get statistics about a RAPTOR tree."""
    tree_name = tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")

    raptor_tree = ra.tree
    all_nodes = raptor_tree.all_nodes if hasattr(raptor_tree, "all_nodes") else {}

    # Use layer_to_nodes if available (more reliable than node.layer attribute)
    layer_counts: Dict[int, int] = {}

    if hasattr(raptor_tree, "layer_to_nodes") and raptor_tree.layer_to_nodes:
        for layer, nodes in raptor_tree.layer_to_nodes.items():
            layer_counts[layer] = len(nodes) if nodes else 0
    else:
        # Fallback to node.layer attribute
        for node in all_nodes.values():
            layer = getattr(node, "layer", 0) or 0
            layer_counts[layer] = layer_counts.get(layer, 0) + 1

    leaf_count = layer_counts.get(0, 0)
    summary_count = sum(c for l, c in layer_counts.items() if l > 0)
    num_layers = (
        raptor_tree.num_layers
        if hasattr(raptor_tree, "num_layers")
        else (max(layer_counts.keys()) + 1 if layer_counts else 0)
    )

    return TreeStatsResponse(
        tree=tree_name,
        total_nodes=len(all_nodes),
        layers=num_layers,
        leaf_nodes=leaf_count,
        summary_nodes=summary_count,
        layer_counts=layer_counts,
    )


@app.get("/api/v1/tree/structure", response_model=TreeStructureResponse)
async def get_tree_structure(
    tree: Optional[str] = None,
    max_layers: int = 3,
    max_nodes_per_layer: int = 200,
):
    """
    Get the tree structure for visualization.

    Returns the top N layers of the tree, suitable for initial rendering.
    Use /tree/nodes/{id}/children to lazy-load deeper nodes.
    """
    tree_name = tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")

    raptor_tree = ra.tree
    all_nodes = raptor_tree.all_nodes if hasattr(raptor_tree, "all_nodes") else {}

    if not all_nodes:
        return TreeStructureResponse(
            tree=tree_name,
            nodes=[],
            edges=[],
            total_nodes=0,
            layers_included=0,
        )

    # Build node to layer mapping using layer_to_nodes
    node_to_layer = _build_node_to_layer_map(raptor_tree)

    # Also create a mapping from node index to layer for lookups
    node_id_to_layer: Dict[Any, int] = {}
    if hasattr(raptor_tree, "layer_to_nodes") and raptor_tree.layer_to_nodes:
        for layer, nodes in raptor_tree.layer_to_nodes.items():
            if nodes:
                for node in nodes:
                    node_idx = getattr(node, "index", None)
                    if node_idx is not None:
                        node_id_to_layer[node_idx] = layer

    # Find max layer
    max_layer_in_tree = (
        raptor_tree.num_layers if hasattr(raptor_tree, "num_layers") else 0
    )
    if hasattr(raptor_tree, "layer_to_nodes") and raptor_tree.layer_to_nodes:
        max_layer_in_tree = max(raptor_tree.layer_to_nodes.keys())

    # Build nodes and edges for top layers (highest layer numbers = top of tree)
    graph_nodes: List[GraphNode] = []
    graph_edges: List[GraphEdge] = []
    included_node_ids = set()

    # Start from top layers and work down
    if hasattr(raptor_tree, "layer_to_nodes") and raptor_tree.layer_to_nodes:
        for layer in range(
            max_layer_in_tree, max(max_layer_in_tree - max_layers, -1), -1
        ):
            layer_nodes = raptor_tree.layer_to_nodes.get(layer, [])

            # Limit nodes per layer
            for node in layer_nodes[:max_nodes_per_layer]:
                node_id = getattr(node, "index", id(node))
                graph_nodes.append(_node_to_graph_node(node, node_id, layer))
                included_node_ids.add(node_id)

                # Add edges to children if they're included
                # children can be a set of node IDs (ints) or Node objects
                children_attr = getattr(node, "children", set()) or set()
                for child_ref in children_attr:
                    # Handle both cases: child_ref could be an int (node ID) or a Node object
                    if isinstance(child_ref, int):
                        child_id = child_ref
                        child_node = all_nodes.get(child_id)
                    else:
                        child_id = getattr(child_ref, "index", id(child_ref))
                        child_node = child_ref

                    # Get child layer from our mapping
                    child_layer = node_id_to_layer.get(
                        child_id,
                        node_to_layer.get(id(child_node) if child_node else 0, 0),
                    )
                    if child_layer >= max_layer_in_tree - max_layers:
                        if child_id not in included_node_ids and child_node is not None:
                            graph_nodes.append(
                                _node_to_graph_node(child_node, child_id, child_layer)
                            )
                            included_node_ids.add(child_id)
                        graph_edges.append(
                            GraphEdge(source=str(node_id), target=str(child_id))
                        )
    else:
        # Fallback to old logic if layer_to_nodes not available
        for node_id, node in list(all_nodes.items())[:max_nodes_per_layer]:
            layer = getattr(node, "layer", 0) or 0
            graph_nodes.append(_node_to_graph_node(node, node_id, layer))
            included_node_ids.add(node_id)

    # Add a synthetic root node
    root_node = GraphNode(
        id="__root__",
        label="ROOT",
        layer=max_layer_in_tree + 1,
        text_preview="Knowledge Base Root",
        has_children=True,
        children_count=len([n for n in graph_nodes if n.layer == max_layer_in_tree]),
        is_root=True,
    )
    graph_nodes.insert(0, root_node)

    # Connect top-layer nodes to root
    for node in graph_nodes:
        if node.layer == max_layer_in_tree and not node.is_root:
            graph_edges.append(GraphEdge(source="__root__", target=node.id))

    return TreeStructureResponse(
        tree=tree_name,
        nodes=graph_nodes,
        edges=graph_edges,
        total_nodes=len(all_nodes),
        layers_included=min(max_layers, max_layer_in_tree + 1),
    )


@app.get("/api/v1/tree/nodes/{node_id}", response_model=GraphNode)
async def get_node_details(node_id: str, tree: Optional[str] = None):
    """Get details for a specific node."""
    tree_name = tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")

    raptor_tree = ra.tree
    all_nodes = raptor_tree.all_nodes if hasattr(raptor_tree, "all_nodes") else {}

    try:
        nid = int(node_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid node ID")

    node = all_nodes.get(nid)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    # Get layer from layer_to_nodes mapping
    index_to_layer = _build_node_index_to_layer_map(raptor_tree)
    layer = index_to_layer.get(nid, 0)
    return _node_to_graph_node(node, nid, layer)


@app.get("/api/v1/tree/nodes/{node_id}/children", response_model=NodeChildrenResponse)
async def get_node_children(node_id: str, tree: Optional[str] = None):
    """
    Get children of a specific node for lazy loading.

    Use this to expand nodes in the visualization.
    """
    tree_name = tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")

    raptor_tree = ra.tree
    all_nodes = raptor_tree.all_nodes if hasattr(raptor_tree, "all_nodes") else {}

    try:
        nid = int(node_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid node ID")

    node = all_nodes.get(nid)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    # Get layer mapping for children
    index_to_layer = _build_node_index_to_layer_map(raptor_tree)

    # children can be a set of node IDs (integers) or a list of Node objects
    children_attr = getattr(node, "children", set()) or set()
    child_nodes: List[GraphNode] = []
    edges: List[GraphEdge] = []

    for child_ref in children_attr:
        # Handle both cases: child_ref could be an int (node ID) or a Node object
        if isinstance(child_ref, int):
            child_id = child_ref
            child_node = all_nodes.get(child_id)
        else:
            child_id = getattr(child_ref, "index", None)
            child_node = child_ref

        if child_id is not None and child_node is not None:
            child_layer = index_to_layer.get(child_id, 0)
            child_nodes.append(_node_to_graph_node(child_node, child_id, child_layer))
            edges.append(GraphEdge(source=node_id, target=str(child_id)))

    return NodeChildrenResponse(
        node_id=node_id,
        children=child_nodes,
        edges=edges,
    )


@app.get("/api/v1/tree/nodes/{node_id}/text")
async def get_node_full_text(node_id: str, tree: Optional[str] = None):
    """Get the full text content of a node."""
    tree_name = tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")

    raptor_tree = ra.tree
    all_nodes = raptor_tree.all_nodes if hasattr(raptor_tree, "all_nodes") else {}

    try:
        nid = int(node_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid node ID")

    node = all_nodes.get(nid)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node not found: {node_id}")

    text = node.text if hasattr(node, "text") else str(node)
    metadata = getattr(node, "metadata", {}) or {}

    # Get layer from layer_to_nodes mapping
    index_to_layer = _build_node_index_to_layer_map(raptor_tree)
    layer = index_to_layer.get(nid, 0)
    children = getattr(node, "children", []) or []

    return {
        "node_id": node_id,
        "layer": layer,
        "text": text,
        "source_url": metadata.get("source_url")
        or getattr(node, "original_content_ref", None),
        "rel_path": metadata.get("rel_path"),
        "children_count": len(children),
        "metadata": metadata,
    }


@app.post("/api/v1/tree/search-nodes", response_model=SearchNodesResponse)
async def search_tree_nodes(request: SearchNodesRequest):
    """
    Search for nodes by content.

    Returns matching nodes with their IDs for highlighting in the visualization.
    """
    tree_name = request.tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")

    try:
        # Use RAPTOR's retrieve to find relevant nodes
        context, layer_info = ra.retrieve(
            question=request.query,
            top_k=request.limit,
            return_layer_information=True,
        )

        raptor_tree = ra.tree
        results: List[SearchNodesResult] = []

        for i, info in enumerate(layer_info):
            idx = int(info["node_index"])
            layer = int(info.get("layer_number", 0))
            node = raptor_tree.all_nodes.get(idx)

            if node:
                text = node.text if hasattr(node, "text") else str(node)
                metadata = getattr(node, "metadata", {}) or {}

                # Create label
                label_text = text[:60].replace("\n", " ")
                if len(text) > 60:
                    label_text += "..."

                results.append(
                    SearchNodesResult(
                        id=str(idx),
                        label=f"L{layer}: {label_text}",
                        layer=layer,
                        text_preview=text[:500],
                        score=1.0 - (i * 0.05),  # Decreasing score by rank
                        source_url=metadata.get("source_url"),
                    )
                )

        return SearchNodesResponse(
            query=request.query,
            tree=tree_name,
            results=results,
            total_matches=len(results),
        )

    except Exception as e:
        logger.error(f"Search nodes error: {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {e}")


@app.post("/api/v1/tree/documents", response_model=AddDocumentsResponse)
async def add_documents(request: AddDocumentsRequest):
    """
    Incrementally add new documents to an existing RAPTOR tree.

    This performs an approximate incremental update:
    - Chunks and embeds the new text as leaf nodes
    - Routes each new leaf to the most similar layer-1 cluster (or creates a new cluster)
    - Re-summarizes only affected parent nodes
    - Optionally rebuilds upper layers for consistency

    Note: This is NOT equivalent to a full rebuild and may drift over time.
    Best practice: use incremental updates frequently, do periodic full rebuilds.
    """
    tree_name = request.tree or DEFAULT_TREE

    try:
        ra = load_tree(tree_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tree not found: {tree_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading tree: {e}")

    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    try:
        # Get initial node count
        initial_nodes = len(ra.tree.all_nodes) if ra.tree else 0
        initial_leaves = len(ra.tree.leaf_nodes) if ra.tree else 0

        # Perform incremental update
        # Note: add_to_existing modifies the tree in place
        ra.add_to_existing(
            request.content,
            similarity_threshold=request.similarity_threshold,
        )

        # Calculate stats
        final_nodes = len(ra.tree.all_nodes)
        final_leaves = len(ra.tree.leaf_nodes)
        new_leaves = final_leaves - initial_leaves

        # Estimate clusters (layer 1 nodes)
        layer1_count = len(ra.tree.layer_to_nodes.get(1, []))

        # Save the updated tree if requested
        if request.save:
            tree_path = TREES_DIR / f"{tree_name}.pkl"
            if not tree_path.exists():
                # Check if it's in a subdirectory
                tree_dir = TREES_DIR / tree_name
                if tree_dir.exists() and tree_dir.is_dir():
                    pkl_files = list(tree_dir.glob("*.pkl"))
                    if pkl_files:
                        tree_path = pkl_files[0]

            with open(tree_path, "wb") as f:
                pickle.dump(ra.tree, f)
            logger.info(f"Saved updated tree to {tree_path}")

        return AddDocumentsResponse(
            tree=tree_name,
            new_leaves=new_leaves,
            updated_clusters=0,  # Would need to track this in add_to_existing
            created_clusters=0,  # Would need to track this in add_to_existing
            total_nodes_after=final_nodes,
            message=f"Successfully added {new_leaves} new leaf nodes to tree '{tree_name}'",
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Add documents error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add documents: {e}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
