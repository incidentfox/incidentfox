"""Add pending_knowledge_teachings table for Self-Learning System.

Stores knowledge taught by agents during investigations, awaiting review/approval.

Revision ID: 20260127_teachings
Revises: 20260122_agent_tracking
Create Date: 2026-01-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260127_teachings"
down_revision = "20260122_agent_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_knowledge_teachings",
        # Primary key
        sa.Column("id", sa.String(64), primary_key=True),
        # Organization/Team reference
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("team_node_id", sa.String(128), nullable=False),
        # The knowledge content
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "knowledge_type",
            sa.String(32),
            nullable=False,
            server_default="procedural",
        ),
        # Metadata
        sa.Column(
            "source", sa.String(128), nullable=False, server_default="agent_learning"
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column(
            "related_services",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        # Context from investigation
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("agent_name", sa.String(64), nullable=True),
        sa.Column("task_context", sa.Text(), nullable=True),
        sa.Column("incident_id", sa.String(64), nullable=True),
        # Similarity analysis
        sa.Column("similar_node_id", sa.Integer(), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column(
            "is_potential_contradiction",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("contradiction_details", sa.Text(), nullable=True),
        # Lifecycle
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("proposed_by", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        # Review
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        # Result after approval
        sa.Column("created_node_id", sa.Integer(), nullable=True),
        sa.Column("merged_with_node_id", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        # Foreign key constraint
        sa.ForeignKeyConstraint(
            ["org_id", "team_node_id"],
            ["org_nodes.org_id", "org_nodes.node_id"],
            name="fk_pending_knowledge_teachings_team_node",
            ondelete="CASCADE",
        ),
    )

    # Create indexes
    op.create_index(
        "ix_pending_knowledge_teachings_org_id",
        "pending_knowledge_teachings",
        ["org_id"],
    )
    op.create_index(
        "ix_pending_knowledge_teachings_org_team",
        "pending_knowledge_teachings",
        ["org_id", "team_node_id"],
    )
    op.create_index(
        "ix_pending_knowledge_teachings_status",
        "pending_knowledge_teachings",
        ["status"],
    )
    op.create_index(
        "ix_pending_knowledge_teachings_proposed_at",
        "pending_knowledge_teachings",
        ["proposed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pending_knowledge_teachings_proposed_at",
        table_name="pending_knowledge_teachings",
    )
    op.drop_index(
        "ix_pending_knowledge_teachings_status",
        table_name="pending_knowledge_teachings",
    )
    op.drop_index(
        "ix_pending_knowledge_teachings_org_team",
        table_name="pending_knowledge_teachings",
    )
    op.drop_index(
        "ix_pending_knowledge_teachings_org_id",
        table_name="pending_knowledge_teachings",
    )
    op.drop_table("pending_knowledge_teachings")
