"""
Ultimate RAG API Server.

FastAPI server that exposes all Ultimate RAG capabilities:
- /query - Knowledge retrieval
- /ingest - Document ingestion
- /graph - Knowledge graph queries
- /teach - Agentic teaching
- /health - Health and maintenance
"""

import logging
import os
import sys

# Pickle compatibility shim for legacy RAPTOR trees.
# Old pickle files reference 'raptor.tree_structures' but the module is now
# at 'knowledge_base.raptor.tree_structures'. This shim creates module aliases
# so pickle.load() can find the classes.
try:
    from knowledge_base import raptor as kb_raptor

    sys.modules["raptor"] = kb_raptor
    # Also alias submodules that might be referenced
    if hasattr(kb_raptor, "tree_structures"):
        sys.modules["raptor.tree_structures"] = kb_raptor.tree_structures
except ImportError:
    pass  # knowledge_base not available, skip shim
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Environment configuration
RAPTOR_TREES_DIR = os.environ.get("RAPTOR_TREES_DIR", "/app/trees")
RAPTOR_DEFAULT_TREE = os.environ.get("RAPTOR_DEFAULT_TREE", "mega_ultra_v2")


# ==================== Request/Response Models ====================


class QueryRequest(BaseModel):
    """Request for knowledge retrieval."""

    query: str = Field(..., description="The query to search for")
    top_k: int = Field(10, ge=1, le=50, description="Number of results")
    mode: Optional[str] = Field(
        None, description="Retrieval mode: standard, fast, thorough, incident"
    )
    filters: Optional[Dict[str, Any]] = Field(None, description="Optional filters")
    include_graph: bool = Field(True, description="Include graph context")


class QueryResult(BaseModel):
    """A single query result."""

    text: str
    score: float
    importance: float
    source: Optional[str] = None
    metadata: Dict[str, Any] = {}


class QueryResponse(BaseModel):
    """Response for knowledge retrieval."""

    query: str
    results: List[QueryResult]
    total_candidates: int
    retrieval_time_ms: float
    mode: str
    strategies_used: List[str]


class IngestRequest(BaseModel):
    """Request for document ingestion."""

    content: Optional[str] = Field(None, description="Raw content to ingest")
    file_path: Optional[str] = Field(None, description="Path to file to ingest")
    source_url: Optional[str] = Field(None, description="URL of the source")
    content_type: Optional[str] = Field(None, description="Content type override")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class IngestResponse(BaseModel):
    """Response for document ingestion."""

    success: bool
    chunks_created: int
    entities_found: List[str]
    relationships_found: int
    processing_time_ms: float
    warnings: List[str] = []


class BatchDocument(BaseModel):
    """A single document in a batch ingest request."""

    content: str = Field(..., description="Document content")
    source_url: Optional[str] = Field(None, description="Source URL")
    content_type: Optional[str] = Field(None, description="Content type")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Document metadata")


class BatchIngestRequest(BaseModel):
    """Request for batch document ingestion."""

    documents: List[BatchDocument] = Field(..., description="Documents to ingest")
    tree: Optional[str] = Field(None, description="Target tree name")


class BatchIngestResponse(BaseModel):
    """Response for batch document ingestion."""

    success: bool
    documents_processed: int
    total_chunks: int
    total_nodes_created: int
    entities_found: List[str]
    processing_time_ms: float
    embedding_time_ms: float
    warnings: List[str] = []


class TeachRequest(BaseModel):
    """Request for teaching the knowledge base."""

    knowledge: str = Field(..., description="The knowledge to teach")
    knowledge_type: Optional[str] = Field(None, description="Type of knowledge")
    source: Optional[str] = Field(None, description="Source of the knowledge")
    entities: Optional[List[str]] = Field(None, description="Related entities")
    importance: Optional[float] = Field(
        None, ge=0, le=1, description="Importance score"
    )


class TeachResponse(BaseModel):
    """Response for teaching."""

    success: bool
    node_id: Optional[int] = None
    status: str
    message: str


class GraphQueryRequest(BaseModel):
    """Request for graph queries."""

    entity_id: Optional[str] = Field(None, description="Entity to query")
    entity_type: Optional[str] = Field(None, description="Filter by entity type")
    relationship_type: Optional[str] = Field(None, description="Filter by relationship")
    max_hops: int = Field(2, ge=1, le=5, description="Max traversal hops")


class GraphEntity(BaseModel):
    """An entity in the graph."""

    entity_id: str
    entity_type: str
    name: str
    description: Optional[str] = None
    properties: Dict[str, Any] = {}


class GraphRelationship(BaseModel):
    """A relationship in the graph."""

    source_id: str
    target_id: str
    relationship_type: str
    properties: Dict[str, Any] = {}


class GraphQueryResponse(BaseModel):
    """Response for graph queries."""

    entities: List[GraphEntity]
    relationships: List[GraphRelationship]
    total_entities: int
    total_relationships: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    uptime_seconds: float
    stats: Dict[str, Any]


class MaintenanceResponse(BaseModel):
    """Maintenance operation response."""

    cycle: int
    started_at: str
    completed_at: str
    stale_detected: int
    gaps_detected: int
    contradictions_detected: int
    tasks_created: int


# ==================== /api/v1 Compatibility Models ====================
# These models match the old knowledge_base/api_server.py interface


class V1SearchRequest(BaseModel):
    """v1 API search request (backward compatible)."""

    query: str = Field(..., description="Search query")
    tree: Optional[str] = Field(None, description="Tree name")
    top_k: int = Field(5, description="Number of results")
    include_summaries: bool = Field(True, description="Include parent summaries")


class V1SearchResult(BaseModel):
    """v1 API search result."""

    text: str
    score: float
    layer: int
    node_id: Optional[str] = None
    is_summary: bool = False


class V1SearchResponse(BaseModel):
    """v1 API search response."""

    query: str
    tree: str
    results: List[V1SearchResult]
    total_nodes_searched: int


class V1AnswerRequest(BaseModel):
    """v1 API answer request."""

    question: str = Field(..., description="Question to answer")
    tree: Optional[str] = Field(None, description="Tree name")
    top_k: int = Field(5, description="Context chunks to use")


class V1AnswerResponse(BaseModel):
    """v1 API answer response."""

    question: str
    answer: str
    tree: str
    context_chunks: List[str]
    confidence: Optional[float] = None


class V1IncidentSearchRequest(BaseModel):
    """v1 API incident search request."""

    symptoms: str = Field(..., description="Incident symptoms")
    affected_service: str = Field("", description="Affected service name")
    include_runbooks: bool = Field(True, description="Include runbooks")
    include_past_incidents: bool = Field(True, description="Include past incidents")
    top_k: int = Field(5, description="Number of results")


class V1IncidentSearchResponse(BaseModel):
    """v1 API incident search response."""

    ok: bool
    symptoms: str
    affected_service: str
    runbooks: List[Dict[str, Any]]
    past_incidents: List[Dict[str, Any]]
    service_context: List[Dict[str, Any]]


class V1GraphQueryRequest(BaseModel):
    """v1 API graph query request."""

    entity_name: str = Field(..., description="Entity to query")
    query_type: str = Field("dependencies", description="Query type")
    max_hops: int = Field(2, description="Max traversal hops")


class V1GraphQueryResponse(BaseModel):
    """v1 API graph query response."""

    ok: bool
    entity: str
    query_type: str
    dependencies: Optional[List[str]] = None
    dependents: Optional[List[str]] = None
    owner: Optional[Dict[str, Any]] = None
    runbooks: Optional[List[Dict[str, Any]]] = None
    incidents: Optional[List[Dict[str, Any]]] = None
    blast_radius: Optional[Dict[str, Any]] = None
    affected_services: Optional[List[str]] = None
    hint: Optional[str] = None


