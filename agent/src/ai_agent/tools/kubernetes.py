"""Kubernetes tools for pod inspection and debugging."""

import json
import time
import traceback
from pathlib import Path

from agents import function_tool
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

from ..core.config import get_config
from ..core.logging import get_logger

logger = get_logger(__name__)

# Default timeout for K8s API calls in seconds
# This prevents tools from hanging indefinitely on slow/unresponsive clusters
K8S_API_TIMEOUT = 15


class K8sConfigError(Exception):
    """Raised when K8s configuration is missing or invalid."""

    def __init__(self, message: str, missing_config: list[str]):
        super().__init__(message)
        self.missing_config = missing_config


def _check_k8s_config() -> tuple[bool, list[str]]:
    """
    Check if Kubernetes is properly configured.

    Returns:
        Tuple of (is_configured, missing_items)
    """
    config = get_config()
    missing = []

    # Check if K8S_ENABLED is set
    if not config.kubernetes.enabled:
        missing.append("K8S_ENABLED=true (Kubernetes integration is disabled)")

    # Check for kubeconfig availability
    kubeconfig_path = config.kubernetes.kubeconfig_path
    if kubeconfig_path:
        if not Path(kubeconfig_path).exists():
            missing.append(f"K8S_KUBECONFIG_PATH={kubeconfig_path} (file not found)")
    else:
        # Check default locations
        default_kubeconfig = Path.home() / ".kube" / "config"
        in_cluster_token = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")

        if not default_kubeconfig.exists() and not in_cluster_token.exists():
            missing.append(
                "kubeconfig (no ~/.kube/config found and not running in-cluster)"
            )

    return len(missing) == 0, missing


def _make_config_required_response(tool_name: str, missing: list[str]) -> str:
    """
    Create a structured response indicating configuration is required.

    This response is designed to be detected by the agent/CLI and trigger
    an interactive configuration flow.
    """
    return json.dumps(
        {
            "config_required": True,
            "integration": "kubernetes",
            "tool": tool_name,
            "message": "Kubernetes is not configured. Please provide the required configuration.",
            "missing_config": missing,
            "help": {
                "description": "To enable Kubernetes integration, you need to:",
                "options": [
                    "Set K8S_ENABLED=true in your .env file",
                    "Ensure ~/.kube/config exists with valid cluster credentials",
                    "Or run the agent inside a Kubernetes cluster (in-cluster config)",
                ],
                "docs_url": "https://docs.incidentfox.ai/integrations/kubernetes",
            },
        }
    )


def _get_k8s_client():
    """
    Get Kubernetes client.

    Raises:
        K8sConfigError: If Kubernetes is not properly configured
    """
    # First check if K8s is configured
    is_configured, missing = _check_k8s_config()
    if not is_configured:
        raise K8sConfigError(
            "Kubernetes is not configured",
            missing,
        )

    try:
        k8s_config.load_kube_config()
    except (FileNotFoundError, k8s_config.ConfigException):
        try:
            # Fallback to in-cluster config if kubeconfig not found
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException as e:
            raise K8sConfigError(
                f"Failed to load Kubernetes config: {e}",
                ["kubeconfig (unable to load local or in-cluster config)"],
            )
    return client.CoreV1Api(), client.AppsV1Api()


@function_tool(strict_mode=False)
def get_pod_logs(
    pod_name: str,
    namespace: str = "default",
    container: str | None = None,
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
        logger.info(
            "k8s_tool_start",
            tool="get_pod_logs",
            pod_name=pod_name,
            namespace=namespace,
        )

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
            "k8s_tool_complete",
            tool="get_pod_logs",
            pod_name=pod_name,
            namespace=namespace,
            elapsed_ms=int(elapsed * 1000),
            log_length=len(logs) if logs else 0,
        )
        return json.dumps({"pod": pod_name, "namespace": namespace, "logs": logs})

    except K8sConfigError as e:
        logger.warning(
            "k8s_not_configured", tool="get_pod_logs", missing=e.missing_config
        )
        return _make_config_required_response("get_pod_logs", e.missing_config)

    except ApiException as e:
        logger.error("failed_to_get_pod_logs", error=str(e), pod=pod_name)
        return json.dumps({"error": str(e), "pod": pod_name, "namespace": namespace})

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="get_pod_logs",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            pod_name=pod_name,
            namespace=namespace,
        )
        return json.dumps(
            {
                "error": f"Unexpected error: {type(e).__name__}: {e}",
                "pod": pod_name,
                "namespace": namespace,
            }
        )


