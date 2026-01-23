"""IncidentFox MCP Server for Claude Code.

A comprehensive SRE investigation toolkit for Claude Code.

Tool Categories:
- Kubernetes (7): Pod/deployment inspection and debugging
- AWS (5): EC2, CloudWatch, ECS
- Datadog (3): Metrics, logs, APM
- Prometheus (4): PromQL queries, alerts
- Unified Logs: Search across all backends
- Anomaly Detection (3): Statistical analysis
- Git (6): Deployment correlation, blame, diff
- Docker (7): Container debugging
- History (8): Investigation tracking
- Postmortem (3): Report generation
- Blast Radius: Impact analysis
- Cost (4): AWS cost analysis
- Remediation (3): Pod restart, scale (with dry-run)

Resources:
- Service catalog (.incidentfox.yaml)
- Runbooks

Total: 50+ tools
"""

from mcp.server.fastmcp import FastMCP

# Resource modules
from .resources import register_all_resources

# Tool modules
from .tools import (
    anomaly,
    aws,
    blast_radius,
    configuration,
    cost,
    datadog,
    docker,
    git,
    history,
    kubernetes,
    postmortem,
    prometheus,
    remediation,
    unified_logs,
)

# Initialize FastMCP server
mcp = FastMCP("incidentfox")

# Register all tool modules
configuration.register_tools(mcp)  # First, so users can check/set config
kubernetes.register_tools(mcp)
aws.register_tools(mcp)
datadog.register_tools(mcp)
anomaly.register_tools(mcp)
git.register_tools(mcp)
remediation.register_tools(mcp)
unified_logs.register_tools(mcp)
prometheus.register_tools(mcp)
history.register_tools(mcp)
docker.register_tools(mcp)
postmortem.register_tools(mcp)
blast_radius.register_tools(mcp)
cost.register_tools(mcp)

# Register resources
register_all_resources(mcp)


def main():
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
