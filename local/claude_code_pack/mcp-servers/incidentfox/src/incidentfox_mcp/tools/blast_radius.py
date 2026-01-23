"""Blast Radius Analysis.

Estimate the impact of service failures using service catalog data.
"""

import json
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP


def _load_catalog() -> dict | None:
    """Load the service catalog."""
    # Check current directory and parents
    current = Path.cwd()
    for directory in [current] + list(current.parents):
        for name in [".incidentfox.yaml", "incidentfox.yaml"]:
            catalog_file = directory / name
            if catalog_file.exists():
                try:
                    with open(catalog_file) as f:
                        return yaml.safe_load(f)
                except Exception:
                    pass

    # Check home directory
    home_catalog = Path.home() / ".incidentfox.yaml"
    if home_catalog.exists():
        try:
            with open(home_catalog) as f:
                return yaml.safe_load(f)
        except Exception:
            pass

    return None


def _build_dependency_graph(catalog: dict) -> tuple[dict, dict]:
    """Build dependency and dependent graphs from catalog.

    Returns:
        (dependencies, dependents) where:
        - dependencies[service] = list of services it depends on
        - dependents[service] = list of services that depend on it
    """
    services = catalog.get("services", {})

    dependencies = {}  # service -> what it depends on
    dependents = {}  # service -> what depends on it

    for service_name, config in services.items():
        deps = config.get("dependencies", [])
        dependencies[service_name] = deps

        for dep in deps:
            if dep not in dependents:
                dependents[dep] = []
            dependents[dep].append(service_name)

    return dependencies, dependents


def _get_transitive_dependents(
    service: str,
    dependents: dict,
    visited: set | None = None,
) -> set:
    """Get all services that transitively depend on a service."""
    if visited is None:
        visited = set()

    if service in visited:
        return set()

    visited.add(service)

    result = set()
    direct = dependents.get(service, [])

    for dep in direct:
        result.add(dep)
        result.update(_get_transitive_dependents(dep, dependents, visited))

    return result


def register_tools(mcp: FastMCP):
    """Register blast radius tools."""

    @mcp.tool()
    def get_blast_radius(service: str) -> str:
        """Estimate the blast radius if a service fails.

        Uses the service catalog (.incidentfox.yaml) to determine which
        other services would be affected by a failure.

        Args:
            service: Name of the failing service

        Returns:
            JSON with direct and transitive impact analysis.
        """
        catalog = _load_catalog()

        if not catalog:
            return json.dumps(
                {
                    "error": "No service catalog found",
                    "hint": "Create .incidentfox.yaml with service dependencies",
                    "example": {
                        "services": {
                            "api-gateway": {
                                "dependencies": ["auth-service", "user-service"]
                            },
                            "payment-api": {"dependencies": ["postgres", "redis"]},
                        }
                    },
                }
            )

        services = catalog.get("services", {})

        if (
            service not in services
            and service not in _build_dependency_graph(catalog)[1]
        ):
            available = list(services.keys())
            return json.dumps(
                {
                    "error": f"Service '{service}' not found in catalog",
                    "available_services": available,
                }
            )

        dependencies, dependents = _build_dependency_graph(catalog)

        # Direct dependents (services that directly call this service)
        direct = dependents.get(service, [])

        # Transitive dependents (services indirectly affected)
        all_affected = _get_transitive_dependents(service, dependents)
        transitive = list(all_affected - set(direct))

        # Get service criticality hints
        affected_details = []
        for svc in direct + transitive:
            config = services.get(svc, {})
            affected_details.append(
                {
                    "service": svc,
                    "type": "direct" if svc in direct else "transitive",
                    "has_oncall": "oncall" in config,
                    "namespace": config.get("namespace"),
                }
            )

        # Calculate severity based on number of affected services
        total_affected = len(direct) + len(transitive)
        if total_affected == 0:
            severity = "low"
            severity_reason = "No other services depend on this"
        elif total_affected <= 2:
            severity = "medium"
            severity_reason = f"Affects {total_affected} other service(s)"
        elif total_affected <= 5:
            severity = "high"
            severity_reason = f"Affects {total_affected} services"
        else:
            severity = "critical"
            severity_reason = f"Widespread impact on {total_affected} services"

        return json.dumps(
            {
                "service": service,
                "blast_radius": {
                    "direct_dependents": direct,
                    "direct_count": len(direct),
                    "transitive_dependents": transitive,
                    "transitive_count": len(transitive),
                    "total_affected": total_affected,
                },
                "severity": severity,
                "severity_reason": severity_reason,
                "affected_services": affected_details,
                "recommendations": _get_recommendations(
                    service, direct, transitive, catalog
                ),
            },
            indent=2,
        )

    @mcp.tool()
    def get_service_dependencies(service: str) -> str:
        """Get what a service depends on (upstream dependencies).

        Args:
            service: Service name

        Returns:
            JSON with the service's dependencies.
        """
        catalog = _load_catalog()

        if not catalog:
            return json.dumps(
                {
                    "error": "No service catalog found",
                    "hint": "Create .incidentfox.yaml",
                }
            )

        services = catalog.get("services", {})
        config = services.get(service, {})

        if not config:
            return json.dumps(
                {
                    "error": f"Service '{service}' not found",
                    "available_services": list(services.keys()),
                }
            )

        deps = config.get("dependencies", [])

        # Get details for each dependency
        dep_details = []
        for dep in deps:
            dep_config = services.get(dep, {})
            dep_details.append(
                {
                    "service": dep,
                    "in_catalog": dep in services,
                    "namespace": dep_config.get("namespace") if dep_config else None,
                }
            )

        return json.dumps(
            {
                "service": service,
                "dependency_count": len(deps),
                "dependencies": dep_details,
            },
            indent=2,
        )

    @mcp.tool()
    def get_dependency_graph() -> str:
        """Get the full service dependency graph.

        Returns:
            JSON with all services and their relationships.
        """
        catalog = _load_catalog()

        if not catalog:
            return json.dumps(
                {
                    "error": "No service catalog found",
                }
            )

        dependencies, dependents = _build_dependency_graph(catalog)

        services = catalog.get("services", {})
        graph = []

        for service_name in services:
            graph.append(
                {
                    "service": service_name,
                    "depends_on": dependencies.get(service_name, []),
                    "depended_by": dependents.get(service_name, []),
                }
            )

        # Find critical services (many dependents)
        critical = sorted(
            [(s, len(dependents.get(s, []))) for s in services],
            key=lambda x: x[1],
            reverse=True,
        )[:5]

        return json.dumps(
            {
                "service_count": len(services),
                "graph": graph,
                "most_critical": [
                    {"service": s, "dependent_count": c} for s, c in critical if c > 0
                ],
            },
            indent=2,
        )


def _get_recommendations(
    service: str,
    direct: list,
    transitive: list,
    catalog: dict,
) -> list[str]:
    """Generate recommendations based on blast radius."""
    recommendations = []

    total = len(direct) + len(transitive)

    if total > 5:
        recommendations.append(
            "High blast radius detected. Consider circuit breakers and fallbacks."
        )

    if total > 0:
        recommendations.append(
            f"Notify teams owning: {', '.join(direct[:3])}{'...' if len(direct) > 3 else ''}"
        )

    # Check for runbooks
    services = catalog.get("services", {})
    service_config = services.get(service, {})
    if service_config.get("runbooks"):
        recommendations.append(
            f"Runbooks available for {service}. Consider following documented procedures."
        )

    # Check for dashboards
    if service_config.get("dashboards"):
        recommendations.append(f"Check {service} dashboards for current state.")

    return recommendations
