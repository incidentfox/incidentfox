"""
Relationship types for the Knowledge Graph.

Relationships represent the "verbs" connecting entities:
DEPENDS_ON, OWNS, DOCUMENTED_BY, etc.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class RelationshipType(str, Enum):
    """Types of relationships between entities."""

    # Service relationships
    DEPENDS_ON = "depends_on"  # Service A depends on Service B
    CALLS = "calls"  # Service A calls Service B
    SHARES_DATA_WITH = "shares_data_with"  # Data flow between services

    # Ownership relationships
    OWNS = "owns"  # Team owns Service
    MAINTAINS = "maintains"  # Person maintains Service/Document
    AUTHORED = "authored"  # Person authored Document

    # Expertise relationships
    EXPERT_IN = "expert_in"  # Person is expert in Service/Technology
    ON_CALL_FOR = "on_call_for"  # Person is on-call for Service

    # Team relationships
    MEMBER_OF = "member_of"  # Person is member of Team
    LEADS = "leads"  # Person leads Team
    ESCALATES_TO = "escalates_to"  # Team A escalates to Team B

    # Documentation relationships
    DOCUMENTS = "documents"  # Document documents Service
    REFERENCES = "references"  # Document references another Document
    SUPERSEDES = "supersedes"  # Document supersedes another Document
    CONTRADICTS = "contradicts"  # Document contradicts another Document

    # Operational relationships
    RESOLVES_ISSUES_FOR = "resolves_issues_for"  # Runbook resolves issues for Service
    USED_IN = "used_in"  # Runbook was used in Incident
    TRIGGERS = "triggers"  # AlertRule triggers Runbook
    ALERTS_FOR = "alerts_for"  # AlertRule monitors Service

    # Incident relationships
    AFFECTED = "affected"  # Incident affected Service
    CAUSED_BY = "caused_by"  # Incident caused by another entity
    SIMILAR_TO = "similar_to"  # Incident is similar to another Incident

    # Technology relationships
    USES = "uses"  # Service uses Technology
    HOSTED_ON = "hosted_on"  # Service hosted on Infrastructure
    DEPLOYED_IN = "deployed_in"  # Service deployed in Environment

    # Generic
    RELATED_TO = "related_to"  # Generic relationship


# Relationship metadata schemas
RELATIONSHIP_PROPERTIES = {
    RelationshipType.DEPENDS_ON: {
        "criticality": "float",  # How critical is this dependency (0-1)
        "sync": "bool",  # Is this a synchronous dependency
        "required": "bool",  # Is this required or optional
    },
    RelationshipType.CALLS: {
        "protocol": "str",  # http, grpc, kafka, etc.
        "endpoint": "str",
        "frequency": "str",  # high, medium, low
    },
    RelationshipType.EXPERT_IN: {
        "level": "str",  # junior, senior, principal
        "years": "int",
    },
    RelationshipType.USED_IN: {
        "success": "bool",  # Did the runbook work?
        "duration_minutes": "int",
    },
    RelationshipType.RESOLVES_ISSUES_FOR: {
        "symptom_match": "float",  # How well symptoms match (0-1)
    },
    RelationshipType.AFFECTED: {
        "impact_level": "float",  # Severity of impact (0-1)
    },
    RelationshipType.CONTRADICTS: {
        "field": "str",  # Which field contradicts
        "resolution": "str",  # How to resolve
    },
}


@dataclass
class Relationship:
    """
    A relationship between two entities.

    Relationships are directional: source -> target
    """

    # Identity
    relationship_id: str
    relationship_type: RelationshipType

    # Endpoints
    source_id: str  # Entity ID
    target_id: str  # Entity ID

    # Properties (relationship-specific)
    properties: Dict[str, Any] = field(default_factory=dict)

    # Confidence
    confidence: float = 1.0  # 0-1, how confident are we in this relationship

    # Provenance
    source_system: Optional[str] = None  # Where this relationship came from
    inferred: bool = False  # Was this inferred by the system?

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    valid_from: Optional[datetime] = None  # When this relationship became valid
    valid_until: Optional[datetime] = None  # When this relationship expires

    def __hash__(self):
        return hash(self.relationship_id)

    def __eq__(self, other):
        if isinstance(other, Relationship):
            return self.relationship_id == other.relationship_id
        return False

    @property
    def is_active(self) -> bool:
        """Check if this relationship is currently active."""
        now = datetime.utcnow()
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True

    def get_property(self, key: str, default: Any = None) -> Any:
        """Get a relationship property."""
        return self.properties.get(key, default)

    def set_property(self, key: str, value: Any) -> None:
        """Set a relationship property."""
        self.properties[key] = value
        self.updated_at = datetime.utcnow()

    def inverse(self) -> "Relationship":
        """
        Create the inverse relationship (swap source and target).

        Note: Not all relationships have meaningful inverses.
        """
        inverse_types = {
            RelationshipType.DEPENDS_ON: RelationshipType.DEPENDS_ON,  # bidirectional
            RelationshipType.OWNS: RelationshipType.MEMBER_OF,  # Team owns -> Person member of
            RelationshipType.CALLS: RelationshipType.CALLS,
            RelationshipType.DOCUMENTS: RelationshipType.RELATED_TO,
        }

        inverse_type = inverse_types.get(
            self.relationship_type, RelationshipType.RELATED_TO
        )

        return Relationship(
            relationship_id=f"{self.relationship_id}_inverse",
            relationship_type=inverse_type,
            source_id=self.target_id,
            target_id=self.source_id,
            properties=self.properties.copy(),
            confidence=self.confidence,
            inferred=True,
            created_at=self.created_at,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""

        def dt_to_str(dt):
            return dt.isoformat() if dt else None

        return {
            "relationship_id": self.relationship_id,
            "relationship_type": self.relationship_type.value,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "properties": self.properties,
            "confidence": self.confidence,
            "source_system": self.source_system,
            "inferred": self.inferred,
            "created_at": dt_to_str(self.created_at),
            "updated_at": dt_to_str(self.updated_at),
            "valid_from": dt_to_str(self.valid_from),
            "valid_until": dt_to_str(self.valid_until),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Relationship":
        """Deserialize from dictionary."""

        def parse_dt(s):
            return datetime.fromisoformat(s) if s else None

        return cls(
            relationship_id=data.get("relationship_id", ""),
            relationship_type=RelationshipType(
                data.get("relationship_type", "related_to")
            ),
            source_id=data.get("source_id", ""),
            target_id=data.get("target_id", ""),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 1.0),
            source_system=data.get("source_system"),
            inferred=data.get("inferred", False),
            created_at=parse_dt(data.get("created_at")) or datetime.utcnow(),
            updated_at=parse_dt(data.get("updated_at")) or datetime.utcnow(),
            valid_from=parse_dt(data.get("valid_from")),
            valid_until=parse_dt(data.get("valid_until")),
        )

    @classmethod
    def create(
        cls,
        rel_type: RelationshipType,
        source_id: str,
        target_id: str,
        **properties,
    ) -> "Relationship":
        """
        Factory method to create a relationship.

        Args:
            rel_type: Type of relationship
            source_id: Source entity ID
            target_id: Target entity ID
            **properties: Relationship-specific properties

        Returns:
            New Relationship instance
        """
        import uuid

        return cls(
            relationship_id=str(uuid.uuid4()),
            relationship_type=rel_type,
            source_id=source_id,
            target_id=target_id,
            properties=properties,
        )
