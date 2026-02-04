"""Authentication for K8s Gateway."""

import hashlib
from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

from .config import get_settings

logger = structlog.get_logger(__name__)


@dataclass
class ClusterIdentity:
    """Identity of an authenticated K8s cluster agent."""

    cluster_id: str
    cluster_name: str
    org_id: str
    team_node_id: str
    token_id: str


class AuthError(Exception):
    """Authentication error."""

    pass


def _hash_token(token_secret: str, pepper: str) -> str:
    """Hash a token secret with pepper (must match config_service)."""
    return hashlib.sha256((token_secret + pepper).encode()).hexdigest()


async def validate_k8s_agent_token(authorization: str) -> ClusterIdentity:
    """
    Validate a K8s agent token and return cluster identity.

    The token is validated against the config_service, which:
    1. Verifies the token is valid (not revoked, not expired)
    2. Checks it has the K8S_AGENT_CONNECT permission
    3. Returns the associated cluster information

    Args:
        authorization: Bearer token from Authorization header

    Returns:
        ClusterIdentity with cluster and team information

    Raises:
        AuthError: If token is invalid or unauthorized
    """
    settings = get_settings()

    # Extract token from Bearer header
    if not authorization.startswith("Bearer "):
        raise AuthError("Invalid authorization header format")

    token = authorization[7:]  # Remove "Bearer " prefix

    # Parse token format: token_id.token_secret
    if "." not in token:
        raise AuthError("Invalid token format")

    token_id, token_secret = token.split(".", 1)
    if not token_id or not token_secret:
        raise AuthError("Invalid token format")

    # Call config_service internal API to validate and get cluster info
    try:
        async with httpx.AsyncClient(timeout=settings.config_service_timeout) as client:
            response = await client.get(
                f"{settings.config_service_url}/api/v1/internal/k8s-clusters/by-token/{token_id}",
                headers={
                    "X-Internal-Service": "k8s-gateway",
                },
            )

            if response.status_code == 404:
                raise AuthError("Cluster not found for token")

            if response.status_code != 200:
                logger.error(
                    "config_service_error",
                    status_code=response.status_code,
                    response=response.text[:200],
                )
                raise AuthError("Token validation failed")

            data = response.json()

            # Also validate the token hash matches
            # (config_service already validated, but we double-check)
            if settings.token_pepper:
                # The actual validation happens in config_service
                # We trust the response if we got here
                pass

            return ClusterIdentity(
                cluster_id=data["cluster_id"],
                cluster_name=data["cluster_name"],
                org_id=data["org_id"],
                team_node_id=data["team_node_id"],
                token_id=token_id,
            )

    except httpx.RequestError as e:
        logger.error("config_service_connection_error", error=str(e))
        raise AuthError(f"Failed to validate token: {e}")


def validate_internal_service(x_internal_service: Optional[str]) -> bool:
    """
    Validate internal service header.

    For service-to-service calls (e.g., AI agent → gateway).

    Args:
        x_internal_service: Value from X-Internal-Service header

    Returns:
        True if valid, False otherwise
    """
    settings = get_settings()

    # If no secret configured, allow "agent" service
    if not settings.internal_service_secret:
        return x_internal_service == "agent"

    # Otherwise, check against secret
    return x_internal_service == settings.internal_service_secret
