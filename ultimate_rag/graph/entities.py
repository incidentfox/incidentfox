"""
Entity types for the Knowledge Graph.

Entities represent the "nouns" in enterprise knowledge:
services, people, teams, runbooks, incidents, etc.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class EntityType(str, Enum):
    """Types of entities in the knowledge graph."""

    SERVICE = "service"
    PERSON = "person"
    TEAM = "team"
    RUNBOOK = "runbook"
    INCIDENT = "incident"
    DOCUMENT = "document"
    TECHNOLOGY = "technology"
    ALERT_RULE = "alert_rule"
    METRIC = "metric"
    ENVIRONMENT = "environment"
    NAMESPACE = "namespace"
    CUSTOM = "custom"


@dataclass
class Entity:
    """
    Base class for all entities in the knowledge graph.

    Entities are connected to RAPTOR nodes via node_ids,
    allowing hybrid graph+tree retrieval.
    """

    # Identity
    entity_id: str
    entity_type: EntityType
    name: str

    # Display
    display_name: Optional[str] = None
    description: Optional[str] = None

    # RAPTOR integration - links to tree nodes
    node_ids: List[int] = field(default_factory=list)  # RAPTOR node indices
    tree_ids: List[str] = field(default_factory=list)  # Which trees contain this entity

    # Metadata
    tags: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    # Aliases for fuzzy matching
    aliases: List[str] = field(default_factory=list)

    def __hash__(self):
        return hash(self.entity_id)

    def __eq__(self, other):
        if isinstance(other, Entity):
            return self.entity_id == other.entity_id
        return False

    def add_node_reference(self, node_id: int, tree_id: str) -> None:
        """Link this entity to a RAPTOR node."""
        if node_id not in self.node_ids:
            self.node_ids.append(node_id)
        if tree_id not in self.tree_ids:
            self.tree_ids.append(tree_id)
        self.updated_at = datetime.utcnow()

    def add_alias(self, alias: str) -> None:
        """Add an alias for fuzzy matching."""
        if alias and alias.lower() not in [a.lower() for a in self.aliases]:
            self.aliases.append(alias)

    def matches_name(self, query: str) -> bool:
        """Check if query matches this entity's name or aliases."""
        query_lower = query.lower()
        if query_lower in self.name.lower():
            return True
        if self.display_name and query_lower in self.display_name.lower():
            return True
        return any(query_lower in alias.lower() for alias in self.aliases)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type.value,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "node_ids": self.node_ids,
            "tree_ids": self.tree_ids,
            "tags": self.tags,
            "properties": self.properties,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "aliases": self.aliases,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Entity":
        """Deserialize from dictionary."""

        def parse_dt(s):
            return datetime.fromisoformat(s) if s else datetime.utcnow()

        return cls(
            entity_id=data.get("entity_id", ""),
            entity_type=EntityType(data.get("entity_type", "custom")),
            name=data.get("name", ""),
            display_name=data.get("display_name"),
            description=data.get("description"),
            node_ids=data.get("node_ids", []),
            tree_ids=data.get("tree_ids", []),
            tags=data.get("tags", []),
            properties=data.get("properties", {}),
            created_at=parse_dt(data.get("created_at")),
            updated_at=parse_dt(data.get("updated_at")),
            aliases=data.get("aliases", []),
        )


