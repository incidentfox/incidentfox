"""Add Slack thread tracking to recall_bots for transcript summaries.

When a meeting bot is invited from a Slack thread, we store the thread
info so we can post transcript summaries back to that thread.

Revision ID: 20260130_recall_slack_thread
Revises: 20260129_recall_bots
Create Date: 2026-01-30
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260130_recall_slack_thread"
down_revision = "20260129_recall_bots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add Slack thread tracking columns to recall_bots
    op.add_column(
        "recall_bots",
        sa.Column("slack_channel_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "recall_bots",
        sa.Column("slack_thread_ts", sa.String(64), nullable=True),
    )
    # Message timestamp for the summary message we post/update
    op.add_column(
        "recall_bots",
        sa.Column("slack_summary_ts", sa.String(64), nullable=True),
    )
    # Track when we last updated the summary
    op.add_column(
        "recall_bots",
        sa.Column("last_summary_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Index for finding bots by Slack thread
    op.create_index(
        "ix_recall_bots_slack_thread",
        "recall_bots",
        ["slack_channel_id", "slack_thread_ts"],
    )


def downgrade() -> None:
    op.drop_index("ix_recall_bots_slack_thread", table_name="recall_bots")
    op.drop_column("recall_bots", "last_summary_at")
    op.drop_column("recall_bots", "slack_summary_ts")
    op.drop_column("recall_bots", "slack_thread_ts")
    op.drop_column("recall_bots", "slack_channel_id")
