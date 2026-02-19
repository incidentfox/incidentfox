"""
Service dependency data endpoints.

Exposes stored dependency data discovered by the dependency-service CronJob.
Used by correlation-service for topology-based alert correlation.
"""

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/dependencies", tags=["dependencies"])


# =============================================================================
# Response Models
# =============================================================================


class ServiceDependency(BaseModel):
    """A directed dependency edge: source_service -> target_service"""

    source_service: str
    target_service: str
    call_count: int = 0
    avg_duration_ms: float = 0.0
    error_rate: float = 0.0
    confidence: float = 0.0
    evidence_sources: List[str] = []


class DependencyGraph(BaseModel):
    """Full dependency graph for a team"""

    team_id: str
    services: List[str]
    edges: List[ServiceDependency]
    total_services: int
    total_edges: int


class ServiceNeighbors(BaseModel):
    """Dependencies and dependents of a specific service"""

    service: str
    team_id: str
    dependencies: List[ServiceDependency]  # Services this service calls
    dependents: List[ServiceDependency]  # Services that call this service


# =============================================================================
# Helper: Extract team_id from internal request header
# =============================================================================


def _get_team_id_from_header(
    x_team_id: Optional[str] = Header(None, alias="X-Team-ID"),
) -> str:
    """
    Extract team_id from X-Team-ID header.

    This endpoint is meant for internal service-to-service calls
    (e.g., correlation-service calling config-service).
    """
    if not x_team_id:
        raise HTTPException(
            status_code=400,
            detail="X-Team-ID header required",
        )
    return x_team_id


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/teams/{team_id}/graph", response_model=DependencyGraph)
def get_team_dependency_graph(
    team_id: str,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> DependencyGraph:
    """
    Get the full dependency graph for a team.

    Returns all services and their dependencies discovered by the
    dependency-service CronJob.

    Args:
        team_id: The team ID to get dependencies for
        min_confidence: Minimum confidence threshold (0.0 - 1.0)
    """
    logger.info("get_dependency_graph", team_id=team_id, min_confidence=min_confidence)

    # Query all dependencies for this team
    query = text("""
        SELECT
            source_service,
            target_service,
            call_count,
            avg_duration_ms,
            error_rate,
            confidence,
            evidence_sources
        FROM service_dependencies
        WHERE team_id = :team_id
          AND confidence >= :min_confidence
        ORDER BY confidence DESC, call_count DESC
    """)

    result = db.execute(query, {"team_id": team_id, "min_confidence": min_confidence})
    rows = result.fetchall()

    # Build edges list and collect unique services
    edges = []
    services_set = set()

    for row in rows:
        edges.append(
            ServiceDependency(
                source_service=row.source_service,
                target_service=row.target_service,
                call_count=row.call_count,
                avg_duration_ms=row.avg_duration_ms,
                error_rate=row.error_rate,
                confidence=row.confidence,
                evidence_sources=row.evidence_sources or [],
            )
        )
        services_set.add(row.source_service)
        services_set.add(row.target_service)

    services = sorted(services_set)

    logger.info(
        "dependency_graph_retrieved",
        team_id=team_id,
        services_count=len(services),
        edges_count=len(edges),
    )

    return DependencyGraph(
        team_id=team_id,
        services=services,
        edges=edges,
        total_services=len(services),
        total_edges=len(edges),
    )


@router.get("/teams/{team_id}/services/{service_name}", response_model=ServiceNeighbors)
def get_service_neighbors(
    team_id: str,
    service_name: str,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> ServiceNeighbors:
    """
    Get dependencies and dependents of a specific service.

    Returns both:
    - Dependencies: services that this service calls (outgoing edges)
    - Dependents: services that call this service (incoming edges)

    Args:
        team_id: The team ID
        service_name: The service to get neighbors for
        min_confidence: Minimum confidence threshold
    """
    logger.info(
        "get_service_neighbors",
        team_id=team_id,
        service=service_name,
        min_confidence=min_confidence,
    )

    # Get dependencies (services this service calls)
    deps_query = text("""
        SELECT
            source_service,
            target_service,
            call_count,
            avg_duration_ms,
            error_rate,
            confidence,
            evidence_sources
        FROM service_dependencies
        WHERE team_id = :team_id
          AND source_service = :service_name
          AND confidence >= :min_confidence
        ORDER BY call_count DESC
    """)

    deps_result = db.execute(
        deps_query,
        {
            "team_id": team_id,
            "service_name": service_name,
            "min_confidence": min_confidence,
        },
    )

    dependencies = [
        ServiceDependency(
            source_service=row.source_service,
            target_service=row.target_service,
            call_count=row.call_count,
            avg_duration_ms=row.avg_duration_ms,
            error_rate=row.error_rate,
            confidence=row.confidence,
            evidence_sources=row.evidence_sources or [],
        )
        for row in deps_result.fetchall()
    ]

    # Get dependents (services that call this service)
    dependents_query = text("""
        SELECT
            source_service,
            target_service,
            call_count,
            avg_duration_ms,
            error_rate,
            confidence,
            evidence_sources
        FROM service_dependencies
        WHERE team_id = :team_id
          AND target_service = :service_name
          AND confidence >= :min_confidence
        ORDER BY call_count DESC
    """)

    dependents_result = db.execute(
        dependents_query,
        {
            "team_id": team_id,
            "service_name": service_name,
            "min_confidence": min_confidence,
        },
    )

    dependents = [
        ServiceDependency(
            source_service=row.source_service,
            target_service=row.target_service,
            call_count=row.call_count,
            avg_duration_ms=row.avg_duration_ms,
            error_rate=row.error_rate,
            confidence=row.confidence,
            evidence_sources=row.evidence_sources or [],
        )
        for row in dependents_result.fetchall()
    ]

    logger.info(
        "service_neighbors_retrieved",
        team_id=team_id,
        service=service_name,
        dependencies_count=len(dependencies),
        dependents_count=len(dependents),
    )

    return ServiceNeighbors(
        service=service_name,
        team_id=team_id,
        dependencies=dependencies,
        dependents=dependents,
    )


@router.get("/teams/{team_id}/related-services", response_model=List[str])
def get_related_services(
    team_id: str,
    service_name: str = Query(..., description="Service to find related services for"),
    max_depth: int = Query(2, ge=1, le=5, description="Max traversal depth"),
    min_confidence: float = Query(0.5, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> List[str]:
    """
    Get services related to a given service within N hops.

    Useful for correlation: find all services that could be affected
    by or affecting a given service.

    Args:
        team_id: The team ID
        service_name: Starting service
        max_depth: Maximum traversal depth (1-5)
        min_confidence: Minimum confidence threshold
    """
    logger.info(
        "get_related_services",
        team_id=team_id,
        service=service_name,
        max_depth=max_depth,
    )

    # BFS to find related services
    visited = {service_name}
    frontier = {service_name}

    for _ in range(max_depth):
        if not frontier:
            break

        # Find neighbors of current frontier
        neighbors_query = text("""
            SELECT DISTINCT
                CASE
                    WHEN source_service = ANY(:frontier) THEN target_service
                    ELSE source_service
                END as neighbor
            FROM service_dependencies
            WHERE team_id = :team_id
              AND confidence >= :min_confidence
              AND (source_service = ANY(:frontier) OR target_service = ANY(:frontier))
        """)

        result = db.execute(
            neighbors_query,
            {
                "team_id": team_id,
                "frontier": list(frontier),
                "min_confidence": min_confidence,
            },
        )

        new_neighbors = {row.neighbor for row in result.fetchall()}
        frontier = new_neighbors - visited
        visited.update(frontier)

    # Remove the starting service from results
    related = sorted(visited - {service_name})

    logger.info(
        "related_services_found",
        team_id=team_id,
        service=service_name,
        related_count=len(related),
    )

    return related
