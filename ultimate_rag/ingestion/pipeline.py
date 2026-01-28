"""
Intelligent Ingestion Pipeline for Ultimate RAG.

This pipeline orchestrates the full content ingestion workflow:
1. Document Processing (parsing, chunking)
2. LLM-Powered Analysis (knowledge type, entities, relationships, importance)
3. Conflict Resolution (duplicate detection, supersession, merging)
4. Storage (RAPTOR tree, vector embeddings, graph)
5. Human Review Integration (FLAG_REVIEW to Proposed Changes)

This replaces heuristic-based extraction with production-quality LLM analysis.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from openai import AsyncOpenAI

from ..intelligence import (
    BatchContentAnalyzer,
    BatchConflictResolver,
    ConflictRecommendation,
    ContentAnalyzer,
    ContentAnalysisResult,
    ConflictResolver,
    PendingKnowledgeChange,
)
from .processor import DocumentProcessor, ProcessedChunk, ProcessingConfig, ProcessingResult

logger = logging.getLogger(__name__)


class StorageBackend(Protocol):
    """Protocol for storage backends."""

    async def store_content(
        self,
        content: str,
        source: str,
        analysis: ContentAnalysisResult,
        related_node_ids: Optional[List[str]] = None,
    ) -> str:
        """Store content and return node ID."""
        ...

    async def update_content(
        self,
        node_id: str,
        content: str,
        source: str,
        analysis: ContentAnalysisResult,
        importance_multiplier: float = 1.0,
    ) -> None:
        """Update existing content."""
        ...

    async def find_similar(
        self,
        content: str,
        limit: int = 5,
        threshold: float = 0.75,
    ) -> List[Dict[str, Any]]:
        """Find similar existing content."""
        ...

    async def store_pending_change(
        self,
        change: PendingKnowledgeChange,
    ) -> str:
        """Store a pending change for review."""
        ...


@dataclass
class PipelineConfig:
    """Configuration for the intelligent ingestion pipeline."""

    # Document processing
    processing_config: ProcessingConfig = field(default_factory=ProcessingConfig)

    # LLM Analysis
    use_stepwise_analysis: bool = False  # More API calls, potentially higher quality
    analysis_batch_size: int = 10
    analysis_max_concurrent: int = 5

    # Conflict Resolution
    similarity_threshold: float = 0.75  # Minimum similarity to check for conflicts
    conflict_check_enabled: bool = True

    # Quality Thresholds
    min_importance_to_store: float = 0.2  # Skip very low importance content
    min_confidence_to_auto_resolve: float = 0.8  # Below this, flag for review

    # Model Configuration
    model: str = "gpt-4o-2024-08-06"
    temperature: float = 0.1

    # Rate Limiting
    max_llm_calls_per_minute: int = 60
    retry_attempts: int = 3


@dataclass
class IngestionResult:
    """Result of ingesting a document."""

    # Source
    source_path: str
    content_type: str

    # Processing Stats
    total_chunks: int
    chunks_analyzed: int
    chunks_stored: int
    chunks_skipped: int
    chunks_flagged: int

    # Time
    processing_time_ms: float
    analysis_time_ms: float
    total_time_ms: float

    # Results
    node_ids: List[str]
    pending_change_ids: List[str]

    # Issues
    warnings: List[str]
    errors: List[str]

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@dataclass
class BatchIngestionResult:
    """Result of batch ingestion."""

    total_documents: int
    successful_documents: int
    failed_documents: int

    total_chunks: int
    chunks_stored: int
    chunks_flagged: int

    total_time_ms: float

    individual_results: List[IngestionResult]


class IntelligentIngestionPipeline:
    """
    Orchestrates the full intelligent ingestion workflow.

    Usage:
        pipeline = IntelligentIngestionPipeline(
            storage_backend=my_storage,
            config=PipelineConfig(),
        )

        # Ingest a single file
        result = await pipeline.ingest_file("docs/runbook.md")

        # Ingest multiple files
        results = await pipeline.ingest_directory("docs/")

        # Ingest raw content
        result = await pipeline.ingest_content(
            content="...",
            source="confluence://page/123",
        )
    """

    def __init__(
        self,
        storage_backend: StorageBackend,
        config: Optional[PipelineConfig] = None,
        openai_client: Optional[AsyncOpenAI] = None,
    ):
        """
        Initialize the pipeline.

        Args:
            storage_backend: Backend for storing content and pending changes.
            config: Pipeline configuration.
            openai_client: OpenAI client for LLM calls.
        """
        self.storage = storage_backend
        self.config = config or PipelineConfig()

        # Initialize components
        self.client = openai_client or AsyncOpenAI()

        self.document_processor = DocumentProcessor(
            config=self.config.processing_config
        )

        self.content_analyzer = ContentAnalyzer(
            openai_client=self.client,
            model=self.config.model,
            temperature=self.config.temperature,
            max_retries=self.config.retry_attempts,
        )

        self.conflict_resolver = ConflictResolver(
            openai_client=self.client,
            model=self.config.model,
            temperature=self.config.temperature,
            similarity_threshold=self.config.similarity_threshold,
            max_retries=self.config.retry_attempts,
        )

        # Batch processors
        self.batch_analyzer = BatchContentAnalyzer(
            analyzer=self.content_analyzer,
            max_concurrent=self.config.analysis_max_concurrent,
            batch_size=self.config.analysis_batch_size,
        )

        self.batch_resolver = BatchConflictResolver(
            resolver=self.conflict_resolver,
            max_concurrent=3,  # Keep conflict resolution sequential-ish
        )

        # Stats
        self._total_ingested = 0
        self._total_chunks = 0
        self._total_flagged = 0

    async def ingest_file(
        self,
        file_path: str,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> IngestionResult:
        """
        Ingest a single file through the full pipeline.

        Args:
            file_path: Path to the file.
            extra_metadata: Additional metadata to attach.

        Returns:
            IngestionResult with stats and node IDs.
        """
        start_time = datetime.utcnow()

        # Step 1: Process document (parsing, chunking)
        processing_result = self.document_processor.process_file(
            file_path=file_path,
            extra_metadata=extra_metadata,
        )

        if not processing_result.success:
            return IngestionResult(
                source_path=file_path,
                content_type=processing_result.content_type.value,
                total_chunks=0,
                chunks_analyzed=0,
                chunks_stored=0,
                chunks_skipped=0,
                chunks_flagged=0,
                processing_time_ms=processing_result.processing_time_ms,
                analysis_time_ms=0,
                total_time_ms=processing_result.processing_time_ms,
                node_ids=[],
                pending_change_ids=[],
                warnings=processing_result.warnings,
                errors=processing_result.errors,
            )

        # Step 2-4: Analyze and store chunks
        return await self._process_chunks(
            chunks=processing_result.chunks,
            source_path=file_path,
            content_type=processing_result.content_type.value,
            processing_time_ms=processing_result.processing_time_ms,
            start_time=start_time,
            warnings=processing_result.warnings,
        )

    async def ingest_content(
        self,
        content: str,
        source: str,
        content_type: str = "text",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> IngestionResult:
        """
        Ingest raw content through the pipeline.

        Args:
            content: Raw text content.
            source: Source attribution (URL, path, etc.).
            content_type: Type of content.
            extra_metadata: Additional metadata.

        Returns:
            IngestionResult with stats and node IDs.
        """
        from .processor import ContentType

        start_time = datetime.utcnow()

        # Map string to ContentType
        try:
            ct = ContentType(content_type)
        except ValueError:
            ct = ContentType.TEXT

        # Step 1: Process content
        processing_result = self.document_processor.process_content(
            content=content,
            source_path=source,
            content_type=ct,
            extra_metadata=extra_metadata,
        )

        processing_end = datetime.utcnow()
        processing_time = (processing_end - start_time).total_seconds() * 1000

        # Step 2-4: Analyze and store chunks
        return await self._process_chunks(
            chunks=processing_result.chunks,
            source_path=source,
            content_type=content_type,
            processing_time_ms=processing_time,
            start_time=start_time,
            warnings=processing_result.warnings,
        )

    async def ingest_directory(
        self,
        directory: str,
        pattern: str = "**/*",
        progress_callback: Optional[callable] = None,
    ) -> BatchIngestionResult:
        """
        Ingest all files in a directory.

        Args:
            directory: Directory path.
            pattern: Glob pattern for files.
            progress_callback: Optional callback(completed, total).

        Returns:
            BatchIngestionResult with aggregate stats.
        """
        from pathlib import Path

        start_time = datetime.utcnow()

        dir_path = Path(directory)
        files = [
            f for f in dir_path.glob(pattern)
            if f.is_file() and not f.name.startswith(".")
        ]

        results = []
        completed = 0

        for file_path in files:
            try:
                result = await self.ingest_file(str(file_path))
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to ingest {file_path}: {e}")
                results.append(IngestionResult(
                    source_path=str(file_path),
                    content_type="unknown",
                    total_chunks=0,
                    chunks_analyzed=0,
                    chunks_stored=0,
                    chunks_skipped=0,
                    chunks_flagged=0,
                    processing_time_ms=0,
                    analysis_time_ms=0,
                    total_time_ms=0,
                    node_ids=[],
                    pending_change_ids=[],
                    warnings=[],
                    errors=[str(e)],
                ))

            completed += 1
            if progress_callback:
                progress_callback(completed, len(files))

        end_time = datetime.utcnow()
        total_time = (end_time - start_time).total_seconds() * 1000

        return BatchIngestionResult(
            total_documents=len(files),
            successful_documents=sum(1 for r in results if r.success),
            failed_documents=sum(1 for r in results if not r.success),
            total_chunks=sum(r.total_chunks for r in results),
            chunks_stored=sum(r.chunks_stored for r in results),
            chunks_flagged=sum(r.chunks_flagged for r in results),
            total_time_ms=total_time,
            individual_results=results,
        )

    async def _process_chunks(
        self,
        chunks: List[ProcessedChunk],
        source_path: str,
        content_type: str,
        processing_time_ms: float,
        start_time: datetime,
        warnings: List[str],
    ) -> IngestionResult:
        """Process chunks through analysis and storage."""
        analysis_start = datetime.utcnow()

        node_ids = []
        pending_change_ids = []
        chunks_stored = 0
        chunks_skipped = 0
        chunks_flagged = 0
        errors = []

        # Prepare chunks for batch analysis
        analysis_inputs = [
            {
                "content": chunk.text,
                "source_url": source_path,
                "chunk_id": chunk.chunk_id,
                "last_modified": chunk.metadata.get("processed_at"),
            }
            for chunk in chunks
        ]

        # Step 2: Batch analyze chunks
        try:
            analyses = await self.batch_analyzer.analyze_batch(
                contents=analysis_inputs,
                use_stepwise=self.config.use_stepwise_analysis,
            )
        except Exception as e:
            logger.error(f"Batch analysis failed: {e}")
            errors.append(f"Analysis failed: {e}")
            analyses = []

        analysis_end = datetime.utcnow()
        analysis_time = (analysis_end - analysis_start).total_seconds() * 1000

        # Step 3 & 4: For each analyzed chunk, resolve conflicts and store
        for chunk, analysis in zip(chunks, analyses):
            try:
                # Check minimum importance threshold
                if analysis.importance.overall_importance < self.config.min_importance_to_store:
                    logger.debug(
                        f"Skipping low importance chunk {chunk.chunk_id}: "
                        f"{analysis.importance.overall_importance:.2f}"
                    )
                    chunks_skipped += 1
                    continue

                # Find similar existing content
                if self.config.conflict_check_enabled:
                    similar = await self.storage.find_similar(
                        content=chunk.text,
                        limit=5,
                        threshold=self.config.similarity_threshold,
                    )
                else:
                    similar = []

                # Resolve conflicts or store directly
                if similar:
                    result = await self.conflict_resolver.resolve_and_apply(
                        new_content=chunk.text,
                        new_source=source_path,
                        new_analysis=analysis,
                        existing_matches=similar,
                        storage_backend=self.storage,
                    )

                    if result["action"] == "flagged_for_review":
                        chunks_flagged += 1
                        if result["pending_change_id"]:
                            pending_change_ids.append(result["pending_change_id"])
                    elif result["action"] in ("skipped_duplicate",):
                        chunks_skipped += 1
                    else:
                        chunks_stored += 1
                        if result["node_id"]:
                            node_ids.append(result["node_id"])
                else:
                    # No conflicts, store directly
                    node_id = await self.storage.store_content(
                        content=chunk.text,
                        source=source_path,
                        analysis=analysis,
                    )
                    node_ids.append(node_id)
                    chunks_stored += 1

            except Exception as e:
                logger.error(f"Failed to process chunk {chunk.chunk_id}: {e}")
                errors.append(f"Chunk {chunk.chunk_id}: {e}")

        end_time = datetime.utcnow()
        total_time = (end_time - start_time).total_seconds() * 1000

        # Update stats
        self._total_ingested += 1
        self._total_chunks += len(chunks)
        self._total_flagged += chunks_flagged

        return IngestionResult(
            source_path=source_path,
            content_type=content_type,
            total_chunks=len(chunks),
            chunks_analyzed=len(analyses),
            chunks_stored=chunks_stored,
            chunks_skipped=chunks_skipped,
            chunks_flagged=chunks_flagged,
            processing_time_ms=processing_time_ms,
            analysis_time_ms=analysis_time,
            total_time_ms=total_time,
            node_ids=node_ids,
            pending_change_ids=pending_change_ids,
            warnings=warnings,
            errors=errors,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        return {
            "total_documents_ingested": self._total_ingested,
            "total_chunks_processed": self._total_chunks,
            "total_chunks_flagged": self._total_flagged,
            "processor_stats": self.document_processor.get_stats(),
        }


class ProposedChangesAPIClient:
    """
    Client for submitting pending changes to the config_service internal API.

    This integrates FLAG_REVIEW items with the existing Proposed Changes
    UI at /team/pending-changes.
    """

    def __init__(
        self,
        api_base_url: str,
        org_id: str,
        team_node_id: str,
        service_name: str = "ai_pipeline",
    ):
        """
        Initialize the API client.

        Args:
            api_base_url: Base URL of the config_service API.
            org_id: Organization ID.
            team_node_id: Team node ID for associating changes.
            service_name: Internal service identifier for auth.
        """
        self.api_base_url = api_base_url.rstrip("/")
        self.org_id = org_id
        self.team_node_id = team_node_id
        self.service_name = service_name

    async def submit_pending_change(
        self,
        change: PendingKnowledgeChange,
    ) -> str:
        """
        Submit a pending change to the internal API.

        Creates a pending knowledge change that appears in the team's
        Proposed Changes UI at /team/pending-changes for human review.

        Args:
            change: The pending change to submit.

        Returns:
            The ID of the created pending change.
        """
        import httpx

        url = f"{self.api_base_url}/api/v1/internal/pending-changes"

        # Build the proposed_value dict that team.py expects for knowledge changes
        proposed_value = {
            "title": change.title,
            "summary": change.new_content,
            "learned_from": change.source,
            "conflict_type": change.conflict_relationship.value,
            "existing_content": change.existing_content,
            "existing_node_id": change.existing_node_id,
            "ai_reasoning": change.conflict_reasoning,
            "ai_confidence": change.confidence,
            "evidence": change.evidence,
        }

        reason = (
            f"{change.conflict_reasoning}\n\n"
            f"Conflict type: {change.conflict_relationship.value}\n"
            f"AI confidence: {change.confidence:.2f}"
        )

        payload = {
            "id": change.id,
            "org_id": self.org_id,
            "node_id": self.team_node_id,
            "change_type": "knowledge",
            "proposed_value": proposed_value,
            "previous_value": (
                {"content": change.existing_content, "node_id": change.existing_node_id}
                if change.existing_content else None
            ),
            "requested_by": change.proposed_by or "content_analyzer",
            "reason": reason,
            "status": "pending",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Internal-Service": self.service_name,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("id", change.id)

    async def get_pending_changes(
        self,
        status: str = "pending",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get pending knowledge changes from the team API.

        Note: This uses the team-facing API, not the internal API.
        Requires proper team authentication.
        """
        import httpx

        # This endpoint is team-facing, needs team auth
        url = f"{self.api_base_url}/api/v1/team/knowledge/proposed-changes"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={
                    "X-Internal-Service": self.service_name,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def approve_change(self, change_id: str) -> None:
        """
        Approve a pending change.

        Note: This is typically done through the UI, but can be called
        programmatically for testing or automation.
        """
        import httpx

        url = f"{self.api_base_url}/api/v1/team/knowledge/proposed-changes/{change_id}/approve"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"X-Internal-Service": self.service_name},
                timeout=30.0,
            )
            response.raise_for_status()

    async def reject_change(self, change_id: str, reason: str = "") -> None:
        """
        Reject a pending change.

        Note: This is typically done through the UI, but can be called
        programmatically for testing or automation.
        """
        import httpx

        url = f"{self.api_base_url}/api/v1/team/knowledge/proposed-changes/{change_id}/reject"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={"reason": reason} if reason else None,
                headers={
                    "Content-Type": "application/json",
                    "X-Internal-Service": self.service_name,
                },
                timeout=30.0,
            )
            response.raise_for_status()


