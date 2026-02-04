"""K8s command executor using the kubernetes Python client."""

import asyncio
from typing import Any, Dict, Optional

import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = structlog.get_logger(__name__)

# Timeout for K8s API calls
K8S_API_TIMEOUT = 15


class K8sExecutor:
    """Executes K8s commands using the official kubernetes Python client."""

    def __init__(self):
        """Initialize K8s client with in-cluster config."""
        try:
            config.load_incluster_config()
            logger.info("loaded_incluster_config")
        except config.ConfigException:
            # Fallback to kubeconfig for local development
            try:
                config.load_kube_config()
                logger.info("loaded_kubeconfig")
            except config.ConfigException as e:
                logger.error("failed_to_load_k8s_config", error=str(e))
                raise

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    async def execute(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a K8s command.

        Args:
            command: Command name (e.g., "list_pods", "get_pod_logs")
            params: Command parameters

        Returns:
            Command result as dict

        Raises:
            ValueError: If command is unknown
            Exception: If command execution fails
        """
        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            raise ValueError(f"Unknown command: {command}")

        # Run in thread pool to avoid blocking
        return await asyncio.to_thread(handler, **params)

    def _cmd_list_pods(
        self,
        namespace: str = "default",
        label_selector: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List pods in a namespace."""
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector,
                _request_timeout=K8S_API_TIMEOUT,
            )

            return {
                "namespace": namespace,
                "pod_count": len(pods.items),
                "pods": [
                    {
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "status": pod.status.phase,
                        "ready": self._get_pod_ready_status(pod),
                        "restarts": self._get_pod_restart_count(pod),
                        "node": pod.spec.node_name,
                        "created_at": (
                            pod.metadata.creation_timestamp.isoformat()
                            if pod.metadata.creation_timestamp
                            else None
                        ),
                    }
                    for pod in pods.items
                ],
            }
        except ApiException as e:
            logger.error("list_pods_failed", namespace=namespace, error=str(e))
            raise Exception(f"Failed to list pods: {e.reason}")

    def _cmd_get_pod_logs(
        self,
        pod_name: str,
        namespace: str = "default",
        container: Optional[str] = None,
        tail_lines: int = 100,
        previous: bool = False,
    ) -> Dict[str, Any]:
        """Get logs from a pod."""
        try:
            logs = self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=tail_lines,
                previous=previous,
                _request_timeout=K8S_API_TIMEOUT,
            )

            return {
                "pod_name": pod_name,
                "namespace": namespace,
                "container": container,
                "logs": logs,
                "line_count": len(logs.split("\n")) if logs else 0,
            }
        except ApiException as e:
            logger.error("get_pod_logs_failed", pod_name=pod_name, error=str(e))
            raise Exception(f"Failed to get pod logs: {e.reason}")

    def _cmd_describe_pod(
        self,
        pod_name: str,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        """Get detailed information about a pod."""
        try:
            pod = self.core_v1.read_namespaced_pod(
                name=pod_name,
                namespace=namespace,
                _request_timeout=K8S_API_TIMEOUT,
            )

            return {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "node": pod.spec.node_name,
                "ip": pod.status.pod_ip,
                "host_ip": pod.status.host_ip,
                "created_at": (
                    pod.metadata.creation_timestamp.isoformat()
                    if pod.metadata.creation_timestamp
                    else None
                ),
                "labels": pod.metadata.labels or {},
                "annotations": pod.metadata.annotations or {},
                "containers": [
                    {
                        "name": c.name,
                        "image": c.image,
                        "ready": self._get_container_ready(pod, c.name),
                        "restart_count": self._get_container_restart_count(pod, c.name),
                    }
                    for c in pod.spec.containers
                ],
                "conditions": [
                    {
                        "type": cond.type,
                        "status": cond.status,
                        "reason": cond.reason,
                        "message": cond.message,
                    }
                    for cond in (pod.status.conditions or [])
                ],
            }
        except ApiException as e:
            logger.error("describe_pod_failed", pod_name=pod_name, error=str(e))
            raise Exception(f"Failed to describe pod: {e.reason}")

    def _cmd_get_pod_events(
        self,
        pod_name: str,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        """Get events related to a pod."""
        try:
            events = self.core_v1.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={pod_name}",
                _request_timeout=K8S_API_TIMEOUT,
            )

            return {
                "pod_name": pod_name,
                "namespace": namespace,
                "event_count": len(events.items),
                "events": [
                    {
                        "type": event.type,
                        "reason": event.reason,
                        "message": event.message,
                        "count": event.count,
                        "first_timestamp": (
                            event.first_timestamp.isoformat()
                            if event.first_timestamp
                            else None
                        ),
                        "last_timestamp": (
                            event.last_timestamp.isoformat()
                            if event.last_timestamp
                            else None
                        ),
                    }
                    for event in sorted(
                        events.items,
                        key=lambda e: e.last_timestamp or e.first_timestamp or "",
                        reverse=True,
                    )
                ],
            }
        except ApiException as e:
            logger.error("get_pod_events_failed", pod_name=pod_name, error=str(e))
            raise Exception(f"Failed to get pod events: {e.reason}")

    def _cmd_describe_deployment(
        self,
        deployment_name: str,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        """Get detailed information about a deployment."""
        try:
            deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                _request_timeout=K8S_API_TIMEOUT,
            )

            return {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": {
                    "desired": deployment.spec.replicas,
                    "ready": deployment.status.ready_replicas or 0,
                    "available": deployment.status.available_replicas or 0,
                    "updated": deployment.status.updated_replicas or 0,
                },
                "strategy": (
                    deployment.spec.strategy.type if deployment.spec.strategy else None
                ),
                "labels": deployment.metadata.labels or {},
                "selector": deployment.spec.selector.match_labels or {},
                "created_at": (
                    deployment.metadata.creation_timestamp.isoformat()
                    if deployment.metadata.creation_timestamp
                    else None
                ),
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
        except ApiException as e:
            logger.error(
                "describe_deployment_failed",
                deployment_name=deployment_name,
                error=str(e),
            )
            raise Exception(f"Failed to describe deployment: {e.reason}")

    def _cmd_list_namespaces(self) -> Dict[str, Any]:
        """List all namespaces."""
        try:
            namespaces = self.core_v1.list_namespace(
                _request_timeout=K8S_API_TIMEOUT,
            )

            return {
                "namespace_count": len(namespaces.items),
                "namespaces": [
                    {
                        "name": ns.metadata.name,
                        "status": ns.status.phase,
                        "created_at": (
                            ns.metadata.creation_timestamp.isoformat()
                            if ns.metadata.creation_timestamp
                            else None
                        ),
                    }
                    for ns in namespaces.items
                ],
            }
        except ApiException as e:
            logger.error("list_namespaces_failed", error=str(e))
            raise Exception(f"Failed to list namespaces: {e.reason}")

    def get_cluster_info(self) -> Dict[str, Any]:
        """Get cluster information for registration."""
        try:
            # Get node count
            nodes = self.core_v1.list_node(_request_timeout=K8S_API_TIMEOUT)
            node_count = len(nodes.items)

            # Get namespace count
            namespaces = self.core_v1.list_namespace(_request_timeout=K8S_API_TIMEOUT)
            namespace_count = len(namespaces.items)

            # Get version info
            version_info = client.VersionApi().get_code(
                _request_timeout=K8S_API_TIMEOUT
            )

            return {
                "kubernetes_version": version_info.git_version,
                "node_count": node_count,
                "namespace_count": namespace_count,
            }
        except Exception as e:
            logger.error("get_cluster_info_failed", error=str(e))
            return {}

    # Helper methods
    def _get_pod_ready_status(self, pod) -> str:
        """Get pod ready status as 'ready/total' string."""
        containers = pod.spec.containers or []
        ready_count = 0
        if pod.status.container_statuses:
            ready_count = sum(1 for cs in pod.status.container_statuses if cs.ready)
        return f"{ready_count}/{len(containers)}"

    def _get_pod_restart_count(self, pod) -> int:
        """Get total restart count for all containers in pod."""
        if not pod.status.container_statuses:
            return 0
        return sum(cs.restart_count for cs in pod.status.container_statuses)

    def _get_container_ready(self, pod, container_name: str) -> bool:
        """Get ready status for a specific container."""
        if not pod.status.container_statuses:
            return False
        for cs in pod.status.container_statuses:
            if cs.name == container_name:
                return cs.ready
        return False

    def _get_container_restart_count(self, pod, container_name: str) -> int:
        """Get restart count for a specific container."""
        if not pod.status.container_statuses:
            return 0
        for cs in pod.status.container_statuses:
            if cs.name == container_name:
                return cs.restart_count
        return 0
