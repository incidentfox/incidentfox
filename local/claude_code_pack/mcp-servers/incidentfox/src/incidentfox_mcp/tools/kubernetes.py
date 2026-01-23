"""Kubernetes tools for pod inspection and debugging.

Provides tools for investigating Kubernetes clusters:
- list_pods: List pods with status
- get_pod_logs: Get pod logs
- get_pod_events: Get pod events (critical: events before logs)
- describe_pod: Detailed pod info
- describe_deployment: Deployment status
- get_deployment_history: Rollout history
- get_pod_resources: Resource usage vs limits
"""

import json
from pathlib import Path

from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException
from mcp.server.fastmcp import FastMCP


class K8sConfigError(Exception):
    """Raised when K8s configuration is missing or invalid."""

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
                "Kubernetes not configured. Ensure ~/.kube/config exists or run in-cluster."
            )
    except k8s_config.ConfigException as e:
        raise K8sConfigError(f"Failed to load Kubernetes config: {e}")

    return client.CoreV1Api(), client.AppsV1Api()


def register_tools(mcp: FastMCP):
    """Register Kubernetes tools with the MCP server."""

    @mcp.tool()
    def list_pods(
        namespace: str = "default",
        label_selector: str | None = None,
    ) -> str:
        """List pods in a Kubernetes namespace with their status.

        Args:
            namespace: Kubernetes namespace (default: "default")
            label_selector: Label selector filter (e.g., "app=myapp")

        Returns:
            JSON with pod list including name, status, ready state, restarts
        """
        try:
            core_v1, _ = _get_k8s_client()
            pods = core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector,
            )

            result = {
                "namespace": namespace,
                "pod_count": len(pods.items),
                "pods": [
                    {
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "ready": f"{sum(1 for cs in (pod.status.container_statuses or []) if cs.ready)}/{len(pod.spec.containers)}",
                        "restarts": sum(
                            cs.restart_count
                            for cs in (pod.status.container_statuses or [])
                        ),
                        "age": str(pod.metadata.creation_timestamp),
                    }
                    for pod in pods.items
                ],
            }
            return json.dumps(result, indent=2)

        except K8sConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ApiException as e:
            return json.dumps({"error": str(e), "namespace": namespace})

    @mcp.tool()
    def get_pod_logs(
        pod_name: str,
        namespace: str = "default",
        container: str | None = None,
        tail_lines: int = 100,
    ) -> str:
        """Get logs from a Kubernetes pod.

        Args:
            pod_name: Name of the pod
            namespace: Kubernetes namespace (default: "default")
            container: Specific container name (optional, for multi-container pods)
            tail_lines: Number of log lines to retrieve (default: 100)

        Returns:
            JSON with pod logs
        """
        try:
            core_v1, _ = _get_k8s_client()
            logs = core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines,
            )

            return json.dumps(
                {"pod": pod_name, "namespace": namespace, "logs": logs}, indent=2
            )

        except K8sConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ApiException as e:
            return json.dumps(
                {"error": str(e), "pod": pod_name, "namespace": namespace}
            )

    @mcp.tool()
    def get_pod_events(pod_name: str, namespace: str = "default") -> str:
        """Get events related to a pod. ALWAYS check events BEFORE logs.

        Events explain most crash/scheduling issues faster than logs.
        Common events: OOMKilled, ImagePullBackOff, FailedScheduling, etc.

        Args:
            pod_name: Name of the pod
            namespace: Kubernetes namespace (default: "default")

        Returns:
            JSON with events including type, reason, message, and timestamps
        """
        try:
            core_v1, _ = _get_k8s_client()
            events = core_v1.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={pod_name}",
            )

            result = {
                "pod": pod_name,
                "namespace": namespace,
                "event_count": len(events.items),
                "events": [
                    {
                        "type": event.type,
                        "reason": event.reason,
                        "message": event.message,
                        "count": event.count,
                        "first_timestamp": str(event.first_timestamp),
                        "last_timestamp": str(event.last_timestamp),
                    }
                    for event in events.items
                ],
            }
            return json.dumps(result, indent=2)

        except K8sConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ApiException as e:
            return json.dumps(
                {"error": str(e), "pod": pod_name, "namespace": namespace}
            )

    @mcp.tool()
    def describe_pod(pod_name: str, namespace: str = "default") -> str:
        """Get detailed information about a pod.

        Includes container status, resource allocation, conditions, and node info.

        Args:
            pod_name: Name of the pod
            namespace: Kubernetes namespace (default: "default")

        Returns:
            JSON with detailed pod information
        """
        try:
            core_v1, _ = _get_k8s_client()
            pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)

            def _extract_resources(container):
                resources = {}
                if container.resources:
                    if container.resources.requests:
                        resources["requests"] = dict(container.resources.requests)
                    if container.resources.limits:
                        resources["limits"] = dict(container.resources.limits)
                return resources if resources else None

            result = {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "node": pod.spec.node_name,
                "containers": [
                    {
                        "name": c.name,
                        "image": c.image,
                        "ready": any(
                            cs.name == c.name and cs.ready
                            for cs in (pod.status.container_statuses or [])
                        ),
                        "restart_count": next(
                            (
                                cs.restart_count
                                for cs in (pod.status.container_statuses or [])
                                if cs.name == c.name
                            ),
                            0,
                        ),
                        "resources": _extract_resources(c),
                    }
                    for c in pod.spec.containers
                ],
                "conditions": [
                    {
                        "type": cond.type,
                        "status": cond.status,
                        "reason": cond.reason,
                    }
                    for cond in (pod.status.conditions or [])
                ],
            }
            return json.dumps(result, indent=2)

        except K8sConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ApiException as e:
            return json.dumps(
                {"error": str(e), "pod": pod_name, "namespace": namespace}
            )

    @mcp.tool()
    def describe_deployment(deployment_name: str, namespace: str = "default") -> str:
        """Get detailed information about a deployment.

        Includes replica counts, strategy, selector, and conditions.

        Args:
            deployment_name: Name of the deployment
            namespace: Kubernetes namespace (default: "default")

        Returns:
            JSON with deployment details
        """
        try:
            _, apps_v1 = _get_k8s_client()
            deployment = apps_v1.read_namespaced_deployment(
                name=deployment_name, namespace=namespace
            )

            result = {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": {
                    "desired": deployment.spec.replicas,
                    "ready": deployment.status.ready_replicas or 0,
                    "available": deployment.status.available_replicas or 0,
                    "updated": deployment.status.updated_replicas or 0,
                },
                "strategy": deployment.spec.strategy.type,
                "selector": deployment.spec.selector.match_labels,
                "conditions": [
                    {
                        "type": cond.type,
                        "status": cond.status,
                        "reason": cond.reason,
                        "message": cond.message,
                    }
                    for cond in (deployment.status.conditions or [])
                ],
            }
            return json.dumps(result, indent=2)

        except K8sConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ApiException as e:
            return json.dumps(
                {"error": str(e), "deployment": deployment_name, "namespace": namespace}
            )

    @mcp.tool()
    def get_deployment_history(deployment_name: str, namespace: str = "default") -> str:
        """Get deployment rollout history.

        Shows all replica sets with their revisions, useful for rollback decisions.

        Args:
            deployment_name: Name of the deployment
            namespace: Kubernetes namespace (default: "default")

        Returns:
            JSON with revision history
        """
        try:
            _, apps_v1 = _get_k8s_client()

            deployment = apps_v1.read_namespaced_deployment(
                name=deployment_name, namespace=namespace
            )
            selector = deployment.spec.selector.match_labels
            label_selector = ",".join([f"{k}={v}" for k, v in selector.items()])

            rs_list = apps_v1.list_namespaced_replica_set(
                namespace=namespace, label_selector=label_selector
            )

            history = []
            for rs in rs_list.items:
                revision = rs.metadata.annotations.get(
                    "deployment.kubernetes.io/revision", "unknown"
                )
                history.append(
                    {
                        "revision": revision,
                        "name": rs.metadata.name,
                        "replicas": rs.spec.replicas,
                        "ready": rs.status.ready_replicas or 0,
                        "created": str(rs.metadata.creation_timestamp),
                    }
                )

            history.sort(key=lambda x: x["revision"], reverse=True)
            return json.dumps(
                {
                    "deployment": deployment_name,
                    "namespace": namespace,
                    "history": history,
                },
                indent=2,
            )

        except K8sConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ApiException as e:
            return json.dumps(
                {"error": str(e), "deployment": deployment_name, "namespace": namespace}
            )

    @mcp.tool()
    def get_pod_resources(pod_name: str, namespace: str = "default") -> str:
        """Get combined resource allocation and usage for a pod.

        Shows configured requests/limits alongside actual runtime usage.
        Requires metrics-server in the cluster for usage data.

        Args:
            pod_name: Name of the pod
            namespace: Kubernetes namespace (default: "default")

        Returns:
            JSON with allocation and usage for each container
        """
        try:
            core_v1, _ = _get_k8s_client()
            pod = core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)

            containers_data = []
            for c in pod.spec.containers:
                container_info = {
                    "name": c.name,
                    "allocation": {
                        "requests": {},
                        "limits": {},
                    },
                    "usage": None,
                }

                if c.resources:
                    if c.resources.requests:
                        container_info["allocation"]["requests"] = dict(
                            c.resources.requests
                        )
                    if c.resources.limits:
                        container_info["allocation"]["limits"] = dict(
                            c.resources.limits
                        )

                containers_data.append(container_info)

            # Try to get actual usage from metrics-server
            usage_available = False
            try:
                api = client.CustomObjectsApi()
                metrics = api.get_namespaced_custom_object(
                    group="metrics.k8s.io",
                    version="v1beta1",
                    namespace=namespace,
                    plural="pods",
                    name=pod_name,
                )

                usage_by_name = {
                    m["name"]: {
                        "cpu": m["usage"]["cpu"],
                        "memory": m["usage"]["memory"],
                    }
                    for m in metrics.get("containers", [])
                }

                for container in containers_data:
                    if container["name"] in usage_by_name:
                        container["usage"] = usage_by_name[container["name"]]
                        usage_available = True

            except Exception:
                pass  # Metrics not available

            result = {
                "pod": pod_name,
                "namespace": namespace,
                "node": pod.spec.node_name,
                "status": pod.status.phase,
                "metrics_available": usage_available,
                "containers": containers_data,
            }

            if not usage_available:
                result["metrics_note"] = (
                    "Usage metrics not available. "
                    "Ensure metrics-server is installed in the cluster."
                )

            return json.dumps(result, indent=2)

        except K8sConfigError as e:
            return json.dumps({"error": str(e), "config_required": True})
        except ApiException as e:
            return json.dumps(
                {"error": str(e), "pod": pod_name, "namespace": namespace}
            )
