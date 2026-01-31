"""Add slack_installations table for OAuth token storage.

Revision ID: 20260131_slack_installations
Revises: 20260130_recall_slack_thread
Create Date: 2026-01-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "20260131_slack_installations"
down_revision = "20260130_recall_slack_thread"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "slack_installations",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("enterprise_id", sa.String(255), nullable=True, index=True),
        sa.Column("team_id", sa.String(255), nullable=False, index=True),
        sa.Column("user_id", sa.String(255), nullable=True, index=True),
        sa.Column("app_id", sa.String(255), nullable=True),
        sa.Column("bot_token", sa.Text, nullable=False),
        sa.Column("bot_id", sa.String(255), nullable=True),
        sa.Column("bot_user_id", sa.String(255), nullable=True),
        sa.Column("bot_scopes", sa.Text, nullable=True),  # Comma-separated
        sa.Column("user_token", sa.Text, nullable=True),
        sa.Column("user_scopes", sa.Text, nullable=True),  # Comma-separated
        sa.Column("incoming_webhook_url", sa.Text, nullable=True),
        sa.Column("incoming_webhook_channel", sa.String(255), nullable=True),
        sa.Column("incoming_webhook_channel_id", sa.String(255), nullable=True),
        sa.Column("incoming_webhook_configuration_url", sa.Text, nullable=True),
        sa.Column("is_enterprise_install", sa.Boolean, default=False),
        sa.Column("token_type", sa.String(50), nullable=True),
        sa.Column("installed_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        # Store full installation data as JSON for future-proofing
        sa.Column("raw_data", JSONB, nullable=True),
    )

    # Create unique constraint for enterprise_id + team_id + user_id combination
    # This allows both workspace-level and user-level installations
    op.create_index(
        "ix_slack_installations_lookup",
        "slack_installations",
        ["enterprise_id", "team_id", "user_id"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_slack_installations_lookup", table_name="slack_installations")
    op.drop_table("slack_installations")
