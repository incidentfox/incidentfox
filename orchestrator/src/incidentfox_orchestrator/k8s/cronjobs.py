"""
CronJob management for scheduled jobs.

Supports:
1. AI Pipeline - ingests data, runs gap analysis, generates proposals
2. Dependency Discovery - discovers service dependencies from observability data

CronJob naming conventions:
- ai-pipeline-{org_id}-{team_node_id}
- dep-discovery-{org_id}-{team_node_id}
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

try:
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False
    ApiException = Exception  # type: ignore

from incidentfox_orchestrator.k8s.client import K8sClient, get_k8s_client


def _log(event: str, **fields) -> None:
    """Structured logging."""
    try:
        payload = {
            "service": "orchestrator",
            "module": "k8s.cronjobs",
            "event": event,
            **fields,
        }
        print(json.dumps(payload, default=str))
    except Exception:
        print(f"{event} {fields}")


def _sanitize_name(value: str) -> str:
    """Sanitize a string for use in K8s resource names."""
    # K8s names must be lowercase alphanumeric with hyphens
    return value.lower().replace("_", "-").replace(".", "-")[:63]


def _get_cronjob_name(org_id: str, team_node_id: str) -> str:
    """Generate CronJob name for a team."""
    org_safe = _sanitize_name(org_id)[:20]
    team_safe = _sanitize_name(team_node_id)[:30]
    return f"ai-pipeline-{org_safe}-{team_safe}"


def create_pipeline_cronjob(
    org_id: str,
    team_node_id: str,
    *,
    schedule: str = "0 2 * * *",  # Default: 2 AM daily
    pipeline_image: Optional[str] = None,
    config_service_url: Optional[str] = None,
    k8s_client: Optional[K8sClient] = None,
) -> Dict[str, Any]:
    """
    Create a CronJob for scheduled AI Pipeline runs.

    Args:
        org_id: Organization ID
        team_node_id: Team node ID
        schedule: Cron schedule expression (default: daily at 2 AM)
        pipeline_image: Docker image for the pipeline (default from env)
        config_service_url: URL to config service (default from env)
        k8s_client: K8s client instance (optional)

    Returns:
        Dict with cronjob metadata (name, namespace, schedule)
    """
    if not K8S_AVAILABLE:
        _log("k8s_not_available", operation="create_pipeline_cronjob")
        return {"error": "kubernetes package not installed"}

    kc = k8s_client or get_k8s_client()
    name = _get_cronjob_name(org_id, team_node_id)
    namespace = kc.namespace

    # Get configuration from environment
    image = pipeline_image or os.getenv(
        "AI_PIPELINE_IMAGE", "incidentfox/ai-pipeline:latest"
    )
    cfg_url = config_service_url or os.getenv(
        "CONFIG_SERVICE_URL", "http://config-service:8080"
    )

    labels = {
        "app.kubernetes.io/name": "ai-pipeline",
        "app.kubernetes.io/component": "scheduled-ingestion",
        "app.kubernetes.io/managed-by": "incidentfox-orchestrator",
        "incidentfox.io/org-id": _sanitize_name(org_id),
        "incidentfox.io/team-node-id": _sanitize_name(team_node_id),
    }

    # Build CronJob spec
    cronjob = client.V1CronJob(
        api_version="batch/v1",
        kind="CronJob",
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels=labels,
        ),
        spec=client.V1CronJobSpec(
            schedule=schedule,
            concurrency_policy="Forbid",  # Don't run if previous still running
            successful_jobs_history_limit=3,
            failed_jobs_history_limit=3,
            job_template=client.V1JobTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1JobSpec(
                    ttl_seconds_after_finished=86400,  # Clean up after 24h
                    backoff_limit=2,
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(labels=labels),
                        spec=client.V1PodSpec(
                            restart_policy="Never",
                            service_account_name=os.getenv(
                                "AI_PIPELINE_SERVICE_ACCOUNT", "ai-pipeline"
                            ),
                            containers=[
                                client.V1Container(
                                    name="ai-pipeline",
                                    image=image,
                                    image_pull_policy="Always",
                                    command=[
                                        "python",
                                        "-m",
                                        "ai_learning_pipeline",
                                        "run-scheduled",
                                    ],
                                    args=[
                                        "--team-id",
                                        team_node_id,
                                        "--org-id",
                                        org_id,
                                    ],
                                    env=[
                                        client.V1EnvVar(name="ORG_ID", value=org_id),
                                        client.V1EnvVar(
                                            name="TEAM_NODE_ID", value=team_node_id
                                        ),
                                        client.V1EnvVar(
                                            name="CONFIG_SERVICE_URL", value=cfg_url
                                        ),
                                    ],
                                    resources=client.V1ResourceRequirements(
                                        requests={"cpu": "500m", "memory": "1Gi"},
                                        limits={"cpu": "2", "memory": "4Gi"},
                                    ),
                                )
                            ],
                        ),
                    ),
                ),
            ),
        ),
    )

    try:
        # Try to create; if exists, update
        try:
            kc.batch_v1.create_namespaced_cron_job(
                namespace=namespace,
                body=cronjob,
            )
            _log(
                "cronjob_created",
                name=name,
                namespace=namespace,
                org_id=org_id,
                team_node_id=team_node_id,
                schedule=schedule,
            )
        except ApiException as e:
            if e.status == 409:  # Already exists
                kc.batch_v1.replace_namespaced_cron_job(
                    name=name,
                    namespace=namespace,
                    body=cronjob,
                )
                _log(
                    "cronjob_updated",
                    name=name,
                    namespace=namespace,
                    org_id=org_id,
                    team_node_id=team_node_id,
                    schedule=schedule,
                )
            else:
                raise

        return {
            "name": name,
            "namespace": namespace,
            "schedule": schedule,
            "org_id": org_id,
            "team_node_id": team_node_id,
            "created": True,
        }

    except ApiException as e:
        _log(
            "cronjob_create_failed",
            name=name,
            namespace=namespace,
            error=str(e),
            status=e.status if hasattr(e, "status") else None,
        )
        return {
            "name": name,
            "namespace": namespace,
            "error": str(e),
            "status": getattr(e, "status", None),
        }


def delete_pipeline_cronjob(
    org_id: str,
    team_node_id: str,
    *,
    k8s_client: Optional[K8sClient] = None,
) -> Dict[str, Any]:
    """
    Delete a team's AI Pipeline CronJob.

    Args:
        org_id: Organization ID
        team_node_id: Team node ID
        k8s_client: K8s client instance (optional)

    Returns:
        Dict with deletion status
    """
    if not K8S_AVAILABLE:
        _log("k8s_not_available", operation="delete_pipeline_cronjob")
        return {"error": "kubernetes package not installed"}

    kc = k8s_client or get_k8s_client()
    name = _get_cronjob_name(org_id, team_node_id)
    namespace = kc.namespace

    try:
        kc.batch_v1.delete_namespaced_cron_job(
            name=name,
            namespace=namespace,
            body=client.V1DeleteOptions(
                propagation_policy="Foreground",  # Delete associated jobs too
            ),
        )
        _log(
            "cronjob_deleted",
            name=name,
            namespace=namespace,
            org_id=org_id,
            team_node_id=team_node_id,
        )
        return {
            "name": name,
            "namespace": namespace,
            "deleted": True,
        }

    except ApiException as e:
        if e.status == 404:
            _log(
                "cronjob_not_found",
                name=name,
                namespace=namespace,
            )
            return {
                "name": name,
                "namespace": namespace,
                "deleted": False,
                "reason": "not_found",
            }

        _log(
            "cronjob_delete_failed",
            name=name,
            namespace=namespace,
            error=str(e),
        )
        return {
            "name": name,
            "namespace": namespace,
            "error": str(e),
        }


def get_pipeline_cronjob(
    org_id: str,
    team_node_id: str,
    *,
    k8s_client: Optional[K8sClient] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get information about a team's AI Pipeline CronJob.

    Args:
        org_id: Organization ID
        team_node_id: Team node ID
        k8s_client: K8s client instance (optional)

    Returns:
        Dict with cronjob info, or None if not found
    """
    if not K8S_AVAILABLE:
        return None

    kc = k8s_client or get_k8s_client()
    name = _get_cronjob_name(org_id, team_node_id)
    namespace = kc.namespace

    try:
        cj = kc.batch_v1.read_namespaced_cron_job(
            name=name,
            namespace=namespace,
        )

        return {
            "name": cj.metadata.name,
            "namespace": cj.metadata.namespace,
            "schedule": cj.spec.schedule,
            "suspended": cj.spec.suspend or False,
            "last_schedule_time": (
                cj.status.last_schedule_time.isoformat()
                if cj.status.last_schedule_time
                else None
            ),
            "active_jobs": len(cj.status.active or []),
        }

    except ApiException as e:
        if e.status == 404:
            return None
        raise


