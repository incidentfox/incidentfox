"""
API Module for Ultimate RAG.

Provides FastAPI server for:
- Knowledge retrieval
- Document ingestion
- Graph queries
- Agentic teaching/learning
- Admin and maintenance
"""

from .server import create_app, UltimateRAGServer

__all__ = [
    "create_app",
    "UltimateRAGServer",
]
