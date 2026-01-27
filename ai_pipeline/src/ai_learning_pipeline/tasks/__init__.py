"""
Pipeline tasks for the Self-Learning System.

- ingestion: Knowledge ingestion from external sources
- teaching: Processing of agent-taught knowledge
- maintenance: Tree health, decay, and gap detection
"""

from .ingestion import KnowledgeIngestionTask
from .maintenance import MaintenanceTask
from .teaching import TeachingProcessorTask

__all__ = ["KnowledgeIngestionTask", "TeachingProcessorTask", "MaintenanceTask"]
