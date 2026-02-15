"""Align org_admin_tokens schema with OrgAdminToken model.

Prod has different column names from an earlier manual schema:
  name -> label, created_by -> issued_by, created_at -> issued_at,
  missing revoked_at, extra is_active.

Demo already matches the model (all columns correct).

This migration inspects the current schema and only applies the
changes that are actually needed.

Revision ID: 20260208_org_admin_token_cols
Revises: 20260203_k8s_clusters
Create Date: 2026-02-08
"""

import sqlalchemy as sa
from alembic import op

revision = "20260208_org_admin_token_cols"
down_revision = "20260203_k8s_clusters"
branch_labels = None
depends_on = None


def _get_existing_columns():
    """Return set of column names for org_admin_tokens."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'org_admin_tokens'"
        )
    )
    return {row[0] for row in result}


def upgrade():
    cols = _get_existing_columns()

    # Rename columns that differ between prod schema and model
    if "name" in cols and "label" not in cols:
        op.alter_column("org_admin_tokens", "name", new_column_name="label")

    if "created_by" in cols and "issued_by" not in cols:
        op.alter_column("org_admin_tokens", "created_by", new_column_name="issued_by")

    if "created_at" in cols and "issued_at" not in cols:
        op.alter_column("org_admin_tokens", "created_at", new_column_name="issued_at")

    # Add missing columns (only if not already present)
    if "revoked_at" not in cols:
        op.add_column(
            "org_admin_tokens",
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "expires_at" not in cols:
        op.add_column(
            "org_admin_tokens",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "last_used_at" not in cols:
        op.add_column(
            "org_admin_tokens",
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        )

    # Migrate is_active=false -> revoked_at (prod only)
    # Then drop is_active since the model uses revoked_at instead.
    if "is_active" in cols:
        conn = op.get_bind()
        conn.execute(
            sa.text(
                "UPDATE org_admin_tokens SET revoked_at = now() "
                "WHERE is_active = false AND revoked_at IS NULL"
            )
        )
        op.drop_column("org_admin_tokens", "is_active")


def downgrade():
    # Best-effort reverse; column renames are reversed, added columns dropped.
    cols = _get_existing_columns()

    if "label" in cols:
        op.alter_column("org_admin_tokens", "label", new_column_name="name")
    if "issued_by" in cols:
        op.alter_column("org_admin_tokens", "issued_by", new_column_name="created_by")
    if "issued_at" in cols:
        op.alter_column("org_admin_tokens", "issued_at", new_column_name="created_at")

    # Re-add is_active
    if "is_active" not in cols:
        op.add_column(
            "org_admin_tokens",
            sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        )
        conn = op.get_bind()
        conn.execute(
            sa.text(
                "UPDATE org_admin_tokens SET is_active = false "
                "WHERE revoked_at IS NOT NULL"
            )
        )

    for col in ("revoked_at", "expires_at", "last_used_at"):
        if col in cols:
            op.drop_column("org_admin_tokens", col)
