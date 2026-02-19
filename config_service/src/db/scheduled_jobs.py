"""SQLAlchemy model for scheduled jobs."""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ScheduledJob(Base):
    """
    A scheduled job that the orchestrator executes on a cron schedule.

    Supports job_type='agent_run' (triggers an agent investigation) with
    extensibility for future job types.

    The orchestrator polls for due jobs via the internal API, claims them
    atomically, executes, and reports completion.
    """

    __tablename__ = "scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team_node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="agent_run"
    )
    schedule: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Execution tracking
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_run_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Distributed claim mechanism
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index(
            "ix_scheduled_jobs_due", "next_run_at", postgresql_where="enabled = true"
        ),
        Index("ix_scheduled_jobs_team", "org_id", "team_node_id"),
    )
