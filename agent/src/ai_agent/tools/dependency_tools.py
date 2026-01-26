"""
Dependency Graph tools for service dependency analysis.

These tools allow agents to query the discovered service dependency
graph to understand:
- What services a given service depends on (calls)
- What services depend on a given service (call it)
- Blast radius analysis for impact assessment
- Overall service topology
"""

from __future__ import annotations

import json
import os

from agents import function_tool

from ..core.logging import get_logger

logger = get_logger(__name__)


def _get_db_session():
    """
    Get database session for dependency queries.

    Uses the same database as the dependency service.
    """
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
    except ImportError:
        raise RuntimeError("sqlalchemy not installed")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        # Build from components
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        database = os.getenv("DB_NAME", "incidentfox")
        user = os.getenv("DB_USER", "postgres")
        password = os.getenv("DB_PASSWORD", "")
        database_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    # Determine SSL mode
    sslmode = os.getenv("DB_SSLMODE", "")
    if not sslmode:
        if "localhost" in database_url or "127.0.0.1" in database_url:
            sslmode = "prefer"
        else:
            sslmode = "require"

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"sslmode": sslmode} if "postgresql" in database_url else {},
    )

    Session = sessionmaker(bind=engine)
    return Session()


def _get_team_id() -> str:
    """Get current team ID from environment or context."""
    return os.getenv("TEAM_ID", os.getenv("INCIDENTFOX_TEAM_ID", "default"))


@function_tool
def get_service_dependencies(service: str, min_confidence: float = 0.5) -> str:
    """
    Get all services that this service depends on (calls).

    Returns outgoing dependencies - the services that the specified service
    makes calls to. Use this to understand what external services this
    service relies on.

    If any of these dependencies fail, this service may be impacted.

    Example use cases:
    - "What does cart-service depend on?"
    - "Show me the dependencies of the failing service"
    - "What databases does this service connect to?"

    Args:
        service: Name of the service to query
        min_confidence: Minimum confidence threshold (0.0 to 1.0, default: 0.5)

    Returns:
        JSON with list of dependencies including call counts and confidence scores
    """
    try:
        session = _get_db_session()
        team_id = _get_team_id()

        # Import here to avoid circular imports

        # Query directly to avoid dependency on dependency_service package
        result = session.execute(
            """
            SELECT target_service, call_count, avg_duration_ms, error_rate,
                   confidence, evidence_sources
            FROM service_dependencies
            WHERE team_id = :team_id
              AND source_service = :service
              AND confidence >= :min_confidence
            ORDER BY call_count DESC
            """,
            {"team_id": team_id, "service": service, "min_confidence": min_confidence},
        )

        dependencies = []
        for row in result:
            dependencies.append(
                {
                    "target": row.target_service,
                    "calls": row.call_count,
                    "avg_duration_ms": round(row.avg_duration_ms, 2),
                    "error_rate": round(row.error_rate, 4),
                    "confidence": round(row.confidence, 2),
                    "sources": row.evidence_sources or [],
                }
            )

        session.close()

        logger.info(
            "get_service_dependencies",
            service=service,
            dependencies_found=len(dependencies),
        )

        return json.dumps(
            {
                "ok": True,
                "service": service,
                "dependency_count": len(dependencies),
                "dependencies": dependencies,
                "interpretation": (
                    f"{service} calls {len(dependencies)} other service(s)"
                    if dependencies
                    else f"No outgoing dependencies found for {service}"
                ),
            }
        )

    except Exception as e:
        logger.error("get_service_dependencies_failed", service=service, error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "service": service,
            }
        )


@function_tool
def get_service_dependents(service: str, min_confidence: float = 0.5) -> str:
    """
    Get all services that depend on this service (call it).

    Returns incoming dependencies - the services that make calls to the
    specified service. Use this for impact analysis.

    If this service fails, all these dependent services may be impacted.

    Example use cases:
    - "What services depend on product-catalog?"
    - "What's the blast radius if this service goes down?"
    - "Who will be affected if we restart this service?"

    Args:
        service: Name of the service to query
        min_confidence: Minimum confidence threshold (0.0 to 1.0, default: 0.5)

    Returns:
        JSON with list of dependent services including call counts and confidence
    """
    try:
        session = _get_db_session()
        team_id = _get_team_id()

        result = session.execute(
            """
            SELECT source_service, call_count, avg_duration_ms, error_rate,
                   confidence, evidence_sources
            FROM service_dependencies
            WHERE team_id = :team_id
              AND target_service = :service
              AND confidence >= :min_confidence
            ORDER BY call_count DESC
            """,
            {"team_id": team_id, "service": service, "min_confidence": min_confidence},
        )

        dependents = []
        for row in result:
            dependents.append(
                {
                    "caller": row.source_service,
                    "calls": row.call_count,
                    "avg_duration_ms": round(row.avg_duration_ms, 2),
                    "error_rate": round(row.error_rate, 4),
                    "confidence": round(row.confidence, 2),
                    "sources": row.evidence_sources or [],
                }
            )

        session.close()

        logger.info(
            "get_service_dependents",
            service=service,
            dependents_found=len(dependents),
        )

        return json.dumps(
            {
                "ok": True,
                "service": service,
                "dependent_count": len(dependents),
                "dependents": dependents,
                "interpretation": (
                    f"{len(dependents)} service(s) depend on {service}"
                    if dependents
                    else f"No services found that depend on {service}"
                ),
            }
        )

    except Exception as e:
        logger.error("get_service_dependents_failed", service=service, error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "service": service,
            }
        )