@function_tool(strict_mode=False)
def describe_pod(pod_name: str, namespace: str = "default") -> str:
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
        logger.info(
            "k8s_tool_start",
            tool="describe_pod",
            pod_name=pod_name,
            namespace=namespace,
        )

        core_v1, _ = _get_k8s_client()
        pod = core_v1.read_namespaced_pod(
            name=pod_name,
            namespace=namespace,
            _request_timeout=K8S_API_TIMEOUT,
        )

        def _extract_resources(container):
            """Extract resource requests and limits from a container spec."""
            resources = {}
            if container.resources:
                if container.resources.requests:
                    resources["requests"] = {
                        k: v for k, v in container.resources.requests.items()
                    }
                if container.resources.limits:
                    resources["limits"] = {
                        k: v for k, v in container.resources.limits.items()
                    }
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
            "k8s_tool_complete",
            tool="describe_pod",
            pod_name=pod_name,
            namespace=namespace,
            elapsed_ms=int(elapsed * 1000),
            status=pod.status.phase,
        )
        return json.dumps(result)

    except K8sConfigError as e:
        logger.warning(
            "k8s_not_configured", tool="describe_pod", missing=e.missing_config
        )
        return _make_config_required_response("describe_pod", e.missing_config)

    except ApiException as e:
        logger.error("failed_to_describe_pod", error=str(e), pod=pod_name)
        return json.dumps({"error": str(e), "pod": pod_name, "namespace": namespace})

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="describe_pod",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            pod_name=pod_name,
            namespace=namespace,
        )
        return json.dumps(
            {
                "error": f"Unexpected error: {type(e).__name__}: {e}",
                "pod": pod_name,
                "namespace": namespace,
            }
        )


@function_tool(strict_mode=False)
def list_pods(
    namespace: str = "default",
    label_selector: str | None = None,
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
            "k8s_tool_start",
            tool="list_pods",
            namespace=namespace,
            label_selector=label_selector,
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
            "k8s_tool_complete",
            tool="list_pods",
            namespace=namespace,
            label_selector=label_selector,
            elapsed_ms=int(elapsed * 1000),
            pod_count=len(pods.items),
        )
        return json.dumps(result)

    except K8sConfigError as e:
        logger.warning("k8s_not_configured", tool="list_pods", missing=e.missing_config)
        return _make_config_required_response("list_pods", e.missing_config)

    except ApiException as e:
        logger.error("failed_to_list_pods", error=str(e), namespace=namespace)
        return json.dumps({"error": str(e), "namespace": namespace})

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="list_pods",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            namespace=namespace,
        )
        return json.dumps(
            {
                "error": f"Unexpected error: {type(e).__name__}: {e}",
                "namespace": namespace,
            }
        )


@function_tool(strict_mode=False)
def list_namespaces() -> str:
    """
    List all namespaces in the Kubernetes cluster.

    Returns:
        List of namespace summaries as JSON string
    """
    try:
        start_time = time.time()
        logger.info("k8s_tool_start", tool="list_namespaces")

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
            "k8s_tool_complete",
            tool="list_namespaces",
            elapsed_ms=int(elapsed * 1000),
            namespace_count=len(namespaces.items),
        )
        return json.dumps(result)

    except K8sConfigError as e:
        logger.warning(
            "k8s_not_configured", tool="list_namespaces", missing=e.missing_config
        )
        return _make_config_required_response("list_namespaces", e.missing_config)

    except ApiException as e:
        logger.error("failed_to_list_namespaces", error=str(e))
        return json.dumps({"error": str(e)})

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="list_namespaces",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
        )
        return json.dumps(
            {
                "error": f"Unexpected error: {type(e).__name__}: {e}",
            }
        )


@function_tool(strict_mode=False)
def get_pod_events(pod_name: str, namespace: str = "default") -> str:
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
        logger.info(
            "k8s_tool_start",
            tool="get_pod_events",
            pod_name=pod_name,
            namespace=namespace,
        )

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
            "k8s_tool_complete",
            tool="get_pod_events",
            pod_name=pod_name,
            namespace=namespace,
            elapsed_ms=int(elapsed * 1000),
            event_count=len(events.items),
        )
        return json.dumps(result)

    except K8sConfigError as e:
        logger.warning(
            "k8s_not_configured", tool="get_pod_events", missing=e.missing_config
        )
        return _make_config_required_response("get_pod_events", e.missing_config)

    except ApiException as e:
        logger.error("failed_to_get_events", error=str(e), pod=pod_name)
        return json.dumps({"error": str(e), "pod": pod_name, "namespace": namespace})

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="get_pod_events",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            pod_name=pod_name,
            namespace=namespace,
        )
        return json.dumps(
            {
                "error": f"Unexpected error: {type(e).__name__}: {e}",
                "pod": pod_name,
                "namespace": namespace,
            }
        )


