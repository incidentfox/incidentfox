"""Add github_installations table for GitHub App OAuth storage.

Stores GitHub App installation data for SaaS model where customers
install our GitHub App to grant repository access.

Revision ID: 20260203_github_installations
Revises: 20260203_token_audit
Create Date: 2026-02-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "20260203_github_installations"
down_revision = "20260203_token_audit"
branch_labels = None
depends_on = None


def upgrade():
    """
    Create github_installations table.

    Stores GitHub App installation data with optional encryption for webhook_secret.
    """
    op.create_table(
        "github_installations",
        sa.Column("id", sa.String(255), primary_key=True),
        # GitHub App identifiers
        sa.Column(
            "installation_id",
            sa.BigInteger,
            nullable=False,
            unique=True,
            index=True,
            comment="GitHub App installation ID",
        ),
        sa.Column("app_id", sa.BigInteger, nullable=False, comment="GitHub App ID"),
        # GitHub account that installed the app
        sa.Column(
            "account_id", sa.BigInteger, nullable=False, comment="GitHub account ID"
        ),
        sa.Column(
            "account_login",
            sa.String(255),
            nullable=False,
            index=True,
            comment="GitHub account login (username or org name)",
        ),
        sa.Column(
            "account_type",
            sa.String(50),
            nullable=False,
            comment="Account type: Organization or User",
        ),
        sa.Column("account_avatar_url", Text, nullable=True),
        # IncidentFox org/team linkage
        sa.Column(
            "org_id",
            sa.String(255),
            nullable=True,
            index=True,
            comment="IncidentFox org ID (set during setup)",
        ),
        sa.Column(
            "team_node_id",
            sa.String(255),
            nullable=True,
            index=True,
            comment="IncidentFox team node ID (set during setup)",
        ),
        # Permissions and repository access
        sa.Column(
            "permissions",
            JSONB,
            nullable=True,
            comment="GitHub App permissions granted",
        ),
        sa.Column(
            "repository_selection",
            sa.String(50),
            nullable=True,
            comment="Repository selection: all or selected",
        ),
        sa.Column(
            "repositories",
            JSONB,
            nullable=True,
            comment="List of selected repository full names",
        ),
        # Webhook secret (encrypted via EncryptedText in models.py)
        sa.Column(
            "webhook_secret",
            Text,
            nullable=True,
            comment="Webhook secret for this installation (encrypted)",
        ),
        # Installation status
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="active",
            comment="Installation status: active, suspended, deleted",
        ),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_by", sa.String(255), nullable=True),
        # Timestamps
        sa.Column(
            "installed_at",
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
        # Raw payload storage
        sa.Column(
            "raw_data",
            JSONB,
            nullable=True,
            comment="Full installation payload from GitHub",
        ),
    )

    # Index for looking up installations by IncidentFox org/team
    op.create_index(
        "ix_github_installations_org_team",
        "github_installations",
        ["org_id", "team_node_id"],
    )


def downgrade():
    """Remove github_installations table."""
    op.drop_index("ix_github_installations_org_team", table_name="github_installations")
    op.drop_table("github_installations")
