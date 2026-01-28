"""
LLM-powered conflict resolution for knowledge base updates.

This module provides the ConflictResolver class that handles conflicts
between new content and existing knowledge, deciding whether to skip,
replace, merge, add as new, or flag for human review.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI

from .models import (
    ConflictRecommendation,
    ConflictRelationship,
    ConflictResolutionResult,
    ContentAnalysisResult,
    ImportanceAdjustment,
    PendingKnowledgeChange,
)
from .prompts import CONFLICT_RESOLUTION_PROMPT

logger = logging.getLogger(__name__)


class ConflictResolver:
    """
    LLM-powered conflict resolver for knowledge base.

    Compares new content against existing knowledge and decides
    the appropriate action: skip, replace, merge, add as new,
    or flag for human review.
    """

    def __init__(
        self,
        openai_client: Optional[AsyncOpenAI] = None,
        model: str = "gpt-4o-2024-08-06",
        temperature: float = 0.1,
        similarity_threshold: float = 0.75,
        max_retries: int = 3,
    ):
        """
        Initialize the ConflictResolver.

        Args:
            openai_client: AsyncOpenAI client instance.
            model: Model to use for resolution.
            temperature: LLM temperature.
            similarity_threshold: Minimum similarity to trigger conflict check.
            max_retries: Number of retries on failures.
        """
        self.client = openai_client or AsyncOpenAI()
        self.model = model
        self.temperature = temperature
        self.similarity_threshold = similarity_threshold
        self.max_retries = max_retries

    async def check_conflicts(
        self,
        new_content: str,
        new_source: str,
        existing_matches: list[dict],
        new_analysis: Optional[ContentAnalysisResult] = None,
    ) -> list[tuple[dict, ConflictResolutionResult]]:
        """
        Check new content against a list of existing matches for conflicts.

        Args:
            new_content: The new content to check.
            new_source: Source of the new content.
            existing_matches: List of existing content dicts with similarity scores.
                Each dict should have: id, content, source, updated_at, similarity_score
            new_analysis: Optional pre-computed analysis of the new content.

        Returns:
            List of (existing_match, resolution) tuples for matches above threshold.
        """
        results = []

        for existing in existing_matches:
            similarity = existing.get("similarity_score", 0)

            if similarity < self.similarity_threshold:
                continue

            resolution = await self.resolve_conflict(
                new_content=new_content,
                new_source=new_source,
                existing_content=existing.get("content", ""),
                existing_node_id=existing.get("id", "unknown"),
                existing_source=existing.get("source", "unknown"),
                existing_updated=existing.get("updated_at", "unknown"),
                similarity_score=similarity,
            )

            results.append((existing, resolution))

        return results

    async def resolve_conflict(
        self,
        new_content: str,
        new_source: str,
        existing_content: str,
        existing_node_id: str,
        existing_source: str,
        existing_updated: str,
        similarity_score: float,
    ) -> ConflictResolutionResult:
        """
        Resolve a conflict between new and existing content.

        Args:
            new_content: The new content.
            new_source: Source of the new content.
            existing_content: The existing content.
            existing_node_id: ID of the existing node.
            existing_source: Source of the existing content.
            existing_updated: When existing content was last updated.
            similarity_score: Similarity score between the contents.

        Returns:
            ConflictResolutionResult with recommended action.
        """
        prompt = CONFLICT_RESOLUTION_PROMPT.format(
            new_content=new_content,
            new_source=new_source,
            existing_content=existing_content,
            existing_node_id=existing_node_id,
            existing_source=existing_source,
            existing_updated=existing_updated,
            similarity_score=similarity_score,
        )

        for attempt in range(self.max_retries):
            try:
                response = await self.client.beta.chat.completions.parse(
                    model=self.model,
                    temperature=self.temperature,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an expert at resolving knowledge conflicts. "
                                "Your decisions affect what information is stored and shown "
                                "to engineers during incidents. Be thorough and careful."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format=ConflictResolutionResult,
                )

                result = response.choices[0].message.parsed
                if result:
                    logger.info(
                        f"Conflict resolution for node {existing_node_id}: "
                        f"{result.relationship.value} -> {result.recommendation.value} "
                        f"(confidence: {result.confidence:.2f})"
                    )
                    return result

            except Exception as e:
                logger.warning(
                    f"Conflict resolution attempt {attempt + 1} failed: {e}"
                )
                if attempt == self.max_retries - 1:
                    # On failure, default to flagging for review
                    return self._create_fallback_resolution()

        return self._create_fallback_resolution()

    async def resolve_and_apply(
        self,
        new_content: str,
        new_source: str,
        new_analysis: ContentAnalysisResult,
        existing_matches: list[dict],
        storage_backend,
    ) -> dict:
        """
        Resolve conflicts and apply the recommended actions.

        This is a higher-level method that handles the full conflict
        resolution workflow including applying the decisions.

        Args:
            new_content: The new content.
            new_source: Source of the new content.
            new_analysis: Analysis of the new content.
            existing_matches: List of existing content with similarity scores.
            storage_backend: Backend for applying changes (needs specific interface).

        Returns:
            Dict with results: {
                'action': str,  # What was done
                'node_id': str,  # ID of stored/updated node if applicable
                'pending_change_id': str,  # ID if flagged for review
                'conflicts_resolved': int,  # Number of conflicts handled
            }
        """
        if not existing_matches:
            # No conflicts, store as new
            node_id = await storage_backend.store_content(
                content=new_content,
                source=new_source,
                analysis=new_analysis,
            )
            return {
                "action": "added_new",
                "node_id": node_id,
                "pending_change_id": None,
                "conflicts_resolved": 0,
            }

        # Check conflicts
        conflict_results = await self.check_conflicts(
            new_content=new_content,
            new_source=new_source,
            existing_matches=existing_matches,
            new_analysis=new_analysis,
        )

        if not conflict_results:
            # All matches below threshold, store as new
            node_id = await storage_backend.store_content(
                content=new_content,
                source=new_source,
                analysis=new_analysis,
            )
            return {
                "action": "added_new",
                "node_id": node_id,
                "pending_change_id": None,
                "conflicts_resolved": 0,
            }

        # Process the most significant conflict (highest similarity)
        existing, resolution = max(
            conflict_results,
            key=lambda x: x[0].get("similarity_score", 0),
        )

        return await self._apply_resolution(
            resolution=resolution,
            new_content=new_content,
            new_source=new_source,
            new_analysis=new_analysis,
            existing=existing,
            storage_backend=storage_backend,
        )

    async def _apply_resolution(
        self,
        resolution: ConflictResolutionResult,
        new_content: str,
        new_source: str,
        new_analysis: ContentAnalysisResult,
        existing: dict,
        storage_backend,
    ) -> dict:
        """Apply a conflict resolution decision."""
        existing_node_id = existing.get("id")

        if resolution.recommendation == ConflictRecommendation.SKIP:
            logger.info(f"Skipping duplicate content for node {existing_node_id}")
            return {
                "action": "skipped_duplicate",
                "node_id": existing_node_id,
                "pending_change_id": None,
                "conflicts_resolved": 1,
            }

        elif resolution.recommendation == ConflictRecommendation.REPLACE:
            # Update existing node with new content
            await storage_backend.update_content(
                node_id=existing_node_id,
                content=new_content,
                source=new_source,
                analysis=new_analysis,
                importance_multiplier=resolution.importance_adjustment.new_importance,
            )
            logger.info(f"Replaced content for node {existing_node_id}")
            return {
                "action": "replaced",
                "node_id": existing_node_id,
                "pending_change_id": None,
                "conflicts_resolved": 1,
            }

        elif resolution.recommendation == ConflictRecommendation.MERGE:
            # Merge contents
            merged_content = resolution.merged_content or f"{existing.get('content', '')}\n\n---\n\n{new_content}"
            await storage_backend.update_content(
                node_id=existing_node_id,
                content=merged_content,
                source=f"{existing.get('source', '')}, {new_source}",
                analysis=new_analysis,
                importance_multiplier=max(
                    resolution.importance_adjustment.existing_multiplier,
                    resolution.importance_adjustment.new_importance,
                ),
            )
            logger.info(f"Merged content for node {existing_node_id}")
            return {
                "action": "merged",
                "node_id": existing_node_id,
                "pending_change_id": None,
                "conflicts_resolved": 1,
            }

        elif resolution.recommendation == ConflictRecommendation.ADD_AS_NEW:
            # Store as new, but link as related
            node_id = await storage_backend.store_content(
                content=new_content,
                source=new_source,
                analysis=new_analysis,
                related_node_ids=[existing_node_id],
            )
            logger.info(f"Added as new content {node_id}, related to {existing_node_id}")
            return {
                "action": "added_as_related",
                "node_id": node_id,
                "pending_change_id": None,
                "conflicts_resolved": 1,
            }

        elif resolution.recommendation == ConflictRecommendation.FLAG_REVIEW:
            # Create pending change for human review
            pending_change = self.create_pending_change(
                new_content=new_content,
                new_source=new_source,
                existing=existing,
                resolution=resolution,
                analysis=new_analysis,
            )
            # Store the pending change
            change_id = await storage_backend.store_pending_change(pending_change)
            logger.info(f"Flagged for review: {change_id}")
            return {
                "action": "flagged_for_review",
                "node_id": None,
                "pending_change_id": change_id,
                "conflicts_resolved": 0,  # Not resolved yet
            }

        # Default: add as new
        node_id = await storage_backend.store_content(
            content=new_content,
            source=new_source,
            analysis=new_analysis,
        )
        return {
            "action": "added_new_default",
            "node_id": node_id,
            "pending_change_id": None,
            "conflicts_resolved": 0,
        }

    def create_pending_change(
        self,
        new_content: str,
        new_source: str,
        existing: dict,
        resolution: ConflictResolutionResult,
        analysis: Optional[ContentAnalysisResult] = None,
    ) -> PendingKnowledgeChange:
        """
        Create a PendingKnowledgeChange for human review.

        This creates a structured change request that can be displayed
        in the Proposed Changes UI.

        Args:
            new_content: The new content.
            new_source: Source of the new content.
            existing: The existing content dict.
            resolution: The conflict resolution result.
            analysis: Optional analysis of the new content.

        Returns:
            PendingKnowledgeChange ready for storage/API submission.
        """
        existing_content = existing.get("content", "")
        existing_node_id = existing.get("id")

        # Create descriptive title based on conflict type
        if resolution.relationship == ConflictRelationship.CONTRADICTS:
            title = f"Conflicting information detected"
        elif resolution.relationship == ConflictRelationship.SUPERSEDES:
            title = f"Potentially outdated information found"
        else:
            title = f"Knowledge update requires review"

        # Create detailed description
        description = self._create_change_description(
            new_source=new_source,
            existing=existing,
            resolution=resolution,
        )

        # Build evidence list
        evidence = [
            {
                "type": "similarity_score",
                "value": existing.get("similarity_score", 0),
                "description": "Content similarity score",
            },
            {
                "type": "conflict_relationship",
                "value": resolution.relationship.value,
                "description": "Detected relationship between contents",
            },
            {
                "type": "ai_confidence",
                "value": resolution.confidence,
                "description": "AI confidence in the analysis",
            },
        ]

        return PendingKnowledgeChange(
            id=str(uuid.uuid4()),
            change_type="knowledge",
            status="pending",
            title=title,
            description=description,
            new_content=new_content,
            existing_content=existing_content,
            existing_node_id=existing_node_id,
            conflict_relationship=resolution.relationship,
            conflict_reasoning=resolution.reasoning,
            confidence=resolution.confidence,
            evidence=evidence,
            source=new_source,
            proposed_by="content_analyzer",
            proposed_at=datetime.utcnow(),
            analysis=analysis,
        )

    def _create_change_description(
        self,
        new_source: str,
        existing: dict,
        resolution: ConflictResolutionResult,
    ) -> str:
        """Create a human-readable description for the pending change."""
        existing_source = existing.get("source", "unknown source")

        if resolution.relationship == ConflictRelationship.CONTRADICTS:
            return (
                f"New content from '{new_source}' appears to contradict existing "
                f"knowledge from '{existing_source}'. The AI could not determine "
                f"which information is correct.\n\n"
                f"AI Analysis:\n{resolution.reasoning}"
            )

        elif resolution.relationship == ConflictRelationship.SUPERSEDES:
            return (
                f"New content from '{new_source}' may be more current than existing "
                f"content from '{existing_source}'. Review needed to confirm the "
                f"update is appropriate.\n\n"
                f"AI Analysis:\n{resolution.reasoning}"
            )

        else:
            return (
                f"A potential knowledge conflict was detected between new content "
                f"from '{new_source}' and existing content from '{existing_source}'.\n\n"
                f"Relationship: {resolution.relationship.value}\n"
                f"AI Analysis:\n{resolution.reasoning}"
            )

    def _create_fallback_resolution(self) -> ConflictResolutionResult:
        """Create a fallback resolution when LLM fails."""
        return ConflictResolutionResult(
            relationship=ConflictRelationship.UNRELATED,
            recommendation=ConflictRecommendation.FLAG_REVIEW,
            confidence=0.3,
            importance_adjustment=ImportanceAdjustment(
                existing_multiplier=1.0,
                new_importance=0.5,
            ),
            reasoning=(
                "Conflict resolution failed due to an error. "
                "Flagging for human review as a precaution."
            ),
            merged_content=None,
        )


class BatchConflictResolver:
    """
    Batch processing wrapper for ConflictResolver.

    Provides efficient batch conflict resolution with parallel
    processing for multiple content items.
    """

    def __init__(
        self,
        resolver: Optional[ConflictResolver] = None,
        max_concurrent: int = 3,
    ):
        """
        Initialize batch resolver.

        Args:
            resolver: ConflictResolver instance to use.
            max_concurrent: Maximum concurrent resolution tasks.
        """
        self.resolver = resolver or ConflictResolver()
        self.max_concurrent = max_concurrent

    async def resolve_batch(
        self,
        items: list[dict],
        storage_backend,
        progress_callback: Optional[callable] = None,
    ) -> list[dict]:
        """
        Resolve conflicts for a batch of content items.

        Args:
            items: List of dicts with 'new_content', 'new_source', 'new_analysis',
                   'existing_matches'.
            storage_backend: Storage backend for applying changes.
            progress_callback: Optional callback(completed, total).

        Returns:
            List of result dicts from resolve_and_apply.
        """
        import asyncio
        from asyncio import Semaphore

        semaphore = Semaphore(self.max_concurrent)
        results = [None] * len(items)
        completed = 0

        async def resolve_one(index: int, item: dict) -> None:
            nonlocal completed
            async with semaphore:
                try:
                    result = await self.resolver.resolve_and_apply(
                        new_content=item["new_content"],
                        new_source=item["new_source"],
                        new_analysis=item["new_analysis"],
                        existing_matches=item.get("existing_matches", []),
                        storage_backend=storage_backend,
                    )
                    results[index] = result
                except Exception as e:
                    logger.error(f"Batch resolution failed for item {index}: {e}")
                    results[index] = {
                        "action": "error",
                        "error": str(e),
                        "node_id": None,
                        "pending_change_id": None,
                        "conflicts_resolved": 0,
                    }
                finally:
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(items))

        tasks = [resolve_one(i, item) for i, item in enumerate(items)]
        await asyncio.gather(*tasks)

        return results