@function_tool
def get_blast_radius(service: str, min_confidence: float = 0.5) -> str:
    """
    Calculate the blast radius if a service fails.

    Returns impact analysis showing how many services would be affected
    if the specified service experiences an outage.

    Includes:
    - Direct dependents (services that directly call this service)
    - Total call volume (how much traffic would be affected)
    - Highest-traffic callers (most impacted services)

    Example use cases:
    - "What's the impact if product-catalog goes down?"
    - "How critical is this service?"
    - "Should we prioritize fixing this service?"

    Args:
        service: Name of the service to analyze
        min_confidence: Minimum confidence threshold (default: 0.5)

    Returns:
        JSON with blast radius analysis including affected services and impact
    """
    try:
        session = _get_db_session()
        team_id = _get_team_id()

        # Get all dependents
        result = session.execute(
            """
            SELECT source_service, call_count, confidence
            FROM service_dependencies
            WHERE team_id = :team_id
              AND target_service = :service
              AND confidence >= :min_confidence
            ORDER BY call_count DESC
            """,
            {"team_id": team_id, "service": service, "min_confidence": min_confidence},
        )

        dependents = []
        total_calls = 0
        for row in result:
            dependents.append(
                {
                    "service": row.source_service,
                    "calls": row.call_count,
                    "confidence": round(row.confidence, 2),
                }
            )
            total_calls += row.call_count

        session.close()

        # Determine severity based on dependent count
        severity = "low"
        if len(dependents) >= 5:
            severity = "high"
        elif len(dependents) >= 2:
            severity = "medium"

        logger.info(
            "get_blast_radius",
            service=service,
            blast_radius=len(dependents),
            severity=severity,
        )

        return json.dumps(
            {
                "ok": True,
                "service": service,
                "blast_radius": len(dependents),
                "severity": severity,
                "total_calls_affected": total_calls,
                "affected_services": [d["service"] for d in dependents],
                "top_callers": dependents[:5],  # Top 5 by call volume
                "interpretation": (
                    (
                        f"If {service} fails, {len(dependents)} service(s) would be affected, "
                        f"impacting approximately {total_calls:,} calls. Severity: {severity.upper()}."
                    )
                    if dependents
                    else f"{service} has no known dependents - failure would have minimal blast radius."
                ),
            }
        )

    except Exception as e:
        logger.error("get_blast_radius_failed", service=service, error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "service": service,
            }
        )


@function_tool
def get_dependency_graph_stats() -> str:
    """
    Get overall statistics about the service dependency graph.

    Returns high-level metrics about the team's service topology:
    - Total number of services
    - Total number of dependencies
    - Average confidence across all dependencies
    - Most connected services (hubs)

    Use this to understand the overall service architecture.

    Returns:
        JSON with graph statistics and top services
    """
    try:
        session = _get_db_session()
        team_id = _get_team_id()

        # Get overall stats
        stats_result = session.execute(
            """
            SELECT
                COUNT(*) as dependency_count,
                AVG(confidence) as avg_confidence,
                SUM(call_count) as total_calls
            FROM service_dependencies
            WHERE team_id = :team_id
            """,
            {"team_id": team_id},
        ).fetchone()

        # Get unique services
        services_result = session.execute(
            """
            SELECT DISTINCT source_service FROM service_dependencies WHERE team_id = :team_id
            UNION
            SELECT DISTINCT target_service FROM service_dependencies WHERE team_id = :team_id
            """,
            {"team_id": team_id},
        )
        services = [row[0] for row in services_result]

        # Get most connected services (by total edges)
        hubs_result = session.execute(
            """
            WITH edge_counts AS (
                SELECT source_service as service, COUNT(*) as edges
                FROM service_dependencies WHERE team_id = :team_id
                GROUP BY source_service
                UNION ALL
                SELECT target_service as service, COUNT(*) as edges
                FROM service_dependencies WHERE team_id = :team_id
                GROUP BY target_service
            )
            SELECT service, SUM(edges) as total_edges
            FROM edge_counts
            GROUP BY service
            ORDER BY total_edges DESC
            LIMIT 5
            """,
            {"team_id": team_id},
        )
        hubs = [{"service": row[0], "connections": row[1]} for row in hubs_result]

        session.close()

        logger.info(
            "get_dependency_graph_stats",
            services=len(services),
            dependencies=stats_result.dependency_count or 0,
        )

        return json.dumps(
            {
                "ok": True,
                "service_count": len(services),
                "dependency_count": stats_result.dependency_count or 0,
                "avg_confidence": round(stats_result.avg_confidence or 0, 2),
                "total_calls": stats_result.total_calls or 0,
                "top_connected_services": hubs,
                "all_services": sorted(services),
            }
        )

    except Exception as e:
        logger.error("get_dependency_graph_stats_failed", error=str(e))
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
            }
        )


# Export all tools for registration
DEPENDENCY_TOOLS = [
    get_service_dependencies,
    get_service_dependents,
    get_blast_radius,
    get_dependency_graph_stats,
]
