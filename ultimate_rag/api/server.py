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
