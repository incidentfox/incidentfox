"""Add visitor playground tables for public demo access.

Creates visitor_emails and visitor_sessions tables to support the
visitor playground feature where users can try IncidentFox without
a paid account.

Revision ID: 20260128_visitor_playground
Revises: 20260127_teachings, 20260125_agent_feedback, 20260119_tool_calls
Create Date: 2026-01-28
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260128_visitor_playground"
# Merge all three existing heads into one:
# - 20260127_teachings (from 20260122_agent_tracking)
# - 20260125_agent_feedback (from 20260122_agent_tracking)
# - 20260119_tool_calls (orphan branch from 20260118_service_dependencies)
down_revision = ("20260127_teachings", "20260125_agent_feedback", "20260119_tool_calls")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create visitor_emails table
    op.create_table(
        "visitor_emails",
        sa.Column("email", sa.String(256), primary_key=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(64), nullable=True),
    )

    op.create_index("ix_visitor_emails_last_seen", "visitor_emails", ["last_seen_at"])

    # Create visitor_sessions table
    op.create_table(
        "visitor_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("warned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_visitor_sessions_email", "visitor_sessions", ["email"])
    op.create_index("ix_visitor_sessions_status", "visitor_sessions", ["status"])
    op.create_index(
        "ix_visitor_sessions_status_created",
        "visitor_sessions",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_visitor_sessions_last_heartbeat",
        "visitor_sessions",
        ["last_heartbeat_at"],
    )


def downgrade() -> None:
    # Drop visitor_sessions
    op.drop_index("ix_visitor_sessions_last_heartbeat", table_name="visitor_sessions")
    op.drop_index("ix_visitor_sessions_status_created", table_name="visitor_sessions")
    op.drop_index("ix_visitor_sessions_status", table_name="visitor_sessions")
    op.drop_index("ix_visitor_sessions_email", table_name="visitor_sessions")
    op.drop_table("visitor_sessions")

    # Drop visitor_emails
    op.drop_index("ix_visitor_emails_last_seen", table_name="visitor_emails")
    op.drop_table("visitor_emails")
