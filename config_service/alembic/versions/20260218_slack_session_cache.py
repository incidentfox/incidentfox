"""Add slack_session_cache table for persisting View Session modal data.

Stores serialized MessageState so the Slack "View Session" button works
after slack-bot restarts or in-memory cache TTL expires. 3-day cleanup.

Revision ID: 20260218_slack_session_cache
Revises: 20260216_scheduled_jobs
Create Date: 2026-02-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260218_slack_session_cache"
down_revision = "20260216_scheduled_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_session_cache",
        sa.Column("message_ts", sa.String(64), nullable=False),
        sa.Column("thread_ts", sa.String(64), nullable=True),
        sa.Column("org_id", sa.String(64), nullable=True),
        sa.Column("team_node_id", sa.String(128), nullable=True),
        sa.Column("state_json", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("message_ts"),
    )
    op.create_index(
        "ix_slack_session_cache_created_at",
        "slack_session_cache",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_slack_session_cache_created_at", table_name="slack_session_cache")
    op.drop_table("slack_session_cache")
