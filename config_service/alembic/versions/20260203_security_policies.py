"""Update security_policies table to match current model schema.

Aligns database schema with models.py for security_policies table.

Revision ID: 20260203_update_security_policies_schema
Revises: 20260203_update_templates_schema
Create Date: 2026-02-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260203_security_policies"
down_revision = "20260203_update_templates_schema"
branch_labels = None
depends_on = None


def upgrade():
    """Update security_policies table to match model schema."""

    # Add new columns
    op.add_column(
        "security_policies",
        sa.Column("token_warn_before_days", sa.Integer, nullable=True),
    )
    op.add_column(
        "security_policies",
        sa.Column("token_revoke_inactive_days", sa.Integer, nullable=True),
    )
    op.add_column(
        "security_policies",
        sa.Column("locked_settings", JSONB, server_default="[]", nullable=False),
    )
    op.add_column(
        "security_policies",
        sa.Column("max_values", JSONB, server_default="{}", nullable=False),
    )
    op.add_column(
        "security_policies",
        sa.Column("required_settings", JSONB, server_default="{}", nullable=False),
    )
    op.add_column(
        "security_policies",
        sa.Column("allowed_values", JSONB, server_default="{}", nullable=False),
    )
    op.add_column(
        "security_policies",
        sa.Column(
            "require_approval_for_prompts",
            sa.Boolean,
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "security_policies",
        sa.Column(
            "require_approval_for_tools",
            sa.Boolean,
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "security_policies",
        sa.Column("log_all_changes", sa.Boolean, server_default="true", nullable=False),
    )

    # Drop old columns that are no longer in the model
    op.drop_column("security_policies", "require_mfa")
    op.drop_column("security_policies", "session_timeout_minutes")
    op.drop_column("security_policies", "allowed_ip_ranges")
    op.drop_column("security_policies", "require_approval_for_config_changes")


def downgrade():
    """Revert security_policies table to old schema."""
    # This is a complex migration - downgrade would need significant work
    raise NotImplementedError("Downgrade not supported for this migration")
