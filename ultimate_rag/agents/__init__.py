"""
Agentic Integration Module

Provides the learning loop between AI agents and the knowledge base:
- Observation collection (feedback from agent work)
- Teaching interface (agents teach KB new knowledge)
- Maintenance agent (proactive KB upkeep)
"""

from .maintenance import (
    Contradiction,
    KnowledgeGap,
    MaintenanceAgent,
    MaintenanceTask,
)
from .observations import (
    AgentObservation,
    ObservationCollector,
    ObservationType,
)
from .teaching import (
    TeachingInterface,
    TeachResult,
)

__all__ = [
    # Observations
    "ObservationType",
    "AgentObservation",
    "ObservationCollector",
    # Teaching
    "TeachResult",
    "TeachingInterface",
    # Maintenance
    "KnowledgeGap",
    "Contradiction",
    "MaintenanceTask",
    "MaintenanceAgent",
]