@function_tool(strict_mode=False)
def describe_deployment(deployment_name: str, namespace: str = "default") -> str:
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
        logger.info(
            "k8s_tool_start",
            tool="describe_deployment",
            deployment_name=deployment_name,
            namespace=namespace,
        )

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
            "k8s_tool_complete",
            tool="describe_deployment",
            deployment_name=deployment_name,
            namespace=namespace,
            elapsed_ms=int(elapsed * 1000),
            replicas_ready=deployment.status.ready_replicas or 0,
        )
        return json.dumps(result)

    except K8sConfigError as e:
        logger.warning(
            "k8s_not_configured", tool="describe_deployment", missing=e.missing_config
        )
        return _make_config_required_response("describe_deployment", e.missing_config)

    except ApiException as e:
        logger.error(
            "failed_to_describe_deployment", error=str(e), deployment=deployment_name
        )
        return json.dumps(
            {"error": str(e), "deployment": deployment_name, "namespace": namespace}
        )

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="describe_deployment",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            deployment_name=deployment_name,
            namespace=namespace,
        )
        return json.dumps(
            {
                "error": f"Unexpected error: {type(e).__name__}: {e}",
                "deployment": deployment_name,
                "namespace": namespace,
            }
        )


@function_tool(strict_mode=False)
def get_deployment_history(deployment_name: str, namespace: str = "default") -> str:
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
        logger.info(
            "k8s_tool_start",
            tool="get_deployment_history",
            deployment_name=deployment_name,
            namespace=namespace,
        )

        _, apps_v1 = _get_k8s_client()

        # Get replica sets for this deployment
        deployment = apps_v1.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
            _request_timeout=K8S_API_TIMEOUT,
        )
        selector = deployment.spec.selector.match_labels
        label_selector = ",".join([f"{k}={v}" for k, v in selector.items()])

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
            "k8s_tool_complete",
            tool="get_deployment_history",
            deployment_name=deployment_name,
            namespace=namespace,
            elapsed_ms=int(elapsed * 1000),
            revision_count=len(history),
        )
        return json.dumps(
            {"deployment": deployment_name, "namespace": namespace, "history": history}
        )

    except K8sConfigError as e:
        logger.warning(
            "k8s_not_configured",
            tool="get_deployment_history",
            missing=e.missing_config,
        )
        return _make_config_required_response(
            "get_deployment_history", e.missing_config
        )

    except ApiException as e:
        logger.error(
            "failed_to_get_deployment_history", error=str(e), deployment=deployment_name
        )
        return json.dumps(
            {"error": str(e), "deployment": deployment_name, "namespace": namespace}
        )

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="get_deployment_history",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            deployment_name=deployment_name,
            namespace=namespace,
        )
        return json.dumps(
            {
                "error": f"Unexpected error: {type(e).__name__}: {e}",
                "deployment": deployment_name,
                "namespace": namespace,
            }
        )


@function_tool(strict_mode=False)
def describe_service(service_name: str, namespace: str = "default") -> str:
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
        logger.info(
            "k8s_tool_start",
            tool="describe_service",
            service_name=service_name,
            namespace=namespace,
        )

        core_v1, _ = _get_k8s_client()
        service = core_v1.read_namespaced_service(
            name=service_name,
            namespace=namespace,
            _request_timeout=K8S_API_TIMEOUT,
        )

        # Get endpoints
        try:
            endpoints = core_v1.read_namespaced_endpoints(
                name=service_name,
                namespace=namespace,
                _request_timeout=K8S_API_TIMEOUT,
            )
            endpoint_list = []
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
            endpoint_list = []

        result = {
            "name": service.metadata.name,
            "namespace": service.metadata.namespace,
            "type": service.spec.type,
            "cluster_ip": service.spec.cluster_ip,
            "external_ips": service.spec.external_i_ps or [],
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
            "k8s_tool_complete",
            tool="describe_service",
            service_name=service_name,
            namespace=namespace,
            elapsed_ms=int(elapsed * 1000),
            endpoint_count=len(endpoint_list),
        )
        return json.dumps(result)

    except K8sConfigError as e:
        logger.warning(
            "k8s_not_configured", tool="describe_service", missing=e.missing_config
        )
        return _make_config_required_response("describe_service", e.missing_config)

    except ApiException as e:
        logger.error("failed_to_describe_service", error=str(e), service=service_name)
        return json.dumps(
            {"error": str(e), "service": service_name, "namespace": namespace}
        )

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="describe_service",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            service_name=service_name,
            namespace=namespace,
        )
        return json.dumps(
            {
                "error": f"Unexpected error: {type(e).__name__}: {e}",
                "service": service_name,
                "namespace": namespace,
            }
        )


