"""Remediation tools for taking corrective actions.

These tools execute Kubernetes remediation actions.
In Claude Code, these are protected by hooks that display confirmation.

Tools:
- propose_pod_restart: Restart a specific pod
- propose_deployment_restart: Rolling restart a deployment
- propose_scale_deployment: Scale a deployment
"""

import json
from pathlib import Path

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException
from mcp.server.fastmcp import FastMCP


class K8sConfigError(Exception):
    """Raised when K8s configuration is missing."""

    def __init__(self, message: str):
        super().__init__(message)


def _get_k8s_client():
    """Get Kubernetes API clients."""
    kubeconfig = Path.home() / ".kube" / "config"
    in_cluster = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")

    try:
        if kubeconfig.exists():
            k8s_config.load_kube_config()
        elif in_cluster.exists():
            k8s_config.load_incluster_config()
        else:
            raise K8sConfigError(
                "Kubernetes not configured. Ensure ~/.kube/config exists."
            )
    except k8s_config.ConfigException as e:
        raise K8sConfigError(f"Failed to load Kubernetes config: {e}")

    return client.CoreV1Api(), client.AppsV1Api()


def register_tools(mcp: FastMCP):
    """Register remediation tools with the MCP server."""

    @mcp.tool()
    def propose_pod_restart(
        pod_name: str,
        namespace: str = "default",
        reason: str = "",
        dry_run: bool = False,
    ) -> str:
        """Restart a Kubernetes pod by deleting it.

        The pod will be recreated by its controller (Deployment, ReplicaSet, etc.).
        This tool is protected by a confirmation hook in Claude Code.

        Args:
            pod_name: Name of the pod to restart
            namespace: Kubernetes namespace (default: "default")
            reason: Reason for the restart (for audit logging)
            dry_run: If True, only show what would happen without executing

        Returns:
            JSON with result of the restart operation
        """
        try:
            core_v1, _ = _get_k8s_client()

            # First check the pod exists
            try:
                pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            except ApiException as e:
                if e.status == 404:
                    return json.dumps(
                        {
                            "error": f"Pod '{pod_name}' not found in namespace '{namespace}'",
                            "executed": False,
                        }
                    )
                raise

            # Dry run - just report what would happen
            if dry_run:
                owner = None
                if pod.metadata.owner_references:
                    owner = pod.metadata.owner_references[0].kind
                return json.dumps(
                    {
                        "action": "pod_restart",
                        "dry_run": True,
                        "pod": pod_name,
                        "namespace": namespace,
                        "current_status": pod.status.phase,
                        "owner_kind": owner,
                        "would_execute": f"kubectl delete pod {pod_name} -n {namespace}",
                        "effect": "Pod will be deleted and recreated by its controller",
                        "reason": reason,
                        "executed": False,
                    },
                    indent=2,
                )

            # Delete the pod (controller will recreate it)
            core_v1.delete_namespaced_pod(name=pod_name, namespace=namespace)

            return json.dumps(
                {
                    "action": "pod_restart",
                    "pod": pod_name,
                    "namespace": namespace,
                    "reason": reason,
                    "executed": True,
                    "message": f"Pod '{pod_name}' deleted. It will be recreated by its controller.",
                },
                indent=2,
            )

        except K8sConfigError as e:
            return json.dumps(
                {"error": str(e), "config_required": True, "executed": False}
            )
        except ApiException as e:
            return json.dumps(
                {
                    "error": str(e),
                    "pod": pod_name,
                    "namespace": namespace,
                    "executed": False,
                }
            )

    @mcp.tool()
    def propose_deployment_restart(
        deployment: str,
        namespace: str = "default",
        reason: str = "",
        dry_run: bool = False,
    ) -> str:
        """Perform a rolling restart of a Kubernetes deployment.

        Updates the deployment's pod template annotation to trigger a rollout.
        This is the safest way to restart all pods in a deployment.
        This tool is protected by a confirmation hook in Claude Code.

        Args:
            deployment: Name of the deployment to restart
            namespace: Kubernetes namespace (default: "default")
            reason: Reason for the restart (for audit logging)
            dry_run: If True, only show what would happen without executing

        Returns:
            JSON with result of the restart operation
        """
        try:
            from datetime import datetime

            _, apps_v1 = _get_k8s_client()

            # Check deployment exists
            try:
                deploy = apps_v1.read_namespaced_deployment(
                    name=deployment, namespace=namespace
                )
            except ApiException as e:
                if e.status == 404:
                    return json.dumps(
                        {
                            "error": f"Deployment '{deployment}' not found in namespace '{namespace}'",
                            "executed": False,
                        }
                    )
                raise

            # Dry run - just report what would happen
            if dry_run:
                return json.dumps(
                    {
                        "action": "deployment_restart",
                        "dry_run": True,
                        "deployment": deployment,
                        "namespace": namespace,
                        "current_replicas": deploy.spec.replicas,
                        "ready_replicas": deploy.status.ready_replicas,
                        "would_execute": f"kubectl rollout restart deployment/{deployment} -n {namespace}",
                        "effect": f"All {deploy.spec.replicas} pods will be restarted in a rolling fashion",
                        "reason": reason,
                        "executed": False,
                    },
                    indent=2,
                )

            # Add/update restart annotation to trigger rollout
            if deploy.spec.template.metadata.annotations is None:
                deploy.spec.template.metadata.annotations = {}

            deploy.spec.template.metadata.annotations[
                "kubectl.kubernetes.io/restartedAt"
            ] = datetime.utcnow().isoformat()

            apps_v1.patch_namespaced_deployment(
                name=deployment,
                namespace=namespace,
                body=deploy,
            )

            return json.dumps(
                {
                    "action": "deployment_restart",
                    "deployment": deployment,
                    "namespace": namespace,
                    "reason": reason,
                    "executed": True,
                    "message": f"Rolling restart initiated for deployment '{deployment}'",
                    "replicas": deploy.spec.replicas,
                },
                indent=2,
            )

        except K8sConfigError as e:
            return json.dumps(
                {"error": str(e), "config_required": True, "executed": False}
            )
        except ApiException as e:
            return json.dumps(
                {
                    "error": str(e),
                    "deployment": deployment,
                    "namespace": namespace,
                    "executed": False,
                }
            )

    @mcp.tool()
    def propose_scale_deployment(
        deployment: str,
        replicas: int,
        namespace: str = "default",
        reason: str = "",
        dry_run: bool = False,
    ) -> str:
        """Scale a Kubernetes deployment to a specified number of replicas.

        This tool is protected by a confirmation hook in Claude Code.

        Args:
            deployment: Name of the deployment to scale
            replicas: Target number of replicas
            namespace: Kubernetes namespace (default: "default")
            reason: Reason for scaling (for audit logging)
            dry_run: If True, only show what would happen without executing

        Returns:
            JSON with result of the scale operation
        """
        try:
            _, apps_v1 = _get_k8s_client()

            # Check deployment exists and get current state
            try:
                deploy = apps_v1.read_namespaced_deployment(
                    name=deployment, namespace=namespace
                )
            except ApiException as e:
                if e.status == 404:
                    return json.dumps(
                        {
                            "error": f"Deployment '{deployment}' not found in namespace '{namespace}'",
                            "executed": False,
                        }
                    )
                raise

            previous_replicas = deploy.spec.replicas

            # Dry run - just report what would happen
            if dry_run:
                direction = "up" if replicas > previous_replicas else "down"
                return json.dumps(
                    {
                        "action": "scale_deployment",
                        "dry_run": True,
                        "deployment": deployment,
                        "namespace": namespace,
                        "current_replicas": previous_replicas,
                        "target_replicas": replicas,
                        "change": f"Scale {direction} by {abs(replicas - previous_replicas)}",
                        "would_execute": f"kubectl scale deployment/{deployment} --replicas={replicas} -n {namespace}",
                        "effect": f"Deployment will have {replicas} pods instead of {previous_replicas}",
                        "reason": reason,
                        "executed": False,
                    },
                    indent=2,
                )

            # Scale the deployment
            deploy.spec.replicas = replicas
            apps_v1.patch_namespaced_deployment(
                name=deployment,
                namespace=namespace,
                body={"spec": {"replicas": replicas}},
            )

            return json.dumps(
                {
                    "action": "scale_deployment",
                    "deployment": deployment,
                    "namespace": namespace,
                    "previous_replicas": previous_replicas,
                    "new_replicas": replicas,
                    "reason": reason,
                    "executed": True,
                    "message": f"Deployment '{deployment}' scaled from {previous_replicas} to {replicas} replicas",
                },
                indent=2,
            )

        except K8sConfigError as e:
            return json.dumps(
                {"error": str(e), "config_required": True, "executed": False}
            )
        except ApiException as e:
            return json.dumps(
                {
                    "error": str(e),
                    "deployment": deployment,
                    "namespace": namespace,
                    "executed": False,
                }
            )
