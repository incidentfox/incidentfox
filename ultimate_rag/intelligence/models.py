"""
Pydantic models for LLM-powered content analysis.

These models define the structured outputs expected from LLM calls
for knowledge type classification, entity extraction, relationship
extraction, importance assessment, and conflict resolution.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Knowledge Type Classification
# =============================================================================


class KnowledgeType(str, Enum):
    """Types of knowledge that can be stored in the knowledge base."""

    PROCEDURAL = "procedural"  # How-to guides, runbooks, troubleshooting steps
    FACTUAL = "factual"  # Facts, configurations, API specs, architecture
    RELATIONAL = "relational"  # Service dependencies, ownership, topology
    TEMPORAL = "temporal"  # Incidents, deployments, changes with timestamps
    SOCIAL = "social"  # Contact info, team structure, escalation paths
    CONTEXTUAL = "contextual"  # Environment-specific (prod vs staging)
    POLICY = "policy"  # Rules, compliance, SLAs, security policies
    META = "meta"  # Knowledge about the KB itself


class KnowledgeTypeResult(BaseModel):
    """Result of knowledge type classification."""

    knowledge_type: KnowledgeType = Field(
        description="Primary knowledge type of the content"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in classification (0-1)"
    )
    secondary_type: Optional[KnowledgeType] = Field(
        default=None, description="Secondary type if content is mixed"
    )
    reasoning: str = Field(description="Brief explanation of classification")


# =============================================================================
# Entity Extraction
# =============================================================================


class EntityType(str, Enum):
    """Types of entities that can be extracted from content."""

    SERVICE = "service"  # Microservices, APIs, workers, databases
    TEAM = "team"  # Engineering teams
    PERSON = "person"  # Individual engineers, on-call contacts
    TECHNOLOGY = "technology"  # Tools, frameworks, infrastructure
    METRIC = "metric"  # Monitoring metrics, SLIs
    RUNBOOK = "runbook"  # Documentation references
    ENVIRONMENT = "environment"  # Deployment environments
    ALERT = "alert"  # Alert rules or conditions
    INCIDENT = "incident"  # Past incidents
    NAMESPACE = "namespace"  # K8s namespaces, cloud projects


class ExtractedEntity(BaseModel):
    """An entity extracted from content."""

    name: str = Field(description="Entity name as it appears in text")
    canonical_name: str = Field(
        description="Normalized name (lowercase, no special chars)"
    )
    entity_type: EntityType = Field(description="Type of entity")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in extraction (0-1)"
    )
    context: str = Field(description="Brief context of how entity is mentioned")


class EntityExtractionResult(BaseModel):
    """Result of entity extraction from content."""

    entities: list[ExtractedEntity] = Field(
        default_factory=list, description="List of extracted entities"
    )


# =============================================================================
# Relationship Extraction
# =============================================================================


class RelationshipType(str, Enum):
    """Types of relationships between entities."""

    DEPENDS_ON = "depends_on"  # Service/system dependency
    CALLS = "calls"  # API or service invocation
    OWNS = "owns"  # Team/person ownership
    MEMBER_OF = "member_of"  # Team membership
    MONITORS = "monitors"  # Observability relationship
    DOCUMENTS = "documents"  # Documentation relationship
    TRIGGERS = "triggers"  # Alert/automation trigger
    SUPERSEDES = "supersedes"  # Newer version replaces older
    RELATED_TO = "related_to"  # General association
    DEPLOYED_TO = "deployed_to"  # Deployment target
    USES = "uses"  # Technology usage


class ExtractedRelationship(BaseModel):
    """A relationship extracted between entities."""

    source: str = Field(description="Source entity name")
    relationship: RelationshipType = Field(description="Type of relationship")
    target: str = Field(description="Target entity name")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in extraction (0-1)"
    )
    evidence: str = Field(description="Quote from text supporting this relationship")


class RelationshipExtractionResult(BaseModel):
    """Result of relationship extraction from content."""

    relationships: list[ExtractedRelationship] = Field(
        default_factory=list, description="List of extracted relationships"
    )


# =============================================================================
# Importance Assessment
# =============================================================================


class ImportanceAssessment(BaseModel):
    """Assessment of content importance for incident response."""

    authority_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How authoritative is this content (official docs, SME, etc.)",
    )
    criticality_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How critical for incident response (P1 incidents, etc.)",
    )
    uniqueness_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How unique is this information (only place it exists, etc.)",
    )
    actionability_score: float = Field(
        ge=0.0, le=1.0, description="How actionable (clear steps vs theoretical)"
    )
    freshness_score: float = Field(
        ge=0.0, le=1.0, description="How current is the content"
    )
    overall_importance: float = Field(
        ge=0.0, le=1.0, description="Overall importance score (weighted combination)"
    )
    reasoning: str = Field(description="Brief explanation of assessment")


# =============================================================================
# Combined Content Analysis Result
# =============================================================================


class ContentAnalysisResult(BaseModel):
    """Complete analysis result for a content chunk."""

    # Source tracking
    chunk_id: str = Field(description="Unique identifier for this chunk")
    source_url: Optional[str] = Field(
        default=None, description="Source URL if available"
    )

    # Knowledge type
    knowledge_type: KnowledgeTypeResult = Field(
        description="Knowledge type classification"
    )

    # Entities and relationships
    entities: list[ExtractedEntity] = Field(
        default_factory=list, description="Extracted entities"
    )
    relationships: list[ExtractedRelationship] = Field(
        default_factory=list, description="Extracted relationships"
    )

    # Importance
    importance: ImportanceAssessment = Field(description="Importance assessment")

    # Summary for indexing
    summary: str = Field(description="Concise summary for search indexing")

    # Keywords for search
    keywords: list[str] = Field(
        default_factory=list, description="Key terms for search"
    )


# =============================================================================
# Conflict Resolution
# =============================================================================


class ConflictRelationship(str, Enum):
    """Relationship between new and existing content."""

    DUPLICATE = "duplicate"  # Same information, no new value
    SUPERSEDES = "supersedes"  # New info is more current/complete
    CONTRADICTS = "contradicts"  # Information conflicts
    COMPLEMENTS = "complements"  # New info adds without conflict
    UNRELATED = "unrelated"  # Despite similarity, topics differ


class ConflictRecommendation(str, Enum):
    """Recommended action for handling conflict."""

    SKIP = "skip"  # Exact duplicate, don't store
    REPLACE = "replace"  # Update existing with new
    MERGE = "merge"  # Combine both into unified content
    ADD_AS_NEW = "add_as_new"  # Store as separate, link as related
    FLAG_REVIEW = "flag_review"  # Contradiction, needs human review


class ImportanceAdjustment(BaseModel):
    """How to adjust importance scores after conflict resolution."""

    existing_multiplier: float = Field(
        ge=0.0,
        le=1.0,
        default=1.0,
        description="Multiplier for existing node importance",
    )
    new_importance: float = Field(
        ge=0.0, le=1.0, default=0.5, description="Importance for new content"
    )


class ConflictResolutionResult(BaseModel):
    """Result of comparing new content with existing knowledge."""

    relationship: ConflictRelationship = Field(
        description="Relationship between new and existing content"
    )
    recommendation: ConflictRecommendation = Field(
        description="Recommended action to take"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in this decision"
    )
    importance_adjustment: ImportanceAdjustment = Field(
        default_factory=ImportanceAdjustment,
        description="How to adjust importance scores",
    )
    reasoning: str = Field(description="Detailed explanation of decision")
    merged_content: Optional[str] = Field(
        default=None, description="Merged content if recommendation is MERGE"
    )


# =============================================================================
# Pending Change (for FLAG_REVIEW)
# =============================================================================


class PendingKnowledgeChange(BaseModel):
    """A knowledge change flagged for human review."""

    id: str = Field(description="Unique identifier for this change")
    change_type: str = Field(default="knowledge", description="Type of change")
    status: str = Field(default="pending", description="Review status")

    # Content
    title: str = Field(description="Brief title describing the change")
    description: str = Field(description="Detailed description of what changed")
    new_content: str = Field(description="The new content being proposed")
    existing_content: Optional[str] = Field(
        default=None, description="Existing content that may be affected"
    )
    existing_node_id: Optional[str] = Field(
        default=None, description="ID of existing node if applicable"
    )

    # Conflict details
    conflict_relationship: ConflictRelationship = Field(
        description="Detected relationship"
    )
    conflict_reasoning: str = Field(description="Why this needs review")
    confidence: float = Field(
        ge=0.0, le=1.0, description="AI confidence in the analysis"
    )

    # Evidence
    evidence: list[dict[str, Any]] = Field(
        default_factory=list, description="Supporting evidence"
    )

    # Metadata
    source: str = Field(default="ai_pipeline", description="Source of the proposal")
    proposed_by: str = Field(
        default="content_analyzer", description="Who/what proposed this"
    )
    proposed_at: datetime = Field(
        default_factory=datetime.utcnow, description="When proposed"
    )

    # Analysis results
    analysis: Optional[ContentAnalysisResult] = Field(
        default=None, description="Full content analysis"
    )
