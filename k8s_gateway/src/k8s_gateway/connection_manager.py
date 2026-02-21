"""Connection manager for K8s agent connections."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

import structlog

from .auth import ClusterIdentity
from .models import K8sCommand, K8sCommandResponse

logger = structlog.get_logger(__name__)


@dataclass
class AgentConnection:
    """Represents an active connection from a K8s agent."""

    cluster_id: str
    cluster_name: str
    org_id: str
    team_node_id: str
    connected_at: datetime
    last_heartbeat: datetime

    # Agent metadata
    agent_version: Optional[str] = None
    kubernetes_version: Optional[str] = None
    node_count: Optional[int] = None
    namespace_count: Optional[int] = None

    # Command queue for sending commands to agent
    command_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    # Pending command responses (request_id -> Future)
    pending_requests: Dict[str, asyncio.Future] = field(default_factory=dict)


class ConnectionManager:
    """
    Manages SSE connections from K8s agents.

    Handles:
    - Agent registration and disconnection
    - Routing commands to agents
    - Tracking heartbeats
    - Multi-tenant isolation
    """

    def __init__(self):
        # cluster_id -> AgentConnection
        self._connections: Dict[str, AgentConnection] = {}

        # team_node_id -> set of cluster_ids (for routing)
        self._by_team: Dict[str, set] = {}

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def register(
        self,
        identity: ClusterIdentity,
        agent_version: Optional[str] = None,
        kubernetes_version: Optional[str] = None,
        node_count: Optional[int] = None,
        namespace_count: Optional[int] = None,
    ) -> AgentConnection:
        """
        Register a new agent connection.

        Args:
            identity: Authenticated cluster identity
            agent_version: Version of the K8s agent
            kubernetes_version: K8s cluster version
            node_count: Number of nodes in cluster
            namespace_count: Number of namespaces

        Returns:
            AgentConnection for sending commands
        """
        async with self._lock:
            # Check for existing connection
            if identity.cluster_id in self._connections:
                logger.warning(
                    "replacing_existing_connection",
                    cluster_id=identity.cluster_id,
                )
                await self._unregister_unsafe(identity.cluster_id)

            # Create new connection
            now = datetime.utcnow()
            conn = AgentConnection(
                cluster_id=identity.cluster_id,
                cluster_name=identity.cluster_name,
                org_id=identity.org_id,
                team_node_id=identity.team_node_id,
                connected_at=now,
                last_heartbeat=now,
                agent_version=agent_version,
                kubernetes_version=kubernetes_version,
                node_count=node_count,
                namespace_count=namespace_count,
            )

            self._connections[identity.cluster_id] = conn

            # Add to team index
            if identity.team_node_id not in self._by_team:
                self._by_team[identity.team_node_id] = set()
            self._by_team[identity.team_node_id].add(identity.cluster_id)

            logger.info(
                "agent_connected",
                cluster_id=identity.cluster_id,
                cluster_name=identity.cluster_name,
                org_id=identity.org_id,
                team_node_id=identity.team_node_id,
                agent_version=agent_version,
            )

            return conn

    async def unregister(self, cluster_id: str) -> None:
        """
        Unregister an agent connection.

        Args:
            cluster_id: ID of the cluster to unregister
        """
        async with self._lock:
            await self._unregister_unsafe(cluster_id)

    async def _unregister_unsafe(self, cluster_id: str) -> None:
        """Unregister without lock (internal use)."""
        conn = self._connections.pop(cluster_id, None)
        if conn is None:
            return

        # Remove from team index
        team_clusters = self._by_team.get(conn.team_node_id)
        if team_clusters:
            team_clusters.discard(cluster_id)
            if not team_clusters:
                del self._by_team[conn.team_node_id]

        # Cancel any pending requests
        for request_id, future in conn.pending_requests.items():
            if not future.done():
                future.set_exception(
                    ConnectionError(f"Agent disconnected: {cluster_id}")
                )

        logger.info(
            "agent_disconnected",
            cluster_id=cluster_id,
            cluster_name=conn.cluster_name,
            connected_duration_seconds=(
                datetime.utcnow() - conn.connected_at
            ).total_seconds(),
        )

    def get_connection(self, cluster_id: str) -> Optional[AgentConnection]:
        """Get connection by cluster ID."""
        return self._connections.get(cluster_id)

    def get_team_clusters(self, team_node_id: str) -> list[str]:
        """Get all cluster IDs for a team."""
        return list(self._by_team.get(team_node_id, set()))

    def get_all_connections(self) -> list[AgentConnection]:
        """Get all active connections (for monitoring)."""
        return list(self._connections.values())

    def update_heartbeat(self, cluster_id: str) -> bool:
        """
        Update the heartbeat timestamp for a cluster.

        Args:
            cluster_id: ID of the cluster

        Returns:
            True if updated, False if cluster not found
        """
        conn = self._connections.get(cluster_id)
        if conn:
            conn.last_heartbeat = datetime.utcnow()
            return True
        return False

    async def send_command(
        self,
        cluster_id: str,
        command: str,
        params: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """
        Send a command to an agent and wait for response.

        Args:
            cluster_id: ID of the cluster to send to
            command: Command name (e.g., "list_pods")
            params: Command parameters
            timeout: Timeout in seconds

        Returns:
            Command result dict

        Raises:
            ValueError: If cluster not connected
            asyncio.TimeoutError: If command times out
            Exception: If command execution fails
        """
        conn = self._connections.get(cluster_id)
        if conn is None:
            raise ValueError(f"Cluster not connected: {cluster_id}")

        # Generate request ID
        request_id = f"req_{uuid.uuid4().hex[:12]}"

        # Create command
        cmd = K8sCommand(
            request_id=request_id,
            command=command,
            params=params,
            timeout=timeout,
        )

        # Create future for response
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        conn.pending_requests[request_id] = future

        try:
            # Queue command for agent
            await conn.command_queue.put(cmd)

            logger.debug(
                "command_sent",
                cluster_id=cluster_id,
                request_id=request_id,
                command=command,
            )

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            logger.warning(
                "command_timeout",
                cluster_id=cluster_id,
                request_id=request_id,
                command=command,
                timeout=timeout,
            )
            raise

        finally:
            # Clean up pending request
            conn.pending_requests.pop(request_id, None)

    def handle_response(self, cluster_id: str, response: K8sCommandResponse) -> bool:
        """
        Handle a command response from an agent.

        Args:
            cluster_id: ID of the cluster
            response: Response from agent

        Returns:
            True if response was handled, False if no pending request
        """
        conn = self._connections.get(cluster_id)
        if conn is None:
            logger.warning(
                "response_for_unknown_cluster",
                cluster_id=cluster_id,
                request_id=response.request_id,
            )
            return False

        future = conn.pending_requests.get(response.request_id)
        if future is None:
            logger.warning(
                "response_for_unknown_request",
                cluster_id=cluster_id,
                request_id=response.request_id,
            )
            return False

        if future.done():
            logger.warning(
                "response_for_completed_request",
                cluster_id=cluster_id,
                request_id=response.request_id,
            )
            return False

        # Set result or exception
        if response.ok:
            future.set_result(response.result or {})
        else:
            future.set_exception(Exception(response.error or "Command failed"))

        logger.debug(
            "command_response_handled",
            cluster_id=cluster_id,
            request_id=response.request_id,
            ok=response.ok,
        )

        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        total_connections = len(self._connections)
        teams_with_connections = len(self._by_team)

        pending_commands = sum(
            len(conn.pending_requests) for conn in self._connections.values()
        )

        return {
            "total_connections": total_connections,
            "teams_with_connections": teams_with_connections,
            "pending_commands": pending_commands,
            "connections_by_team": {
                team: len(clusters) for team, clusters in self._by_team.items()
            },
        }


# Global connection manager instance
connection_manager = ConnectionManager()