@dataclass
class Service(Entity):
    """
    A service entity representing a software service/microservice.
    """

    # Service-specific fields
    tier: str = "P3"  # P1, P2, P3 (criticality)
    team_id: Optional[str] = None
    repo_url: Optional[str] = None
    health_endpoint: Optional[str] = None
    documentation_url: Optional[str] = None

    # Technical details
    language: Optional[str] = None
    framework: Optional[str] = None
    runtime: Optional[str] = None  # k8s, ecs, lambda, etc.

    # SLOs
    slo_availability: Optional[float] = None  # e.g., 99.9
    slo_latency_p99_ms: Optional[int] = None

    def __post_init__(self):
        self.entity_type = EntityType.SERVICE

    @property
    def is_critical(self) -> bool:
        """Check if this is a critical (P1) service."""
        return self.tier == "P1"

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "tier": self.tier,
                "team_id": self.team_id,
                "repo_url": self.repo_url,
                "health_endpoint": self.health_endpoint,
                "documentation_url": self.documentation_url,
                "language": self.language,
                "framework": self.framework,
                "runtime": self.runtime,
                "slo_availability": self.slo_availability,
                "slo_latency_p99_ms": self.slo_latency_p99_ms,
            }
        )
        return base


@dataclass
class Person(Entity):
    """
    A person entity representing a team member.
    """

    # Contact info
    email: Optional[str] = None
    slack_handle: Optional[str] = None
    phone: Optional[str] = None

    # Organization
    team_id: Optional[str] = None
    role: Optional[str] = None
    manager_id: Optional[str] = None

    # Expertise
    expertise_areas: List[str] = field(default_factory=list)
    expertise_level: Dict[str, str] = field(
        default_factory=dict
    )  # area -> junior/senior/principal

    # Availability
    timezone: Optional[str] = None
    is_oncall: bool = False

    def __post_init__(self):
        self.entity_type = EntityType.PERSON

    def is_expert_in(self, area: str) -> bool:
        """Check if person is expert in an area."""
        area_lower = area.lower()
        return any(area_lower in exp.lower() for exp in self.expertise_areas)

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "email": self.email,
                "slack_handle": self.slack_handle,
                "phone": self.phone,
                "team_id": self.team_id,
                "role": self.role,
                "manager_id": self.manager_id,
                "expertise_areas": self.expertise_areas,
                "expertise_level": self.expertise_level,
                "timezone": self.timezone,
                "is_oncall": self.is_oncall,
            }
        )
        return base


@dataclass
class Team(Entity):
    """
    A team entity representing an organizational unit.
    """

    # Communication
    slack_channel: Optional[str] = None
    email_list: Optional[str] = None

    # On-call
    oncall_schedule_id: Optional[str] = None
    escalation_policy_id: Optional[str] = None
    pagerduty_service_id: Optional[str] = None

    # Members
    member_ids: List[str] = field(default_factory=list)
    lead_id: Optional[str] = None

    # Services owned
    service_ids: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.entity_type = EntityType.TEAM

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "slack_channel": self.slack_channel,
                "email_list": self.email_list,
                "oncall_schedule_id": self.oncall_schedule_id,
                "escalation_policy_id": self.escalation_policy_id,
                "pagerduty_service_id": self.pagerduty_service_id,
                "member_ids": self.member_ids,
                "lead_id": self.lead_id,
                "service_ids": self.service_ids,
            }
        )
        return base


