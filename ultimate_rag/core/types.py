"""
Core types for the Ultimate RAG system.

This module defines the fundamental types used throughout the system,
including knowledge classification and importance scoring.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional


class KnowledgeType(str, Enum):
    """
    Classification of knowledge types in an enterprise.

    Each type has different storage and retrieval characteristics.
    """

    # How to do things
    PROCEDURAL = "procedural"  # Runbooks, SOPs, playbooks, workflows

    # What things are
    FACTUAL = "factual"  # Service docs, API specs, architecture

    # How things connect
    RELATIONAL = "relational"  # Dependencies, ownership, integrations

    # What happened and when
    TEMPORAL = "temporal"  # Incidents, changes, deployments, postmortems

    # Who knows what
    SOCIAL = "social"  # SMEs, teams, escalation paths, contacts

    # Current state (ephemeral)
    CONTEXTUAL = "contextual"  # Active incidents, health, alerts

    # Rules and constraints
    POLICY = "policy"  # Compliance, security, SLAs, change management

    # Knowledge about knowledge
    META = "meta"  # Staleness, authority, confidence, gaps

    @classmethod
    def from_string(cls, s: str) -> "KnowledgeType":
        """Parse knowledge type from string, with fuzzy matching."""
        s = s.lower().strip()
        mapping = {
            "procedural": cls.PROCEDURAL,
            "runbook": cls.PROCEDURAL,
            "sop": cls.PROCEDURAL,
            "playbook": cls.PROCEDURAL,
            "how-to": cls.PROCEDURAL,
            "factual": cls.FACTUAL,
            "documentation": cls.FACTUAL,
            "docs": cls.FACTUAL,
            "api": cls.FACTUAL,
            "spec": cls.FACTUAL,
            "relational": cls.RELATIONAL,
            "dependency": cls.RELATIONAL,
            "architecture": cls.RELATIONAL,
            "temporal": cls.TEMPORAL,
            "incident": cls.TEMPORAL,
            "postmortem": cls.TEMPORAL,
            "changelog": cls.TEMPORAL,
            "social": cls.SOCIAL,
            "team": cls.SOCIAL,
            "people": cls.SOCIAL,
            "contact": cls.SOCIAL,
            "contextual": cls.CONTEXTUAL,
            "live": cls.CONTEXTUAL,
            "current": cls.CONTEXTUAL,
            "policy": cls.POLICY,
            "compliance": cls.POLICY,
            "security": cls.POLICY,
            "sla": cls.POLICY,
            "meta": cls.META,
        }
        return mapping.get(s, cls.FACTUAL)

    @property
    def volatility(self) -> str:
        """How frequently this knowledge type changes."""
        volatility_map = {
            self.PROCEDURAL: "low",
            self.FACTUAL: "medium",
            self.RELATIONAL: "medium",
            self.TEMPORAL: "high",
            self.SOCIAL: "medium",
            self.CONTEXTUAL: "very_high",
            self.POLICY: "low",
            self.META: "continuous",
        }
        return volatility_map.get(self, "medium")

    @property
    def default_ttl_days(self) -> int:
        """Default time-to-live before requiring revalidation."""
        ttl_map = {
            self.PROCEDURAL: 90,
            self.FACTUAL: 60,
            self.RELATIONAL: 30,
            self.TEMPORAL: 365,  # Historical, but needs accuracy
            self.SOCIAL: 30,
            self.CONTEXTUAL: 1,  # Very short TTL
            self.POLICY: 180,
            self.META: 7,
        }
        return ttl_map.get(self, 60)


@dataclass
class ImportanceWeights:
    """
    Weights for combining importance signals.

    Allows customization per organization or use case.
    """

    explicit: float = 0.25  # Admin/author-assigned importance
    frequency: float = 0.15  # Access frequency
    recency: float = 0.10  # Recency of access
    authority: float = 0.15  # Author expertise, review status
    criticality: float = 0.15  # Related to critical services
    uniqueness: float = 0.05  # How unique is this info
    rating: float = 0.10  # User feedback
    outcome: float = 0.05  # Task success when using this

    def to_dict(self) -> Dict[str, float]:
        return {
            "explicit": self.explicit,
            "frequency": self.frequency,
            "recency": self.recency,
            "authority": self.authority,
            "criticality": self.criticality,
            "uniqueness": self.uniqueness,
            "rating": self.rating,
            "outcome": self.outcome,
        }

    @classmethod
    def for_incident_response(cls) -> "ImportanceWeights":
        """Weights optimized for incident response scenarios."""
        return cls(
            explicit=0.20,
            frequency=0.10,
            recency=0.20,  # Recent info more important
            authority=0.10,
            criticality=0.25,  # Critical services prioritized
            uniqueness=0.05,
            rating=0.05,
            outcome=0.05,
        )

    @classmethod
    def for_onboarding(cls) -> "ImportanceWeights":
        """Weights optimized for new employee onboarding."""
        return cls(
            explicit=0.30,  # Curated content important
            frequency=0.20,  # Popular content
            recency=0.05,
            authority=0.20,  # Expert content
            criticality=0.05,
            uniqueness=0.05,
            rating=0.10,
            outcome=0.05,
        )


DEFAULT_IMPORTANCE_WEIGHTS = ImportanceWeights()


@dataclass
class ImportanceScore:
    """
    Multi-signal importance score for a knowledge node.

    Combines explicit signals (human-provided), usage signals (observed),
    content signals (derived), quality signals (feedback), and freshness.
    """

    # Explicit signals (human-provided)
    explicit_priority: float = 0.5  # 0-1, admin/author marked importance

    # Usage signals (observed behavior)
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    citation_count: int = 0  # How often referenced by other nodes

    # Content signals (derived from content)
    authority_score: float = 0.5  # Author expertise, review status
    criticality_score: float = 0.5  # Related to critical services
    uniqueness_score: float = 0.5  # How unique is this information

    # Quality signals (feedback-based)
    positive_feedback: int = 0
    negative_feedback: int = 0
    task_success_count: int = 0
    task_failure_count: int = 0

    # Freshness signals
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_validated: Optional[datetime] = None
    source_last_checked: Optional[datetime] = None

    # Contextual boosts (temporary)
    contextual_boosts: Dict[str, float] = field(default_factory=dict)

    def _normalize_access_frequency(self, max_accesses: int = 1000) -> float:
        """Normalize access count to 0-1 scale."""
        if max_accesses <= 0:
            return 0.0
        return min(1.0, self.access_count / max_accesses)

    def _normalize_recency(self, max_days: int = 30) -> float:
        """Normalize recency of access to 0-1 scale."""
        if not self.last_accessed:
            return 0.0
        days_since = (datetime.utcnow() - self.last_accessed).days
        return max(0.0, 1.0 - (days_since / max_days))

    def _compute_user_rating(self) -> float:
        """Compute rating from positive/negative feedback."""
        total = self.positive_feedback + self.negative_feedback
        if total == 0:
            return 0.5  # Neutral if no feedback
        return self.positive_feedback / total

    def _compute_outcome_success(self) -> float:
        """Compute success rate when this knowledge was used."""
        total = self.task_success_count + self.task_failure_count
        if total == 0:
            return 0.5  # Neutral if no data
        return self.task_success_count / total

    def _compute_content_freshness(self, ttl_days: int = 90) -> float:
        """Compute freshness score based on last update."""
        days_since_update = (datetime.utcnow() - self.updated_at).days
        return max(0.0, 1.0 - (days_since_update / ttl_days))

    def _compute_source_freshness(self, ttl_days: int = 30) -> float:
        """Compute freshness score based on source validation."""
        if not self.source_last_checked:
            return 0.3  # Assume somewhat stale if never checked
        days_since_check = (datetime.utcnow() - self.source_last_checked).days
        return max(0.0, 1.0 - (days_since_check / ttl_days))

    def compute_final(
        self,
        weights: Optional[ImportanceWeights] = None,
        max_accesses: int = 1000,
        content_ttl_days: int = 90,
        source_ttl_days: int = 30,
    ) -> float:
        """
        Compute final importance score as weighted combination.

        Args:
            weights: Custom weights for combining signals
            max_accesses: Normalization factor for access frequency
            content_ttl_days: TTL for content freshness calculation
            source_ttl_days: TTL for source freshness calculation

        Returns:
            Final importance score in [0, 1]
        """
        if weights is None:
            weights = DEFAULT_IMPORTANCE_WEIGHTS

        w = weights.to_dict()

        # Compute normalized signals
        signals = {
            "explicit": self.explicit_priority,
            "frequency": self._normalize_access_frequency(max_accesses),
            "recency": self._normalize_recency(),
            "authority": self.authority_score,
            "criticality": self.criticality_score,
            "uniqueness": self.uniqueness_score,
            "rating": self._compute_user_rating(),
            "outcome": self._compute_outcome_success(),
        }

        # Weighted sum
        total_weight = sum(w.values())
        base_score = sum(signals[k] * w.get(k, 0) for k in signals)
        base_score = base_score / total_weight if total_weight > 0 else 0.5

        # Apply freshness decay
        content_freshness = self._compute_content_freshness(content_ttl_days)
        source_freshness = self._compute_source_freshness(source_ttl_days)
        freshness_factor = (content_freshness + source_freshness) / 2

        # Decay formula: base * (0.5 + 0.5 * freshness)
        # This means even stale content keeps at least 50% of its score
        decayed_score = base_score * (0.5 + 0.5 * freshness_factor)

        # Apply contextual boosts
        boost = sum(self.contextual_boosts.values())
        boosted_score = decayed_score * (1.0 + min(boost, 0.5))  # Cap boost at 50%

        return min(1.0, max(0.0, boosted_score))

    def record_access(self) -> None:
        """Record an access to this knowledge."""
        self.access_count += 1
        self.last_accessed = datetime.utcnow()

    def record_feedback(self, positive: bool) -> None:
        """Record user feedback."""
        if positive:
            self.positive_feedback += 1
        else:
            self.negative_feedback += 1

    def record_task_outcome(self, success: bool) -> None:
        """Record outcome when this knowledge was used in a task."""
        if success:
            self.task_success_count += 1
        else:
            self.task_failure_count += 1

    def add_contextual_boost(self, reason: str, amount: float) -> None:
        """Add a temporary contextual boost."""
        self.contextual_boosts[reason] = amount

    def clear_contextual_boosts(self) -> None:
        """Clear all temporary contextual boosts."""
        self.contextual_boosts.clear()

    def mark_validated(self) -> None:
        """Mark this knowledge as recently validated."""
        self.last_validated = datetime.utcnow()

    def mark_source_checked(self) -> None:
        """Mark that the source was recently checked."""
        self.source_last_checked = datetime.utcnow()

    def is_stale(self, ttl_days: int = 90) -> bool:
        """Check if this knowledge is considered stale."""
        days_since_update = (datetime.utcnow() - self.updated_at).days
        return days_since_update > ttl_days

    def needs_validation(self, validation_interval_days: int = 30) -> bool:
        """Check if this knowledge needs revalidation."""
        if not self.last_validated:
            return True
        days_since_validation = (datetime.utcnow() - self.last_validated).days
        return days_since_validation > validation_interval_days

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "explicit_priority": self.explicit_priority,
            "access_count": self.access_count,
            "last_accessed": (
                self.last_accessed.isoformat() if self.last_accessed else None
            ),
            "citation_count": self.citation_count,
            "authority_score": self.authority_score,
            "criticality_score": self.criticality_score,
            "uniqueness_score": self.uniqueness_score,
            "positive_feedback": self.positive_feedback,
            "negative_feedback": self.negative_feedback,
            "task_success_count": self.task_success_count,
            "task_failure_count": self.task_failure_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_validated": (
                self.last_validated.isoformat() if self.last_validated else None
            ),
            "source_last_checked": (
                self.source_last_checked.isoformat()
                if self.source_last_checked
                else None
            ),
            "contextual_boosts": self.contextual_boosts,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImportanceScore":
        """Deserialize from dictionary."""

        def parse_dt(s):
            return datetime.fromisoformat(s) if s else None

        return cls(
            explicit_priority=data.get("explicit_priority", 0.5),
            access_count=data.get("access_count", 0),
            last_accessed=parse_dt(data.get("last_accessed")),
            citation_count=data.get("citation_count", 0),
            authority_score=data.get("authority_score", 0.5),
            criticality_score=data.get("criticality_score", 0.5),
            uniqueness_score=data.get("uniqueness_score", 0.5),
            positive_feedback=data.get("positive_feedback", 0),
            negative_feedback=data.get("negative_feedback", 0),
            task_success_count=data.get("task_success_count", 0),
            task_failure_count=data.get("task_failure_count", 0),
            created_at=parse_dt(data.get("created_at")) or datetime.utcnow(),
            updated_at=parse_dt(data.get("updated_at")) or datetime.utcnow(),
            last_validated=parse_dt(data.get("last_validated")),
            source_last_checked=parse_dt(data.get("source_last_checked")),
            contextual_boosts=data.get("contextual_boosts", {}),
        )
