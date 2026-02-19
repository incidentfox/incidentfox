"""Scheduled jobs API routes.

Team-facing routes use /api/v1/config/me/scheduled-jobs with team auth.
Internal routes use /api/v1/internal/scheduled-jobs for orchestrator polling.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from croniter import croniter
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.scheduled_jobs import ScheduledJob
from ...db.session import get_db
from ..auth import TeamPrincipal, require_team_auth

logger = structlog.get_logger(__name__)


# =============================================================================
# Request / Response Models
# =============================================================================


class CreateScheduledJobRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Human-readable job name")
    job_type: str = Field(
        default="agent_run", description="Job type (currently only 'agent_run')"
    )
    schedule: str = Field(
        ..., max_length=128, description="Cron expression (e.g., '0 8,20 * * *')"
    )
    timezone: str = Field(
        default="UTC",
        max_length=64,
        description="IANA timezone (e.g., 'America/Los_Angeles')",
    )
    enabled: bool = Field(default=True)
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Job-specific config. For agent_run: {prompt, agent_name, max_turns, output_destinations}",
    )


class UpdateScheduledJobRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    schedule: Optional[str] = Field(None, max_length=128)
    timezone: Optional[str] = Field(None, max_length=64)
    enabled: Optional[bool] = None
    config: Optional[dict[str, Any]] = None


class ScheduledJobResponse(BaseModel):
    id: str
    org_id: str
    team_node_id: str
    name: str
    job_type: str
    schedule: str
    timezone: str
    enabled: bool
    config: dict[str, Any]
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    last_run_error: Optional[str] = None
    next_run_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_model(cls, job: ScheduledJob) -> "ScheduledJobResponse":
        return cls(
            id=str(job.id),
            org_id=job.org_id,
            team_node_id=job.team_node_id,
            name=job.name,
            job_type=job.job_type,
            schedule=job.schedule,
            timezone=job.timezone,
            enabled=job.enabled,
            config=job.config or {},
            last_run_at=job.last_run_at.isoformat() if job.last_run_at else None,
            last_run_status=job.last_run_status,
            last_run_error=job.last_run_error,
            next_run_at=job.next_run_at.isoformat() if job.next_run_at else None,
            created_at=job.created_at.isoformat() if job.created_at else None,
            updated_at=job.updated_at.isoformat() if job.updated_at else None,
        )


# =============================================================================
# Helpers
# =============================================================================


def _compute_next_run(
    schedule: str, tz_name: str, after: datetime | None = None
) -> datetime:
    """Compute next run time from cron expression and timezone."""
    import zoneinfo

    tz = zoneinfo.ZoneInfo(tz_name)
    base = after or datetime.now(tz)
    if base.tzinfo is None:
        base = base.replace(tzinfo=tz)
    cron = croniter(schedule, base)
    next_dt = cron.get_next(datetime)
    # Ensure it's timezone-aware in UTC for storage
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=tz)
    return next_dt.astimezone(timezone.utc)


def _validate_cron(schedule: str) -> None:
    """Validate a cron expression."""
    if not croniter.is_valid(schedule):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid cron expression: '{schedule}'",
        )


def _validate_timezone(tz_name: str) -> None:
    """Validate IANA timezone name."""
    import zoneinfo

    try:
        zoneinfo.ZoneInfo(tz_name)
    except (KeyError, Exception):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid timezone: '{tz_name}'",
        )


# =============================================================================
# Team-facing routes
# =============================================================================

router = APIRouter(prefix="/api/v1/config/me/scheduled-jobs", tags=["scheduled-jobs"])


@router.get("", response_model=list[ScheduledJobResponse])
async def list_scheduled_jobs(
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """List all scheduled jobs for this team."""
    jobs = (
        db.execute(
            select(ScheduledJob)
            .where(
                ScheduledJob.org_id == team.org_id,
                ScheduledJob.team_node_id == team.team_node_id,
            )
            .order_by(ScheduledJob.created_at)
        )
        .scalars()
        .all()
    )
    return [ScheduledJobResponse.from_model(j) for j in jobs]


@router.post("", response_model=ScheduledJobResponse, status_code=201)
async def create_scheduled_job(
    body: CreateScheduledJobRequest,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Create a new scheduled job."""
    _validate_cron(body.schedule)
    _validate_timezone(body.timezone)

    next_run = _compute_next_run(body.schedule, body.timezone)

    job = ScheduledJob(
        id=uuid.uuid4(),
        org_id=team.org_id,
        team_node_id=team.team_node_id,
        name=body.name,
        job_type=body.job_type,
        schedule=body.schedule,
        timezone=body.timezone,
        enabled=body.enabled,
        config=body.config,
        next_run_at=next_run,
        created_by=team.subject or "api",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(
        "scheduled_job_created",
        job_id=str(job.id),
        org_id=team.org_id,
        team_node_id=team.team_node_id,
        name=body.name,
        schedule=body.schedule,
        next_run_at=next_run.isoformat(),
    )

    return ScheduledJobResponse.from_model(job)


@router.get("/{job_id}", response_model=ScheduledJobResponse)
async def get_scheduled_job(
    job_id: str,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Get a specific scheduled job."""
    job = db.execute(
        select(ScheduledJob).where(
            ScheduledJob.id == uuid.UUID(job_id),
            ScheduledJob.org_id == team.org_id,
            ScheduledJob.team_node_id == team.team_node_id,
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")
    return ScheduledJobResponse.from_model(job)


@router.patch("/{job_id}", response_model=ScheduledJobResponse)
async def update_scheduled_job(
    job_id: str,
    body: UpdateScheduledJobRequest,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Update a scheduled job."""
    job = db.execute(
        select(ScheduledJob).where(
            ScheduledJob.id == uuid.UUID(job_id),
            ScheduledJob.org_id == team.org_id,
            ScheduledJob.team_node_id == team.team_node_id,
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    if body.schedule is not None:
        _validate_cron(body.schedule)
        job.schedule = body.schedule
    if body.timezone is not None:
        _validate_timezone(body.timezone)
        job.timezone = body.timezone
    if body.name is not None:
        job.name = body.name
    if body.enabled is not None:
        job.enabled = body.enabled
    if body.config is not None:
        job.config = body.config

    # Recompute next_run_at if schedule or timezone changed
    if body.schedule is not None or body.timezone is not None:
        job.next_run_at = _compute_next_run(job.schedule, job.timezone)

    db.commit()
    db.refresh(job)

    logger.info(
        "scheduled_job_updated",
        job_id=str(job.id),
        org_id=team.org_id,
        team_node_id=team.team_node_id,
    )

    return ScheduledJobResponse.from_model(job)


@router.delete("/{job_id}", status_code=204)
async def delete_scheduled_job(
    job_id: str,
    db: Session = Depends(get_db),
    team: TeamPrincipal = Depends(require_team_auth),
):
    """Delete a scheduled job."""
    job = db.execute(
        select(ScheduledJob).where(
            ScheduledJob.id == uuid.UUID(job_id),
            ScheduledJob.org_id == team.org_id,
            ScheduledJob.team_node_id == team.team_node_id,
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    db.delete(job)
    db.commit()

    logger.info(
        "scheduled_job_deleted",
        job_id=job_id,
        org_id=team.org_id,
        team_node_id=team.team_node_id,
    )


# =============================================================================
# Internal routes (for orchestrator)
# =============================================================================

internal_router = APIRouter(prefix="/api/v1/internal/scheduled-jobs", tags=["internal"])

# Claim timeout: if a job was claimed more than 10 minutes ago and not
# completed, consider it abandoned and re-claimable.
CLAIM_TIMEOUT_SECONDS = 600


def _require_internal_service(
    x_internal_service: str = Header(default="", alias="X-Internal-Service"),
) -> str:
    if not x_internal_service:
        raise HTTPException(status_code=401, detail="Missing internal service header")
    return x_internal_service


@internal_router.get("/due")
async def get_due_jobs(
    limit: int = 10,
    db: Session = Depends(get_db),
    caller: str = Depends(_require_internal_service),
):
    """Return jobs that are due for execution and atomically claim them.

    A job is due when:
    - enabled = true
    - next_run_at <= now()
    - Not already claimed (or claim is stale > 10 minutes)
    """
    now = datetime.now(timezone.utc)
    stale_threshold = datetime.fromtimestamp(
        now.timestamp() - CLAIM_TIMEOUT_SECONDS, tz=timezone.utc
    )

    # Find due, unclaimed (or stale-claimed) jobs
    jobs = (
        db.execute(
            select(ScheduledJob)
            .where(
                ScheduledJob.enabled == True,  # noqa: E712
                ScheduledJob.next_run_at <= now,
                # Not claimed, or claim is stale
                (ScheduledJob.claimed_at == None)  # noqa: E711
                | (ScheduledJob.claimed_at < stale_threshold),
            )
            .order_by(ScheduledJob.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )

    # Claim all found jobs atomically
    result = []
    for job in jobs:
        job.claimed_at = now
        job.claimed_by = caller
        result.append(
            {
                "id": str(job.id),
                "org_id": job.org_id,
                "team_node_id": job.team_node_id,
                "name": job.name,
                "job_type": job.job_type,
                "schedule": job.schedule,
                "timezone": job.timezone,
                "config": job.config or {},
            }
        )

    db.commit()

    logger.info(
        "scheduled_jobs_claimed",
        count=len(result),
        caller=caller,
    )

    return {"jobs": result, "count": len(result)}


class JobCompletionRequest(BaseModel):
    status: str = Field(..., description="'success' or 'error'")
    error: Optional[str] = Field(None, description="Error message if status='error'")


@internal_router.post("/{job_id}/complete")
async def complete_job(
    job_id: str,
    body: JobCompletionRequest,
    db: Session = Depends(get_db),
    caller: str = Depends(_require_internal_service),
):
    """Report job completion and compute next run time."""
    job = db.execute(
        select(ScheduledJob).where(ScheduledJob.id == uuid.UUID(job_id))
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    now = datetime.now(timezone.utc)

    job.last_run_at = now
    job.last_run_status = body.status
    job.last_run_error = body.error if body.status == "error" else None
    job.claimed_at = None
    job.claimed_by = None

    # Compute next run
    job.next_run_at = _compute_next_run(job.schedule, job.timezone, after=now)

    db.commit()

    logger.info(
        "scheduled_job_completed",
        job_id=job_id,
        status=body.status,
        next_run_at=job.next_run_at.isoformat() if job.next_run_at else None,
    )

    return {
        "id": str(job.id),
        "status": body.status,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
    }
