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
    # Create the enum idempotently via raw SQL (PostgreSQL has no
    # CREATE TYPE IF NOT EXISTS, so we catch duplicate_object).
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE k8s_cluster_status AS ENUM ('disconnected', 'connected', 'error'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    )

    # Create the table using raw SQL to avoid SQLAlchemy trying to
    # re-create the enum type (create_type=False is unreliable).
    op.execute("""
        CREATE TABLE IF NOT EXISTS k8s_clusters (
            id VARCHAR(64) PRIMARY KEY,
            org_id VARCHAR(64) NOT NULL,
            team_node_id VARCHAR(128) NOT NULL,
            cluster_name VARCHAR(256) NOT NULL,
            display_name VARCHAR(256),
            token_id VARCHAR(128) NOT NULL UNIQUE,
            status k8s_cluster_status NOT NULL DEFAULT 'disconnected',
            last_heartbeat_at TIMESTAMP WITH TIME ZONE,
            last_error TEXT,
            agent_version VARCHAR(32),
            agent_pod_name VARCHAR(256),
            kubernetes_version VARCHAR(32),
            node_count INTEGER,
            namespace_count INTEGER,
            cluster_info JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        """)

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
