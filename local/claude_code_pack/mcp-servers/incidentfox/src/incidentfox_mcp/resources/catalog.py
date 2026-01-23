"""Service Catalog Resource.

Loads .incidentfox.yaml from the current directory or user's home to provide
context about the user's infrastructure during investigations.
"""

import os
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP


def _find_catalog_file() -> Path | None:
    """Find .incidentfox.yaml in current directory or parent directories."""
    # Check current directory and parents
    current = Path.cwd()
    for directory in [current] + list(current.parents):
        catalog_file = directory / ".incidentfox.yaml"
        if catalog_file.exists():
            return catalog_file
        # Also check without dot prefix
        catalog_file = directory / "incidentfox.yaml"
        if catalog_file.exists():
            return catalog_file

    # Check home directory
    home_catalog = Path.home() / ".incidentfox.yaml"
    if home_catalog.exists():
        return home_catalog

    return None


def _load_catalog() -> dict | None:
    """Load the service catalog."""
    catalog_file = _find_catalog_file()
    if not catalog_file:
        return None

    try:
        with open(catalog_file) as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def register_resources(mcp: FastMCP):
    """Register service catalog as an MCP resource."""

    @mcp.resource("incidentfox://catalog")
    def get_service_catalog() -> str:
        """Service catalog describing the user's infrastructure.

        Contains:
        - Services and their Kubernetes deployments
        - Dependencies between services
        - Log locations (Datadog, CloudWatch, etc.)
        - Dashboard URLs
        - Runbook references
        - On-call information
        - Known issues and their solutions
        """
        catalog = _load_catalog()

        if not catalog:
            return """# No Service Catalog Found

Create a `.incidentfox.yaml` file in your project root to personalize investigations.

Example:
```yaml
services:
  payment-api:
    namespace: production
    deployments: [payment-api, payment-worker]
    dependencies: [postgres, redis, stripe-api]
    logs:
      datadog: "service:payment-api"
      cloudwatch: "/aws/eks/payment-api"
    dashboards:
      grafana: "https://grafana.example.com/d/abc123"
    runbooks:
      high-latency: "./runbooks/payment-latency.md"
    oncall:
      slack: "#payment-oncall"

alerts:
  payment-high-latency:
    service: payment-api
    severity: P2
    runbook: high-latency

known_issues:
  - pattern: "ConnectionResetError.*redis"
    cause: "Redis connection pool exhaustion"
    solution: "Scale redis replicas or increase pool size"
    services: [payment-api, cart-service]
```
"""

        # Format catalog as readable text
        output = ["# Service Catalog", ""]

        # Services section
        if "services" in catalog:
            output.append("## Services")
            output.append("")
            for name, config in catalog.get("services", {}).items():
                output.append(f"### {name}")
                if "namespace" in config:
                    output.append(f"- Namespace: {config['namespace']}")
                if "deployments" in config:
                    output.append(f"- Deployments: {', '.join(config['deployments'])}")
                if "dependencies" in config:
                    output.append(
                        f"- Dependencies: {', '.join(config['dependencies'])}"
                    )
                if "logs" in config:
                    output.append("- Logs:")
                    for backend, query in config["logs"].items():
                        output.append(f"  - {backend}: `{query}`")
                if "dashboards" in config:
                    output.append("- Dashboards:")
                    for name, url in config["dashboards"].items():
                        output.append(f"  - {name}: {url}")
                if "runbooks" in config:
                    output.append("- Runbooks:")
                    for issue, path in config["runbooks"].items():
                        output.append(f"  - {issue}: {path}")
                if "oncall" in config:
                    output.append("- On-call:")
                    for channel, value in config["oncall"].items():
                        output.append(f"  - {channel}: {value}")
                output.append("")

        # Alerts section
        if "alerts" in catalog:
            output.append("## Alerts")
            output.append("")
            for name, config in catalog.get("alerts", {}).items():
                output.append(f"### {name}")
                if "service" in config:
                    output.append(f"- Service: {config['service']}")
                if "severity" in config:
                    output.append(f"- Severity: {config['severity']}")
                if "runbook" in config:
                    output.append(f"- Runbook: {config['runbook']}")
                output.append("")

        # Known issues section
        if "known_issues" in catalog:
            output.append("## Known Issues")
            output.append("")
            for issue in catalog.get("known_issues", []):
                output.append(f"### Pattern: `{issue.get('pattern', 'N/A')}`")
                output.append(f"- Cause: {issue.get('cause', 'Unknown')}")
                output.append(f"- Solution: {issue.get('solution', 'N/A')}")
                if "services" in issue:
                    output.append(
                        f"- Affected services: {', '.join(issue['services'])}"
                    )
                output.append("")

        return "\n".join(output)

    # Also expose catalog as a tool for querying specific services
    @mcp.tool()
    def get_service_info(service_name: str) -> str:
        """Get detailed information about a specific service from the catalog.

        Args:
            service_name: Name of the service to look up

        Returns:
            JSON with service configuration including deployments,
            dependencies, log locations, dashboards, and runbooks.
        """
        import json

        catalog = _load_catalog()
        if not catalog:
            return json.dumps(
                {
                    "error": "No .incidentfox.yaml found",
                    "hint": "Create a service catalog file to personalize investigations",
                }
            )

        services = catalog.get("services", {})
        if service_name not in services:
            available = list(services.keys())
            return json.dumps(
                {
                    "error": f"Service '{service_name}' not found in catalog",
                    "available_services": available,
                }
            )

        service = services[service_name]

        # Find related alerts
        related_alerts = [
            {"name": name, **config}
            for name, config in catalog.get("alerts", {}).items()
            if config.get("service") == service_name
        ]

        # Find related known issues
        related_issues = [
            issue
            for issue in catalog.get("known_issues", [])
            if service_name in issue.get("services", [])
        ]

        return json.dumps(
            {
                "service": service_name,
                "config": service,
                "related_alerts": related_alerts,
                "known_issues": related_issues,
            },
            indent=2,
        )

    @mcp.tool()
    def check_known_issues(error_message: str) -> str:
        """Check if an error matches any known issues in the catalog.

        Args:
            error_message: The error message or pattern to check

        Returns:
            JSON with matching known issues and their solutions.
        """
        import json
        import re

        catalog = _load_catalog()
        if not catalog:
            return json.dumps(
                {
                    "matches": [],
                    "hint": "No .incidentfox.yaml found - create one to track known issues",
                }
            )

        matches = []
        for issue in catalog.get("known_issues", []):
            pattern = issue.get("pattern", "")
            try:
                if re.search(pattern, error_message, re.IGNORECASE):
                    matches.append(
                        {
                            "pattern": pattern,
                            "cause": issue.get("cause"),
                            "solution": issue.get("solution"),
                            "affected_services": issue.get("services", []),
                        }
                    )
            except re.error:
                # Invalid regex, try simple substring match
                if pattern.lower() in error_message.lower():
                    matches.append(
                        {
                            "pattern": pattern,
                            "cause": issue.get("cause"),
                            "solution": issue.get("solution"),
                            "affected_services": issue.get("services", []),
                        }
                    )

        return json.dumps(
            {
                "query": error_message[:200],  # Truncate for readability
                "matches": matches,
                "match_count": len(matches),
            },
            indent=2,
        )
