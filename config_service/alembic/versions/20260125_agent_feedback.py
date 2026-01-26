"""Add agent_feedback table for tracking user feedback on agent responses.

Revision ID: 20260125_agent_feedback
Revises: 20260122_agent_tracking
Create Date: 2026-01-25
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260125_agent_feedback"
down_revision = "20260122_agent_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_feedback",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("feedback_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("ix_agent_feedback_run_id", "agent_feedback", ["run_id"])
    op.create_index("ix_agent_feedback_type", "agent_feedback", ["feedback_type"])
    op.create_index("ix_agent_feedback_source", "agent_feedback", ["source"])
    op.create_index("ix_agent_feedback_created_at", "agent_feedback", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_feedback_created_at", table_name="agent_feedback")
    op.drop_index("ix_agent_feedback_source", table_name="agent_feedback")
    op.drop_index("ix_agent_feedback_type", table_name="agent_feedback")
    op.drop_index("ix_agent_feedback_run_id", table_name="agent_feedback")
    op.drop_table("agent_feedback")
