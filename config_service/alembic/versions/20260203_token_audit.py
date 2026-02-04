"""Update token_audit table to match current model schema.

Aligns database schema with models.py for token_audit table.

Revision ID: 20260203_token_audit
Revises: 20260203_security_policies
Create Date: 2026-02-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260203_token_audit"
down_revision = "20260203_security_policies"
branch_labels = None
depends_on = None


def upgrade():
    """Update token_audit table to match model schema."""

    # Add new columns
    op.add_column(
        "token_audit",
        sa.Column(
            "event_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "token_audit",
        sa.Column("actor", sa.String(128), nullable=True),
    )
    op.add_column(
        "token_audit",
        sa.Column("details", JSONB, nullable=True),
    )

    # Migrate data from created_at to event_at
    op.execute("""
        UPDATE token_audit
        SET event_at = created_at
        WHERE created_at IS NOT NULL
    """)

    # Drop old columns
    op.drop_column("token_audit", "endpoint")
    op.drop_column("token_audit", "success")
    op.drop_column("token_audit", "error_message")
    op.drop_column("token_audit", "created_at")

    # Create indexes
    op.create_index("ix_token_audit_event_at", "token_audit", ["event_at"])


def downgrade():
    """Revert token_audit table to old schema."""
    raise NotImplementedError("Downgrade not supported for this migration")