# =============================================================================
# Dependency Discovery CronJob
# =============================================================================


def _get_dependency_cronjob_name(org_id: str, team_node_id: str) -> str:
    """Generate CronJob name for dependency discovery."""
    org_safe = _sanitize_name(org_id)[:20]
    team_safe = _sanitize_name(team_node_id)[:30]
    return f"dep-discovery-{org_safe}-{team_safe}"


def create_dependency_discovery_cronjob(
    org_id: str,
    team_node_id: str,
    *,
    schedule: str = "0 */2 * * *",  # Default: every 2 hours
    discovery_image: Optional[str] = None,
    config_service_url: Optional[str] = None,
    k8s_client: Optional[K8sClient] = None,
) -> Dict[str, Any]:
    """
    Create a CronJob for scheduled dependency discovery.

    Args:
        org_id: Organization ID
        team_node_id: Team node ID
        schedule: Cron schedule expression (default: every 2 hours)
        discovery_image: Docker image for the discovery job (default from env)
        config_service_url: URL to config service (default from env)
        k8s_client: K8s client instance (optional)

    Returns:
        Dict with cronjob metadata (name, namespace, schedule)
    """
    if not K8S_AVAILABLE:
        _log("k8s_not_available", operation="create_dependency_discovery_cronjob")
        return {"error": "kubernetes package not installed"}

    kc = k8s_client or get_k8s_client()
    name = _get_dependency_cronjob_name(org_id, team_node_id)
    namespace = kc.namespace

    # Get configuration from environment
    image = discovery_image or os.getenv(
        "DEPENDENCY_SERVICE_IMAGE", "incidentfox/dependency-service:latest"
    )
    cfg_url = config_service_url or os.getenv(
        "CONFIG_SERVICE_URL", "http://config-service:8080"
    )

    labels = {
        "app.kubernetes.io/name": "dependency-discovery",
        "app.kubernetes.io/component": "scheduled-discovery",
        "app.kubernetes.io/managed-by": "incidentfox-orchestrator",
        "incidentfox.io/org-id": _sanitize_name(org_id),
        "incidentfox.io/team-node-id": _sanitize_name(team_node_id),
    }

    # Build CronJob spec
    cronjob = client.V1CronJob(
        api_version="batch/v1",
        kind="CronJob",
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels=labels,
        ),
        spec=client.V1CronJobSpec(
            schedule=schedule,
            concurrency_policy="Forbid",  # Don't run if previous still running
            successful_jobs_history_limit=3,
            failed_jobs_history_limit=3,
            job_template=client.V1JobTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1JobSpec(
                    ttl_seconds_after_finished=86400,  # Clean up after 24h
                    backoff_limit=2,
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(labels=labels),
                        spec=client.V1PodSpec(
                            restart_policy="Never",
                            service_account_name=os.getenv(
                                "DEPENDENCY_SERVICE_ACCOUNT", "dependency-discovery"
                            ),
                            containers=[
                                client.V1Container(
                                    name="dependency-discovery",
                                    image=image,
                                    image_pull_policy="Always",
                                    command=[
                                        "python",
                                        "-m",
                                        "dependency_service.scripts.run_discovery",
                                    ],
                                    args=[
                                        "--team-id",
                                        team_node_id,
                                    ],
                                    env=[
                                        client.V1EnvVar(name="ORG_ID", value=org_id),
                                        client.V1EnvVar(
                                            name="TEAM_ID", value=team_node_id
                                        ),
                                        client.V1EnvVar(
                                            name="CONFIG_SERVICE_URL", value=cfg_url
                                        ),
                                    ],
                                    resources=client.V1ResourceRequirements(
                                        requests={"cpu": "250m", "memory": "512Mi"},
                                        limits={"cpu": "1", "memory": "2Gi"},
                                    ),
                                )
                            ],
                        ),
                    ),
                ),
            ),
        ),
    )

    try:
        # Try to create; if exists, update
        try:
            kc.batch_v1.create_namespaced_cron_job(
                namespace=namespace,
                body=cronjob,
            )
            _log(
                "dependency_cronjob_created",
                name=name,
                namespace=namespace,
                org_id=org_id,
                team_node_id=team_node_id,
                schedule=schedule,
            )
        except ApiException as e:
            if e.status == 409:  # Already exists
                kc.batch_v1.replace_namespaced_cron_job(
                    name=name,
                    namespace=namespace,
                    body=cronjob,
                )
                _log(
                    "dependency_cronjob_updated",
                    name=name,
                    namespace=namespace,
                    org_id=org_id,
                    team_node_id=team_node_id,
                    schedule=schedule,
                )
            else:
                raise

        return {
            "name": name,
            "namespace": namespace,
            "schedule": schedule,
            "org_id": org_id,
            "team_node_id": team_node_id,
            "created": True,
        }

    except ApiException as e:
        _log(
            "dependency_cronjob_create_failed",
            name=name,
            namespace=namespace,
            error=str(e),
            status=e.status if hasattr(e, "status") else None,
        )
        return {
            "name": name,
            "namespace": namespace,
            "error": str(e),
            "status": getattr(e, "status", None),
        }


