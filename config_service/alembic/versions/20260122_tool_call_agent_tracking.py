"""Add agent_name and parent_agent columns to agent_tool_calls for sub-agent tracking.

Revision ID: 20260122_agent_tracking
Revises: 20260119_meeting_data
Create Date: 2026-01-22
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260122_agent_tracking"
down_revision = "20260119_meeting_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add agent_name column - which agent made this tool call
    op.add_column(
        "agent_tool_calls",
        sa.Column("agent_name", sa.String(64), nullable=True),
    )
    # Add parent_agent column - for tracking sub-agent hierarchy
    op.add_column(
        "agent_tool_calls",
        sa.Column("parent_agent", sa.String(64), nullable=True),
    )
    # Add index on agent_name for filtering
    op.create_index(
        "ix_agent_tool_calls_agent_name",
        "agent_tool_calls",
        ["agent_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tool_calls_agent_name", table_name="agent_tool_calls")
    op.drop_column("agent_tool_calls", "parent_agent")
    op.drop_column("agent_tool_calls", "agent_name")
