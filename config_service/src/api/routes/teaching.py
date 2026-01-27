"""
Knowledge Teaching API routes.

Handles the approval workflow for knowledge taught by agents.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.models import PendingKnowledgeTeaching
from ...db.session import get_db
from ..auth import AdminPrincipal, require_admin

logger = structlog.get_logger(__name__)


# =============================================================================
# Request/Response Models
# =============================================================================


class ProposeTeachingRequest(BaseModel):
    """Request to propose new knowledge teaching."""

    content: str = Field(..., description="The knowledge content to teach")
    knowledge_type: str = Field(
        default="procedural",
        description="Type of knowledge: procedural, factual, service_info, troubleshooting",
    )
    source: str = Field(default="agent_learning", description="Source of the knowledge")
    confidence: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Confidence score"
    )
    related_services: List[str] = Field(default_factory=list)
    correlation_id: Optional[str] = None
    agent_name: Optional[str] = None
    task_context: Optional[str] = None
    incident_id: Optional[str] = None


class TeachingResponse(BaseModel):
    """Response model for a teaching record."""

    id: str
    org_id: str
    team_node_id: Optional[str]
    content: str
    knowledge_type: str
    source: str
    confidence: float
    related_services: Optional[List[str]]
    correlation_id: Optional[str]
    agent_name: Optional[str]
    task_context: Optional[str]
    incident_id: Optional[str]
    similar_node_id: Optional[int]
    similarity_score: Optional[float]
    is_potential_contradiction: bool
    proposed_at: datetime
    status: str
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[str]
    review_comment: Optional[str]
    created_node_id: Optional[int]
    merged_with_node_id: Optional[int]
    applied_at: Optional[datetime]


class ReviewTeachingRequest(BaseModel):
    """Request to review a teaching."""

    action: str = Field(..., pattern="^(approve|reject|merge)$")
    comment: Optional[str] = None
    merge_with_node_id: Optional[int] = Field(
        default=None, description="Node ID to merge with (for merge action)"
    )


class TeachingListResponse(BaseModel):
    """Response for listing teachings."""

    teachings: List[TeachingResponse]
    total: int
    has_more: bool


class PatchTeachingRequest(BaseModel):
    """Request to patch teaching metadata (internal use)."""

    similar_node_id: Optional[int] = None
    similarity_score: Optional[float] = None
    is_potential_contradiction: Optional[bool] = None
    status: Optional[str] = None
    created_node_id: Optional[int] = None
    merged_with_node_id: Optional[int] = None
    applied_at: Optional[datetime] = None


# =============================================================================
# Router
# =============================================================================

router = APIRouter(prefix="/api/v1", tags=["teaching"])


@router.post("/teachings", response_model=TeachingResponse, status_code=201)
async def propose_teaching(
    body: ProposeTeachingRequest,
    db: Session = Depends(get_db),
    x_org_id: str = Header(default="org-default"),
    x_team_node_id: str = Header(default=None),
):
    """
    Propose new knowledge to be added to the knowledge base.

    Called by agents when they learn something useful during investigations.
    """
    teaching = PendingKnowledgeTeaching(
        id=f"teach-{uuid.uuid4().hex[:12]}",
        org_id=x_org_id,
        team_node_id=x_team_node_id,
        content=body.content,
        knowledge_type=body.knowledge_type,
        source=body.source,
        confidence=body.confidence,
        related_services=body.related_services,
        correlation_id=body.correlation_id,
        agent_name=body.agent_name,
        task_context=body.task_context,
        incident_id=body.incident_id,
        status="pending",
        is_potential_contradiction=False,
    )

    db.add(teaching)
    db.commit()
    db.refresh(teaching)

    logger.info(
        "teaching_proposed",
        id=teaching.id,
        knowledge_type=body.knowledge_type,
        confidence=body.confidence,
        agent=body.agent_name,
    )

    return _to_response(teaching)


@router.get("/teachings", response_model=TeachingListResponse)
async def list_teachings(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    knowledge_type: Optional[str] = Query(default=None, description="Filter by type"),
    is_contradiction: Optional[bool] = Query(
        default=None, description="Filter by contradiction flag"
    ),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """List pending knowledge teachings for review."""
    query = db.query(PendingKnowledgeTeaching).filter(
        PendingKnowledgeTeaching.org_id == admin.org_id
    )

    if status:
        query = query.filter(PendingKnowledgeTeaching.status == status)
    if knowledge_type:
        query = query.filter(PendingKnowledgeTeaching.knowledge_type == knowledge_type)
    if is_contradiction is not None:
        query = query.filter(
            PendingKnowledgeTeaching.is_potential_contradiction == is_contradiction
        )

    total = query.count()
    teachings = (
        query.order_by(PendingKnowledgeTeaching.proposed_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return TeachingListResponse(
        teachings=[_to_response(t) for t in teachings],
        total=total,
        has_more=offset + len(teachings) < total,
    )


@router.get(
    "/orgs/{org_id}/teams/{team_node_id}/pending-teachings",
    response_model=TeachingListResponse,
)
async def list_team_teachings(
    org_id: str,
    team_node_id: str,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    """
    List pending teachings for a specific team.

    Used by the AI Pipeline teaching processor.
    """
    query = db.query(PendingKnowledgeTeaching).filter(
        PendingKnowledgeTeaching.org_id == org_id,
        PendingKnowledgeTeaching.team_node_id == team_node_id,
    )

    if status:
        query = query.filter(PendingKnowledgeTeaching.status == status)

    total = query.count()
    teachings = (
        query.order_by(PendingKnowledgeTeaching.proposed_at.desc()).limit(limit).all()
    )

    return TeachingListResponse(
        teachings=[_to_response(t) for t in teachings],
        total=total,
        has_more=len(teachings) < total,
    )


@router.get("/teachings/{teaching_id}", response_model=TeachingResponse)
async def get_teaching(
    teaching_id: str,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """Get details of a teaching proposal."""
    teaching = (
        db.query(PendingKnowledgeTeaching)
        .filter(
            PendingKnowledgeTeaching.id == teaching_id,
            PendingKnowledgeTeaching.org_id == admin.org_id,
        )
        .first()
    )

    if not teaching:
        raise HTTPException(status_code=404, detail="Teaching not found")

    return _to_response(teaching)


@router.post("/teachings/{teaching_id}/review", response_model=TeachingResponse)
async def review_teaching(
    teaching_id: str,
    body: ReviewTeachingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: AdminPrincipal = Depends(require_admin),
):
    """Approve, reject, or merge a teaching proposal."""
    teaching = (
        db.query(PendingKnowledgeTeaching)
        .filter(
            PendingKnowledgeTeaching.id == teaching_id,
            PendingKnowledgeTeaching.org_id == admin.org_id,
        )
        .first()
    )

    if not teaching:
        raise HTTPException(status_code=404, detail="Teaching not found")

    if teaching.status not in ("pending", "auto_approved"):
        raise HTTPException(
            status_code=400, detail=f"Teaching already {teaching.status}"
        )

    reviewer = admin.subject if hasattr(admin, "subject") else "admin"

    teaching.reviewed_at = datetime.now(timezone.utc)
    teaching.reviewed_by = reviewer
    teaching.review_comment = body.comment

    if body.action == "approve":
        teaching.status = "approved"
        db.commit()

        logger.info(
            "teaching_approved",
            id=teaching_id,
            knowledge_type=teaching.knowledge_type,
            by=reviewer,
        )

        # Ingest the teaching in background
        background_tasks.add_task(ingest_teaching, teaching.id)

    elif body.action == "reject":
        teaching.status = "rejected"
        db.commit()

        logger.info(
            "teaching_rejected",
            id=teaching_id,
            knowledge_type=teaching.knowledge_type,
            by=reviewer,
        )

    elif body.action == "merge":
        if not body.merge_with_node_id:
            raise HTTPException(
                status_code=400, detail="merge_with_node_id required for merge action"
            )

        teaching.status = "merged"
        teaching.merged_with_node_id = body.merge_with_node_id
        db.commit()

        logger.info(
            "teaching_merged",
            id=teaching_id,
            merged_with=body.merge_with_node_id,
            by=reviewer,
        )

        # Update the existing node in background
        background_tasks.add_task(
            merge_teaching, teaching.id, body.merge_with_node_id
        )

    db.refresh(teaching)
    return _to_response(teaching)


@router.patch("/pending-teachings/{teaching_id}", response_model=TeachingResponse)
async def patch_teaching(
    teaching_id: str,
    body: PatchTeachingRequest,
    db: Session = Depends(get_db),
):
    """
    Update teaching metadata.

    Internal API used by the AI Pipeline teaching processor.
    """
    teaching = (
        db.query(PendingKnowledgeTeaching)
        .filter(PendingKnowledgeTeaching.id == teaching_id)
        .first()
    )

    if not teaching:
        raise HTTPException(status_code=404, detail="Teaching not found")

    # Update provided fields
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(teaching, field, value)

    db.commit()
    db.refresh(teaching)

    return _to_response(teaching)


# =============================================================================
# Background Tasks
# =============================================================================


def ingest_teaching(teaching_id: str):
    """Ingest approved teaching into the knowledge base."""
    from ...db.session import SessionLocal

    session = SessionLocal()
    try:
        teaching = (
            session.query(PendingKnowledgeTeaching)
            .filter(PendingKnowledgeTeaching.id == teaching_id)
            .first()
        )

        if not teaching or teaching.status != "approved":
            return

        raptor_url = os.getenv("RAPTOR_URL", "http://knowledge-base:8000")

        try:
            with httpx.Client(base_url=raptor_url, timeout=60.0) as client:
                response = client.post(
                    "/api/v1/teach",
                    json={
                        "content": teaching.content,
                        "knowledge_type": teaching.knowledge_type,
                        "metadata": {
                            "source": teaching.source,
                            "teaching_id": teaching.id,
                            "correlation_id": teaching.correlation_id,
                            "agent_name": teaching.agent_name,
                            "confidence": teaching.confidence,
                            "services": teaching.related_services or [],
                        },
                    },
                )

                if response.status_code == 200:
                    result = response.json()
                    teaching.created_node_id = result.get("node_id")
                    teaching.applied_at = datetime.now(timezone.utc)
                    session.commit()

                    logger.info(
                        "teaching_ingested",
                        id=teaching_id,
                        node_id=teaching.created_node_id,
                    )
                else:
                    logger.error(
                        "teaching_ingest_failed",
                        id=teaching_id,
                        status=response.status_code,
                        response=response.text[:500],
                    )

        except Exception as e:
            logger.error("teaching_ingest_error", id=teaching_id, error=str(e))

    finally:
        session.close()


def merge_teaching(teaching_id: str, merge_with_node_id: int):
    """Merge teaching content with existing node."""
    from ...db.session import SessionLocal

    session = SessionLocal()
    try:
        teaching = (
            session.query(PendingKnowledgeTeaching)
            .filter(PendingKnowledgeTeaching.id == teaching_id)
            .first()
        )

        if not teaching or teaching.status != "merged":
            return

        raptor_url = os.getenv("RAPTOR_URL", "http://knowledge-base:8000")

        try:
            with httpx.Client(base_url=raptor_url, timeout=60.0) as client:
                # Fetch existing node
                get_response = client.get(f"/nodes/{merge_with_node_id}")

                if get_response.status_code != 200:
                    logger.error(
                        "merge_node_not_found",
                        teaching_id=teaching_id,
                        node_id=merge_with_node_id,
                    )
                    return

                existing_node = get_response.json()
                existing_content = existing_node.get("content", "")

                # Merge content
                merged_content = f"{existing_content}\n\n---\n\n{teaching.content}"

                # Update the node
                update_response = client.patch(
                    f"/nodes/{merge_with_node_id}",
                    json={
                        "content": merged_content,
                        "metadata": {
                            **existing_node.get("metadata", {}),
                            "merged_teaching_ids": existing_node.get("metadata", {}).get(
                                "merged_teaching_ids", []
                            )
                            + [teaching.id],
                            "last_merged_at": datetime.now(timezone.utc).isoformat(),
                        },
                    },
                )

                if update_response.status_code == 200:
                    teaching.applied_at = datetime.now(timezone.utc)
                    session.commit()

                    logger.info(
                        "teaching_merged",
                        id=teaching_id,
                        merged_with=merge_with_node_id,
                    )
                else:
                    logger.error(
                        "teaching_merge_failed",
                        id=teaching_id,
                        status=update_response.status_code,
                    )

        except Exception as e:
            logger.error("teaching_merge_error", id=teaching_id, error=str(e))

    finally:
        session.close()


# =============================================================================
# Helpers
# =============================================================================


def _to_response(t: PendingKnowledgeTeaching) -> TeachingResponse:
    return TeachingResponse(
        id=t.id,
        org_id=t.org_id,
        team_node_id=t.team_node_id,
        content=t.content,
        knowledge_type=t.knowledge_type,
        source=t.source,
        confidence=t.confidence,
        related_services=t.related_services,
        correlation_id=t.correlation_id,
        agent_name=t.agent_name,
        task_context=t.task_context,
        incident_id=t.incident_id,
        similar_node_id=t.similar_node_id,
        similarity_score=t.similarity_score,
        is_potential_contradiction=t.is_potential_contradiction,
        proposed_at=t.proposed_at,
        status=t.status,
        reviewed_at=t.reviewed_at,
        reviewed_by=t.reviewed_by,
        review_comment=t.review_comment,
        created_node_id=t.created_node_id,
        merged_with_node_id=t.merged_with_node_id,
        applied_at=t.applied_at,
    )
