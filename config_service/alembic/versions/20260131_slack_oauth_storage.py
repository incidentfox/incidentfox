"""Add slack_installations table with encrypted OAuth token storage.

Stores Slack OAuth installation data with column-level encryption for sensitive tokens.

Revision ID: 20260131_slack_oauth_storage
Revises: 20260130_recall_slack_thread
Create Date: 2026-01-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "20260131_slack_oauth_storage"
down_revision = "20260130_recall_slack_thread"
branch_labels = None
depends_on = None


def upgrade():
    """
    Create slack_installations table with column-level encryption.

    Note: bot_token, user_token, and incoming_webhook_url columns use Text type in migration
    but are mapped to EncryptedText in models.py, providing transparent encryption/decryption.
    """
    op.create_table(
        "slack_installations",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("enterprise_id", sa.String(255), nullable=True, index=True),
        sa.Column("team_id", sa.String(255), nullable=False, index=True),
        sa.Column("user_id", sa.String(255), nullable=True, index=True),
        sa.Column("app_id", sa.String(255), nullable=True),
        # OAuth tokens - encrypted via EncryptedText SQLAlchemy type in models.py
        sa.Column(
            "bot_token",
            Text,
            nullable=False,
            comment="Slack bot OAuth token (encrypted with Fernet)",
        ),
        sa.Column("bot_id", sa.String(255), nullable=True),
        sa.Column("bot_user_id", sa.String(255), nullable=True),
        sa.Column("bot_scopes", Text, nullable=True),  # Comma-separated scopes
        sa.Column(
            "user_token",
            Text,
            nullable=True,
            comment="Slack user OAuth token (encrypted with Fernet)",
        ),
        sa.Column("user_scopes", Text, nullable=True),  # Comma-separated scopes
        # Webhook URL contains sensitive token in query parameters - encrypted
        sa.Column(
            "incoming_webhook_url",
            Text,
            nullable=True,
            comment="Incoming webhook URL (encrypted with Fernet)",
        ),
        sa.Column("incoming_webhook_channel", sa.String(255), nullable=True),
        sa.Column("incoming_webhook_channel_id", sa.String(255), nullable=True),
        sa.Column("incoming_webhook_configuration_url", Text, nullable=True),
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
    # Supports both workspace-level and user-level Slack app installations
    op.create_index(
        "ix_slack_installations_lookup",
        "slack_installations",
        ["enterprise_id", "team_id", "user_id"],
        unique=True,
    )


def downgrade():
    """Remove slack_installations table."""
    op.drop_index("ix_slack_installations_lookup", table_name="slack_installations")
    op.drop_table("slack_installations")
