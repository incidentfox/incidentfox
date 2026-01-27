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
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


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

        # Stats
        self._start_time = datetime.utcnow()
        self._query_count = 0
        self._ingest_count = 0

    async def initialize(
        self,
        tree_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize all components."""
        from ..agents.maintenance import MaintenanceAgent
        from ..agents.observations import ObservationCollector
        from ..agents.teaching import TeachingInterface
        from ..core.node import TreeForest
        from ..graph.graph import KnowledgeGraph
        from ..ingestion.processor import DocumentProcessor, ProcessingConfig
        from ..retrieval.retriever import RetrievalConfig, UltimateRetriever

        logger.info("Initializing Ultimate RAG server...")

        # Initialize forest
        self.forest = TreeForest()

        # Load existing tree if provided
        if tree_path:
            from ..raptor.bridge import import_raptor_tree

            try:
                tree = import_raptor_tree(tree_path)
                self.forest.add_tree("main", tree)
                logger.info(f"Loaded tree from {tree_path}")
            except Exception as e:
                logger.error(f"Failed to load tree: {e}")

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

        # Initialize teaching
        self.teaching = TeachingInterface(
            forest=self.forest,
            graph=self.graph,
            observation_collector=self.observations,
        )

        # Initialize maintenance
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
                    knowledge=request.knowledge,
                    knowledge_type=knowledge_type,
                    source=request.source,
                    entity_ids=request.entities,
                    importance=request.importance,
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

        @app.get("/api/v1/trees", tags=["v1-compat"])
        async def v1_list_trees():
            """List available knowledge trees (v1 compatible)."""
            trees = list(self.forest.trees.keys()) if self.forest else []
            return {
                "trees": trees,
                "default": trees[0] if trees else "main",
                "loaded": trees,
            }

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
                result = self.processor.process_content(
                    content=request.content,
                    source_path="api_upload",
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
        if not type_str:
            return None

        from ..ingestion.processor import ContentType

        try:
            return ContentType(type_str)
        except ValueError:
            return None

    async def _add_chunk_to_tree(self, chunk):
        """Add a processed chunk to the tree."""
        if self.teaching:
            await self.teaching.teach(
                knowledge=chunk.text,
                source=chunk.source_path,
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
