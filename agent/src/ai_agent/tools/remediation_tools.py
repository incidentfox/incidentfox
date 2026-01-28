"""
Remediation tools for taking corrective actions.

These tools allow agents to PROPOSE remediation actions that require
human approval before execution. This ensures safety while enabling
automated incident response.

Flow:
1. Agent investigates and identifies a fix
2. Agent calls propose_remediation() with the action
3. Human reviews in UI and approves/rejects
4. If approved, the action is executed automatically
5. Results are logged for audit

IMPORTANT: Agents cannot execute dangerous actions directly.
All remediations go through the approval queue.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from agents import function_tool

from ..core.logging import get_logger

logger = get_logger(__name__)

# Configuration
# Use same default as agent_runner.py for k8s service discovery
CONFIG_SERVICE_URL = os.getenv("CONFIG_SERVICE_URL", "http://incidentfox-config-service:8080")
REMEDIATION_API_URL = os.getenv("REMEDIATION_API_URL", CONFIG_SERVICE_URL)


def _get_client():
    """Get HTTP client for remediation API."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError("httpx not installed")
    return httpx.Client(base_url=REMEDIATION_API_URL, timeout=30.0)


# =============================================================================
# SAFE ACTIONS (Can execute directly - read-only or low-risk)
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
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except:
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
        return json.dumps({"ok": False, "error": str(e)})


# =============================================================================
# REMEDIATION PROPOSALS (Require approval before execution)
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

    This is the PRIMARY way to suggest fixes. The action will be queued
    for human review before execution.

    Supported action_types:
    - restart_pod: Restart a specific pod
    - restart_deployment: Rolling restart of a deployment
    - scale_deployment: Change replica count
    - rollback_deployment: Rollback to previous revision
    - delete_pod: Delete a stuck/crashed pod (will be recreated)
    - patch_configmap: Update a ConfigMap
    - drain_node: Drain a node for maintenance

    Args:
        action_type: Type of remediation action
        target: Target resource (e.g., "deployment/api-service" or "pod/web-abc123")
        reason: Why this action is needed (from investigation)
        parameters: JSON string of action-specific parameters
        urgency: "low", "medium", "high", "critical"
        rollback_action: How to undo this action if it fails

    Returns:
        JSON with proposal ID and status

    Example:
        propose_remediation(
            action_type="restart_deployment",
            target="deployment/api-service",
            reason="Memory leak detected, pods at 95% memory usage",
            parameters='{"namespace": "production"}',
            urgency="high",
            rollback_action="Deployment will auto-recover, no manual rollback needed"
        )
    """
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
                logger.info(
                    "remediation_proposed",
                    action=action_type,
                    target=target,
                    proposal_id=data.get("id"),
                )
                return json.dumps(
                    {
                        "ok": True,
                        "status": "pending_approval",
                        "proposal_id": data.get("id"),
                        "message": f"Remediation proposed: {action_type} on {target}. Awaiting human approval.",
                        "next_step": "A human operator will review this proposal in the IncidentFox UI.",
                        "urgency": urgency,
                    }
                )
            else:
                # API not available, log locally
                logger.warning(
                    "remediation_api_unavailable", status=response.status_code
                )
    except Exception as e:
        logger.warning("remediation_api_error", error=str(e))

    # Fallback: Log the proposal even if API is unavailable
    logger.info("remediation_proposed_local", proposal=proposal)
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
    pod_name: str, namespace: str = "default", reason: str = ""
) -> str:
    """
    Propose restarting a specific pod.

    Use when:
    - Pod is in CrashLoopBackOff
    - Pod is unresponsive
    - Pod has a memory leak

    The pod will be deleted and Kubernetes will recreate it.

    Args:
        pod_name: Name of the pod to restart
        namespace: Kubernetes namespace
        reason: Why the restart is needed

    Returns:
        JSON with proposal status
    """
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
    deployment: str, namespace: str = "default", reason: str = ""
) -> str:
    """
    Propose a rolling restart of a deployment.

    Use when:
    - Multiple pods in the deployment need restart
    - Configuration was updated externally
    - Memory/connection leaks affecting all pods

    This triggers a rolling restart (zero-downtime if replicas > 1).

    Args:
        deployment: Deployment name
        namespace: Kubernetes namespace
        reason: Why restart is needed

    Returns:
        JSON with proposal status
    """
    return propose_remediation(
        action_type="restart_deployment",
        target=f"deployment/{deployment}",
        reason=reason or "Deployment needs rolling restart",
        parameters=json.dumps({"namespace": namespace, "deployment": deployment}),
        urgency="medium",
        rollback_action="Previous pods will be replaced with new ones; no rollback needed",
    )


@function_tool
def propose_scale_deployment(
    deployment: str, replicas: int, namespace: str = "default", reason: str = ""
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
    # Get current replicas for the rollback action
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
def propose_deployment_rollback(
    deployment: str, namespace: str = "default", revision: int = 0, reason: str = ""
) -> str:
    """
    Propose rolling back a deployment to a previous revision.

    Use when:
    - Recent deployment caused issues
    - Need to revert to last known good state

    Args:
        deployment: Deployment name
        namespace: Kubernetes namespace
        revision: Revision to rollback to (0 = previous)
        reason: Why rollback is needed

    Returns:
        JSON with proposal status
    """
    return propose_remediation(
        action_type="rollback_deployment",
        target=f"deployment/{deployment}",
        reason=reason or "Rollback to previous revision",
        parameters=json.dumps(
            {
                "namespace": namespace,
                "deployment": deployment,
                "revision": revision,
            }
        ),
        urgency="high",
        rollback_action="Re-deploy the current version if rollback causes issues",
    )


@function_tool
def list_pending_remediations() -> str:
    """
    List all pending remediation proposals awaiting approval.

    Returns:
        JSON with list of pending remediations
    """
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
        logger.warning("list_remediations_failed", error=str(e))

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
        logger.warning("get_remediation_failed", error=str(e))

    return json.dumps(
        {
            "ok": False,
            "error": f"Could not fetch remediation {proposal_id}",
        }
    )


# =============================================================================
# EMERGENCY ACTIONS (Still require approval but marked as critical)
# =============================================================================


@function_tool
def propose_emergency_action(
    action_type: str, target: str, reason: str, parameters: str = "{}"
) -> str:
    """
    Propose an EMERGENCY remediation action.

    Use only for critical situations:
    - Service is completely down
    - Security incident requiring immediate action
    - Data corruption in progress

    Emergency actions are:
    - Flagged as CRITICAL urgency
    - Sent to on-call immediately
    - May have shorter approval SLA

    Args:
        action_type: Type of action
        target: Target resource
        reason: Why this is an emergency
        parameters: Action parameters as JSON

    Returns:
        JSON with proposal status
    """
    return propose_remediation(
        action_type=action_type,
        target=target,
        reason=f"[EMERGENCY] {reason}",
        parameters=parameters,
        urgency="critical",
        rollback_action="Manual intervention may be required",
    )
