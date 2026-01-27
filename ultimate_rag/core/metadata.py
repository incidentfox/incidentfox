"""
Metadata structures for knowledge nodes.

Tracks provenance, validation status, and source information.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ValidationStatus(str, Enum):
    """Status of knowledge validation."""

    VALIDATED = "validated"  # Human-reviewed and confirmed accurate
    PROVISIONAL = "provisional"  # Auto-ingested, not yet reviewed
    NEEDS_REVIEW = "needs_review"  # Flagged for human review
    STALE = "stale"  # Outdated, needs refresh
    DEPRECATED = "deprecated"  # No longer accurate, kept for history
    CONTRADICTION = "contradiction"  # Conflicts with other knowledge


@dataclass
class SourceInfo:
    """
    Information about the source of knowledge.

    Tracks where knowledge came from and how to refresh it.
    """

    # Source identification
    source_type: str  # 'confluence', 'github', 'slack', 'manual', 'agent', etc.
    source_url: Optional[str] = None
    source_id: Optional[str] = None  # ID in the source system

    # Source metadata
    author: Optional[str] = None
    author_email: Optional[str] = None
    organization: Optional[str] = None
    repository: Optional[str] = None
    file_path: Optional[str] = None

    # Timestamps
    source_created_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    ingested_at: datetime = field(default_factory=datetime.utcnow)
    last_synced_at: Optional[datetime] = None

    # Sync configuration
    auto_sync: bool = True  # Should this be auto-refreshed
    sync_interval_hours: int = 24  # How often to check for updates
    content_hash: Optional[str] = None  # For change detection

    def needs_sync(self) -> bool:
        """Check if this source needs to be synced."""
        if not self.auto_sync:
            return False
        if not self.last_synced_at:
            return True
        hours_since_sync = (
            datetime.utcnow() - self.last_synced_at
        ).total_seconds() / 3600
        return hours_since_sync > self.sync_interval_hours

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "source_type": self.source_type,
            "source_url": self.source_url,
            "source_id": self.source_id,
            "author": self.author,
            "author_email": self.author_email,
            "organization": self.organization,
            "repository": self.repository,
            "file_path": self.file_path,
            "source_created_at": (
                self.source_created_at.isoformat() if self.source_created_at else None
            ),
            "source_updated_at": (
                self.source_updated_at.isoformat() if self.source_updated_at else None
            ),
            "ingested_at": self.ingested_at.isoformat(),
            "last_synced_at": (
                self.last_synced_at.isoformat() if self.last_synced_at else None
            ),
            "auto_sync": self.auto_sync,
            "sync_interval_hours": self.sync_interval_hours,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceInfo":
        """Deserialize from dictionary."""

        def parse_dt(s):
            return datetime.fromisoformat(s) if s else None

        return cls(
            source_type=data.get("source_type", "unknown"),
            source_url=data.get("source_url"),
            source_id=data.get("source_id"),
            author=data.get("author"),
            author_email=data.get("author_email"),
            organization=data.get("organization"),
            repository=data.get("repository"),
            file_path=data.get("file_path"),
            source_created_at=parse_dt(data.get("source_created_at")),
            source_updated_at=parse_dt(data.get("source_updated_at")),
            ingested_at=parse_dt(data.get("ingested_at")) or datetime.utcnow(),
            last_synced_at=parse_dt(data.get("last_synced_at")),
            auto_sync=data.get("auto_sync", True),
            sync_interval_hours=data.get("sync_interval_hours", 24),
            content_hash=data.get("content_hash"),
        )


@dataclass
class NodeMetadata:
    """
    Comprehensive metadata for a knowledge node.

    Includes provenance, validation, entities, and relationships.
    """

    # Identification
    node_id: int
    tree_id: str
    layer: int

    # Classification
    knowledge_type: str  # KnowledgeType value
    tags: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)

    # Source information
    source: Optional[SourceInfo] = None
    sources: List[SourceInfo] = field(default_factory=list)  # For merged nodes

    # Validation
    validation_status: ValidationStatus = ValidationStatus.PROVISIONAL
    validated_by: Optional[str] = None
    validated_at: Optional[datetime] = None
    review_notes: Optional[str] = None

    # Entity references (for graph integration)
    entities_mentioned: List[str] = field(default_factory=list)  # Entity IDs
    services_related: List[str] = field(default_factory=list)
    people_related: List[str] = field(default_factory=list)
    teams_related: List[str] = field(default_factory=list)

    # Hierarchical relationships
    parent_nodes: List[int] = field(default_factory=list)  # Nodes that summarize this
    child_nodes: List[int] = field(default_factory=list)  # Nodes this summarizes

    # Cross-references
    references: List[str] = field(default_factory=list)  # URLs/IDs this node references
    referenced_by: List[int] = field(default_factory=list)  # Nodes that reference this

    # Quality indicators
    confidence: float = 0.5  # 0-1, how confident are we in this knowledge
    completeness: float = 0.5  # 0-1, how complete is this knowledge
    clarity: float = 0.5  # 0-1, how clear/readable is this

    # Provenance for summarized nodes
    citations: List[Dict[str, Any]] = field(default_factory=list)
    citation_total: int = 0

    # Lifecycle
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None  # For time-limited knowledge
    archived_at: Optional[datetime] = None

    # Agent learning
    learned_from: Optional[str] = None  # 'ingestion', 'agent_teaching', 'correction'
    learning_context: Optional[Dict[str, Any]] = None

    def add_entity(self, entity_id: str) -> None:
        """Add an entity reference."""
        if entity_id not in self.entities_mentioned:
            self.entities_mentioned.append(entity_id)

    def add_service(self, service_id: str) -> None:
        """Add a related service."""
        if service_id not in self.services_related:
            self.services_related.append(service_id)

    def add_citation(self, source: str, count: int = 1, **details) -> None:
        """Add a citation."""
        existing = next((c for c in self.citations if c.get("ref") == source), None)
        if existing:
            existing["count"] = existing.get("count", 0) + count
        else:
            citation = {"ref": source, "count": count}
            citation.update(details)
            self.citations.append(citation)
        self.citation_total += count

    def mark_validated(self, by: str, notes: Optional[str] = None) -> None:
        """Mark this node as validated."""
        self.validation_status = ValidationStatus.VALIDATED
        self.validated_by = by
        self.validated_at = datetime.utcnow()
        self.review_notes = notes
        self.confidence = max(self.confidence, 0.8)  # Boost confidence

    def mark_stale(self, reason: Optional[str] = None) -> None:
        """Mark this node as stale."""
        self.validation_status = ValidationStatus.STALE
        self.review_notes = reason

    def mark_deprecated(self, reason: str) -> None:
        """Mark this node as deprecated."""
        self.validation_status = ValidationStatus.DEPRECATED
        self.archived_at = datetime.utcnow()
        self.review_notes = reason

    def is_active(self) -> bool:
        """Check if this node is active (not deprecated/archived)."""
        if self.archived_at:
            return False
        if self.validation_status == ValidationStatus.DEPRECATED:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""

        def dt_to_str(dt):
            return dt.isoformat() if dt else None

        return {
            "node_id": self.node_id,
            "tree_id": self.tree_id,
            "layer": self.layer,
            "knowledge_type": self.knowledge_type,
            "tags": self.tags,
            "topics": self.topics,
            "source": self.source.to_dict() if self.source else None,
            "sources": [s.to_dict() for s in self.sources],
            "validation_status": self.validation_status.value,
            "validated_by": self.validated_by,
            "validated_at": dt_to_str(self.validated_at),
            "review_notes": self.review_notes,
            "entities_mentioned": self.entities_mentioned,
            "services_related": self.services_related,
            "people_related": self.people_related,
            "teams_related": self.teams_related,
            "parent_nodes": self.parent_nodes,
            "child_nodes": self.child_nodes,
            "references": self.references,
            "referenced_by": self.referenced_by,
            "confidence": self.confidence,
            "completeness": self.completeness,
            "clarity": self.clarity,
            "citations": self.citations,
            "citation_total": self.citation_total,
            "created_at": dt_to_str(self.created_at),
            "updated_at": dt_to_str(self.updated_at),
            "expires_at": dt_to_str(self.expires_at),
            "archived_at": dt_to_str(self.archived_at),
            "learned_from": self.learned_from,
            "learning_context": self.learning_context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeMetadata":
        """Deserialize from dictionary."""

        def parse_dt(s):
            return datetime.fromisoformat(s) if s else None

        return cls(
            node_id=data.get("node_id", 0),
            tree_id=data.get("tree_id", ""),
            layer=data.get("layer", 0),
            knowledge_type=data.get("knowledge_type", "factual"),
            tags=data.get("tags", []),
            topics=data.get("topics", []),
            source=SourceInfo.from_dict(data["source"]) if data.get("source") else None,
            sources=[SourceInfo.from_dict(s) for s in data.get("sources", [])],
            validation_status=ValidationStatus(
                data.get("validation_status", "provisional")
            ),
            validated_by=data.get("validated_by"),
            validated_at=parse_dt(data.get("validated_at")),
            review_notes=data.get("review_notes"),
            entities_mentioned=data.get("entities_mentioned", []),
            services_related=data.get("services_related", []),
            people_related=data.get("people_related", []),
            teams_related=data.get("teams_related", []),
            parent_nodes=data.get("parent_nodes", []),
            child_nodes=data.get("child_nodes", []),
            references=data.get("references", []),
            referenced_by=data.get("referenced_by", []),
            confidence=data.get("confidence", 0.5),
            completeness=data.get("completeness", 0.5),
            clarity=data.get("clarity", 0.5),
            citations=data.get("citations", []),
            citation_total=data.get("citation_total", 0),
            created_at=parse_dt(data.get("created_at")) or datetime.utcnow(),
            updated_at=parse_dt(data.get("updated_at")) or datetime.utcnow(),
            expires_at=parse_dt(data.get("expires_at")),
            archived_at=parse_dt(data.get("archived_at")),
            learned_from=data.get("learned_from"),
            learning_context=data.get("learning_context"),
        )
