"""K8s Gateway Client for SaaS mode.

Routes K8s commands through the K8s Gateway service to reach
customer clusters that are connected via the k8s-agent.
"""

from __future__ import annotations

import httpx
import structlog

from ..core.config import get_config

logger = structlog.get_logger(__name__)

# Default timeout for gateway requests
GATEWAY_TIMEOUT = 60.0


class K8sGatewayError(Exception):
    """Error communicating with K8s Gateway."""

    pass


class K8sGatewayClient:
    """Client for K8s Gateway service."""

    def __init__(self, gateway_url: str, team_node_id: str):
        """
        Initialize gateway client.

        Args:
            gateway_url: URL of the K8s Gateway service
            team_node_id: Team node ID for authorization
        """
        self.gateway_url = gateway_url.rstrip("/")
        self.team_node_id = team_node_id

    async def execute(
        self,
        cluster_id: str,
        command: str,
        params: dict,
        timeout: float = 30.0,
    ) -> dict:
        """
        Execute a K8s command on a remote cluster via gateway.

        Args:
            cluster_id: ID of the target cluster
            command: Command to execute (e.g., "list_pods")
            params: Command parameters
            timeout: Command timeout in seconds

        Returns:
            Command result dict

        Raises:
            K8sGatewayError: If communication fails or command fails
        """
        url = f"{self.gateway_url}/internal/execute"

        body = {
            "cluster_id": cluster_id,
            "team_node_id": self.team_node_id,
            "command": command,
            "params": params,
            "timeout": timeout,
        }

        headers = {
            "X-Internal-Service": "agent",
            "Content-Type": "application/json",
        }

        logger.info(
            "k8s_gateway_execute",
            cluster_id=cluster_id,
            command=command,
            params_keys=list(params.keys()),
        )

        try:
            async with httpx.AsyncClient(timeout=GATEWAY_TIMEOUT) as client:
                response = await client.post(url, json=body, headers=headers)

                if response.status_code != 200:
                    logger.error(
                        "k8s_gateway_http_error",
                        status_code=response.status_code,
                        response=response.text[:500],
                    )
                    raise K8sGatewayError(
                        f"Gateway returned {response.status_code}: {response.text[:200]}"
                    )

                result = response.json()

                if not result.get("ok"):
                    error_msg = result.get("error", "Unknown error")
                    logger.error(
                        "k8s_gateway_command_failed",
                        cluster_id=cluster_id,
                        command=command,
                        error=error_msg,
                    )
                    raise K8sGatewayError(f"Command failed: {error_msg}")

                logger.info(
                    "k8s_gateway_execute_success",
                    cluster_id=cluster_id,
                    command=command,
                )

                return result.get("result", {})

        except httpx.TimeoutException:
            logger.error(
                "k8s_gateway_timeout",
                cluster_id=cluster_id,
                command=command,
            )
            raise K8sGatewayError(f"Gateway request timed out after {GATEWAY_TIMEOUT}s")

        except httpx.RequestError as e:
            logger.error(
                "k8s_gateway_request_error",
                cluster_id=cluster_id,
                command=command,
                error=str(e),
            )
            raise K8sGatewayError(f"Gateway request failed: {e}")

    async def check_cluster_connected(self, cluster_id: str) -> bool:
        """
        Check if a cluster is connected to the gateway.

        Args:
            cluster_id: ID of the cluster

        Returns:
            True if connected, False otherwise
        """
        url = f"{self.gateway_url}/internal/clusters/{cluster_id}"

        headers = {
            "X-Internal-Service": "agent",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                return response.status_code == 200
        except Exception:
            return False


def get_gateway_client(team_node_id: str) -> K8sGatewayClient:
    """
    Get a K8s Gateway client configured from settings.

    Args:
        team_node_id: Team node ID for authorization

    Returns:
        K8sGatewayClient instance
    """
    config = get_config()
    gateway_url = config.k8s_gateway_url

    if not gateway_url:
        raise K8sGatewayError("K8S_GATEWAY_URL not configured")

    return K8sGatewayClient(gateway_url=gateway_url, team_node_id=team_node_id)
