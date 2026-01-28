"""
LLM-powered content analysis for the knowledge base.

This module provides the ContentAnalyzer class that uses GPT-4o with
structured outputs to extract knowledge types, entities, relationships,
and importance scores from content.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI

from .models import (
    ContentAnalysisResult,
    EntityExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
    ImportanceAssessment,
    KnowledgeType,
    KnowledgeTypeResult,
    RelationshipExtractionResult,
)
from .prompts import (
    CONTENT_ANALYSIS_PROMPT,
    ENTITY_EXTRACTION_PROMPT,
    IMPORTANCE_ASSESSMENT_PROMPT,
    KNOWLEDGE_TYPE_CLASSIFICATION_PROMPT,
    RELATIONSHIP_EXTRACTION_PROMPT,
    SUMMARY_GENERATION_PROMPT,
)

logger = logging.getLogger(__name__)


class ContentAnalyzer:
    """
    LLM-powered content analyzer for knowledge base ingestion.

    Uses GPT-4o with structured outputs to perform comprehensive
    content analysis including:
    - Knowledge type classification
    - Entity extraction
    - Relationship extraction
    - Importance assessment
    - Summary and keyword generation
    """

    def __init__(
        self,
        openai_client: Optional[AsyncOpenAI] = None,
        model: str = "gpt-4o-2024-08-06",
        temperature: float = 0.1,
        max_retries: int = 3,
    ):
        """
        Initialize the ContentAnalyzer.

        Args:
            openai_client: AsyncOpenAI client instance. If None, creates one.
            model: Model to use. Default gpt-4o-2024-08-06 supports structured outputs.
            temperature: LLM temperature. Low for consistency.
            max_retries: Number of retries on failures.
        """
        self.client = openai_client or AsyncOpenAI()
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries

    def _generate_chunk_id(self, content: str, source_url: Optional[str] = None) -> str:
        """Generate a unique chunk ID based on content hash."""
        hash_input = f"{source_url or ''}{content}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    async def analyze_content(
        self,
        content: str,
        source_url: Optional[str] = None,
        chunk_id: Optional[str] = None,
        source_metadata: Optional[dict] = None,
    ) -> ContentAnalysisResult:
        """
        Perform comprehensive content analysis using a single LLM call.

        This is the main entry point for content analysis. It uses a combined
        prompt that extracts all information in one call for efficiency.

        Args:
            content: The text content to analyze.
            source_url: Original source URL if available.
            chunk_id: Pre-generated chunk ID, or will be generated.
            source_metadata: Additional metadata about the source.

        Returns:
            ContentAnalysisResult with all analysis components.
        """
        chunk_id = chunk_id or self._generate_chunk_id(content, source_url)

        prompt = CONTENT_ANALYSIS_PROMPT.format(
            chunk_id=chunk_id,
            source_url=source_url or "unknown",
            content=content,
        )

        for attempt in range(self.max_retries):
            try:
                response = await self.client.beta.chat.completions.parse(
                    model=self.model,
                    temperature=self.temperature,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert technical content analyzer. Respond with structured JSON.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format=ContentAnalysisResult,
                )

                result = response.choices[0].message.parsed
                if result:
                    # Ensure chunk_id is set
                    result.chunk_id = chunk_id
                    result.source_url = source_url
                    logger.info(
                        f"Successfully analyzed content chunk {chunk_id}: "
                        f"type={result.knowledge_type.knowledge_type.value}, "
                        f"entities={len(result.entities)}, "
                        f"relationships={len(result.relationships)}"
                    )
                    return result

            except Exception as e:
                logger.warning(
                    f"Content analysis attempt {attempt + 1} failed: {e}"
                )
                if attempt == self.max_retries - 1:
                    logger.error(f"All {self.max_retries} analysis attempts failed")
                    # Return a minimal result on failure
                    return self._create_fallback_result(chunk_id, content, source_url)

        return self._create_fallback_result(chunk_id, content, source_url)

    async def analyze_content_stepwise(
        self,
        content: str,
        source_url: Optional[str] = None,
        chunk_id: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> ContentAnalysisResult:
        """
        Perform content analysis using separate LLM calls for each component.

        This method makes multiple LLM calls (one per analysis type) which
        can provide higher quality results at the cost of more API calls.
        Use this for high-value content where quality is paramount.

        Args:
            content: The text content to analyze.
            source_url: Original source URL if available.
            chunk_id: Pre-generated chunk ID, or will be generated.
            last_modified: Last modification date for freshness scoring.

        Returns:
            ContentAnalysisResult with all analysis components.
        """
        chunk_id = chunk_id or self._generate_chunk_id(content, source_url)
        last_modified = last_modified or datetime.utcnow().isoformat()

        # Run all analyses in parallel for efficiency
        import asyncio

        knowledge_type_task = self._classify_knowledge_type(content)
        entities_task = self._extract_entities(content)
        importance_task = self._assess_importance(content, source_url or "unknown", last_modified)
        summary_task = self._generate_summary(content)

        results = await asyncio.gather(
            knowledge_type_task,
            entities_task,
            importance_task,
            summary_task,
            return_exceptions=True,
        )

        knowledge_type = results[0] if not isinstance(results[0], Exception) else self._default_knowledge_type()
        entities = results[1] if not isinstance(results[1], Exception) else []
        importance = results[2] if not isinstance(results[2], Exception) else self._default_importance()
        summary = results[3] if not isinstance(results[3], Exception) else content[:150]

        # Extract relationships needs entities first
        relationships = []
        if entities:
            try:
                relationships = await self._extract_relationships(content, entities)
            except Exception as e:
                logger.warning(f"Relationship extraction failed: {e}")

        # Generate keywords from entities and content
        keywords = self._extract_keywords(content, entities)

        return ContentAnalysisResult(
            chunk_id=chunk_id,
            source_url=source_url,
            knowledge_type=knowledge_type,
            entities=entities,
            relationships=relationships,
            importance=importance,
            summary=summary,
            keywords=keywords,
        )

    async def _classify_knowledge_type(self, content: str) -> KnowledgeTypeResult:
        """Classify the knowledge type of content."""
        prompt = KNOWLEDGE_TYPE_CLASSIFICATION_PROMPT.format(content=content)

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at classifying technical documentation.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format=KnowledgeTypeResult,
        )

        return response.choices[0].message.parsed or self._default_knowledge_type()

    async def _extract_entities(self, content: str) -> list[ExtractedEntity]:
        """Extract entities from content."""
        prompt = ENTITY_EXTRACTION_PROMPT.format(content=content)

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at extracting technical entities from documentation.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format=EntityExtractionResult,
        )

        result = response.choices[0].message.parsed
        return result.entities if result else []

    async def _extract_relationships(
        self,
        content: str,
        entities: list[ExtractedEntity],
    ) -> list[ExtractedRelationship]:
        """Extract relationships between entities."""
        entities_str = "\n".join(
            f"- {e.name} ({e.entity_type.value}): {e.context}"
            for e in entities
        )

        prompt = RELATIONSHIP_EXTRACTION_PROMPT.format(
            content=content,
            entities=entities_str,
        )

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at identifying relationships in technical documentation.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format=RelationshipExtractionResult,
        )

        result = response.choices[0].message.parsed
        return result.relationships if result else []

    async def _assess_importance(
        self,
        content: str,
        source: str,
        last_modified: str,
    ) -> ImportanceAssessment:
        """Assess the importance of content."""
        prompt = IMPORTANCE_ASSESSMENT_PROMPT.format(
            content=content,
            source=source,
            last_modified=last_modified,
        )

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at assessing technical documentation importance.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format=ImportanceAssessment,
        )

        return response.choices[0].message.parsed or self._default_importance()

    async def _generate_summary(self, content: str) -> str:
        """Generate a search-optimized summary."""
        prompt = SUMMARY_GENERATION_PROMPT.format(content=content)

        response = await self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            max_tokens=100,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at creating concise technical summaries.",
                },
                {"role": "user", "content": prompt},
            ],
        )

        return response.choices[0].message.content or content[:150]

    def _extract_keywords(
        self,
        content: str,
        entities: list[ExtractedEntity],
    ) -> list[str]:
        """Extract keywords from content and entities."""
        keywords = set()

        # Add entity canonical names as keywords
        for entity in entities:
            keywords.add(entity.canonical_name)
            # Also add the original name if different
            if entity.name.lower() != entity.canonical_name:
                keywords.add(entity.name.lower())

        # Add entity types for filtering
        entity_types = {e.entity_type.value for e in entities}
        keywords.update(entity_types)

        return list(keywords)[:20]  # Limit to 20 keywords

    def _default_knowledge_type(self) -> KnowledgeTypeResult:
        """Return a default knowledge type result for fallback."""
        return KnowledgeTypeResult(
            knowledge_type=KnowledgeType.FACTUAL,
            confidence=0.3,
            secondary_type=None,
            reasoning="Default classification due to analysis failure",
        )

    def _default_importance(self) -> ImportanceAssessment:
        """Return a default importance assessment for fallback."""
        return ImportanceAssessment(
            authority_score=0.5,
            criticality_score=0.5,
            uniqueness_score=0.5,
            actionability_score=0.5,
            freshness_score=0.5,
            overall_importance=0.5,
            reasoning="Default scores due to assessment failure",
        )

    def _create_fallback_result(
        self,
        chunk_id: str,
        content: str,
        source_url: Optional[str],
    ) -> ContentAnalysisResult:
        """Create a minimal fallback result when analysis fails."""
        return ContentAnalysisResult(
            chunk_id=chunk_id,
            source_url=source_url,
            knowledge_type=self._default_knowledge_type(),
            entities=[],
            relationships=[],
            importance=self._default_importance(),
            summary=content[:150] if content else "Content analysis failed",
            keywords=[],
        )


class BatchContentAnalyzer:
    """
    Batch processing wrapper for ContentAnalyzer.

    Provides efficient batch analysis with rate limiting, parallel
    processing, and progress tracking.
    """

    def __init__(
        self,
        analyzer: Optional[ContentAnalyzer] = None,
        max_concurrent: int = 5,
        batch_size: int = 10,
    ):
        """
        Initialize batch analyzer.

        Args:
            analyzer: ContentAnalyzer instance to use.
            max_concurrent: Maximum concurrent analysis tasks.
            batch_size: Number of items to process before yielding progress.
        """
        self.analyzer = analyzer or ContentAnalyzer()
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size

    async def analyze_batch(
        self,
        contents: list[dict],
        use_stepwise: bool = False,
        progress_callback: Optional[callable] = None,
    ) -> list[ContentAnalysisResult]:
        """
        Analyze a batch of content items.

        Args:
            contents: List of dicts with 'content', optional 'source_url', 'chunk_id'.
            use_stepwise: If True, use stepwise analysis (higher quality, more API calls).
            progress_callback: Optional callback(completed, total) for progress updates.

        Returns:
            List of ContentAnalysisResult in same order as input.
        """
        import asyncio
        from asyncio import Semaphore

        semaphore = Semaphore(self.max_concurrent)
        results = [None] * len(contents)
        completed = 0

        async def analyze_one(index: int, item: dict) -> None:
            nonlocal completed
            async with semaphore:
                try:
                    if use_stepwise:
                        result = await self.analyzer.analyze_content_stepwise(
                            content=item["content"],
                            source_url=item.get("source_url"),
                            chunk_id=item.get("chunk_id"),
                            last_modified=item.get("last_modified"),
                        )
                    else:
                        result = await self.analyzer.analyze_content(
                            content=item["content"],
                            source_url=item.get("source_url"),
                            chunk_id=item.get("chunk_id"),
                            source_metadata=item.get("metadata"),
                        )
                    results[index] = result
                except Exception as e:
                    logger.error(f"Batch analysis failed for item {index}: {e}")
                    results[index] = self.analyzer._create_fallback_result(
                        chunk_id=item.get("chunk_id", f"batch-{index}"),
                        content=item["content"],
                        source_url=item.get("source_url"),
                    )
                finally:
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(contents))

        # Process all items
        tasks = [
            analyze_one(i, item)
            for i, item in enumerate(contents)
        ]
        await asyncio.gather(*tasks)

        return results

    async def analyze_stream(
        self,
        content_stream,
        use_stepwise: bool = False,
    ):
        """
        Analyze content from an async stream, yielding results as they complete.

        Args:
            content_stream: Async iterator of content dicts.
            use_stepwise: If True, use stepwise analysis.

        Yields:
            ContentAnalysisResult as each item completes.
        """
        import asyncio
        from asyncio import Queue

        queue = Queue(maxsize=self.max_concurrent * 2)
        results_queue = Queue()

        async def producer():
            async for item in content_stream:
                await queue.put(item)
            # Signal completion
            for _ in range(self.max_concurrent):
                await queue.put(None)

        async def worker():
            while True:
                item = await queue.get()
                if item is None:
                    break
                try:
                    if use_stepwise:
                        result = await self.analyzer.analyze_content_stepwise(
                            content=item["content"],
                            source_url=item.get("source_url"),
                            chunk_id=item.get("chunk_id"),
                        )
                    else:
                        result = await self.analyzer.analyze_content(
                            content=item["content"],
                            source_url=item.get("source_url"),
                            chunk_id=item.get("chunk_id"),
                        )
                    await results_queue.put(result)
                except Exception as e:
                    logger.error(f"Stream analysis failed: {e}")
                    await results_queue.put(
                        self.analyzer._create_fallback_result(
                            chunk_id=item.get("chunk_id", "stream"),
                            content=item["content"],
                            source_url=item.get("source_url"),
                        )
                    )

        # Start workers
        workers = [
            asyncio.create_task(worker())
            for _ in range(self.max_concurrent)
        ]

        # Start producer
        producer_task = asyncio.create_task(producer())

        # Yield results as they come in
        active_workers = self.max_concurrent
        while active_workers > 0:
            try:
                result = await asyncio.wait_for(
                    results_queue.get(),
                    timeout=1.0,
                )
                yield result
            except asyncio.TimeoutError:
                # Check if workers are done
                done_workers = sum(1 for w in workers if w.done())
                active_workers = self.max_concurrent - done_workers

        # Wait for completion
        await producer_task
        await asyncio.gather(*workers)