class V1TeachRequest(BaseModel):
    """v1 API teach request."""

    content: str = Field(..., description="Knowledge to teach")
    knowledge_type: str = Field("procedural", description="Type of knowledge")
    source: str = Field("agent_learning", description="Source")
    confidence: float = Field(0.7, description="Confidence score")
    related_entities: List[str] = Field(
        default_factory=list, description="Related services"
    )
    learned_from: str = Field("agent_investigation", description="Learning context")
    task_context: str = Field("", description="Task context")


class V1TeachResponse(BaseModel):
    """v1 API teach response."""

    status: str
    action: Optional[str] = None
    node_id: Optional[int] = None
    message: Optional[str] = None


class V1SimilarIncidentsRequest(BaseModel):
    """v1 API similar incidents request."""

    symptoms: str = Field(..., description="Current symptoms")
    service: str = Field("", description="Service filter")
    limit: int = Field(5, description="Max results")


class V1SimilarIncident(BaseModel):
    """A similar past incident."""

    incident_id: Optional[str] = None
    date: Optional[str] = None
    similarity: float = 0.0
    symptoms: str = ""
    root_cause: str = ""
    resolution: str = ""
    services_affected: List[str] = []


class V1SimilarIncidentsResponse(BaseModel):
    """v1 API similar incidents response."""

    ok: bool
    query_symptoms: str
    similar_incidents: List[V1SimilarIncident]
    total_found: int
    hint: Optional[str] = None


class V1AddDocumentsRequest(BaseModel):
    """v1 API add documents request."""

    content: str = Field(..., description="Content to add")
    tree: Optional[str] = Field(None, description="Tree name")
    similarity_threshold: float = Field(0.25, description="Cluster threshold")
    auto_rebuild_upper: bool = Field(True, description="Rebuild upper layers")
    save: bool = Field(True, description="Save tree to disk")


class V1AddDocumentsResponse(BaseModel):
    """v1 API add documents response."""

    tree: str
    new_leaves: int
    updated_clusters: int
    created_clusters: int
    total_nodes_after: int
    message: str


class V1CreateTreeRequest(BaseModel):
    """v1 API create tree request."""

    tree_name: str = Field(
        ..., description="Name for the new tree (alphanumeric, hyphens, underscores)"
    )
    description: Optional[str] = Field(None, description="Optional description")


class V1CreateTreeResponse(BaseModel):
    """v1 API create tree response."""

    tree_name: str
    message: str
    tree_path: Optional[str] = None


class V1TreeStatsResponse(BaseModel):
    """v1 API tree stats response."""

    tree: str
    total_nodes: int
    layers: int
    leaf_nodes: int
    summary_nodes: int
    layer_counts: Dict[int, int]


class V1GraphNode(BaseModel):
    """Node for tree visualization."""

    id: str
    label: str
    layer: int
    text_preview: str
    has_children: bool
    children_count: int
    source_url: Optional[str] = None
    is_root: bool = False


class V1GraphEdge(BaseModel):
    """Edge for tree visualization."""

    source: str
    target: str


class V1TreeStructureResponse(BaseModel):
    """v1 API tree structure response."""

    tree: str
    nodes: List[V1GraphNode]
    edges: List[V1GraphEdge]
    total_nodes: int
    layers_included: int


class V1NodeChildrenResponse(BaseModel):
    """v1 API node children response."""

    node_id: str
    children: List[V1GraphNode]
    edges: List[V1GraphEdge]


class V1NodeTextResponse(BaseModel):
    """v1 API node text response."""

    node_id: str
    text: str
    layer: int
    is_leaf: bool
    children_count: int
    source_url: Optional[str] = None


class V1SearchNodesRequest(BaseModel):
    """v1 API search nodes request."""

    query: str = Field(..., description="Search query for node content")
    tree: Optional[str] = Field(None, description="Tree name")
    limit: int = Field(50, description="Max nodes to return")


class V1SearchNodesResult(BaseModel):
    """v1 API search nodes result."""

    id: str
    label: str
    layer: int
    text_preview: str
    score: float
    source_url: Optional[str] = None


class V1SearchNodesResponse(BaseModel):
    """v1 API search nodes response."""

    tree: str
    query: str
    results: List[V1SearchNodesResult]
    total_results: int


class V1AddDocumentsRequest(BaseModel):
    """v1 API add documents request."""

    content: str = Field(..., description="Content to add")
    tree: Optional[str] = Field(None, description="Tree name")


# ==================== Persistence Models ====================


class SaveTreeRequest(BaseModel):
    """Request to save a tree."""

    tree: Optional[str] = Field(None, description="Tree name (default: all trees)")
    to_local: bool = Field(True, description="Save to local disk")
    to_s3: bool = Field(False, description="Save to S3")
    format: str = Field("pickle", description="Format: 'pickle' or 'json'")


class SaveTreeResponse(BaseModel):
    """Response from save operation."""

    success: bool
    trees_saved: List[str]
    paths: Dict[str, Dict[str, str]]  # tree_id -> {local: path, s3: uri}
    message: str


class LoadTreeRequest(BaseModel):
    """Request to load a tree."""

    tree: str = Field(..., description="Tree name to load")
    from_s3: bool = Field(False, description="Load from S3 (default: local)")


class LoadTreeResponse(BaseModel):
    """Response from load operation."""

    success: bool
    tree: str
    source: str  # "local" or "s3"
    node_count: int
    message: str


class ListTreesResponse(BaseModel):
    """Response listing available trees."""

    local_trees: List[str]
    s3_trees: List[str]
    loaded_trees: List[str]


# ==================== API Server ====================


