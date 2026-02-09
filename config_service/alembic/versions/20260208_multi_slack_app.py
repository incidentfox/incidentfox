"""Add slack_apps table and slack_app_slug to slack_installations.

Enables multi-app support: each row in slack_apps represents a separate
Slack app registration (with its own signing_secret, client_id, client_secret).
The slack_installations table gains a foreign key to track which app each
workspace installed.

Revision ID: 20260208_multi_slack_app
Revises: 20260208_org_admin_token_cols
Create Date: 2026-02-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text

revision = "20260208_multi_slack_app"
down_revision = "20260208_org_admin_token_cols"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create slack_apps table
    op.create_table(
        "slack_apps",
        sa.Column("slug", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("app_id", sa.String(255), nullable=True),
        # Encrypted via EncryptedText in models.py
        sa.Column(
            "client_id",
            Text,
            nullable=True,
            comment="Slack OAuth client ID (encrypted with Fernet)",
        ),
        sa.Column(
            "client_secret",
            Text,
            nullable=True,
            comment="Slack OAuth client secret (encrypted with Fernet)",
        ),
        sa.Column(
            "signing_secret",
            Text,
            nullable=True,
            comment="Slack webhook signing secret (encrypted with Fernet)",
        ),
        sa.Column("bot_scopes", Text, nullable=True),
        sa.Column("oauth_redirect_url", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    op.create_index("ix_slack_apps_app_id", "slack_apps", ["app_id"], unique=True)

    # 2. Add slack_app_slug column to slack_installations (nullable initially)
    op.add_column(
        "slack_installations",
        sa.Column(
            "slack_app_slug",
            sa.String(64),
            sa.ForeignKey("slack_apps.slug"),
            nullable=True,
        ),
    )

    # 3. Drop old unique index, create new one that includes slack_app_slug
    op.drop_index("ix_slack_installations_lookup", table_name="slack_installations")
    op.create_index(
        "ix_slack_installations_lookup",
        "slack_installations",
        ["slack_app_slug", "enterprise_id", "team_id", "user_id"],
        unique=True,
    )


def downgrade():
    # Restore old unique index
    op.drop_index("ix_slack_installations_lookup", table_name="slack_installations")
    op.create_index(
        "ix_slack_installations_lookup",
        "slack_installations",
        ["enterprise_id", "team_id", "user_id"],
        unique=True,
    )

    # Remove slack_app_slug column
    op.drop_column("slack_installations", "slack_app_slug")

    # Drop slack_apps table
    op.drop_index("ix_slack_apps_app_id", table_name="slack_apps")
    op.drop_table("slack_apps")
