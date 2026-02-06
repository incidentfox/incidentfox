"""
Remediation tools for taking corrective actions.

Provides safe remediation proposals that require human approval.
All remediations go through an approval queue for safety.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from ..core.agent import function_tool
from . import register_tool

logger = logging.getLogger(__name__)

# Configuration
CONFIG_SERVICE_URL = os.getenv(
    "CONFIG_SERVICE_URL", "http://incidentfox-config-service:8080"
)
REMEDIATION_API_URL = os.getenv("REMEDIATION_API_URL", CONFIG_SERVICE_URL)


def _get_client():
    """Get HTTP client for remediation API."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError("httpx not installed: pip install httpx")
    return httpx.Client(base_url=REMEDIATION_API_URL, timeout=30.0)


# =============================================================================
# SAFE ACTIONS (Read-only, no approval needed)
# =============================================================================


@function_tool
def get_current_replicas(deployment: str, namespace: str = "default") -> str:
    """
    Get current replica count for a deployment.

    This is a READ-ONLY action that doesn't require approval.

    Args:
        deployment: Deployment name
        namespace: Kubernetes namespace

    Returns:
        JSON with current and desired replica counts
    """
    if not deployment:
        return json.dumps({"ok": False, "error": "deployment is required"})

    logger.info(f"get_current_replicas: deployment={deployment}, namespace={namespace}")

    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()

        apps_v1 = client.AppsV1Api()
        deploy = apps_v1.read_namespaced_deployment(deployment, namespace)

        return json.dumps(
            {
                "ok": True,
                "deployment": deployment,
                "namespace": namespace,
                "desired_replicas": deploy.spec.replicas,
                "ready_replicas": deploy.status.ready_replicas or 0,
                "available_replicas": deploy.status.available_replicas or 0,
            }
        )

    except Exception as e:
        logger.error(f"get_current_replicas error: {e}")
        return json.dumps({"ok": False, "error": str(e)})


# =============================================================================
# REMEDIATION PROPOSALS (Require human approval)
# =============================================================================


@function_tool
def propose_remediation(
    action_type: str,
    target: str,
    reason: str,
    parameters: str = "{}",
    urgency: str = "medium",
    rollback_action: str = "",
) -> str:
    """
    Propose a remediation action for human approval.

    Supported action_types:
    - restart_pod: Restart a specific pod
    - restart_deployment: Rolling restart of a deployment
    - scale_deployment: Change replica count
    - rollback_deployment: Rollback to previous revision
    - delete_pod: Delete a stuck/crashed pod

    Args:
        action_type: Type of remediation action
        target: Target resource (e.g., "deployment/api-service")
        reason: Why this action is needed
        parameters: JSON string of action-specific parameters
        urgency: "low", "medium", "high", "critical"
        rollback_action: How to undo this action if it fails

    Returns:
        JSON with proposal status
    """
    if not action_type or not target or not reason:
        return json.dumps(
            {"ok": False, "error": "action_type, target, and reason are required"}
        )

    logger.info(f"propose_remediation: action={action_type}, target={target}")

    try:
        params = json.loads(parameters) if parameters else {}
    except json.JSONDecodeError:
        params = {"raw": parameters}

    proposal = {
        "action_type": action_type,
        "target": target,
        "reason": reason,
        "parameters": params,
        "urgency": urgency,
        "rollback_action": rollback_action or f"Undo {action_type} on {target}",
        "proposed_at": datetime.utcnow().isoformat(),
        "status": "pending_approval",
    }

    # Try to submit to remediation API
    try:
        with _get_client() as client:
            response = client.post(
                "/api/v1/remediations",
                json=proposal,
                headers={"Content-Type": "application/json"},
            )
            if response.status_code in (200, 201):
                data = response.json()
                logger.info(f"remediation_proposed: id={data.get('id')}")
                return json.dumps(
                    {
                        "ok": True,
                        "status": "pending_approval",
                        "proposal_id": data.get("id"),
                        "message": f"Remediation proposed: {action_type} on {target}. Awaiting approval.",
                        "urgency": urgency,
                    }
                )
    except Exception as e:
        logger.warning(f"remediation_api_error: {e}")

    # Fallback: Log the proposal
    logger.info(f"remediation_proposed_local: {proposal}")
    return json.dumps(
        {
            "ok": True,
            "status": "logged_for_review",
            "proposal": proposal,
            "message": f"Remediation logged: {action_type} on {target}. Please review manually.",
            "note": "Remediation API unavailable - proposal logged but not queued.",
        }
    )


