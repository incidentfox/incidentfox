"""Add scheduled_jobs table for generic scheduled agent runs.

Enables any team to create scheduled jobs (e.g., status reports at 8AM/8PM)
that the orchestrator polls and executes. Replaces per-customer K8s CronJobs
with a DB-backed, API-manageable scheduling system.

Revision ID: 20260216_scheduled_jobs
Revises: 20260208_multi_slack_app
Create Date: 2026-02-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260216_scheduled_jobs"
down_revision = "20260208_multi_slack_app"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scheduled_jobs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("team_node_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "job_type",
            sa.String(64),
            nullable=False,
            server_default="agent_run",
        ),
        sa.Column("schedule", sa.String(128), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        # Execution tracking
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(32), nullable=True),
        sa.Column("last_run_error", sa.Text, nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        # Claim mechanism for distributed execution
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(128), nullable=True),
        # Metadata
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column("created_by", sa.String(255), nullable=True),
    )

    # Index for the orchestrator's poll query: find enabled jobs that are due
    op.create_index(
        "ix_scheduled_jobs_due",
        "scheduled_jobs",
        ["next_run_at"],
        postgresql_where=sa.text("enabled = true"),
    )

    # Index for listing jobs by team
    op.create_index(
        "ix_scheduled_jobs_team",
        "scheduled_jobs",
        ["org_id", "team_node_id"],
    )


def downgrade():
    op.drop_index("ix_scheduled_jobs_team", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_due", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")
