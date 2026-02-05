"""
Kubernetes tools for pod inspection and debugging.

Supports two modes:
1. Direct mode: Agent runs with kubeconfig access to K8s cluster
2. Gateway mode (SaaS): Commands route through K8s Gateway to customer-deployed agents
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)

# Default timeout for K8s API calls
K8S_API_TIMEOUT = 15

# Lazy-loaded K8s client
_k8s_core_v1 = None
_k8s_apps_v1 = None


class K8sConfigError(Exception):
    """Raised when K8s configuration is missing or invalid."""

    def __init__(self, message: str, missing_config: list[str]):
        super().__init__(message)
        self.missing_config = missing_config


def _get_k8s_client():
    """
    Get Kubernetes client (lazy loaded).

    Raises:
        K8sConfigError: If Kubernetes is not properly configured
    """
    global _k8s_core_v1, _k8s_apps_v1

    if _k8s_core_v1 is not None:
        return _k8s_core_v1, _k8s_apps_v1

    try:
        from kubernetes import client
        from kubernetes import config as k8s_config

        try:
            k8s_config.load_kube_config()
        except Exception:
            try:
                k8s_config.load_incluster_config()
            except Exception as e:
                raise K8sConfigError(
                    f"Failed to load Kubernetes config: {e}",
                    ["kubeconfig (unable to load local or in-cluster config)"],
                )

        _k8s_core_v1 = client.CoreV1Api()
        _k8s_apps_v1 = client.AppsV1Api()
        return _k8s_core_v1, _k8s_apps_v1

    except ImportError:
        raise K8sConfigError(
            "kubernetes package not installed",
            ["pip install kubernetes"],
        )


def _make_error_response(tool_name: str, error: str, **kwargs) -> str:
    """Create a standard error response."""
    return json.dumps(
        {
            "error": error,
            "tool": tool_name,
            **kwargs,
        }
    )


# =============================================================================
# Tool Functions
# =============================================================================


@function_tool
def list_pods(
    namespace: str = "default",
    label_selector: Optional[str] = None,
) -> str:
    """
    List pods in a namespace.

    Args:
        namespace: Kubernetes namespace
        label_selector: Label selector (e.g., "app=myapp")

    Returns:
        List of pod summaries as JSON string
    """
    try:
        start_time = time.time()
        logger.info(
            f"list_pods: namespace={namespace}, label_selector={label_selector}"
        )

        core_v1, _ = _get_k8s_client()
        pods = core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector,
            _request_timeout=K8S_API_TIMEOUT,
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
                        cs.restart_count for cs in (pod.status.container_statuses or [])
                    ),
                    "age": str(pod.metadata.creation_timestamp),
                }
                for pod in pods.items
            ],
        }

        elapsed = time.time() - start_time
        logger.info(
            f"list_pods completed: {len(pods.items)} pods in {elapsed*1000:.0f}ms"
        )
        return json.dumps(result)

    except K8sConfigError as e:
        return _make_error_response("list_pods", str(e), namespace=namespace)
    except Exception as e:
        logger.error(f"list_pods error: {e}")
        return _make_error_response("list_pods", str(e), namespace=namespace)


@function_tool
def describe_pod(
    pod_name: str,
    namespace: str = "default",
) -> str:
    """
    Get detailed information about a pod.

    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace

    Returns:
        Pod details as JSON string
    """
    try:
        start_time = time.time()
        logger.info(f"describe_pod: {namespace}/{pod_name}")

        core_v1, _ = _get_k8s_client()
        pod = core_v1.read_namespaced_pod(
            name=pod_name,
            namespace=namespace,
            _request_timeout=K8S_API_TIMEOUT,
        )

        def _extract_resources(container):
            """Extract resource requests and limits."""
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
                {"type": cond.type, "status": cond.status, "reason": cond.reason}
                for cond in (pod.status.conditions or [])
            ],
        }

        elapsed = time.time() - start_time
        logger.info(
            f"describe_pod completed: status={pod.status.phase} in {elapsed*1000:.0f}ms"
        )
        return json.dumps(result)

    except K8sConfigError as e:
        return _make_error_response(
            "describe_pod", str(e), pod=pod_name, namespace=namespace
        )
    except Exception as e:
        logger.error(f"describe_pod error: {e}")
        return _make_error_response(
            "describe_pod", str(e), pod=pod_name, namespace=namespace
        )


@function_tool
def get_pod_logs(
    pod_name: str,
    namespace: str = "default",
    container: Optional[str] = None,
    tail_lines: int = 100,
) -> str:
    """
    Get logs from a Kubernetes pod.

    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace
        container: Specific container name (optional)
        tail_lines: Number of log lines to retrieve

    Returns:
        Pod logs as JSON string
    """
    try:
        start_time = time.time()
        logger.info(f"get_pod_logs: {namespace}/{pod_name} (tail={tail_lines})")

        core_v1, _ = _get_k8s_client()
        logs = core_v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
            _request_timeout=K8S_API_TIMEOUT,
        )

        elapsed = time.time() - start_time
        logger.info(
            f"get_pod_logs completed: {len(logs) if logs else 0} bytes in {elapsed*1000:.0f}ms"
        )
        return json.dumps({"pod": pod_name, "namespace": namespace, "logs": logs})

    except K8sConfigError as e:
        return _make_error_response(
            "get_pod_logs", str(e), pod=pod_name, namespace=namespace
        )
    except Exception as e:
        logger.error(f"get_pod_logs error: {e}")
        return _make_error_response(
            "get_pod_logs", str(e), pod=pod_name, namespace=namespace
        )


@function_tool
def get_pod_events(
    pod_name: str,
    namespace: str = "default",
) -> str:
    """
    Get events related to a pod.

    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace

    Returns:
        List of events as JSON string
    """
    try:
        start_time = time.time()
        logger.info(f"get_pod_events: {namespace}/{pod_name}")

        core_v1, _ = _get_k8s_client()
        events = core_v1.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name}",
            _request_timeout=K8S_API_TIMEOUT,
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

        elapsed = time.time() - start_time
        logger.info(
            f"get_pod_events completed: {len(events.items)} events in {elapsed*1000:.0f}ms"
        )
        return json.dumps(result)

    except K8sConfigError as e:
        return _make_error_response(
            "get_pod_events", str(e), pod=pod_name, namespace=namespace
        )
    except Exception as e:
        logger.error(f"get_pod_events error: {e}")
        return _make_error_response(
            "get_pod_events", str(e), pod=pod_name, namespace=namespace
        )


@function_tool
def describe_deployment(
    deployment_name: str,
    namespace: str = "default",
) -> str:
    """
    Get detailed information about a deployment.

    Args:
        deployment_name: Name of the deployment
        namespace: Kubernetes namespace

    Returns:
        Deployment details as JSON string
    """
    try:
        start_time = time.time()
        logger.info(f"describe_deployment: {namespace}/{deployment_name}")

        _, apps_v1 = _get_k8s_client()
        deployment = apps_v1.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
            _request_timeout=K8S_API_TIMEOUT,
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

        elapsed = time.time() - start_time
        logger.info(
            f"describe_deployment completed: ready={deployment.status.ready_replicas or 0}/{deployment.spec.replicas} in {elapsed*1000:.0f}ms"
        )
        return json.dumps(result)

    except K8sConfigError as e:
        return _make_error_response(
            "describe_deployment",
            str(e),
            deployment=deployment_name,
            namespace=namespace,
        )
    except Exception as e:
        logger.error(f"describe_deployment error: {e}")
        return _make_error_response(
            "describe_deployment",
            str(e),
            deployment=deployment_name,
            namespace=namespace,
        )


@function_tool
def get_deployment_history(
    deployment_name: str,
    namespace: str = "default",
) -> str:
    """
    Get deployment rollout history.

    Args:
        deployment_name: Name of the deployment
        namespace: Kubernetes namespace

    Returns:
        List of replica sets with revision history as JSON string
    """
    try:
        start_time = time.time()
        logger.info(f"get_deployment_history: {namespace}/{deployment_name}")

        _, apps_v1 = _get_k8s_client()

        # Get deployment to find selector
        deployment = apps_v1.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
            _request_timeout=K8S_API_TIMEOUT,
        )
        selector = deployment.spec.selector.match_labels
        label_selector = ",".join([f"{k}={v}" for k, v in selector.items()])

        # Get replica sets
        rs_list = apps_v1.list_namespaced_replica_set(
            namespace=namespace,
            label_selector=label_selector,
            _request_timeout=K8S_API_TIMEOUT,
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

        # Sort by revision
        history.sort(key=lambda x: x["revision"], reverse=True)

        elapsed = time.time() - start_time
        logger.info(
            f"get_deployment_history completed: {len(history)} revisions in {elapsed*1000:.0f}ms"
        )
        return json.dumps(
            {
                "deployment": deployment_name,
                "namespace": namespace,
                "history": history,
            }
        )

    except K8sConfigError as e:
        return _make_error_response(
            "get_deployment_history",
            str(e),
            deployment=deployment_name,
            namespace=namespace,
        )
    except Exception as e:
        logger.error(f"get_deployment_history error: {e}")
        return _make_error_response(
            "get_deployment_history",
            str(e),
            deployment=deployment_name,
            namespace=namespace,
        )


@function_tool
def describe_service(
    service_name: str,
    namespace: str = "default",
) -> str:
    """
    Get information about a Kubernetes service.

    Args:
        service_name: Name of the service
        namespace: Kubernetes namespace

    Returns:
        Service details including endpoints as JSON string
    """
    try:
        start_time = time.time()
        logger.info(f"describe_service: {namespace}/{service_name}")

        core_v1, _ = _get_k8s_client()
        service = core_v1.read_namespaced_service(
            name=service_name,
            namespace=namespace,
            _request_timeout=K8S_API_TIMEOUT,
        )

        # Get endpoints
        endpoint_list = []
        try:
            endpoints = core_v1.read_namespaced_endpoints(
                name=service_name,
                namespace=namespace,
                _request_timeout=K8S_API_TIMEOUT,
            )
            for subset in endpoints.subsets or []:
                for address in subset.addresses or []:
                    endpoint_list.append(
                        {
                            "ip": address.ip,
                            "ready": True,
                            "target": (
                                address.target_ref.name if address.target_ref else None
                            ),
                        }
                    )
        except Exception:
            pass

        result = {
            "name": service.metadata.name,
            "namespace": service.metadata.namespace,
            "type": service.spec.type,
            "cluster_ip": service.spec.cluster_ip,
            "ports": [
                {
                    "name": port.name,
                    "port": port.port,
                    "target_port": str(port.target_port),
                    "protocol": port.protocol,
                }
                for port in service.spec.ports
            ],
            "selector": service.spec.selector or {},
            "endpoints": endpoint_list,
        }

        elapsed = time.time() - start_time
        logger.info(
            f"describe_service completed: {len(endpoint_list)} endpoints in {elapsed*1000:.0f}ms"
        )
        return json.dumps(result)

    except K8sConfigError as e:
        return _make_error_response(
            "describe_service", str(e), service=service_name, namespace=namespace
        )
    except Exception as e:
        logger.error(f"describe_service error: {e}")
        return _make_error_response(
            "describe_service", str(e), service=service_name, namespace=namespace
        )


@function_tool
def list_namespaces() -> str:
    """
    List all namespaces in the Kubernetes cluster.

    Returns:
        List of namespace summaries as JSON string
    """
    try:
        start_time = time.time()
        logger.info("list_namespaces")

        core_v1, _ = _get_k8s_client()
        namespaces = core_v1.list_namespace(_request_timeout=K8S_API_TIMEOUT)

        result = {
            "namespace_count": len(namespaces.items),
            "namespaces": [
                {
                    "name": ns.metadata.name,
                    "status": ns.status.phase,
                    "labels": ns.metadata.labels or {},
                    "age": str(ns.metadata.creation_timestamp),
                }
                for ns in namespaces.items
            ],
        }

        elapsed = time.time() - start_time
        logger.info(
            f"list_namespaces completed: {len(namespaces.items)} namespaces in {elapsed*1000:.0f}ms"
        )
        return json.dumps(result)

    except K8sConfigError as e:
        return _make_error_response("list_namespaces", str(e))
    except Exception as e:
        logger.error(f"list_namespaces error: {e}")
        return _make_error_response("list_namespaces", str(e))


# =============================================================================
# Register Tools
# =============================================================================

register_tool("list_pods", list_pods)
register_tool("describe_pod", describe_pod)
register_tool("get_pod_logs", get_pod_logs)
register_tool("get_pod_events", get_pod_events)
register_tool("describe_deployment", describe_deployment)
register_tool("get_deployment_history", get_deployment_history)
register_tool("describe_service", describe_service)
register_tool("list_namespaces", list_namespaces)
