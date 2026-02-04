"""K8s Gateway Service - Main FastAPI Application."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import httpx
import structlog
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from sse_starlette.sse import EventSourceResponse

from .auth import (
    AuthError,
    ClusterIdentity,
    validate_internal_service,
    validate_k8s_agent_token,
)
from .config import get_settings
from .connection_manager import connection_manager
from .models import (
    AgentRegistration,
    ClusterConnectionInfo,
    ExecuteCommandRequest,
    ExecuteCommandResponse,
    K8sCommand,
    K8sCommandResponse,
    ListClustersResponse,
)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger(__name__)

# Prometheus metrics
AGENT_CONNECTIONS = Gauge(
    "k8s_gateway_agent_connections",
    "Number of connected K8s agents",
    ["team_node_id"],
)
COMMANDS_TOTAL = Counter(
    "k8s_gateway_commands_total",
    "Total K8s commands executed",
    ["command", "status"],
)
COMMAND_DURATION = Histogram(
    "k8s_gateway_command_duration_seconds",
    "Command execution duration",
    ["command"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("k8s_gateway_starting")
    yield
    logger.info("k8s_gateway_stopping")


settings = get_settings()

app = FastAPI(
    title="K8s Gateway",
    description="Gateway service for K8s agents in IncidentFox SaaS",
    version="0.1.0",
    lifespan=lifespan,
)


# =============================================================================
# Health & Metrics Endpoints (root level - no prefix)
# =============================================================================


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "k8s-gateway"}


@app.get("/ready")
async def ready():
    """Readiness check endpoint."""
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return JSONResponse(
        content=generate_latest().decode("utf-8"),
        media_type="text/plain",
    )


@app.get("/stats")
async def stats():
    """Connection statistics endpoint."""
    return connection_manager.get_stats()


# Also expose health at /gateway/health for external access via ingress
@app.get("/gateway/health")
async def gateway_health():
    """Health check endpoint (via gateway prefix)."""
    return {"status": "healthy", "service": "k8s-gateway"}


# =============================================================================
# Agent SSE Connection Endpoint
# Routes are duplicated at /agent/* and /gateway/agent/* to support both:
# - Internal cluster access (direct to service)
# - External ingress access (via /gateway prefix)
# =============================================================================


@app.get("/agent/connect")
@app.get("/gateway/agent/connect")
async def agent_connect(
    request: Request,
    authorization: str = Header(default=""),
):
    """
    SSE endpoint for K8s agents to connect.

    Protocol:
    1. Agent authenticates with K8s agent token (Bearer)
    2. Agent receives SSE stream of commands
    3. Agent POSTs responses to /agent/response/{request_id}

    Events sent to agent:
    - connected: Initial connection confirmation
    - command: K8s command to execute
    - heartbeat: Keep-alive message
    """
    settings = get_settings()

    # Authenticate
    try:
        identity = await validate_k8s_agent_token(authorization)
    except AuthError as e:
        logger.warning("agent_auth_failed", error=str(e))
        raise HTTPException(status_code=401, detail=str(e))

    # Parse registration info from query params (optional)
    agent_version = request.query_params.get("agent_version")
    kubernetes_version = request.query_params.get("kubernetes_version")
    node_count = request.query_params.get("node_count")
    namespace_count = request.query_params.get("namespace_count")

    # Register connection
    conn = await connection_manager.register(
        identity=identity,
        agent_version=agent_version,
        kubernetes_version=kubernetes_version,
        node_count=int(node_count) if node_count else None,
        namespace_count=int(namespace_count) if namespace_count else None,
    )

    # Update Prometheus metric
    AGENT_CONNECTIONS.labels(team_node_id=identity.team_node_id).inc()

    # Update cluster status in config_service
    await _update_cluster_status(
        identity.cluster_id,
        status="connected",
        agent_version=agent_version,
        kubernetes_version=kubernetes_version,
        node_count=int(node_count) if node_count else None,
        namespace_count=int(namespace_count) if namespace_count else None,
    )

    async def event_generator():
        """Generate SSE events for the agent."""
        try:
            # Send connected event
            yield {
                "event": "connected",
                "data": json.dumps(
                    {
                        "cluster_id": identity.cluster_id,
                        "message": "Connected to K8s Gateway",
                    }
                ),
            }

            while True:
                try:
                    # Wait for command or heartbeat timeout
                    cmd: K8sCommand = await asyncio.wait_for(
                        conn.command_queue.get(),
                        timeout=settings.heartbeat_interval_seconds,
                    )

                    # Send command event
                    yield {
                        "event": "command",
                        "id": cmd.request_id,
                        "data": json.dumps(
                            {
                                "request_id": cmd.request_id,
                                "command": cmd.command,
                                "params": cmd.params,
                                "timeout": cmd.timeout,
                            }
                        ),
                    }

                except asyncio.TimeoutError:
                    # Send heartbeat
                    connection_manager.update_heartbeat(identity.cluster_id)
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps(
                            {
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        ),
                    }

        except asyncio.CancelledError:
            logger.info("agent_connection_cancelled", cluster_id=identity.cluster_id)
        except Exception as e:
            logger.error(
                "agent_connection_error", cluster_id=identity.cluster_id, error=str(e)
            )
        finally:
            # Clean up on disconnect
            await connection_manager.unregister(identity.cluster_id)
            AGENT_CONNECTIONS.labels(team_node_id=identity.team_node_id).dec()

            # Update cluster status
            await _update_cluster_status(
                identity.cluster_id,
                status="disconnected",
            )

    return EventSourceResponse(event_generator())


@app.post("/agent/response/{request_id}")
@app.post("/gateway/agent/response/{request_id}")
async def agent_response(
    request_id: str,
    body: K8sCommandResponse,
    authorization: str = Header(default=""),
):
    """
    Endpoint for agents to send command responses.

    Called by the agent after executing a command.
    """
    # Authenticate
    try:
        identity = await validate_k8s_agent_token(authorization)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # Ensure request_id matches body
    if body.request_id != request_id:
        raise HTTPException(status_code=400, detail="Request ID mismatch")

    # Handle the response
    handled = connection_manager.handle_response(identity.cluster_id, body)

    if not handled:
        raise HTTPException(
            status_code=404, detail="Request not found or already completed"
        )

    return {"ok": True}


@app.post("/agent/heartbeat")
@app.post("/gateway/agent/heartbeat")
async def agent_heartbeat(
    authorization: str = Header(default=""),
):
    """
    Alternative heartbeat endpoint (in addition to SSE heartbeats).

    Agents can POST here if they want to send heartbeats outside the SSE stream.
    """
    # Authenticate
    try:
        identity = await validate_k8s_agent_token(authorization)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    updated = connection_manager.update_heartbeat(identity.cluster_id)

    if not updated:
        raise HTTPException(status_code=404, detail="Agent not connected")

    return {"ok": True, "timestamp": datetime.utcnow().isoformat()}


# =============================================================================
# Internal API (for AI Agent)
# =============================================================================


@app.post("/internal/execute", response_model=ExecuteCommandResponse)
async def execute_command(
    body: ExecuteCommandRequest,
    x_internal_service: Optional[str] = Header(default=None),
):
    """
    Execute a K8s command on a connected agent.

    Internal API for AI agent to execute K8s operations.

    Flow:
    1. AI agent calls this endpoint with cluster_id and command
    2. Gateway finds the connected agent and sends command via SSE
    3. Agent executes command and POSTs response
    4. Gateway returns result to AI agent
    """
    # Validate internal service header
    if not validate_internal_service(x_internal_service):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Check if cluster is connected
    conn = connection_manager.get_connection(body.cluster_id)
    if conn is None:
        return ExecuteCommandResponse(
            ok=False,
            error=f"Cluster not connected: {body.cluster_id}",
        )

    # Verify team ownership
    if conn.team_node_id != body.team_node_id:
        return ExecuteCommandResponse(
            ok=False,
            error="Cluster does not belong to this team",
        )

    # Execute command with metrics
    start_time = datetime.utcnow()
    try:
        result = await connection_manager.send_command(
            cluster_id=body.cluster_id,
            command=body.command,
            params=body.params,
            timeout=body.timeout,
        )

        duration = (datetime.utcnow() - start_time).total_seconds()
        COMMANDS_TOTAL.labels(command=body.command, status="success").inc()
        COMMAND_DURATION.labels(command=body.command).observe(duration)

        return ExecuteCommandResponse(ok=True, result=result)

    except asyncio.TimeoutError:
        COMMANDS_TOTAL.labels(command=body.command, status="timeout").inc()
        return ExecuteCommandResponse(
            ok=False,
            error=f"Command timed out after {body.timeout}s",
        )

    except Exception as e:
        COMMANDS_TOTAL.labels(command=body.command, status="error").inc()
        logger.error(
            "command_execution_error",
            cluster_id=body.cluster_id,
            command=body.command,
            error=str(e),
        )
        return ExecuteCommandResponse(ok=False, error=str(e))


@app.get("/internal/clusters", response_model=ListClustersResponse)
async def list_connected_clusters(
    team_node_id: Optional[str] = None,
    x_internal_service: Optional[str] = Header(default=None),
):
    """
    List connected clusters.

    Internal API for monitoring and debugging.
    """
    # Validate internal service header
    if not validate_internal_service(x_internal_service):
        raise HTTPException(status_code=401, detail="Unauthorized")

    connections = connection_manager.get_all_connections()

    # Filter by team if specified
    if team_node_id:
        connections = [c for c in connections if c.team_node_id == team_node_id]

    clusters = [
        ClusterConnectionInfo(
            cluster_id=c.cluster_id,
            cluster_name=c.cluster_name,
            org_id=c.org_id,
            team_node_id=c.team_node_id,
            connected_at=c.connected_at,
            last_heartbeat=c.last_heartbeat,
            agent_version=c.agent_version,
            kubernetes_version=c.kubernetes_version,
            node_count=c.node_count,
        )
        for c in connections
    ]

    return ListClustersResponse(clusters=clusters, total=len(clusters))


@app.get("/internal/clusters/{cluster_id}")
async def get_cluster_connection(
    cluster_id: str,
    x_internal_service: Optional[str] = Header(default=None),
):
    """Get connection info for a specific cluster."""
    # Validate internal service header
    if not validate_internal_service(x_internal_service):
        raise HTTPException(status_code=401, detail="Unauthorized")

    conn = connection_manager.get_connection(cluster_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Cluster not connected")

    return ClusterConnectionInfo(
        cluster_id=conn.cluster_id,
        cluster_name=conn.cluster_name,
        org_id=conn.org_id,
        team_node_id=conn.team_node_id,
        connected_at=conn.connected_at,
        last_heartbeat=conn.last_heartbeat,
        agent_version=conn.agent_version,
        kubernetes_version=conn.kubernetes_version,
        node_count=conn.node_count,
    )


# =============================================================================
# Helper Functions
# =============================================================================


async def _update_cluster_status(
    cluster_id: str,
    status: str,
    agent_version: Optional[str] = None,
    kubernetes_version: Optional[str] = None,
    node_count: Optional[int] = None,
    namespace_count: Optional[int] = None,
) -> None:
    """Update cluster status in config_service."""
    settings = get_settings()

    try:
        async with httpx.AsyncClient(timeout=settings.config_service_timeout) as client:
            await client.put(
                f"{settings.config_service_url}/api/v1/internal/k8s-clusters/{cluster_id}/status",
                json={
                    "status": status,
                    "agent_version": agent_version,
                    "kubernetes_version": kubernetes_version,
                    "node_count": node_count,
                    "namespace_count": namespace_count,
                },
                headers={"X-Internal-Service": "k8s-gateway"},
            )
    except Exception as e:
        logger.error(
            "failed_to_update_cluster_status",
            cluster_id=cluster_id,
            status=status,
            error=str(e),
        )