def delete_dependency_discovery_cronjob(
    org_id: str,
    team_node_id: str,
    *,
    k8s_client: Optional[K8sClient] = None,
) -> Dict[str, Any]:
    """
    Delete a team's dependency discovery CronJob.

    Args:
        org_id: Organization ID
        team_node_id: Team node ID
        k8s_client: K8s client instance (optional)

    Returns:
        Dict with deletion status
    """
    if not K8S_AVAILABLE:
        _log("k8s_not_available", operation="delete_dependency_discovery_cronjob")
        return {"error": "kubernetes package not installed"}

    kc = k8s_client or get_k8s_client()
    name = _get_dependency_cronjob_name(org_id, team_node_id)
    namespace = kc.namespace

    try:
        kc.batch_v1.delete_namespaced_cron_job(
            name=name,
            namespace=namespace,
            body=client.V1DeleteOptions(
                propagation_policy="Foreground",
            ),
        )
        _log(
            "dependency_cronjob_deleted",
            name=name,
            namespace=namespace,
            org_id=org_id,
            team_node_id=team_node_id,
        )
        return {
            "name": name,
            "namespace": namespace,
            "deleted": True,
        }

    except ApiException as e:
        if e.status == 404:
            _log(
                "dependency_cronjob_not_found",
                name=name,
                namespace=namespace,
            )
            return {
                "name": name,
                "namespace": namespace,
                "deleted": False,
                "reason": "not_found",
            }

        _log(
            "dependency_cronjob_delete_failed",
            name=name,
            namespace=namespace,
            error=str(e),
        )
        return {
            "name": name,
            "namespace": namespace,
            "error": str(e),
        }