@function_tool(strict_mode=False)
def get_pod_resource_usage(pod_name: str, namespace: str = "default") -> str:
    """
    Get resource usage for a pod (requires metrics-server).

    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace

    Returns:
        CPU and memory usage as JSON string
    """
    # First check if K8s is configured
    is_configured, missing = _check_k8s_config()
    if not is_configured:
        logger.warning(
            "k8s_not_configured", tool="get_pod_resource_usage", missing=missing
        )
        return _make_config_required_response("get_pod_resource_usage", missing)

    try:
        start_time = time.time()
        logger.info(
            "k8s_tool_start",
            tool="get_pod_resource_usage",
            pod_name=pod_name,
            namespace=namespace,
        )

        from kubernetes import client as k8s_client_module

        api = k8s_client_module.CustomObjectsApi()

        metrics = api.get_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="pods",
            name=pod_name,
            _request_timeout=K8S_API_TIMEOUT,
        )

        containers = []
        for container in metrics.get("containers", []):
            containers.append(
                {
                    "name": container["name"],
                    "cpu": container["usage"]["cpu"],
                    "memory": container["usage"]["memory"],
                }
            )

        result = {
            "pod": pod_name,
            "namespace": namespace,
            "timestamp": metrics.get("timestamp"),
            "containers": containers,
        }

        elapsed = time.time() - start_time
        logger.info(
            "k8s_tool_complete",
            tool="get_pod_resource_usage",
            pod_name=pod_name,
            namespace=namespace,
            elapsed_ms=int(elapsed * 1000),
            container_count=len(containers),
        )
        return json.dumps(result)

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="get_pod_resource_usage",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            pod_name=pod_name,
            namespace=namespace,
        )
        # Return graceful error - metrics-server might not be installed
        return json.dumps(
            {
                "error": f"Metrics not available ({type(e).__name__}: {e})",
                "pod": pod_name,
                "namespace": namespace,
            }
        )


@function_tool(strict_mode=False)
def get_pod_resources(pod_name: str, namespace: str = "default") -> str:
    """
    Get combined resource allocation and usage for a pod.

    Shows both the configured requests/limits (allocation) and actual
    runtime usage (from metrics-server) side-by-side for each container.

    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace

    Returns:
        Combined resource allocation and usage as JSON string
    """
    try:
        start_time = time.time()
        logger.info(
            "k8s_tool_start",
            tool="get_pod_resources",
            pod_name=pod_name,
            namespace=namespace,
        )

        core_v1, _ = _get_k8s_client()
        pod = core_v1.read_namespaced_pod(
            name=pod_name,
            namespace=namespace,
            _request_timeout=K8S_API_TIMEOUT,
        )

        # Get allocation from pod spec
        containers_data = []
        for c in pod.spec.containers:
            container_info = {
                "name": c.name,
                "allocation": {
                    "requests": {},
                    "limits": {},
                },
                "usage": None,  # Will be populated if metrics available
            }

            if c.resources:
                if c.resources.requests:
                    container_info["allocation"]["requests"] = {
                        k: v for k, v in c.resources.requests.items()
                    }
                if c.resources.limits:
                    container_info["allocation"]["limits"] = {
                        k: v for k, v in c.resources.limits.items()
                    }

            containers_data.append(container_info)

        # Try to get actual usage from metrics-server
        usage_available = False
        try:
            from kubernetes import client as k8s_client_module

            api = k8s_client_module.CustomObjectsApi()
            metrics = api.get_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods",
                name=pod_name,
                _request_timeout=K8S_API_TIMEOUT,
            )

            # Map usage to containers
            usage_by_name = {
                m["name"]: {"cpu": m["usage"]["cpu"], "memory": m["usage"]["memory"]}
                for m in metrics.get("containers", [])
            }

            for container in containers_data:
                if container["name"] in usage_by_name:
                    container["usage"] = usage_by_name[container["name"]]
                    usage_available = True

        except Exception as metrics_error:
            logger.debug(
                "metrics_not_available",
                pod=pod_name,
                error=str(metrics_error),
            )

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

        elapsed = time.time() - start_time
        logger.info(
            "k8s_tool_complete",
            tool="get_pod_resources",
            pod_name=pod_name,
            namespace=namespace,
            elapsed_ms=int(elapsed * 1000),
            metrics_available=usage_available,
        )
        return json.dumps(result)

    except K8sConfigError as e:
        logger.warning(
            "k8s_not_configured", tool="get_pod_resources", missing=e.missing_config
        )
        return _make_config_required_response("get_pod_resources", e.missing_config)

    except ApiException as e:
        logger.error("failed_to_get_pod_resources", error=str(e), pod=pod_name)
        return json.dumps({"error": str(e), "pod": pod_name, "namespace": namespace})

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(
            "k8s_tool_unexpected_error",
            tool="get_pod_resources",
            error=str(e),
            error_type=type(e).__name__,
            traceback=tb_str,
            pod_name=pod_name,
            namespace=namespace,
        )
        return json.dumps(
            {
                "error": f"Unexpected error: {type(e).__name__}: {e}",
                "pod": pod_name,
                "namespace": namespace,
            }
        )
