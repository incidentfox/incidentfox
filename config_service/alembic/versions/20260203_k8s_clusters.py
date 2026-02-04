"""Add k8s_clusters table for SaaS K8s integration.

Tracks customer K8s clusters that connect via the in-cluster agent pattern.
Customers deploy an agent that connects outbound to the IncidentFox gateway.

Revision ID: 20260203_k8s_clusters
Revises: 20260131_slack_oauth_storage
Create Date: 2026-02-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "20260203_k8s_clusters"
down_revision = "20260203_github_installations"
branch_labels = None
depends_on = None


def upgrade():
    """Create k8s_clusters table and status enum."""
    # Create the status enum
    k8s_cluster_status = sa.Enum(
        "disconnected", "connected", "error", name="k8s_cluster_status"
    )
    k8s_cluster_status.create(op.get_bind(), checkfirst=True)

    # Create the table
    op.create_table(
        "k8s_clusters",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("team_node_id", sa.String(128), nullable=False),
        # Cluster identity
        sa.Column("cluster_name", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=True),
        # Token reference (for revocation)
        sa.Column("token_id", sa.String(128), nullable=False, unique=True),
        # Connection status
        sa.Column(
            "status",
            k8s_cluster_status,
            nullable=False,
            server_default="disconnected",
        ),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        # Agent info (populated when agent connects)
        sa.Column("agent_version", sa.String(32), nullable=True),
        sa.Column("agent_pod_name", sa.String(256), nullable=True),
        # Cluster info (populated when agent connects)
        sa.Column("kubernetes_version", sa.String(32), nullable=True),
        sa.Column("node_count", sa.Integer, nullable=True),
        sa.Column("namespace_count", sa.Integer, nullable=True),
        sa.Column("cluster_info", JSONB, nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # Create indexes for common queries
    op.create_index(
        "ix_k8s_clusters_org_id",
        "k8s_clusters",
        ["org_id"],
    )
    op.create_index(
        "ix_k8s_clusters_team_node_id",
        "k8s_clusters",
        ["team_node_id"],
    )
    op.create_index(
        "ix_k8s_clusters_status",
        "k8s_clusters",
        ["status"],
    )
    # Unique constraint: one cluster name per team
    op.create_index(
        "ix_k8s_clusters_team_cluster_name",
        "k8s_clusters",
        ["team_node_id", "cluster_name"],
        unique=True,
    )


def downgrade():
    """Remove k8s_clusters table and status enum."""
    op.drop_index("ix_k8s_clusters_team_cluster_name", table_name="k8s_clusters")
    op.drop_index("ix_k8s_clusters_status", table_name="k8s_clusters")
    op.drop_index("ix_k8s_clusters_team_node_id", table_name="k8s_clusters")
    op.drop_index("ix_k8s_clusters_org_id", table_name="k8s_clusters")
    op.drop_table("k8s_clusters")

    # Drop the enum type
    sa.Enum(name="k8s_cluster_status").drop(op.get_bind(), checkfirst=True)
