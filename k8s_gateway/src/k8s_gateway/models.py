"""Pydantic models for K8s Gateway."""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

# =============================================================================
# Agent Connection Models
# =============================================================================


class AgentRegistration(BaseModel):
    """Information sent by agent when connecting."""

    agent_version: str
    agent_pod_name: Optional[str] = None
    kubernetes_version: Optional[str] = None
    node_count: Optional[int] = None
    namespace_count: Optional[int] = None
    cluster_info: Optional[Dict[str, Any]] = None


class AgentHeartbeat(BaseModel):
    """Heartbeat message from agent."""

    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Command Models
# =============================================================================


class K8sCommand(BaseModel):
    """Command to be executed by the K8s agent."""

    request_id: str
    command: str  # e.g., "list_pods", "get_pod_logs"
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout: float = 30.0


class K8sCommandResponse(BaseModel):
    """Response from K8s agent after executing a command."""

    request_id: str
    ok: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# =============================================================================
# Internal API Models (for AI Agent)
# =============================================================================


class ExecuteCommandRequest(BaseModel):
    """Request from AI agent to execute a K8s command."""

    cluster_id: str
    team_node_id: str
    command: str
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout: float = 30.0


class ExecuteCommandResponse(BaseModel):
    """Response to AI agent after command execution."""

    ok: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ClusterConnectionInfo(BaseModel):
    """Information about a connected cluster."""

    cluster_id: str
    cluster_name: str
    org_id: str
    team_node_id: str
    connected_at: datetime
    last_heartbeat: datetime
    agent_version: Optional[str] = None
    kubernetes_version: Optional[str] = None
    node_count: Optional[int] = None


class ListClustersResponse(BaseModel):
    """Response listing connected clusters."""

    clusters: list[ClusterConnectionInfo]
    total: int


# =============================================================================
# SSE Event Models
# =============================================================================


class SSEEvent(BaseModel):
    """Server-Sent Event structure."""

    event: str
    data: str
    id: Optional[str] = None
    retry: Optional[int] = None
