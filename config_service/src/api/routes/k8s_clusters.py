"""K8s cluster management API routes for SaaS model."""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.security import get_token_pepper
from ...db.models import K8sClusterStatus
from ...db.repository import (
    get_k8s_cluster,
    issue_k8s_agent_token,
    list_k8s_clusters,
    revoke_k8s_cluster,
    update_k8s_cluster_status,
)
from ...db.session import get_db
from ..auth import (
    AdminPrincipal,
    TeamPrincipal,
    authenticate_admin_request,
    require_team_auth,
)

logger = structlog.get_logger(__name__)


def require_admin(
    principal: AdminPrincipal = Depends(authenticate_admin_request),
) -> AdminPrincipal:
    return principal


def check_org_access(principal: AdminPrincipal, org_id: str) -> None:
    """Verify that the principal has access to the specified org."""
    if principal.org_id is not None and principal.org_id != org_id:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: you can only access org '{principal.org_id}'",
        )


router = APIRouter(prefix="/api/v1/team/k8s-clusters", tags=["k8s-clusters"])


# =============================================================================
# Request/Response Models
# =============================================================================


class CreateK8sClusterRequest(BaseModel):
    """Request to register a new K8s cluster."""

    cluster_name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Unique name for this cluster (e.g., 'prod-us-east-1')",
    )
    display_name: Optional[str] = Field(
        None,
        max_length=256,
        description="Human-friendly display name",
    )


class K8sClusterCreatedResponse(BaseModel):
    """Response after creating a K8s cluster.

    IMPORTANT: The token is only returned once and cannot be retrieved again.
    """

    cluster_id: str
    cluster_name: str
    display_name: Optional[str]
    token: str = Field(
        ...,
        description="API token for the K8s agent. Store securely - shown only once!",
    )
    helm_install_command: str = Field(
        ...,
        description="Ready-to-use Helm install command",
    )


class K8sClusterSummary(BaseModel):
    """Summary information about a K8s cluster."""

    cluster_id: str
    cluster_name: str
    display_name: Optional[str]
    status: str  # connected, disconnected, error
    last_heartbeat_at: Optional[str]
    kubernetes_version: Optional[str]
    node_count: Optional[int]
    agent_version: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class K8sClusterDetail(K8sClusterSummary):
    """Detailed information about a K8s cluster."""

    namespace_count: Optional[int]
    agent_pod_name: Optional[str]
    last_error: Optional[str]
    cluster_info: Optional[Dict[str, Any]]
    updated_at: str


class K8sClusterStatusUpdate(BaseModel):
    """Request to update cluster status (used by gateway)."""

    status: str = Field(..., description="connected, disconnected, or error")
    agent_version: Optional[str] = None
    agent_pod_name: Optional[str] = None
    kubernetes_version: Optional[str] = None
    node_count: Optional[int] = None
    namespace_count: Optional[int] = None
    cluster_info: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("", response_model=K8sClusterCreatedResponse, status_code=201)
