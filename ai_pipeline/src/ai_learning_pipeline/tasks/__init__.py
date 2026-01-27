"""
Pipeline tasks for the Self-Learning System.

- ingestion: Knowledge ingestion from external sources
- teaching: Processing of agent-taught knowledge
- maintenance: Tree health, decay, and gap detection
"""

from .ingestion import KnowledgeIngestionTask
from .teaching import TeachingProcessorTask
from .maintenance import MaintenanceTask

__all__ = ["KnowledgeIngestionTask", "TeachingProcessorTask", "MaintenanceTask"]
