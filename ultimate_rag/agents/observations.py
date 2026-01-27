"""
Agent Observation Collection

Captures feedback from agents working with the knowledge base,
enabling the learning loop that improves knowledge over time.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ObservationType(str, Enum):
    """Types of observations agents can report."""

    # Success indicators
    QUERY_SUCCESS = "query_success"  # Found relevant info, task succeeded
    RUNBOOK_SUCCESS = "runbook_success"  # Runbook worked for incident

    # Partial success
    QUERY_PARTIAL = "query_partial"  # Found some info, needed more

    # Failures
    QUERY_FAILURE = "query_failure"  # Couldn't find needed info
    RUNBOOK_FAILURE = "runbook_failure"  # Runbook didn't work

    # Quality issues
    OUTDATED = "outdated"  # Information was stale/wrong
    CONTRADICTION = "contradiction"  # Found conflicting information
    INCOMPLETE = "incomplete"  # Information was incomplete
    UNCLEAR = "unclear"  # Information was confusing

    # Learning opportunities
    CORRECTION = "correction"  # User corrected agent's answer
    NEW_KNOWLEDGE = "new_knowledge"  # Learned something new during task

    # Proactive suggestions
    SUGGESTED_UPDATE = "suggested_update"  # Agent suggests updating knowledge
    SUGGESTED_LINK = "suggested_link"  # Agent suggests linking entities


@dataclass
class AgentObservation:
    """
    An observation from an agent about knowledge quality.

    Agents report these observations during and after tasks,
    enabling the KB to learn and improve.
    """

    # Identity
    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    observation_type: ObservationType = ObservationType.QUERY_SUCCESS

    # Context
    query: str = ""  # The original query
    task_id: Optional[str] = None  # Related task/incident ID
    agent_id: Optional[str] = None  # Which agent reported this
    session_id: Optional[str] = None  # Conversation/session ID

    # What was retrieved
    retrieved_nodes: List[int] = field(default_factory=list)
    retrieved_entities: List[str] = field(default_factory=list)
    trees_searched: List[str] = field(default_factory=list)

    # Timing
    timestamp: datetime = field(default_factory=datetime.utcnow)
    retrieval_latency_ms: Optional[int] = None

    # Outcome assessment
    success_score: float = 0.5  # 0-1, how successful was the retrieval
    relevance_score: float = 0.5  # 0-1, how relevant were the results
    completeness_score: float = 0.5  # 0-1, how complete was the information

    # User feedback
    user_feedback: Optional[str] = None  # Explicit feedback text
    user_rating: Optional[int] = None  # 1-5 rating

    # For corrections
    correction_text: Optional[str] = None  # What the correct info should be
    original_answer: Optional[str] = None  # What the agent originally said

    # For gaps
    gap_description: Optional[str] = None  # What info was missing
    gap_queries: List[str] = field(default_factory=list)  # Related failed queries

    # For contradictions
    contradicting_nodes: List[int] = field(default_factory=list)
    contradiction_description: Optional[str] = None

    # Actions to take
    should_create_node: bool = False  # Should we add new knowledge
    should_invalidate: List[int] = field(default_factory=list)  # Nodes to mark stale
    should_boost: List[int] = field(default_factory=list)  # Nodes to boost importance
    should_demote: List[int] = field(default_factory=list)  # Nodes to demote

    # Additional context
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_positive(self) -> bool:
        """Check if this is a positive observation."""
        return self.observation_type in (
            ObservationType.QUERY_SUCCESS,
            ObservationType.RUNBOOK_SUCCESS,
        )

    def is_negative(self) -> bool:
        """Check if this is a negative observation."""
        return self.observation_type in (
            ObservationType.QUERY_FAILURE,
            ObservationType.RUNBOOK_FAILURE,
            ObservationType.OUTDATED,
            ObservationType.CONTRADICTION,
        )

    def indicates_gap(self) -> bool:
        """Check if this observation indicates a knowledge gap."""
        return self.observation_type in (
            ObservationType.QUERY_FAILURE,
            ObservationType.QUERY_PARTIAL,
            ObservationType.INCOMPLETE,
        )

    def indicates_quality_issue(self) -> bool:
        """Check if this indicates a quality issue with existing knowledge."""
        return self.observation_type in (
            ObservationType.OUTDATED,
            ObservationType.CONTRADICTION,
            ObservationType.UNCLEAR,
            ObservationType.CORRECTION,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "observation_id": self.observation_id,
            "observation_type": self.observation_type.value,
            "query": self.query,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "retrieved_nodes": self.retrieved_nodes,
            "retrieved_entities": self.retrieved_entities,
            "trees_searched": self.trees_searched,
            "timestamp": self.timestamp.isoformat(),
            "retrieval_latency_ms": self.retrieval_latency_ms,
            "success_score": self.success_score,
            "relevance_score": self.relevance_score,
            "completeness_score": self.completeness_score,
            "user_feedback": self.user_feedback,
            "user_rating": self.user_rating,
            "correction_text": self.correction_text,
            "original_answer": self.original_answer,
            "gap_description": self.gap_description,
            "gap_queries": self.gap_queries,
            "contradicting_nodes": self.contradicting_nodes,
            "contradiction_description": self.contradiction_description,
            "should_create_node": self.should_create_node,
            "should_invalidate": self.should_invalidate,
            "should_boost": self.should_boost,
            "should_demote": self.should_demote,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentObservation":
        """Deserialize from dictionary."""
        return cls(
            observation_id=data.get("observation_id", str(uuid.uuid4())),
            observation_type=ObservationType(
                data.get("observation_type", "query_success")
            ),
            query=data.get("query", ""),
            task_id=data.get("task_id"),
            agent_id=data.get("agent_id"),
            session_id=data.get("session_id"),
            retrieved_nodes=data.get("retrieved_nodes", []),
            retrieved_entities=data.get("retrieved_entities", []),
            trees_searched=data.get("trees_searched", []),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if data.get("timestamp")
                else datetime.utcnow()
            ),
            retrieval_latency_ms=data.get("retrieval_latency_ms"),
            success_score=data.get("success_score", 0.5),
            relevance_score=data.get("relevance_score", 0.5),
            completeness_score=data.get("completeness_score", 0.5),
            user_feedback=data.get("user_feedback"),
            user_rating=data.get("user_rating"),
            correction_text=data.get("correction_text"),
            original_answer=data.get("original_answer"),
            gap_description=data.get("gap_description"),
            gap_queries=data.get("gap_queries", []),
            contradicting_nodes=data.get("contradicting_nodes", []),
            contradiction_description=data.get("contradiction_description"),
            should_create_node=data.get("should_create_node", False),
            should_invalidate=data.get("should_invalidate", []),
            should_boost=data.get("should_boost", []),
            should_demote=data.get("should_demote", []),
            metadata=data.get("metadata", {}),
        )


class ObservationCollector:
    """
    Collects and processes agent observations.

    This is the main interface for agents to report feedback
    to the knowledge base.
    """

    def __init__(self, max_observations: int = 10000):
        self._observations: List[AgentObservation] = []
        self._max_observations = max_observations

        # Indexes for efficient lookup
        self._by_node: Dict[int, List[str]] = {}  # node_id -> observation_ids
        self._by_query: Dict[str, List[str]] = {}  # query_hash -> observation_ids
        self._by_type: Dict[ObservationType, List[str]] = {}

    def record(self, observation: AgentObservation) -> None:
        """Record an observation."""
        self._observations.append(observation)

        # Update indexes
        for node_id in observation.retrieved_nodes:
            if node_id not in self._by_node:
                self._by_node[node_id] = []
            self._by_node[node_id].append(observation.observation_id)

        query_hash = hash(observation.query.lower().strip())
        if query_hash not in self._by_query:
            self._by_query[query_hash] = []
        self._by_query[query_hash].append(observation.observation_id)

        if observation.observation_type not in self._by_type:
            self._by_type[observation.observation_type] = []
        self._by_type[observation.observation_type].append(observation.observation_id)

        # Trim if needed
        if len(self._observations) > self._max_observations:
            self._trim_old_observations()

        logger.info(
            f"Recorded observation: type={observation.observation_type.value} "
            f"success={observation.success_score:.2f} nodes={len(observation.retrieved_nodes)}"
        )

    def _trim_old_observations(self) -> None:
        """Remove oldest observations to stay within limit."""
        # Keep most recent half
        keep_count = self._max_observations // 2
        self._observations = self._observations[-keep_count:]

        # Rebuild indexes
        self._by_node.clear()
        self._by_query.clear()
        self._by_type.clear()

        for obs in self._observations:
            for node_id in obs.retrieved_nodes:
                if node_id not in self._by_node:
                    self._by_node[node_id] = []
                self._by_node[node_id].append(obs.observation_id)

            query_hash = hash(obs.query.lower().strip())
            if query_hash not in self._by_query:
                self._by_query[query_hash] = []
            self._by_query[query_hash].append(obs.observation_id)

            if obs.observation_type not in self._by_type:
                self._by_type[obs.observation_type] = []
            self._by_type[obs.observation_type].append(obs.observation_id)

    # ==================== Observation Factories ====================

    def record_success(
        self,
        query: str,
        retrieved_nodes: List[int],
        success_score: float = 1.0,
        **kwargs,
    ) -> AgentObservation:
        """Record a successful query."""
        obs = AgentObservation(
            observation_type=ObservationType.QUERY_SUCCESS,
            query=query,
            retrieved_nodes=retrieved_nodes,
            success_score=success_score,
            should_boost=retrieved_nodes,  # Boost nodes that worked
            **kwargs,
        )
        self.record(obs)
        return obs

    def record_failure(
        self,
        query: str,
        gap_description: str,
        retrieved_nodes: Optional[List[int]] = None,
        **kwargs,
    ) -> AgentObservation:
        """Record a failed query (knowledge gap)."""
        obs = AgentObservation(
            observation_type=ObservationType.QUERY_FAILURE,
            query=query,
            retrieved_nodes=retrieved_nodes or [],
            success_score=0.0,
            gap_description=gap_description,
            **kwargs,
        )
        self.record(obs)
        return obs

    def record_correction(
        self,
        query: str,
        original_answer: str,
        correction_text: str,
        retrieved_nodes: List[int],
        **kwargs,
    ) -> AgentObservation:
        """Record a user correction."""
        obs = AgentObservation(
            observation_type=ObservationType.CORRECTION,
            query=query,
            retrieved_nodes=retrieved_nodes,
            original_answer=original_answer,
            correction_text=correction_text,
            success_score=0.2,  # Low score since correction was needed
            should_create_node=True,  # Might need to add correct info
            should_demote=retrieved_nodes,  # Demote nodes that were wrong
            **kwargs,
        )
        self.record(obs)
        return obs

    def record_outdated(
        self,
        query: str,
        outdated_nodes: List[int],
        reason: str,
        **kwargs,
    ) -> AgentObservation:
        """Record that some knowledge is outdated."""
        obs = AgentObservation(
            observation_type=ObservationType.OUTDATED,
            query=query,
            retrieved_nodes=outdated_nodes,
            gap_description=reason,
            should_invalidate=outdated_nodes,
            **kwargs,
        )
        self.record(obs)
        return obs

    def record_contradiction(
        self,
        query: str,
        contradicting_nodes: List[int],
        description: str,
        **kwargs,
    ) -> AgentObservation:
        """Record a contradiction between knowledge nodes."""
        obs = AgentObservation(
            observation_type=ObservationType.CONTRADICTION,
            query=query,
            contradicting_nodes=contradicting_nodes,
            contradiction_description=description,
            **kwargs,
        )
        self.record(obs)
        return obs

    def record_runbook_usage(
        self,
        runbook_node_id: int,
        success: bool,
        incident_id: Optional[str] = None,
        **kwargs,
    ) -> AgentObservation:
        """Record runbook usage outcome."""
        obs_type = (
            ObservationType.RUNBOOK_SUCCESS
            if success
            else ObservationType.RUNBOOK_FAILURE
        )
        obs = AgentObservation(
            observation_type=obs_type,
            retrieved_nodes=[runbook_node_id],
            task_id=incident_id,
            success_score=1.0 if success else 0.0,
            should_boost=[runbook_node_id] if success else [],
            should_demote=[runbook_node_id] if not success else [],
            **kwargs,
        )
        self.record(obs)
        return obs

    # ==================== Analysis ====================

    def get_observations_for_node(self, node_id: int) -> List[AgentObservation]:
        """Get all observations involving a specific node."""
        obs_ids = self._by_node.get(node_id, [])
        return [obs for obs in self._observations if obs.observation_id in obs_ids]

    def get_node_success_rate(self, node_id: int) -> float:
        """Calculate success rate for a specific node."""
        observations = self.get_observations_for_node(node_id)
        if not observations:
            return 0.5  # Neutral if no data

        scores = [obs.success_score for obs in observations]
        return sum(scores) / len(scores)

    def get_recent_failures(
        self,
        days: int = 7,
        limit: int = 100,
    ) -> List[AgentObservation]:
        """Get recent query failures."""
        cutoff = datetime.utcnow()
        from datetime import timedelta

        cutoff = cutoff - timedelta(days=days)

        failures = [
            obs
            for obs in self._observations
            if obs.indicates_gap() and obs.timestamp > cutoff
        ]

        # Sort by recency
        failures.sort(key=lambda x: x.timestamp, reverse=True)
        return failures[:limit]

    def get_quality_issues(
        self,
        days: int = 30,
    ) -> List[AgentObservation]:
        """Get recent quality issue observations."""
        cutoff = datetime.utcnow()
        from datetime import timedelta

        cutoff = cutoff - timedelta(days=days)

        return [
            obs
            for obs in self._observations
            if obs.indicates_quality_issue() and obs.timestamp > cutoff
        ]

    def get_nodes_needing_review(self) -> List[int]:
        """Get node IDs that have negative observations."""
        nodes_to_review = set()

        for obs in self._observations:
            nodes_to_review.update(obs.should_invalidate)
            nodes_to_review.update(obs.should_demote)
            nodes_to_review.update(obs.contradicting_nodes)

        return list(nodes_to_review)

    def get_stats(self) -> Dict[str, Any]:
        """Get observation statistics."""
        total = len(self._observations)
        if total == 0:
            return {"total_observations": 0}

        type_counts = {}
        for obs_type, obs_ids in self._by_type.items():
            type_counts[obs_type.value] = len(obs_ids)

        success_scores = [obs.success_score for obs in self._observations]
        avg_success = sum(success_scores) / len(success_scores)

        gaps = [obs for obs in self._observations if obs.indicates_gap()]
        quality_issues = [
            obs for obs in self._observations if obs.indicates_quality_issue()
        ]

        return {
            "total_observations": total,
            "by_type": type_counts,
            "avg_success_score": avg_success,
            "gap_count": len(gaps),
            "quality_issue_count": len(quality_issues),
            "nodes_tracked": len(self._by_node),
            "unique_queries": len(self._by_query),
        }