class InMemoryStorageBackend:
    """
    In-memory storage backend for testing.

    Implements the StorageBackend protocol for unit testing the pipeline
    without requiring actual database connections.
    """

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.pending_changes: Dict[str, PendingKnowledgeChange] = {}
        self._node_counter = 0

    async def store_content(
        self,
        content: str,
        source: str,
        analysis: ContentAnalysisResult,
        related_node_ids: Optional[List[str]] = None,
    ) -> str:
        """Store content and return node ID."""
        self._node_counter += 1
        node_id = f"node_{self._node_counter}"

        self.nodes[node_id] = {
            "id": node_id,
            "content": content,
            "source": source,
            "analysis": analysis,
            "related_node_ids": related_node_ids or [],
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        return node_id

    async def update_content(
        self,
        node_id: str,
        content: str,
        source: str,
        analysis: ContentAnalysisResult,
        importance_multiplier: float = 1.0,
    ) -> None:
        """Update existing content."""
        if node_id in self.nodes:
            self.nodes[node_id].update({
                "content": content,
                "source": source,
                "analysis": analysis,
                "updated_at": datetime.utcnow().isoformat(),
            })

    async def find_similar(
        self,
        content: str,
        limit: int = 5,
        threshold: float = 0.75,
    ) -> List[Dict[str, Any]]:
        """
        Find similar existing content.

        Note: In production, this would use vector similarity search.
        This implementation uses simple text overlap for testing.
        """
        results = []

        content_words = set(content.lower().split())

        for node_id, node in self.nodes.items():
            node_content = node.get("content", "")
            node_words = set(node_content.lower().split())

            if not node_words:
                continue

            # Jaccard similarity
            intersection = len(content_words & node_words)
            union = len(content_words | node_words)
            similarity = intersection / union if union > 0 else 0

            if similarity >= threshold:
                results.append({
                    "id": node_id,
                    "content": node_content,
                    "source": node.get("source", "unknown"),
                    "updated_at": node.get("updated_at", "unknown"),
                    "similarity_score": similarity,
                })

        # Sort by similarity and limit
        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return results[:limit]

    async def store_pending_change(
        self,
        change: PendingKnowledgeChange,
    ) -> str:
        """Store a pending change for review."""
        self.pending_changes[change.id] = change
        return change.id