class UltimateRAGServer:
    """
    Main server class that manages all components.

    Usage:
        server = UltimateRAGServer()
        await server.initialize()
        app = server.create_app()
    """

    def __init__(self):
        # Components (initialized lazily)
        self.forest = None
        self.graph = None
        self.retriever = None
        self.processor = None
        self.teaching = None
        self.maintenance = None
        self.observations = None
        self.persistence = None

        # Stats
        self._start_time = datetime.utcnow()
        self._query_count = 0
        self._ingest_count = 0

    async def initialize(
        self,
        tree_path: Optional[str] = None,
        trees_dir: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize all components.

        Args:
            tree_path: Path to a single tree pickle file to load
            trees_dir: Directory containing multiple tree pickle files
            config: Optional configuration dict
        """
        from ..agents.maintenance import MaintenanceAgent
        from ..agents.observations import ObservationCollector
        from ..agents.teaching import TeachingInterface
        from ..core.node import TreeForest
        from ..core.persistence import TreePersistence
        from ..graph.graph import KnowledgeGraph
        from ..ingestion.processor import DocumentProcessor, ProcessingConfig
        from ..retrieval.retriever import RetrievalConfig, UltimateRetriever

        logger.info("Initializing Ultimate RAG server...")

        # Initialize persistence layer
        local_trees_dir = os.environ.get("TREES_LOCAL_DIR", "./trees")
        s3_bucket = os.environ.get("TREES_S3_BUCKET")
        self.persistence = TreePersistence(
            local_dir=local_trees_dir,
            s3_bucket=s3_bucket,
        )
        logger.info(
            f"Persistence initialized: local_dir={local_trees_dir}, s3_bucket={s3_bucket or 'disabled'}"
        )

        # Initialize forest
        self.forest = TreeForest(
            forest_id="default",
            name="Default Forest",
            description="Auto-created forest for RAPTOR trees",
        )

        # Determine trees directory from parameter or environment
        effective_trees_dir = trees_dir or RAPTOR_TREES_DIR

        # Load trees from directory if it exists and has pickle files
        trees_path = Path(effective_trees_dir)
        if trees_path.exists() and trees_path.is_dir():
            pkl_files = list(trees_path.glob("*.pkl"))
            if pkl_files:
                from ..raptor.bridge import import_raptor_tree

                logger.info(
                    f"Loading {len(pkl_files)} trees from {effective_trees_dir}"
                )
                for pkl_file in pkl_files:
                    try:
                        tree_name = pkl_file.stem
                        tree = import_raptor_tree(str(pkl_file), tree_name=tree_name)
                        tree.tree_id = tree_name
                        self.forest.add_tree(tree)
                        logger.info(f"Loaded tree '{tree_name}' from {pkl_file}")
                    except Exception as e:
                        logger.error(f"Failed to load tree from {pkl_file}: {e}")

        # Load single tree if provided (takes precedence for 'main')
        if tree_path:
            from ..raptor.bridge import import_raptor_tree

            try:
                tree = import_raptor_tree(tree_path)
                tree.tree_id = "main"  # Ensure tree has the expected ID
                self.forest.add_tree(tree)
                logger.info(f"Loaded tree from {tree_path}")
            except Exception as e:
                logger.error(f"Failed to load tree: {e}")

        # If no trees were loaded, create a default empty tree
        if not self.forest.trees:
            from ..core.node import KnowledgeTree

            default_tree = KnowledgeTree(
                tree_id="default",
                name="Default Knowledge Tree",
                description="Auto-created tree for ingested content",
            )
            self.forest.add_tree(default_tree)
            logger.info("Created default empty tree for ingestion")

        logger.info(
            f"Forest initialized with {len(self.forest.trees)} trees: {list(self.forest.trees.keys())}"
        )

        # Initialize graph
        self.graph = KnowledgeGraph()

        # Initialize observations
        self.observations = ObservationCollector()

        # Initialize retriever
        retrieval_config = RetrievalConfig()
        self.retriever = UltimateRetriever(
            forest=self.forest,
            graph=self.graph,
            observation_collector=self.observations,
            config=retrieval_config,
        )

        # Initialize processor
        processing_config = ProcessingConfig()
        self.processor = DocumentProcessor(processing_config)

        # Initialize teaching (uses default tree from forest)
        default_tree = None
        if self.forest.default_tree:
            default_tree = self.forest.get_tree(self.forest.default_tree)
        # Initialize embedder for teaching interface
        embedder = None
        try:
            from knowledge_base.raptor.EmbeddingModels import OpenAIEmbeddingModel

            embedder = OpenAIEmbeddingModel()
            logger.info("Initialized OpenAI embedder for TeachingInterface")
        except ImportError:
            logger.warning(
                "OpenAI embedder not available, nodes will not have embeddings"
            )

        self.teaching = (
            TeachingInterface(
                tree=default_tree,
                graph=self.graph,
                embedder=embedder,
            )
            if default_tree
            else None
        )

        # Initialize maintenance (works with forest)
        self.maintenance = MaintenanceAgent(
            forest=self.forest,
            graph=self.graph,
            observation_collector=self.observations,
        )

        logger.info("Ultimate RAG server initialized")

    def create_app(self) -> FastAPI:
        """Create FastAPI application."""

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Startup
            if not self.forest:
                await self.initialize()
            yield
            # Shutdown
            logger.info("Shutting down Ultimate RAG server")

        app = FastAPI(
            title="Ultimate RAG API",
            description="Enterprise knowledge base with advanced retrieval",
            version="1.0.0",
            lifespan=lifespan,
        )

        # Add CORS
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Register routes
        self._register_routes(app)

        return app

    def _register_routes(self, app: FastAPI):
        """Register all API routes."""

        # ==================== Query Routes ====================

        @app.post("/query", response_model=QueryResponse, tags=["Query"])
        async def query(request: QueryRequest):
            """
            Query the knowledge base.

            Supports multiple retrieval modes:
            - standard: Balanced retrieval
            - fast: Speed-optimized
            - thorough: Quality-optimized
            - incident: Incident response mode
            """
            if not self.retriever:
                raise HTTPException(503, "Server not initialized")

            self._query_count += 1

            try:
                from ..retrieval.retriever import RetrievalMode

                mode = None
                if request.mode:
                    mode = RetrievalMode(request.mode)

                result = await self.retriever.retrieve(
                    query=request.query,
                    top_k=request.top_k,
                    mode=mode,
                    filters=request.filters,
                )

                return QueryResponse(
                    query=request.query,
                    results=[
                        QueryResult(
                            text=chunk.text,
                            score=chunk.score,
                            importance=chunk.importance,
                            source=chunk.metadata.get("source"),
                            metadata=chunk.metadata,
                        )
                        for chunk in result.chunks
                    ],
                    total_candidates=result.total_candidates,
                    retrieval_time_ms=result.retrieval_time_ms,
                    mode=result.mode.value,
                    strategies_used=result.strategies_used,
                )

            except Exception as e:
                logger.error(f"Query failed: {e}")
                raise HTTPException(500, str(e))

        @app.post("/query/incident", response_model=QueryResponse, tags=["Query"])
        async def query_for_incident(
            symptoms: str,
            services: Optional[List[str]] = None,
            top_k: int = 10,
        ):
            """
            Specialized query for incident response.

            Prioritizes runbooks and similar past incidents.
            """
            if not self.retriever:
                raise HTTPException(503, "Server not initialized")

            result = await self.retriever.retrieve_for_incident(
                symptoms=symptoms,
                affected_services=services,
                top_k=top_k,
            )

            return QueryResponse(
                query=symptoms,
                results=[
                    QueryResult(
                        text=chunk.text,
                        score=chunk.score,
                        importance=chunk.importance,
                        metadata=chunk.metadata,
                    )
                    for chunk in result.chunks
                ],
                total_candidates=result.total_candidates,
                retrieval_time_ms=result.retrieval_time_ms,
                mode=result.mode.value,
                strategies_used=result.strategies_used,
            )

        # ==================== Ingest Routes ====================

        @app.post("/ingest", response_model=IngestResponse, tags=["Ingest"])
        async def ingest(request: IngestRequest, background_tasks: BackgroundTasks):
            """
            Ingest content into the knowledge base.

            Provide either content directly or a file_path.
            """
            if not self.processor:
                raise HTTPException(503, "Server not initialized")

            self._ingest_count += 1

            try:
                if request.content:
                    result = self.processor.process_content(
                        content=request.content,
                        source_path=request.source_url or "direct_input",
                        content_type=self._get_content_type(request.content_type),
                        extra_metadata=request.metadata,
                    )
                elif request.file_path:
                    result = self.processor.process_file(
                        file_path=request.file_path,
                        content_type=self._get_content_type(request.content_type),
                        extra_metadata=request.metadata,
                    )
                else:
                    raise HTTPException(400, "Provide either content or file_path")

                # Add chunks to tree in background
                if result.chunks and self.teaching:
                    for chunk in result.chunks:
                        background_tasks.add_task(
                            self._add_chunk_to_tree,
                            chunk,
                        )

                return IngestResponse(
                    success=result.success,
                    chunks_created=result.total_chunks,
                    entities_found=result.entities_found,
                    relationships_found=len(result.relationships_found),
                    processing_time_ms=result.processing_time_ms,
                    warnings=result.warnings,
                )

            except Exception as e:
                logger.error(f"Ingest failed: {e}")
                raise HTTPException(500, str(e))

        @app.post("/ingest/batch", response_model=BatchIngestResponse, tags=["Ingest"])
        async def ingest_batch(request: BatchIngestRequest):
            """
            Batch ingest multiple documents efficiently.

            This endpoint uses batch embedding to process all document chunks
            in a single API call, significantly faster than ingesting one at a time.
            Use this when you have multiple documents to add at once.
            """
            import time

            if not self.processor or not self.forest:
                raise HTTPException(503, "Server not initialized")

            start_time = time.time()
            self._ingest_count += len(request.documents)

            try:
                # Step 1: Process all documents into chunks
                all_chunks = []
                all_entities = []
                warnings = []

                for doc in request.documents:
                    try:
                        result = self.processor.process_content(
                            content=doc.content,
                            source_path=doc.source_url or "batch_input",
                            content_type=self._get_content_type(doc.content_type),
                            extra_metadata=doc.metadata,
                        )
                        all_chunks.extend(result.chunks)
                        all_entities.extend(result.entities_found)
                        warnings.extend(result.warnings)
                    except Exception as e:
                        warnings.append(f"Failed to process document: {e}")

                if not all_chunks:
                    return BatchIngestResponse(
                        success=False,
                        documents_processed=len(request.documents),
                        total_chunks=0,
                        total_nodes_created=0,
                        entities_found=[],
                        processing_time_ms=(time.time() - start_time) * 1000,
                        embedding_time_ms=0,
                        warnings=warnings or ["No chunks created from documents"],
                    )

                # Step 2: Batch embed all chunks
                embed_start = time.time()
                texts = [chunk.text for chunk in all_chunks]

                try:
                    from knowledge_base.raptor.EmbeddingModels import (
                        OpenAIEmbeddingModel,
                    )

                    embedding_model = OpenAIEmbeddingModel()
                    embeddings = embedding_model.create_embeddings_batch(texts)
                except ImportError:
                    # Fallback: no batch embedding available
                    warnings.append("Batch embedding not available, using single calls")
                    embeddings = None
                except Exception as e:
                    warnings.append(f"Batch embedding failed: {e}")
                    embeddings = None

                embed_time_ms = (time.time() - embed_start) * 1000

                # Step 3: Create nodes with pre-computed embeddings
                tree_name = request.tree or self.forest.default_tree or "default"
                tree = self.forest.get_tree(tree_name)

                if not tree:
                    raise HTTPException(404, f"Tree '{tree_name}' not found")

                nodes_created = 0
                from ..core.node import KnowledgeNode
                from ..core.types import ImportanceScore, KnowledgeType

                max_index = max(tree.all_nodes.keys()) if tree.all_nodes else -1

                for i, chunk in enumerate(all_chunks):
                    new_index = max_index + 1 + i

                    # Create importance score
                    importance = ImportanceScore(
                        explicit_priority=0.5,
                        authority_score=0.7,  # Ingested docs start with decent authority
                    )

                    # Create node
                    node = KnowledgeNode(
                        text=chunk.text,
                        index=new_index,
                        layer=0,
                        knowledge_type=KnowledgeType.FACTUAL,
                        importance=importance,
                        source_url=chunk.source_path,
                        tree_id=tree.tree_id,
                    )

                    # Set embedding if we have it
                    if embeddings and i < len(embeddings):
                        node.set_embedding("OpenAI", embeddings[i])

                    # Add to tree
                    tree.add_node(node)
                    nodes_created += 1

                processing_time_ms = (time.time() - start_time) * 1000

                return BatchIngestResponse(
                    success=True,
                    documents_processed=len(request.documents),
                    total_chunks=len(all_chunks),
                    total_nodes_created=nodes_created,
                    entities_found=list(set(all_entities)),
                    processing_time_ms=processing_time_ms,
                    embedding_time_ms=embed_time_ms,
                    warnings=warnings,
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Batch ingest failed: {e}")
                raise HTTPException(500, str(e))

        # ==================== Teach Routes ====================

        @app.post("/teach", response_model=TeachResponse, tags=["Teach"])
        async def teach(request: TeachRequest):
            """
            Teach new knowledge to the knowledge base.

            Use this for agentic learning - agents can teach
            what they learn during work.
            """
            if not self.teaching:
                raise HTTPException(503, "Server not initialized")

            try:
                from ..core.types import KnowledgeType

                knowledge_type = None
                if request.knowledge_type:
                    knowledge_type = KnowledgeType(request.knowledge_type)

                result = await self.teaching.teach(
                    content=request.knowledge,
                    knowledge_type=(
                        knowledge_type.value if knowledge_type else "factual"
                    ),
                    source=request.source or "api",
                    confidence=request.importance or 0.8,
                    related_entities=request.entities,
                )

                return TeachResponse(
                    success=result.status.value in ["added", "updated"],
                    node_id=result.node_id,
                    status=result.status.value,
                    message=result.message,
                )

            except Exception as e:
                logger.error(f"Teach failed: {e}")
                raise HTTPException(500, str(e))

        @app.post("/teach/correction", response_model=TeachResponse, tags=["Teach"])
        async def teach_correction(
            original_query: str,
            wrong_answer: str,
            correct_answer: str,
            context: Optional[str] = None,
        ):
            """
            Teach from a correction.

            Use when an agent's answer was wrong and needs correcting.
            """
            if not self.teaching:
                raise HTTPException(503, "Server not initialized")

            result = await self.teaching.teach_from_correction(
                original_query=original_query,
                wrong_answer=wrong_answer,
                correct_answer=correct_answer,
                context=context,
            )

            return TeachResponse(
                success=result.status.value in ["added", "updated"],
                node_id=result.node_id,
                status=result.status.value,
                message=result.message,
            )

        # ==================== Graph Routes ====================

        @app.post("/graph/query", response_model=GraphQueryResponse, tags=["Graph"])
        async def query_graph(request: GraphQueryRequest):
            """
            Query the knowledge graph.

            Find entities and their relationships.
            """
            if not self.graph:
                raise HTTPException(503, "Server not initialized")

            entities = []
            relationships = []

            if request.entity_id:
                # Get specific entity and neighborhood
                entity = self.graph.get_entity(request.entity_id)
                if entity:
                    entities.append(
                        GraphEntity(
                            entity_id=entity.entity_id,
                            entity_type=entity.entity_type.value,
                            name=entity.name,
                            description=entity.description,
                            properties=entity.properties,
                        )
                    )

                    # Get relationships
                    for rel in self.graph.get_relationships_for_entity(
                        request.entity_id
                    ):
                        relationships.append(
                            GraphRelationship(
                                source_id=rel.source_id,
                                target_id=rel.target_id,
                                relationship_type=rel.relationship_type.value,
                                properties=rel.properties,
                            )
                        )

            elif request.entity_type:
                # Get all entities of type
                from ..graph.entities import EntityType

                entity_type = EntityType(request.entity_type)
                for entity in self.graph.get_entities_by_type(entity_type):
                    entities.append(
                        GraphEntity(
                            entity_id=entity.entity_id,
                            entity_type=entity.entity_type.value,
                            name=entity.name,
                            description=entity.description,
                        )
                    )

            return GraphQueryResponse(
                entities=entities,
                relationships=relationships,
                total_entities=len(entities),
                total_relationships=len(relationships),
            )

        @app.get("/graph/entity/{entity_id}", tags=["Graph"])
        async def get_entity(entity_id: str):
            """Get a specific entity by ID."""
            if not self.graph:
                raise HTTPException(503, "Server not initialized")

            entity = self.graph.get_entity(entity_id)
            if not entity:
                raise HTTPException(404, f"Entity {entity_id} not found")

            return GraphEntity(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type.value,
                name=entity.name,
                description=entity.description,
                properties=entity.properties,
            )

        @app.get("/graph/stats", tags=["Graph"])
        async def get_graph_stats():
            """Get knowledge graph statistics."""
            if not self.graph:
                raise HTTPException(503, "Server not initialized")

            return self.graph.get_stats()

        # ==================== Health/Admin Routes ====================

        @app.get("/health", response_model=HealthResponse, tags=["Admin"])
        async def health():
            """Health check endpoint."""
            uptime = (datetime.utcnow() - self._start_time).total_seconds()

            stats = {
                "query_count": self._query_count,
                "ingest_count": self._ingest_count,
            }

            if self.retriever:
                stats["retriever"] = self.retriever.get_stats()

            if self.processor:
                stats["processor"] = self.processor.get_stats()

            if self.maintenance:
                stats["maintenance"] = self.maintenance.get_stats()

            return HealthResponse(
                status="healthy",
                version="1.0.0",
                uptime_seconds=uptime,
                stats=stats,
            )

        @app.post(
            "/maintenance/run", response_model=MaintenanceResponse, tags=["Admin"]
        )
        async def run_maintenance():
            """Run a maintenance cycle."""
            if not self.maintenance:
                raise HTTPException(503, "Server not initialized")

            result = await self.maintenance.run_maintenance_cycle()

            return MaintenanceResponse(
                cycle=result["cycle"],
                started_at=result["started_at"],
                completed_at=result["completed_at"],
                stale_detected=result["stale_detected"],
                gaps_detected=result["gaps_detected"],
                contradictions_detected=result["contradictions_detected"],
                tasks_created=result["tasks_created"],
            )

        @app.get("/maintenance/report", tags=["Admin"])
        async def get_health_report():
            """Get knowledge base health report."""
            if not self.maintenance:
                raise HTTPException(503, "Server not initialized")

            return self.maintenance.get_health_report()

        @app.get("/maintenance/gaps", tags=["Admin"])
        async def get_knowledge_gaps():
            """Get detected knowledge gaps."""
            if not self.maintenance:
                raise HTTPException(503, "Server not initialized")

            return [gap.to_dict() for gap in self.maintenance.get_gaps()]

        # ==================== /api/v1 Compatibility Routes ====================
        # These routes provide backward compatibility with the old knowledge_base API

        @app.get("/api/v1/cache/stats", tags=["v1-compat"])
        async def v1_cache_stats():
            """
            Get cache statistics (v1 compatible).

            Returns information about cached trees. Required by web UI to check
            if trees are loaded before attempting queries.
            """
            trees_info = []
            total_nodes = 0

            if self.forest:
                for tree_name, tree in self.forest.trees.items():
                    node_count = len(tree.all_nodes) if tree.all_nodes else 0
                    total_nodes += node_count
                    # Estimate size based on node count (rough approximation)
                    estimated_size_bytes = node_count * 10000  # ~10KB per node estimate
                    trees_info.append(
                        {
                            "name": tree_name,
                            "size_gb": round(estimated_size_bytes / 1024**3, 3),
                            "size_bytes": estimated_size_bytes,
                            "node_count": node_count,
                        }
                    )

            total_size_bytes = sum(t["size_bytes"] for t in trees_info)
            max_size_gb = 16.0  # Default max cache size

            return {
                "trees_cached": len(trees_info),
                "max_trees": 5,
                "total_size_gb": round(total_size_bytes / 1024**3, 3),
                "max_size_gb": max_size_gb,
                "utilization_percent": (
                    round((total_size_bytes / (max_size_gb * 1024**3)) * 100, 1)
                    if max_size_gb > 0
                    else 0
                ),
                "trees": trees_info,
                "s3_enabled": bool(os.environ.get("TREES_S3_BUCKET")),
                "s3_bucket": os.environ.get("TREES_S3_BUCKET"),
            }

        @app.get("/api/v1/trees", tags=["v1-compat"])
        async def v1_list_trees():
            """List available knowledge trees (v1 compatible)."""
            trees = list(self.forest.trees.keys()) if self.forest else []
            return {
                "trees": trees,
                "default": trees[0] if trees else "main",
                "loaded": trees,
            }

        @app.post(
            "/api/v1/trees", response_model=V1CreateTreeResponse, tags=["v1-compat"]
        )
        async def v1_create_tree(request: V1CreateTreeRequest):
            """
            Create a new empty knowledge tree (v1 compatible).

            The tree will be initialized with an empty structure and can have
            documents added via the /api/v1/tree/documents endpoint.
            """
            import re

            from ..core.node import KnowledgeTree

            if not self.forest:
                raise HTTPException(503, "Server not initialized")

            # Validate tree name
            if not re.match(r"^[a-zA-Z0-9_-]+$", request.tree_name):
                raise HTTPException(
                    status_code=400,
                    detail="Tree name must contain only alphanumeric characters, hyphens, and underscores",
                )

            # Check if tree already exists
            if request.tree_name in self.forest.trees:
                raise HTTPException(
                    status_code=409,
                    detail=f"Tree '{request.tree_name}' already exists",
                )

            try:
                # Create empty tree
                tree = KnowledgeTree(
                    tree_id=request.tree_name,
                    name=request.tree_name,
                    description=request.description or "",
                )

                # Add to forest
                self.forest.add_tree(tree)

                logger.info(f"Created new tree: {request.tree_name}")

                return V1CreateTreeResponse(
                    tree_name=request.tree_name,
                    message=f"Tree '{request.tree_name}' created successfully",
                )

            except Exception as e:
                logger.error(f"Error creating tree: {e}")
                raise HTTPException(
                    status_code=500, detail=f"Failed to create tree: {e}"
                )

        # ==================== Persistence Endpoints ====================

        @app.post("/persist/save", response_model=SaveTreeResponse, tags=["Persist"])
        async def save_trees(request: SaveTreeRequest):
            """
            Save trees to disk and/or S3.

            Use this to persist changes made via /teach, /ingest, etc.
            By default saves to local disk only. Set to_s3=true to also
            save to S3 for production durability.
            """
            if not self.forest or not self.persistence:
                raise HTTPException(503, "Server not initialized")

            try:
                trees_to_save = []
                if request.tree:
                    # Save specific tree
                    tree = self.forest.get_tree(request.tree)
                    if not tree:
                        raise HTTPException(404, f"Tree '{request.tree}' not found")
                    trees_to_save = [tree]
                else:
                    # Save all trees
                    trees_to_save = list(self.forest.trees.values())

                all_paths = {}
                for tree in trees_to_save:
                    paths = self.persistence.save_tree(
                        tree,
                        to_local=request.to_local,
                        to_s3=request.to_s3,
                    )
                    all_paths[tree.tree_id] = paths

                saved_trees = list(all_paths.keys())
                return SaveTreeResponse(
                    success=True,
                    trees_saved=saved_trees,
                    paths=all_paths,
                    message=f"Successfully saved {len(saved_trees)} tree(s)",
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Save failed: {e}")
                raise HTTPException(500, str(e))

        @app.post("/persist/load", response_model=LoadTreeResponse, tags=["Persist"])
        async def load_tree(request: LoadTreeRequest):
            """
            Load a tree from disk or S3.

            Loads a previously saved tree into memory. Use from_s3=true
            to load from S3 instead of local disk.
            """
            if not self.forest or not self.persistence:
                raise HTTPException(503, "Server not initialized")

            try:
                tree = self.persistence.load_tree(
                    request.tree,
                    prefer_s3=request.from_s3,
                )

                if not tree:
                    raise HTTPException(
                        404,
                        f"Tree '{request.tree}' not found in "
                        + ("S3" if request.from_s3 else "local storage"),
                    )

                # Add to forest (replaces if exists)
                self.forest.add_tree(tree)

                return LoadTreeResponse(
                    success=True,
                    tree=tree.tree_id,
                    source="s3" if request.from_s3 else "local",
                    node_count=len(tree.all_nodes),
                    message=f"Successfully loaded tree '{tree.tree_id}' with {len(tree.all_nodes)} nodes",
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Load failed: {e}")
                raise HTTPException(500, str(e))

        @app.get(
            "/persist/available", response_model=ListTreesResponse, tags=["Persist"]
        )
        async def list_available_trees():
            """
            List trees available for loading.

            Shows trees available locally, in S3, and currently loaded in memory.
            """
            if not self.persistence:
                raise HTTPException(503, "Server not initialized")

            try:
                local_trees = self.persistence.list_local_trees()
                s3_trees = (
                    self.persistence.list_s3_trees()
                    if self.persistence.s3_bucket
                    else []
                )
                loaded_trees = list(self.forest.trees.keys()) if self.forest else []

                return ListTreesResponse(
                    local_trees=local_trees,
                    s3_trees=s3_trees,
                    loaded_trees=loaded_trees,
                )

            except Exception as e:
                logger.error(f"List failed: {e}")
                raise HTTPException(500, str(e))

        @app.post("/persist/export-raptor", tags=["Persist"])
        async def export_raptor_format(tree: str, output_path: Optional[str] = None):
            """
            Export a tree in RAPTOR-compatible pickle format.

            Creates a .pkl file that can be loaded by the original RAPTOR
            RetrievalAugmentation class. Useful for sharing with other systems.
            """
            if not self.forest or not self.persistence:
                raise HTTPException(503, "Server not initialized")

            knowledge_tree = self.forest.get_tree(tree)
            if not knowledge_tree:
                raise HTTPException(404, f"Tree '{tree}' not found")

            try:
                if not output_path:
                    output_path = str(self.persistence.local_dir / f"{tree}_raptor.pkl")

                saved_path = self.persistence.export_to_raptor_format(
                    knowledge_tree, output_path
                )

                return {
                    "success": True,
                    "tree": tree,
                    "output_path": saved_path,
                    "message": f"Exported RAPTOR-compatible tree to {saved_path}",
                }

            except Exception as e:
                logger.error(f"Export failed: {e}")
                raise HTTPException(500, str(e))

        @app.get(
            "/api/v1/tree/stats", response_model=V1TreeStatsResponse, tags=["v1-compat"]
        )
        async def v1_tree_stats(tree: Optional[str] = None):
            """
            Get statistics about a knowledge tree (v1 compatible).

            Returns node counts, layer information, and other tree statistics.
            """
            if not self.forest:
                raise HTTPException(503, "Server not initialized")

            tree_name = tree or "main"

            # Get the tree from forest
            knowledge_tree = self.forest.get_tree(tree_name)
            if not knowledge_tree:
                raise HTTPException(
                    status_code=404,
                    detail=f"Tree '{tree_name}' not found",
                )

            try:
                # Calculate layer counts
                layer_counts: Dict[int, int] = {}
                if knowledge_tree.layer_to_nodes:
                    for layer, nodes in knowledge_tree.layer_to_nodes.items():
                        layer_counts[layer] = len(nodes) if nodes else 0
                else:
                    # Fallback to counting from all_nodes
                    for node in knowledge_tree.all_nodes.values():
                        layer = getattr(node, "layer", 0) or 0
                        layer_counts[layer] = layer_counts.get(layer, 0) + 1

                leaf_count = layer_counts.get(0, 0)
                summary_count = sum(c for l, c in layer_counts.items() if l > 0)

                return V1TreeStatsResponse(
                    tree=tree_name,
                    total_nodes=len(knowledge_tree.all_nodes),
                    layers=knowledge_tree.num_layers
                    or (max(layer_counts.keys()) + 1 if layer_counts else 0),
                    leaf_nodes=leaf_count,
                    summary_nodes=summary_count,
                    layer_counts=layer_counts,
                )

            except Exception as e:
                logger.error(f"Error getting tree stats: {e}")
                raise HTTPException(
                    status_code=500, detail=f"Failed to get tree stats: {e}"
                )

        def _node_to_graph_node(node, node_id: int, layer: int) -> V1GraphNode:
            """Convert a KnowledgeNode to V1GraphNode."""
            text = getattr(node, "text", "") or ""
            children = getattr(node, "children", set()) or set()
            source_url = None
            if hasattr(node, "metadata") and node.metadata:
                source_url = node.metadata.get("source_url")

            return V1GraphNode(
                id=str(node_id),
                label=text[:100] + "..." if len(text) > 100 else text,
                layer=layer,
                text_preview=text[:200] + "..." if len(text) > 200 else text,
                has_children=len(children) > 0,
                children_count=len(children),
                source_url=source_url,
                is_root=layer > 0 and len(children) > 0,
            )

        @app.get(
            "/api/v1/tree/structure",
            response_model=V1TreeStructureResponse,
            tags=["v1-compat"],
        )
        async def v1_tree_structure(
            tree: Optional[str] = None,
            max_layers: int = 3,
            max_nodes_per_layer: int = 200,
        ):
            """Get tree structure for visualization (v1 compatible)."""
            if not self.forest:
                raise HTTPException(503, "Server not initialized")

            tree_name = tree or "main"
            knowledge_tree = self.forest.get_tree(tree_name)

            if not knowledge_tree:
                raise HTTPException(404, f"Tree '{tree_name}' not found")

            # Handle empty trees
            if not knowledge_tree.all_nodes:
                return V1TreeStructureResponse(
                    tree=tree_name,
                    nodes=[],
                    edges=[],
                    total_nodes=0,
                    layers_included=0,
                )

            graph_nodes: List[V1GraphNode] = []
            graph_edges: List[V1GraphEdge] = []
            included_node_ids = set()

            max_layer = knowledge_tree.num_layers or 0
            if knowledge_tree.layer_to_nodes:
                max_layer = max(knowledge_tree.layer_to_nodes.keys())

            # Build nodes from top layers down
            layers_included = 0
            if knowledge_tree.layer_to_nodes:
                for layer in range(max_layer, max(max_layer - max_layers, -1), -1):
                    layer_nodes = knowledge_tree.layer_to_nodes.get(layer, [])
                    if layer_nodes:
                        layers_included += 1

                    for node in layer_nodes[:max_nodes_per_layer]:
                        node_id = getattr(node, "index", id(node))
                        graph_nodes.append(_node_to_graph_node(node, node_id, layer))
                        included_node_ids.add(node_id)

                        # Add edges to children
                        children = getattr(node, "children", set()) or set()
                        for child_ref in children:
                            if isinstance(child_ref, int):
                                child_id = child_ref
                            else:
                                child_id = getattr(child_ref, "index", id(child_ref))

                            if child_id in included_node_ids:
                                graph_edges.append(
                                    V1GraphEdge(
                                        source=str(node_id), target=str(child_id)
                                    )
                                )

            return V1TreeStructureResponse(
                tree=tree_name,
                nodes=graph_nodes,
                edges=graph_edges,
                total_nodes=len(knowledge_tree.all_nodes),
                layers_included=layers_included,
            )

        @app.get(
            "/api/v1/tree/nodes/{node_id}/children",
            response_model=V1NodeChildrenResponse,
            tags=["v1-compat"],
        )
        async def v1_node_children(node_id: str, tree: Optional[str] = None):
            """Get children of a node (v1 compatible)."""
            if not self.forest:
                raise HTTPException(503, "Server not initialized")

            tree_name = tree or "main"
            knowledge_tree = self.forest.get_tree(tree_name)

            if not knowledge_tree:
                raise HTTPException(404, f"Tree '{tree_name}' not found")

            node = knowledge_tree.all_nodes.get(int(node_id))
            if not node:
                raise HTTPException(404, f"Node '{node_id}' not found")

            children_nodes: List[V1GraphNode] = []
            edges: List[V1GraphEdge] = []

            children = getattr(node, "children", set()) or set()
            for child_ref in children:
                if isinstance(child_ref, int):
                    child_id = child_ref
                    child_node = knowledge_tree.all_nodes.get(child_id)
                else:
                    child_id = getattr(child_ref, "index", id(child_ref))
                    child_node = child_ref

                if child_node:
                    child_layer = getattr(child_node, "layer", 0)
                    children_nodes.append(
                        _node_to_graph_node(child_node, child_id, child_layer)
                    )
                    edges.append(V1GraphEdge(source=node_id, target=str(child_id)))

            return V1NodeChildrenResponse(
                node_id=node_id, children=children_nodes, edges=edges
            )

        @app.get(
            "/api/v1/tree/nodes/{node_id}/text",
            response_model=V1NodeTextResponse,
            tags=["v1-compat"],
        )
        async def v1_node_text(node_id: str, tree: Optional[str] = None):
            """Get full text of a node (v1 compatible)."""
            if not self.forest:
                raise HTTPException(503, "Server not initialized")

            tree_name = tree or "main"
            knowledge_tree = self.forest.get_tree(tree_name)

            if not knowledge_tree:
                raise HTTPException(404, f"Tree '{tree_name}' not found")

            node = knowledge_tree.all_nodes.get(int(node_id))
            if not node:
                raise HTTPException(404, f"Node '{node_id}' not found")

            text = getattr(node, "text", "") or ""
            layer = getattr(node, "layer", 0)
            children = getattr(node, "children", set()) or set()
            source_url = None
            if hasattr(node, "metadata") and node.metadata:
                source_url = node.metadata.get("source_url")

            return V1NodeTextResponse(
                node_id=node_id,
                text=text,
                layer=layer,
                is_leaf=layer == 0,
                children_count=len(children),
                source_url=source_url,
            )

        @app.post(
            "/api/v1/tree/search-nodes",
            response_model=V1SearchNodesResponse,
            tags=["v1-compat"],
        )
        async def v1_search_nodes(request: V1SearchNodesRequest):
            """Search for nodes by content (v1 compatible)."""
            if not self.forest:
                raise HTTPException(503, "Server not initialized")

            tree_name = request.tree or "main"
            knowledge_tree = self.forest.get_tree(tree_name)

            if not knowledge_tree:
                raise HTTPException(404, f"Tree '{tree_name}' not found")

            # Simple text search through nodes
            results: List[V1SearchNodesResult] = []
            query_lower = request.query.lower()

            for node_id, node in knowledge_tree.all_nodes.items():
                text = getattr(node, "text", "") or ""
                if query_lower in text.lower():
                    layer = getattr(node, "layer", 0)
                    source_url = None
                    if hasattr(node, "metadata") and node.metadata:
                        source_url = node.metadata.get("source_url")

                    results.append(
                        V1SearchNodesResult(
                            id=str(node_id),
                            label=text[:100] + "..." if len(text) > 100 else text,
                            layer=layer,
                            text_preview=(
                                text[:200] + "..." if len(text) > 200 else text
                            ),
                            score=1.0,  # Simple match
                            source_url=source_url,
                        )
                    )

                    if len(results) >= request.limit:
                        break

            return V1SearchNodesResponse(
                tree=tree_name,
                query=request.query,
                results=results,
                total_results=len(results),
            )

        @app.post("/api/v1/search", response_model=V1SearchResponse, tags=["v1-compat"])
        async def v1_search(request: V1SearchRequest):
            """Search the knowledge base (v1 compatible)."""
            if not self.retriever:
                raise HTTPException(503, "Server not initialized")

            tree_name = request.tree or "main"

            try:
                result = await self.retriever.retrieve(
                    query=request.query,
                    top_k=request.top_k,
                )

                results = []
                for i, chunk in enumerate(result.chunks):
                    results.append(
                        V1SearchResult(
                            text=chunk.text[:2000],
                            score=chunk.score,
                            layer=chunk.metadata.get("layer", 0),
                            node_id=str(chunk.metadata.get("node_id", i)),
                            is_summary=chunk.metadata.get("layer", 0) > 0,
                        )
                    )

                return V1SearchResponse(
                    query=request.query,
                    tree=tree_name,
                    results=results,
                    total_nodes_searched=result.total_candidates,
                )

            except Exception as e:
                logger.error(f"v1 search failed: {e}")
                raise HTTPException(500, str(e))

        @app.post("/api/v1/answer", response_model=V1AnswerResponse, tags=["v1-compat"])
        async def v1_answer(request: V1AnswerRequest):
            """Answer a question (v1 compatible)."""
            if not self.retriever:
                raise HTTPException(503, "Server not initialized")

            tree_name = request.tree or "main"

            try:
                result = await self.retriever.retrieve(
                    query=request.question,
                    top_k=request.top_k,
                )

                # Build context from retrieved chunks
                context_chunks = [chunk.text[:500] for chunk in result.chunks]
                context = "\n\n".join(context_chunks)

                # Generate answer (simplified - real implementation would use LLM)
                answer = f"Based on the knowledge base:\n\n{context[:1500]}"

                return V1AnswerResponse(
                    question=request.question,
                    answer=answer,
                    tree=tree_name,
                    context_chunks=context_chunks,
                    confidence=0.8 if result.chunks else 0.3,
                )

            except Exception as e:
                logger.error(f"v1 answer failed: {e}")
                raise HTTPException(500, str(e))

        @app.post(
            "/api/v1/incident-search",
            response_model=V1IncidentSearchResponse,
            tags=["v1-compat"],
        )
        async def v1_incident_search(request: V1IncidentSearchRequest):
            """
            Search with incident awareness (v1 compatible).

            This is the primary endpoint for incident investigation tools.
            """
            if not self.retriever:
                raise HTTPException(503, "Server not initialized")

            try:
                services = (
                    [request.affected_service] if request.affected_service else None
                )

                result = await self.retriever.retrieve_for_incident(
                    symptoms=request.symptoms,
                    affected_services=services,
                    top_k=request.top_k,
                )

                # Categorize results
                runbooks = []
                past_incidents = []
                service_context = []

                for chunk in result.chunks:
                    metadata = chunk.metadata
                    category = metadata.get("category", "general")

                    if category == "runbook" and request.include_runbooks:
                        runbooks.append(
                            {
                                "title": metadata.get("title", ""),
                                "text": chunk.text[:500],
                                "relevance": chunk.score,
                                "runbook_id": metadata.get("runbook_id"),
                            }
                        )
                    elif category == "incident" and request.include_past_incidents:
                        past_incidents.append(
                            {
                                "incident_id": metadata.get("incident_id"),
                                "summary": chunk.text[:500],
                                "resolution": metadata.get("resolution", ""),
                                "relevance": chunk.score,
                            }
                        )
                    else:
                        service_context.append(
                            {
                                "text": chunk.text[:500],
                                "relevance": chunk.score,
                            }
                        )

                return V1IncidentSearchResponse(
                    ok=True,
                    symptoms=request.symptoms,
                    affected_service=request.affected_service,
                    runbooks=runbooks,
                    past_incidents=past_incidents,
                    service_context=service_context,
                )

            except Exception as e:
                logger.error(f"v1 incident search failed: {e}")
                return V1IncidentSearchResponse(
                    ok=False,
                    symptoms=request.symptoms,
                    affected_service=request.affected_service,
                    runbooks=[],
                    past_incidents=[],
                    service_context=[{"text": f"Error: {e}", "relevance": 0}],
                )

        @app.post(
            "/api/v1/graph/query",
            response_model=V1GraphQueryResponse,
            tags=["v1-compat"],
        )
        async def v1_graph_query(request: V1GraphQueryRequest):
            """Query service graph (v1 compatible)."""
            if not self.graph:
                raise HTTPException(503, "Server not initialized")

            try:
                result = V1GraphQueryResponse(
                    ok=True,
                    entity=request.entity_name,
                    query_type=request.query_type,
                )

                # Find entity by name
                entity = None
                for e in self.graph.entities.values():
                    if e.name.lower() == request.entity_name.lower():
                        entity = e
                        break

                if not entity:
                    result.hint = (
                        f"Entity '{request.entity_name}' not found in knowledge graph"
                    )
                    return result

                # Get relationships based on query type
                relationships = self.graph.get_relationships_for_entity(
                    entity.entity_id
                )

                if request.query_type == "dependencies":
                    deps = [
                        r.target_id
                        for r in relationships
                        if r.relationship_type.value == "depends_on"
                    ]
                    result.dependencies = deps
                    result.hint = "Services this entity depends on"

                elif request.query_type == "dependents":
                    # Reverse lookup - find entities that depend on this one
                    deps = []
                    for rel in self.graph.relationships.values():
                        if (
                            rel.target_id == entity.entity_id
                            and rel.relationship_type.value == "depends_on"
                        ):
                            deps.append(rel.source_id)
                    result.dependents = deps
                    result.hint = "Services that depend on this entity"

                elif request.query_type == "owner":
                    for r in relationships:
                        if r.relationship_type.value == "owned_by":
                            owner_entity = self.graph.get_entity(r.target_id)
                            if owner_entity:
                                result.owner = {
                                    "team": owner_entity.name,
                                    "entity_id": owner_entity.entity_id,
                                }
                                break

                elif request.query_type == "runbooks":
                    rbs = []
                    for r in relationships:
                        if r.relationship_type.value == "has_runbook":
                            rbs.append(
                                {
                                    "runbook_id": r.target_id,
                                    "properties": r.properties,
                                }
                            )
                    result.runbooks = rbs

                elif request.query_type == "incidents":
                    incs = []
                    for r in relationships:
                        if r.relationship_type.value == "had_incident":
                            incs.append(
                                {
                                    "incident_id": r.target_id,
                                    "properties": r.properties,
                                }
                            )
                    result.incidents = incs

                elif request.query_type == "blast_radius":
                    # Traverse dependents recursively
                    affected = set()
                    to_visit = [entity.entity_id]
                    visited = set()

                    while to_visit and len(visited) < request.max_hops * 10:
                        current = to_visit.pop(0)
                        if current in visited:
                            continue
                        visited.add(current)

                        for rel in self.graph.relationships.values():
                            if (
                                rel.target_id == current
                                and rel.relationship_type.value == "depends_on"
                            ):
                                affected.add(rel.source_id)
                                if len(visited) < request.max_hops:
                                    to_visit.append(rel.source_id)

                    result.affected_services = list(affected)
                    result.blast_radius = {
                        "direct_dependents": len([a for a in affected]),
                        "total_affected": len(affected),
                    }
                    result.hint = f"Services affected if {request.entity_name} fails"

                return result

            except Exception as e:
                logger.error(f"v1 graph query failed: {e}")
                return V1GraphQueryResponse(
                    ok=False,
                    entity=request.entity_name,
                    query_type=request.query_type,
                    hint=f"Error: {e}",
                )

        @app.post("/api/v1/teach", response_model=V1TeachResponse, tags=["v1-compat"])
        async def v1_teach(request: V1TeachRequest):
            """Teach new knowledge (v1 compatible)."""
            if not self.teaching:
                raise HTTPException(503, "Server not initialized")

            try:
                from ..core.types import KnowledgeType

                # Map knowledge type
                type_map = {
                    "procedural": KnowledgeType.PROCEDURAL,
                    "factual": KnowledgeType.FACTUAL,
                    "temporal": KnowledgeType.TEMPORAL,
                    "relational": KnowledgeType.RELATIONAL,
                }
                knowledge_type = type_map.get(
                    request.knowledge_type, KnowledgeType.PROCEDURAL
                )

                result = await self.teaching.teach(
                    knowledge=request.content,
                    knowledge_type=knowledge_type,
                    source=request.source,
                    entity_ids=request.related_entities,
                    importance=request.confidence,
                )

                # Map status to v1 format
                status = result.status.value
                message = result.message

                if status == "added":
                    message = "New knowledge successfully added to the knowledge base."
                elif status == "updated":
                    message = "Knowledge merged with existing similar content."
                elif status == "duplicate":
                    message = "This knowledge already exists in the knowledge base."
                elif status == "pending_review":
                    message = "Knowledge queued for human review before adding."
                elif status == "contradiction":
                    message = (
                        "This may contradict existing knowledge. Queued for review."
                    )

                return V1TeachResponse(
                    status=status,
                    action=status,
                    node_id=result.node_id,
                    message=message,
                )

            except Exception as e:
                logger.error(f"v1 teach failed: {e}")
                raise HTTPException(500, str(e))

        @app.post(
            "/api/v1/similar-incidents",
            response_model=V1SimilarIncidentsResponse,
            tags=["v1-compat"],
        )
        async def v1_similar_incidents(request: V1SimilarIncidentsRequest):
            """
            Find similar past incidents (v1 compatible).

            This searches for past incidents with similar symptoms.
            """
            if not self.retriever:
                raise HTTPException(503, "Server not initialized")

            try:
                # Build query for incident similarity
                query = request.symptoms
                if request.service:
                    query = f"{request.service}: {query}"

                # Use incident-aware retrieval with filter for incidents only
                result = await self.retriever.retrieve(
                    query=query,
                    top_k=request.limit * 2,  # Get more, filter down
                    filters={"category": "incident"},
                )

                similar = []
                for chunk in result.chunks:
                    if len(similar) >= request.limit:
                        break

                    metadata = chunk.metadata
                    # Only include if it looks like an incident
                    if (
                        metadata.get("category") == "incident"
                        or "incident" in chunk.text.lower()
                    ):
                        similar.append(
                            V1SimilarIncident(
                                incident_id=metadata.get("incident_id"),
                                date=metadata.get("date"),
                                similarity=chunk.score,
                                symptoms=metadata.get("symptoms", chunk.text[:200]),
                                root_cause=metadata.get("root_cause", ""),
                                resolution=metadata.get("resolution", ""),
                                services_affected=metadata.get("services_affected", []),
                            )
                        )

                hint = None
                if not similar:
                    hint = (
                        "No similar past incidents found. This may be a new issue type."
                    )

                return V1SimilarIncidentsResponse(
                    ok=True,
                    query_symptoms=request.symptoms,
                    similar_incidents=similar,
                    total_found=len(similar),
                    hint=hint,
                )

            except Exception as e:
                logger.error(f"v1 similar incidents failed: {e}")
                return V1SimilarIncidentsResponse(
                    ok=False,
                    query_symptoms=request.symptoms,
                    similar_incidents=[],
                    total_found=0,
                    hint=f"Error: {e}",
                )

        @app.post("/api/v1/retrieve", tags=["v1-compat"])
        async def v1_retrieve(query: str, tree: Optional[str] = None, top_k: int = 10):
            """Retrieve chunks without generating answer (v1 compatible)."""
            if not self.retriever:
                raise HTTPException(503, "Server not initialized")

            try:
                result = await self.retriever.retrieve(
                    query=query,
                    top_k=top_k,
                )

                chunks = []
                for chunk in result.chunks:
                    chunks.append(
                        {
                            "text": chunk.text,
                            "score": chunk.score,
                            "layer": chunk.metadata.get("layer", 0),
                            "is_summary": chunk.metadata.get("layer", 0) > 0,
                            "source_url": chunk.metadata.get("source"),
                        }
                    )

                return {
                    "query": query,
                    "tree": tree or "main",
                    "chunks": chunks,
                }

            except Exception as e:
                logger.error(f"v1 retrieve failed: {e}")
                raise HTTPException(500, str(e))

        @app.post(
            "/api/v1/tree/documents",
            response_model=V1AddDocumentsResponse,
            tags=["v1-compat"],
        )
        async def v1_add_documents(
            request: V1AddDocumentsRequest, background_tasks: BackgroundTasks
        ):
            """Add documents to tree (v1 compatible)."""
            if not self.processor or not self.teaching:
                raise HTTPException(503, "Server not initialized")

            tree_name = request.tree or "main"

            try:
                # Process the content
                from ..ingestion.processor import ContentType

                result = self.processor.process_content(
                    content=request.content,
                    source_path="api_upload",
                    content_type=ContentType.TEXT,
                )

                # Add chunks via teaching
                chunks_added = 0
                for chunk in result.chunks:
                    background_tasks.add_task(
                        self._add_chunk_to_tree,
                        chunk,
                    )
                    chunks_added += 1

                return V1AddDocumentsResponse(
                    tree=tree_name,
                    new_leaves=chunks_added,
                    updated_clusters=0,
                    created_clusters=0,
                    total_nodes_after=chunks_added,
                    message=f"Successfully queued {chunks_added} chunks for addition",
                )

            except Exception as e:
                logger.error(f"v1 add documents failed: {e}")
                raise HTTPException(500, str(e))

    def _get_content_type(self, type_str: Optional[str]):
        """Convert string to ContentType."""
        from ..ingestion.processor import ContentType

        if not type_str:
            return ContentType.TEXT  # Default to TEXT

        try:
            return ContentType(type_str)
        except ValueError:
            return ContentType.TEXT  # Default to TEXT on invalid values

    async def _add_chunk_to_tree(self, chunk):
        """Add a processed chunk to the tree."""
        if self.teaching:
            await self.teaching.teach(
                content=chunk.text,
                knowledge_type="factual",
                source=chunk.source_path,
                confidence=0.95,  # Auto-approve ingested documents
                learned_from="document_ingestion",
            )


def create_app(
    tree_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> FastAPI:
    """
    Factory function to create the API application.

    Args:
        tree_path: Path to existing RAPTOR tree to load
        config: Optional configuration

    Returns:
        Configured FastAPI application
    """
    server = UltimateRAGServer()
    app = server.create_app()

    # Store server reference for access
    app.state.server = server

    return app


# For running directly
if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
