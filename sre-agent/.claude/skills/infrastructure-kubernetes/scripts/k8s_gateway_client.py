"""Shared client for routing K8s commands through the k8s-gateway.

When a customer deploys the k8s-agent Helm chart in their cluster, commands
can be routed through the k8s-gateway instead of requiring direct K8s API
access. This module provides the HTTP plumbing for that path.

Usage from other scripts:

    from k8s_gateway_client import is_gateway_mode, execute_command

    if is_gateway_mode(args.cluster_id):
        result = execute_command(args.cluster_id, "list_pods", {"namespace": "default"})
    else:
        # direct k8s API path
        ...
"""

import json
import os
import sys

import httpx


def is_gateway_mode(cluster_id: str | None) -> bool:
    """Check if we should route through the k8s-gateway."""
    return bool(cluster_id and os.getenv("K8S_GATEWAY_URL"))


def execute_command(
    cluster_id: str,
    command: str,
    params: dict,
    timeout: float = 30.0,
) -> dict:
    """Execute a K8s command on a remote cluster via the k8s-gateway.

    Args:
        cluster_id: Target cluster ID (from list_clusters.py).
        command: Gateway command name (list_pods, describe_pod, etc.).
        params: Command parameters.
        timeout: Command timeout in seconds.

    Returns:
        Result dict from the k8s-agent executor.

    Raises:
        RuntimeError: On gateway errors (cluster not connected, timeout, etc.).
    """
    gateway_url = os.environ["K8S_GATEWAY_URL"]
    org_id = os.environ.get("INCIDENTFOX_TENANT_ID", "")

    if not org_id:
        raise RuntimeError(
            "INCIDENTFOX_TENANT_ID not set — cannot identify org for gateway request"
        )

    url = f"{gateway_url.rstrip('/')}/internal/execute"

    try:
        with httpx.Client(timeout=timeout + 5.0) as client:
            response = client.post(
                url,
                headers={
                    "X-Internal-Service": "agent",
                    "Content-Type": "application/json",
                },
                json={
                    "cluster_id": cluster_id,
                    "org_id": org_id,
                    "command": command,
                    "params": params,
                    "timeout": timeout,
                },
            )
    except httpx.ConnectError:
        raise RuntimeError(
            f"Cannot reach k8s-gateway at {gateway_url}. "
            "Is the k8s-gateway service running?"
        )
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Timeout waiting for command '{command}' on cluster {cluster_id}"
        )

    if response.status_code >= 400:
        raise RuntimeError(f"k8s-gateway error {response.status_code}: {response.text}")

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(
            f"K8s command '{command}' failed: {data.get('error', 'unknown error')}"
        )

    return data["result"]


def list_connected_clusters() -> list[dict]:
    """List clusters connected to the k8s-gateway for the current team.

    Returns:
        List of cluster connection info dicts.
    """
    gateway_url = os.environ.get("K8S_GATEWAY_URL")
    if not gateway_url:
        return []

    org_id = os.environ.get("INCIDENTFOX_TENANT_ID", "")
    url = f"{gateway_url.rstrip('/')}/internal/clusters"
    params = {}
    if org_id:
        params["org_id"] = org_id

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                url,
                headers={"X-Internal-Service": "agent"},
                params=params,
            )
        if response.status_code >= 400:
            print(
                f"Warning: k8s-gateway returned {response.status_code}",
                file=sys.stderr,
            )
            return []
        data = response.json()
        return data.get("clusters", [])
    except Exception as e:
        print(f"Warning: cannot reach k8s-gateway: {e}", file=sys.stderr)
        return []


def add_cluster_id_arg(parser) -> None:
    """Add the --cluster-id argument to an argparse parser."""
    parser.add_argument(
        "--cluster-id",
        dest="cluster_id",
        help="Route command through k8s-gateway to a remote cluster (from list_clusters.py)",
    )


def print_result(result: dict, json_mode: bool = False) -> None:
    """Print a gateway result dict as JSON."""
    if json_mode:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result, indent=2))
