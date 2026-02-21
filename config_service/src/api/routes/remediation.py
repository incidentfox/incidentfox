"""
Remediation API routes.

Handles the approval workflow for remediation actions proposed by agents.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.models import PendingRemediation
from ...db.session import get_db
from ..auth import AdminPrincipal, require_admin

logger = structlog.get_logger(__name__)


# =============================================================================
# Request/Response Models
# =============================================================================


class ProposeRemediationRequest(BaseModel):
    action_type: str
    target: str
    reason: str
    parameters: dict = Field(default_factory=dict)
    urgency: str = "medium"
    rollback_action: Optional[str] = None
    correlation_id: Optional[str] = None
    agent_name: Optional[str] = None
    investigation_summary: Optional[str] = None


class RemediationResponse(BaseModel):
    id: str
    action_type: str
    target: str
    reason: str
    parameters: dict
    urgency: str
    rollback_action: Optional[str]
    status: str
    proposed_at: datetime
    proposed_by: Optional[str]
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[str]
    review_comment: Optional[str]
    executed_at: Optional[datetime]
    execution_result: Optional[dict]
    execution_error: Optional[str]


class ReviewRemediationRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    comment: Optional[str] = None


# =============================================================================
# Router
# =============================================================================

router = APIRouter(prefix="/api/v1", tags=["remediation"])


@router.post("/remediations", response_model=RemediationResponse, status_code=201)
async def propose_remediation(
    body: ProposeRemediationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    x_org_id: str = Header(default="org-default"),
    x_team_node_id: str = Header(default=None),
    x_proposed_by: str = Header(default="agent"),
):
    """
    Propose a remediation action for approval.

    Called by agents when they identify a fix.
    """
    remediation = PendingRemediation(
        id=f"rem-{uuid.uuid4().hex[:12]}",
        org_id=x_org_id,
        team_node_id=x_team_node_id,
        action_type=body.action_type,
        target=body.target,
        reason=body.reason,
        parameters=body.parameters,
        urgency=body.urgency,
        rollback_action=body.rollback_action,
        correlation_id=body.correlation_id,
        agent_name=body.agent_name,
        investigation_summary=body.investigation_summary,
        proposed_by=x_proposed_by,
        status="pending",
    )

    db.add(remediation)
    db.commit()
    db.refresh(remediation)

    logger.info(
        "remediation_proposed",
        id=remediation.id,
        action_type=body.action_type,
        target=body.target,
        urgency=body.urgency,
    )

    # Send notification for critical urgency
    if body.urgency == "critical":
        background_tasks.add_task(send_critical_remediation_alert, remediation)

    return _to_response(remediation)


@router.get("/remediations", response_model=List[RemediationResponse])
async def list_remediations(
    status: Optional[str] = None,
    urgency: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """List pending remediation actions."""
    query = db.query(PendingRemediation).filter(
        PendingRemediation.org_id == admin.org_id
    )

    if status:
        query = query.filter(PendingRemediation.status == status)
    if urgency:
        query = query.filter(PendingRemediation.urgency == urgency)

    query = query.order_by(PendingRemediation.proposed_at.desc()).limit(limit)

    return [_to_response(r) for r in query.all()]


@router.get("/remediations/{remediation_id}", response_model=RemediationResponse)
async def get_remediation(
    remediation_id: str,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """Get details of a remediation proposal."""
    remediation = (
        db.query(PendingRemediation)
        .filter(
            PendingRemediation.id == remediation_id,
            PendingRemediation.org_id == admin.org_id,
        )
        .first()
    )

    if not remediation:
        raise HTTPException(status_code=404, detail="Remediation not found")

    return _to_response(remediation)


@router.post(
    "/remediations/{remediation_id}/review", response_model=RemediationResponse
)
async def review_remediation(
    remediation_id: str,
    body: ReviewRemediationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """Approve or reject a remediation proposal."""
    remediation = (
        db.query(PendingRemediation)
        .filter(
            PendingRemediation.id == remediation_id,
            PendingRemediation.org_id == admin.org_id,
        )
        .first()
    )

    if not remediation:
        raise HTTPException(status_code=404, detail="Remediation not found")

    if remediation.status != "pending":
        raise HTTPException(
            status_code=400, detail=f"Remediation already {remediation.status}"
        )

    reviewer = admin.subject if hasattr(admin, "subject") else "admin"

    remediation.reviewed_at = datetime.now(timezone.utc)
    remediation.reviewed_by = reviewer
    remediation.review_comment = body.comment

    if body.action == "approve":
        remediation.status = "approved"
        db.commit()

        logger.info(
            "remediation_approved",
            id=remediation_id,
            action=remediation.action_type,
            target=remediation.target,
            by=reviewer,
        )

        # Execute the remediation in background
        background_tasks.add_task(execute_remediation, remediation.id, db)

    elif body.action == "reject":
        remediation.status = "rejected"
        db.commit()

        logger.info(
            "remediation_rejected",
            id=remediation_id,
            action=remediation.action_type,
            by=reviewer,
        )

    db.refresh(remediation)
    return _to_response(remediation)


@router.post(
    "/remediations/{remediation_id}/rollback", response_model=RemediationResponse
)
async def rollback_remediation(
    remediation_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """Rollback an executed remediation."""
    remediation = (
        db.query(PendingRemediation)
        .filter(
            PendingRemediation.id == remediation_id,
            PendingRemediation.org_id == admin.org_id,
        )
        .first()
    )

    if not remediation:
        raise HTTPException(status_code=404, detail="Remediation not found")

    if remediation.status != "executed":
        raise HTTPException(
            status_code=400, detail="Can only rollback executed remediations"
        )

    if remediation.rolled_back:
        raise HTTPException(status_code=400, detail="Already rolled back")

    background_tasks.add_task(execute_rollback, remediation.id, db)

    return _to_response(remediation)


# =============================================================================
# Execution Logic
# =============================================================================


def execute_remediation(remediation_id: str, db: Session):
    """Execute an approved remediation action."""
    from ...db.session import SessionLocal

    # Use a new session for background task
    session = SessionLocal()
    try:
        remediation = (
            session.query(PendingRemediation)
            .filter(PendingRemediation.id == remediation_id)
            .first()
        )

        if not remediation or remediation.status != "approved":
            return

        logger.info(
            "executing_remediation",
            id=remediation_id,
            action=remediation.action_type,
            target=remediation.target,
        )

        try:
            result = _execute_action(
                action_type=remediation.action_type,
                target=remediation.target,
                parameters=remediation.parameters or {},
            )

            remediation.status = "executed"
            remediation.executed_at = datetime.now(timezone.utc)
            remediation.execution_result = result

            logger.info("remediation_executed", id=remediation_id, result=result)

        except Exception as e:
            remediation.status = "failed"
            remediation.executed_at = datetime.now(timezone.utc)
            remediation.execution_error = str(e)

            logger.error("remediation_failed", id=remediation_id, error=str(e))

        session.commit()

    finally:
        session.close()


def execute_rollback(remediation_id: str, db: Session):
    """Execute rollback for a remediation."""
    from ...db.session import SessionLocal

    session = SessionLocal()
    try:
        remediation = (
            session.query(PendingRemediation)
            .filter(PendingRemediation.id == remediation_id)
            .first()
        )

        if not remediation:
            return

        logger.info("executing_rollback", id=remediation_id)

        try:
            # Execute rollback based on action type
            result = _execute_rollback_action(
                action_type=remediation.action_type,
                target=remediation.target,
                parameters=remediation.parameters or {},
                original_result=remediation.execution_result,
            )

            remediation.rolled_back = True
            remediation.rollback_at = datetime.now(timezone.utc)
            remediation.rollback_result = result

            logger.info("rollback_executed", id=remediation_id, result=result)

        except Exception as e:
            logger.error("rollback_failed", id=remediation_id, error=str(e))

        session.commit()

    finally:
        session.close()


def _execute_action(action_type: str, target: str, parameters: dict) -> dict:
    """Execute the actual remediation action."""
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()

    namespace = parameters.get("namespace", "default")

    if action_type == "restart_pod":
        pod_name = parameters.get("pod_name") or target.split("/")[-1]
        v1 = client.CoreV1Api()
        v1.delete_namespaced_pod(pod_name, namespace)
        return {"deleted_pod": pod_name, "namespace": namespace}

    elif action_type == "restart_deployment":
        deployment = parameters.get("deployment") or target.split("/")[-1]
        apps_v1 = client.AppsV1Api()

        # Trigger rolling restart by patching annotation
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.now(
                                timezone.utc
                            ).isoformat()
                        }
                    }
                }
            }
        }
        apps_v1.patch_namespaced_deployment(deployment, namespace, patch)
        return {"restarted_deployment": deployment, "namespace": namespace}

    elif action_type == "scale_deployment":
        deployment = parameters.get("deployment") or target.split("/")[-1]
        replicas = parameters.get("replicas", 1)
        apps_v1 = client.AppsV1Api()

        # Get current replicas for rollback info
        current = apps_v1.read_namespaced_deployment(deployment, namespace)
        previous_replicas = current.spec.replicas

        # Scale
        patch = {"spec": {"replicas": replicas}}
        apps_v1.patch_namespaced_deployment(deployment, namespace, patch)

        return {
            "scaled_deployment": deployment,
            "namespace": namespace,
            "previous_replicas": previous_replicas,
            "new_replicas": replicas,
        }

    elif action_type == "rollback_deployment":
        deployment = parameters.get("deployment") or target.split("/")[-1]
        revision = parameters.get("revision", 0)

        # Use kubectl rollout undo via subprocess (K8s API rollback is complex)
        import subprocess

        cmd = [
            "kubectl",
            "rollout",
            "undo",
            f"deployment/{deployment}",
            "-n",
            namespace,
        ]
        if revision:
            cmd.extend(["--to-revision", str(revision)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        return {
            "rolled_back_deployment": deployment,
            "namespace": namespace,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    elif action_type == "delete_pod":
        pod_name = parameters.get("pod_name") or target.split("/")[-1]
        v1 = client.CoreV1Api()
        v1.delete_namespaced_pod(pod_name, namespace)
        return {"deleted_pod": pod_name, "namespace": namespace}

    else:
        raise ValueError(f"Unknown action type: {action_type}")


def _execute_rollback_action(
    action_type: str,
    target: str,
    parameters: dict,
    original_result: dict,
) -> dict:
    """Execute rollback for an action."""
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()

    namespace = parameters.get("namespace", "default")

    if action_type == "scale_deployment":
        # Scale back to original
        deployment = parameters.get("deployment") or target.split("/")[-1]
        previous_replicas = original_result.get("previous_replicas", 1)

        apps_v1 = client.AppsV1Api()
        patch = {"spec": {"replicas": previous_replicas}}
        apps_v1.patch_namespaced_deployment(deployment, namespace, patch)

        return {
            "scaled_deployment": deployment,
            "replicas": previous_replicas,
        }

    # Most actions don't have automatic rollback
    return {"message": "Manual rollback may be required", "action_type": action_type}


def send_critical_remediation_alert(remediation: PendingRemediation):
    """Send alert for critical remediation."""
    from ...services.email_service import send_email

    admin_emails = os.getenv("ADMIN_NOTIFICATION_EMAILS", "").split(",")
    admin_emails = [e.strip() for e in admin_emails if e.strip()]

    if not admin_emails:
        return

    subject = f"🚨 CRITICAL Remediation Needs Approval: {remediation.action_type}"
    html_body = f"""
    <h2>Critical Remediation Proposed</h2>
    <p><strong>Action:</strong> {remediation.action_type}</p>
    <p><strong>Target:</strong> {remediation.target}</p>
    <p><strong>Reason:</strong> {remediation.reason}</p>
    <p><strong>Urgency:</strong> {remediation.urgency}</p>
    <p><a href="{os.getenv('WEB_UI_URL', 'http://localhost:3000')}/admin/remediations">
        Review Now →
    </a></p>
    """

    send_email(admin_emails, subject, html_body)


def _to_response(r: PendingRemediation) -> RemediationResponse:
    return RemediationResponse(
        id=r.id,
        action_type=r.action_type,
        target=r.target,
        reason=r.reason,
        parameters=r.parameters or {},
        urgency=r.urgency,
        rollback_action=r.rollback_action,
        status=r.status,
        proposed_at=r.proposed_at,
        proposed_by=r.proposed_by,
        reviewed_at=r.reviewed_at,
        reviewed_by=r.reviewed_by,
        review_comment=r.review_comment,
        executed_at=r.executed_at,
        execution_result=r.execution_result,
        execution_error=r.execution_error,
    )
