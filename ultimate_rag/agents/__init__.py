"""
Agentic Integration Module

Provides the learning loop between AI agents and the knowledge base:
- Observation collection (feedback from agent work)
- Teaching interface (agents teach KB new knowledge)
- Maintenance agent (proactive KB upkeep)
"""

from .observations import (
    ObservationType,
    AgentObservation,
    ObservationCollector,
)
from .teaching import (
    TeachResult,
    TeachingInterface,
)
from .maintenance import (
    KnowledgeGap,
    Contradiction,
    MaintenanceTask,
    MaintenanceAgent,
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
