"""MCP Resources for IncidentFox.

Resources provide read-only data that Claude can access during investigations:
- Service catalog (.incidentfox.yaml)
- Runbooks (markdown files)
- Known issues database
"""

from .catalog import register_resources as register_catalog_resources
from .runbooks import register_resources as register_runbook_resources


def register_all_resources(mcp):
    """Register all MCP resources."""
    register_catalog_resources(mcp)
    register_runbook_resources(mcp)
