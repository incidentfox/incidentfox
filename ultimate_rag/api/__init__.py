"""
API Module for Ultimate RAG.

Provides FastAPI server for:
- Knowledge retrieval
- Document ingestion
- Graph queries
- Agentic teaching/learning
- Admin and maintenance
"""

from .server import UltimateRAGServer, create_app

__all__ = [
    "create_app",
    "UltimateRAGServer",
]