@function_tool
def propose_pod_restart(
    pod_name: str,
    namespace: str = "default",
    reason: str = "",
) -> str:
    """
    Propose restarting a specific pod.

    Use when:
    - Pod is in CrashLoopBackOff
    - Pod is unresponsive
    - Pod has a memory leak

    Args:
        pod_name: Name of the pod to restart
        namespace: Kubernetes namespace
        reason: Why the restart is needed

    Returns:
        JSON with proposal status
    """
    if not pod_name:
        return json.dumps({"ok": False, "error": "pod_name is required"})

    return propose_remediation(
        action_type="restart_pod",
        target=f"pod/{pod_name}",
        reason=reason or "Pod needs restart",
        parameters=json.dumps({"namespace": namespace, "pod_name": pod_name}),
        urgency="medium",
        rollback_action="Pod will be automatically recreated by its controller",
    )


@function_tool
def propose_deployment_restart(
    deployment: str,
    namespace: str = "default",
    reason: str = "",
) -> str:
    """
    Propose a rolling restart of a deployment.

    Use when:
    - Multiple pods in the deployment need restart
    - Configuration was updated externally
    - Memory/connection leaks affecting all pods

    Args:
        deployment: Deployment name
        namespace: Kubernetes namespace
        reason: Why restart is needed

    Returns:
        JSON with proposal status
    """
    if not deployment:
        return json.dumps({"ok": False, "error": "deployment is required"})

    return propose_remediation(
        action_type="restart_deployment",
        target=f"deployment/{deployment}",
        reason=reason or "Deployment needs rolling restart",
        parameters=json.dumps({"namespace": namespace, "deployment": deployment}),
        urgency="medium",
        rollback_action="Previous pods will be replaced; no rollback needed",
    )


@function_tool
def propose_scale_deployment(
    deployment: str,
    replicas: int,
    namespace: str = "default",
    reason: str = "",
) -> str:
    """
    Propose scaling a deployment up or down.

    Use when:
    - High load requires more replicas
    - Cost optimization (scale down)
    - Capacity issues causing errors

    Args:
        deployment: Deployment name
        replicas: Desired replica count
        namespace: Kubernetes namespace
        reason: Why scaling is needed

    Returns:
        JSON with proposal status
    """
    if not deployment:
        return json.dumps({"ok": False, "error": "deployment is required"})

    # Get current replicas for rollback info
    current = get_current_replicas(deployment, namespace)
    current_data = json.loads(current)
    current_replicas = current_data.get("desired_replicas", "unknown")

    return propose_remediation(
        action_type="scale_deployment",
        target=f"deployment/{deployment}",
        reason=reason or f"Scale to {replicas} replicas",
        parameters=json.dumps(
            {
                "namespace": namespace,
                "deployment": deployment,
                "replicas": replicas,
            }
        ),
        urgency="medium" if replicas > 0 else "high",
        rollback_action=f"Scale back to {current_replicas} replicas",
    )


@function_tool
def list_pending_remediations() -> str:
    """
    List all pending remediation proposals awaiting approval.

    Returns:
        JSON with list of pending remediations
    """
    logger.info("list_pending_remediations")

    try:
        with _get_client() as client:
            response = client.get("/api/v1/remediations?status=pending")
            if response.status_code == 200:
                return json.dumps(
                    {
                        "ok": True,
                        "remediations": response.json(),
                    }
                )
    except Exception as e:
        logger.warning(f"list_remediations_failed: {e}")

    return json.dumps(
        {
            "ok": False,
            "error": "Could not fetch pending remediations",
            "remediations": [],
        }
    )


@function_tool
def get_remediation_status(proposal_id: str) -> str:
    """
    Get the status of a remediation proposal.

    Args:
        proposal_id: ID of the proposal

    Returns:
        JSON with proposal status and execution details
    """
    if not proposal_id:
        return json.dumps({"ok": False, "error": "proposal_id is required"})

    logger.info(f"get_remediation_status: id={proposal_id}")

    try:
        with _get_client() as client:
            response = client.get(f"/api/v1/remediations/{proposal_id}")
            if response.status_code == 200:
                return json.dumps(
                    {
                        "ok": True,
                        **response.json(),
                    }
                )
    except Exception as e:
        logger.warning(f"get_remediation_failed: {e}")

    return json.dumps(
        {
            "ok": False,
            "error": f"Could not fetch remediation {proposal_id}",
        }
    )


# Register tools
register_tool("get_current_replicas", get_current_replicas)
register_tool("propose_remediation", propose_remediation)
register_tool("propose_pod_restart", propose_pod_restart)
register_tool("propose_deployment_restart", propose_deployment_restart)
register_tool("propose_scale_deployment", propose_scale_deployment)
register_tool("list_pending_remediations", list_pending_remediations)
register_tool("get_remediation_status", get_remediation_status)