async def create_k8s_cluster(
    body: CreateK8sClusterRequest,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Register a new K8s cluster and generate an API key.

    This creates a cluster registration and returns a one-time API token.
    The token should be used to configure the K8s agent deployed in the cluster.

    **IMPORTANT**: The token is only shown once. Store it securely.

    Returns a ready-to-use Helm install command.
    """
    pepper = get_token_pepper()

    # Check for duplicate cluster name
    existing_clusters = list_k8s_clusters(
        db,
        org_id=team.org_id,
        team_node_id=team.team_node_id,
    )
    for cluster in existing_clusters:
        if cluster.cluster_name == body.cluster_name:
            raise HTTPException(
                status_code=409,
                detail=f"Cluster with name '{body.cluster_name}' already exists",
            )

    # Issue token and create cluster
    result = issue_k8s_agent_token(
        db,
        org_id=team.org_id,
        team_node_id=team.team_node_id,
        cluster_name=body.cluster_name,
        display_name=body.display_name,
        issued_by=team.subject,
        pepper=pepper,
    )

    db.commit()

    logger.info(
        "k8s_cluster_created",
        cluster_id=result.cluster_id,
        cluster_name=result.cluster_name,
        org_id=team.org_id,
        team_node_id=team.team_node_id,
    )

    # Generate Helm install command
    gateway_url = "https://orchestrator.incidentfox.ai/gateway"
    helm_command = (
        f"helm repo add incidentfox https://charts.incidentfox.io && "
        f"helm install incidentfox-agent incidentfox/k8s-agent "
        f"--set apiKey={result.token} "
        f"--set clusterName={body.cluster_name} "
        f"--set gatewayUrl={gateway_url} "
        f"--namespace incidentfox --create-namespace"
    )

    return K8sClusterCreatedResponse(
        cluster_id=result.cluster_id,
        cluster_name=result.cluster_name,
        display_name=body.display_name,
        token=result.token,
        helm_install_command=helm_command,
    )


@router.get("", response_model=List[K8sClusterSummary])
async def list_clusters(
    include_revoked: bool = False,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    List all K8s clusters for the team.

    By default, only active (non-revoked) clusters are returned.
    """
    clusters = list_k8s_clusters(
        db,
        org_id=team.org_id,
        team_node_id=team.team_node_id,
        include_revoked=include_revoked,
    )

    return [
        K8sClusterSummary(
            cluster_id=c.id,
            cluster_name=c.cluster_name,
            display_name=c.display_name,
            status=(
                c.status.value if isinstance(c.status, K8sClusterStatus) else c.status
            ),
            last_heartbeat_at=(
                c.last_heartbeat_at.isoformat() if c.last_heartbeat_at else None
            ),
            kubernetes_version=c.kubernetes_version,
            node_count=c.node_count,
            agent_version=c.agent_version,
            created_at=c.created_at.isoformat(),
        )
        for c in clusters
    ]


@router.get("/{cluster_id}", response_model=K8sClusterDetail)
async def get_cluster_detail(
    cluster_id: str,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Get detailed information about a specific K8s cluster.
    """
    cluster = get_k8s_cluster(db, cluster_id=cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    # Verify ownership
    if cluster.org_id != team.org_id or cluster.team_node_id != team.team_node_id:
        raise HTTPException(status_code=404, detail="Cluster not found")

    return K8sClusterDetail(
        cluster_id=cluster.id,
        cluster_name=cluster.cluster_name,
        display_name=cluster.display_name,
        status=(
            cluster.status.value
            if isinstance(cluster.status, K8sClusterStatus)
            else cluster.status
        ),
        last_heartbeat_at=(
            cluster.last_heartbeat_at.isoformat() if cluster.last_heartbeat_at else None
        ),
        kubernetes_version=cluster.kubernetes_version,
        node_count=cluster.node_count,
        namespace_count=cluster.namespace_count,
        agent_version=cluster.agent_version,
        agent_pod_name=cluster.agent_pod_name,
        last_error=cluster.last_error,
        cluster_info=cluster.cluster_info,
        created_at=cluster.created_at.isoformat(),
        updated_at=cluster.updated_at.isoformat(),
    )


@router.delete("/{cluster_id}", status_code=204)
async def delete_cluster(
    cluster_id: str,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """
    Revoke a K8s cluster's access.

    This revokes the cluster's API token, causing the agent to be disconnected.
    The cluster record is kept for audit purposes.
    """
    cluster = get_k8s_cluster(db, cluster_id=cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    # Verify ownership
    if cluster.org_id != team.org_id or cluster.team_node_id != team.team_node_id:
        raise HTTPException(status_code=404, detail="Cluster not found")

    success = revoke_k8s_cluster(
        db,
        cluster_id=cluster_id,
        revoked_by=team.subject,
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to revoke cluster")

    db.commit()

    logger.info(
        "k8s_cluster_revoked",
        cluster_id=cluster_id,
        cluster_name=cluster.cluster_name,
        org_id=team.org_id,
        team_node_id=team.team_node_id,
        revoked_by=team.subject,
    )

    return None


# =============================================================================
# Internal API (for gateway service)
# =============================================================================

internal_router = APIRouter(prefix="/api/v1/internal/k8s-clusters", tags=["internal"])


@internal_router.put("/{cluster_id}/status")
async def update_cluster_status_internal(
    cluster_id: str,
    body: K8sClusterStatusUpdate,
    db: Session = Depends(get_db),
    # TODO: Add internal service authentication
):
    """
    Update cluster connection status.

    This endpoint is called by the K8s Gateway service when:
    - Agent connects (status=connected)
    - Agent sends heartbeat
    - Agent disconnects (status=disconnected)
    - Agent encounters error (status=error)

    Internal API - not exposed to external clients.
    """
    # Parse status
    try:
        status = K8sClusterStatus(body.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {body.status}. Must be one of: connected, disconnected, error",
        )

    cluster = update_k8s_cluster_status(
        db,
        cluster_id=cluster_id,
        status=status,
        agent_version=body.agent_version,
        agent_pod_name=body.agent_pod_name,
        kubernetes_version=body.kubernetes_version,
        node_count=body.node_count,
        namespace_count=body.namespace_count,
        cluster_info=body.cluster_info,
        last_error=body.last_error,
    )

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    db.commit()

    return {"ok": True, "cluster_id": cluster_id, "status": body.status}


@internal_router.get("/by-token/{token_id}")
async def get_cluster_by_token_internal(
    token_id: str,
    db: Session = Depends(get_db),
    # TODO: Add internal service authentication
):
    """
    Get cluster by token ID.

    Used by gateway to look up cluster info after validating a token.

    Internal API - not exposed to external clients.
    """
    from ...db.repository import get_k8s_cluster_by_token

    cluster = get_k8s_cluster_by_token(db, token_id=token_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    return {
        "cluster_id": cluster.id,
        "cluster_name": cluster.cluster_name,
        "org_id": cluster.org_id,
        "team_node_id": cluster.team_node_id,
        "status": (
            cluster.status.value
            if isinstance(cluster.status, K8sClusterStatus)
            else cluster.status
        ),
    }


# =============================================================================
# Admin API (for slack-bot and admin dashboard)
# =============================================================================

admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@admin_router.post(
    "/orgs/{org_id}/teams/{team_node_id}/k8s-clusters",
    response_model=K8sClusterCreatedResponse,
    status_code=201,
)
async def admin_create_k8s_cluster(
    org_id: str,
    team_node_id: str,
    body: CreateK8sClusterRequest,
    db: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
):
    """
    Register a new K8s cluster and generate an API key (admin endpoint).

    Used by slack-bot to create clusters on behalf of users.
    """
    check_org_access(principal, org_id)
    pepper = get_token_pepper()

    # Check for duplicate cluster name
    existing_clusters = list_k8s_clusters(
        db,
        org_id=org_id,
        team_node_id=team_node_id,
    )
    for cluster in existing_clusters:
        if cluster.cluster_name == body.cluster_name:
            raise HTTPException(
                status_code=409,
                detail=f"Cluster with name '{body.cluster_name}' already exists",
            )

    # Issue token and create cluster
    result = issue_k8s_agent_token(
        db,
        org_id=org_id,
        team_node_id=team_node_id,
        cluster_name=body.cluster_name,
        display_name=body.display_name,
        issued_by=principal.subject or "admin",
        pepper=pepper,
    )

    db.commit()

    logger.info(
        "k8s_cluster_created_admin",
        cluster_id=result.cluster_id,
        cluster_name=result.cluster_name,
        org_id=org_id,
        team_node_id=team_node_id,
        admin=principal.subject,
    )

    # Generate Helm install command
    gateway_url = "https://orchestrator.incidentfox.ai/gateway"
    helm_command = (
        f"helm repo add incidentfox https://charts.incidentfox.io && "
        f"helm install incidentfox-agent incidentfox/k8s-agent "
        f"--set apiKey={result.token} "
        f"--set clusterName={body.cluster_name} "
        f"--set gatewayUrl={gateway_url} "
        f"--namespace incidentfox --create-namespace"
    )

    return K8sClusterCreatedResponse(
        cluster_id=result.cluster_id,
        cluster_name=result.cluster_name,
        display_name=body.display_name,
        token=result.token,
        helm_install_command=helm_command,
    )


@admin_router.get(
    "/orgs/{org_id}/teams/{team_node_id}/k8s-clusters",
    response_model=List[K8sClusterSummary],
)
async def admin_list_k8s_clusters(
    org_id: str,
    team_node_id: str,
    include_revoked: bool = False,
    db: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
):
    """
    List all K8s clusters for a team (admin endpoint).

    Used by slack-bot to show cluster list to users.
    """
    check_org_access(principal, org_id)

    clusters = list_k8s_clusters(
        db,
        org_id=org_id,
        team_node_id=team_node_id,
        include_revoked=include_revoked,
    )

    return [
        K8sClusterSummary(
            cluster_id=c.id,
            cluster_name=c.cluster_name,
            display_name=c.display_name,
            status=(
                c.status.value if isinstance(c.status, K8sClusterStatus) else c.status
            ),
            last_heartbeat_at=(
                c.last_heartbeat_at.isoformat() if c.last_heartbeat_at else None
            ),
            kubernetes_version=c.kubernetes_version,
            node_count=c.node_count,
            agent_version=c.agent_version,
            created_at=c.created_at.isoformat(),
        )
        for c in clusters
    ]


@admin_router.delete(
    "/orgs/{org_id}/teams/{team_node_id}/k8s-clusters/{cluster_id}",
    status_code=204,
)
async def admin_delete_k8s_cluster(
    org_id: str,
    team_node_id: str,
    cluster_id: str,
    db: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
):
    """
    Revoke a K8s cluster's access (admin endpoint).

    Used by slack-bot to disconnect clusters on behalf of users.
    """
    check_org_access(principal, org_id)

    cluster = get_k8s_cluster(db, cluster_id=cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    # Verify ownership
    if cluster.org_id != org_id or cluster.team_node_id != team_node_id:
        raise HTTPException(status_code=404, detail="Cluster not found")

    success = revoke_k8s_cluster(
        db,
        cluster_id=cluster_id,
        revoked_by=principal.subject or "admin",
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to revoke cluster")

    db.commit()

    logger.info(
        "k8s_cluster_revoked_admin",
        cluster_id=cluster_id,
        cluster_name=cluster.cluster_name,
        org_id=org_id,
        team_node_id=team_node_id,
        admin=principal.subject,
    )

    return None