@dataclass
class Runbook(Entity):
    """
    A runbook entity for operational procedures.
    """

    # Content
    title: str = ""
    summary: Optional[str] = None

    # Applicability
    applies_to_services: List[str] = field(default_factory=list)
    applies_to_alerts: List[str] = field(default_factory=list)
    symptoms: List[str] = field(
        default_factory=list
    )  # What symptoms trigger this runbook

    # Quality
    last_used: Optional[datetime] = None
    success_count: int = 0
    failure_count: int = 0

    # Ownership
    author_id: Optional[str] = None
    reviewer_ids: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.entity_type = EntityType.RUNBOOK

    @property
    def success_rate(self) -> float:
        """Get success rate when this runbook was used."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.5
        return self.success_count / total

    def record_usage(self, success: bool) -> None:
        """Record usage of this runbook."""
        self.last_used = datetime.utcnow()
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1

    def matches_symptoms(self, symptom_text: str) -> float:
        """
        Score how well this runbook matches given symptoms.

        Returns a score from 0 to 1.
        """
        if not self.symptoms:
            return 0.0

        symptom_lower = symptom_text.lower()
        matches = sum(1 for s in self.symptoms if s.lower() in symptom_lower)
        return min(1.0, matches / len(self.symptoms))

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "title": self.title,
                "summary": self.summary,
                "applies_to_services": self.applies_to_services,
                "applies_to_alerts": self.applies_to_alerts,
                "symptoms": self.symptoms,
                "last_used": self.last_used.isoformat() if self.last_used else None,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "author_id": self.author_id,
                "reviewer_ids": self.reviewer_ids,
            }
        )
        return base


@dataclass
class Incident(Entity):
    """
    An incident entity representing a past incident.
    """

    # Incident details
    severity: str = "P3"  # P1-P5
    status: str = "resolved"  # triggered, acknowledged, resolved

    # Impact
    services_affected: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None

    # Analysis
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    runbooks_used: List[str] = field(default_factory=list)

    # Postmortem
    postmortem_node_id: Optional[int] = None
    lessons_learned: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.entity_type = EntityType.INCIDENT

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "severity": self.severity,
                "status": self.status,
                "services_affected": self.services_affected,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "resolved_at": (
                    self.resolved_at.isoformat() if self.resolved_at else None
                ),
                "duration_minutes": self.duration_minutes,
                "root_cause": self.root_cause,
                "resolution": self.resolution,
                "runbooks_used": self.runbooks_used,
                "postmortem_node_id": self.postmortem_node_id,
                "lessons_learned": self.lessons_learned,
                "action_items": self.action_items,
            }
        )
        return base


@dataclass
class Document(Entity):
    """
    A document entity representing a piece of documentation.
    """

    # Document info
    title: str = ""
    doc_type: str = "general"  # api_spec, architecture, how_to, reference, etc.
    url: Optional[str] = None

    # Content references
    primary_node_id: Optional[int] = None  # Main RAPTOR node for this doc

    # Quality
    word_count: int = 0
    last_reviewed: Optional[datetime] = None
    reviewer_id: Optional[str] = None

    def __post_init__(self):
        self.entity_type = EntityType.DOCUMENT

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "title": self.title,
                "doc_type": self.doc_type,
                "url": self.url,
                "primary_node_id": self.primary_node_id,
                "word_count": self.word_count,
                "last_reviewed": (
                    self.last_reviewed.isoformat() if self.last_reviewed else None
                ),
                "reviewer_id": self.reviewer_id,
            }
        )
        return base


@dataclass
class Technology(Entity):
    """
    A technology entity (language, framework, database, etc.).
    """

    # Tech details
    category: str = "other"  # language, framework, database, cloud_service, tool
    version: Optional[str] = None
    vendor: Optional[str] = None
    license: Optional[str] = None

    # Usage
    used_by_services: List[str] = field(default_factory=list)

    # Experts
    expert_ids: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.entity_type = EntityType.TECHNOLOGY

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "category": self.category,
                "version": self.version,
                "vendor": self.vendor,
                "license": self.license,
                "used_by_services": self.used_by_services,
                "expert_ids": self.expert_ids,
            }
        )
        return base


@dataclass
class AlertRule(Entity):
    """
    An alert rule entity.
    """

    # Alert details
    query: Optional[str] = None  # PromQL, Datadog query, etc.
    threshold: Optional[str] = None
    severity: str = "warning"  # critical, warning, info

    # Scope
    services: List[str] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)

    # Runbook link
    runbook_id: Optional[str] = None
    auto_link_runbook: bool = False

    def __post_init__(self):
        self.entity_type = EntityType.ALERT_RULE

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "query": self.query,
                "threshold": self.threshold,
                "severity": self.severity,
                "services": self.services,
                "environments": self.environments,
                "runbook_id": self.runbook_id,
                "auto_link_runbook": self.auto_link_runbook,
            }
        )
        return base
