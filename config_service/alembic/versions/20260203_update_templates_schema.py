"""Update templates tables to match current model schema.

Aligns database schema with models.py for templates, template_applications,
and template_analytics tables.

Revision ID: 20260203_update_templates_schema
Revises: 20260131_slack_oauth_storage
Create Date: 2026-02-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260203_update_templates_schema"
down_revision = "20260131_slack_oauth_storage"
branch_labels = None
depends_on = None


def upgrade():
    """Update templates tables to match model schema."""

    # ========================================
    # 1. Update templates table
    # ========================================

    # Rename columns
    op.alter_column("templates", "template_id", new_column_name="id")
    op.alter_column("templates", "category", new_column_name="use_case_category")
    op.alter_column("templates", "template_config", new_column_name="template_json")
    op.alter_column("templates", "is_public", new_column_name="is_published")

    # Drop old columns
    op.drop_column("templates", "created_by_team_id")
    op.drop_column("templates", "tags")
    op.drop_column("templates", "is_featured")

    # Add new columns
    op.add_column("templates", sa.Column("slug", sa.String(100), nullable=True))
    op.add_column(
        "templates", sa.Column("detailed_description", sa.Text, nullable=True)
    )
    op.add_column("templates", sa.Column("icon_url", sa.String(500), nullable=True))
    op.add_column(
        "templates",
        sa.Column("example_scenarios", JSONB, server_default="[]", nullable=False),
    )
    op.add_column(
        "templates", sa.Column("demo_video_url", sa.String(500), nullable=True)
    )
    op.add_column(
        "templates",
        sa.Column(
            "is_system_template", sa.Boolean, server_default="true", nullable=False
        ),
    )
    op.add_column(
        "templates",
        sa.Column("version", sa.String(20), server_default="1.0.0", nullable=False),
    )
    op.add_column(
        "templates",
        sa.Column("required_mcps", JSONB, server_default="[]", nullable=False),
    )
    op.add_column(
        "templates",
        sa.Column("required_tools", JSONB, server_default="[]", nullable=False),
    )
    op.add_column(
        "templates", sa.Column("minimum_agent_version", sa.String(20), nullable=True)
    )
    op.add_column(
        "templates",
        sa.Column("usage_count", sa.Integer, server_default="0", nullable=False),
    )
    op.add_column("templates", sa.Column("avg_rating", sa.Integer, nullable=True))

    # Make org_id nullable (model allows it)
    op.alter_column("templates", "org_id", nullable=True)

    # Update slug from name (generate slug from existing data)
    op.execute("""
        UPDATE templates
        SET slug = LOWER(REPLACE(REPLACE(name, ' ', '-'), '.', ''))
        WHERE slug IS NULL
    """)

    # Now make slug NOT NULL and unique
    op.alter_column("templates", "slug", nullable=False)
    op.create_unique_constraint("uq_templates_slug", "templates", ["slug"])

    # Update indexes
    op.drop_index("ix_templates_is_public", "templates")
    op.drop_index("ix_templates_org_id", "templates")
    # ix_templates_category already exists but on wrong column, recreate
    op.drop_index("ix_templates_category", "templates")
    op.create_index("ix_templates_category", "templates", ["use_case_category"])
    op.create_index(
        "ix_templates_published", "templates", ["is_published", "is_system_template"]
    )
    op.create_index("ix_templates_org", "templates", ["org_id"])

    # ========================================
    # 2. Update template_applications table
    # ========================================

    # Drop foreign key constraints first
    op.drop_constraint(
        "template_applications_template_id_fkey",
        "template_applications",
        type_="foreignkey",
    )
    op.drop_constraint(
        "template_applications_org_id_team_node_id_fkey",
        "template_applications",
        type_="foreignkey",
    )

    # Drop indexes before dropping columns (PG auto-drops indexes when columns are removed)
    op.drop_index("ix_template_applications_org_team", "template_applications")
    op.drop_index("ix_template_applications_template_id", "template_applications")

    # Rename primary key column
    op.alter_column("template_applications", "application_id", new_column_name="id")

    # Drop old columns
    op.drop_column("template_applications", "org_id")
    op.drop_column("template_applications", "applied_config")
    op.drop_column("template_applications", "notes")

    # Add new columns
    op.add_column(
        "template_applications",
        sa.Column(
            "template_version", sa.String(20), server_default="1.0.0", nullable=False
        ),
    )
    op.add_column(
        "template_applications",
        sa.Column(
            "has_customizations", sa.Boolean, server_default="false", nullable=False
        ),
    )
    op.add_column(
        "template_applications",
        sa.Column("customization_summary", JSONB, nullable=True),
    )
    op.add_column(
        "template_applications",
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
    )
    op.add_column(
        "template_applications",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Recreate foreign key to templates (now referencing 'id' instead of 'template_id')
    op.create_foreign_key(
        "fk_template_applications_template",
        "template_applications",
        "templates",
        ["template_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Create new indexes (old ones already dropped above before column removal)
    op.create_index(
        "ix_template_applications_template", "template_applications", ["template_id"]
    )
    op.create_index(
        "ix_template_applications_team", "template_applications", ["team_node_id"]
    )
    op.create_index(
        "ix_template_applications_active", "template_applications", ["is_active"]
    )

    # ========================================
    # 3. Recreate template_analytics table
    # ========================================
    # The schema change is too significant (PK change), easier to recreate

    op.drop_table("template_analytics")

    op.create_table(
        "template_analytics",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("team_node_id", sa.String(128), nullable=False),
        sa.Column("first_agent_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_agent_runs", sa.Integer, server_default="0", nullable=False),
        sa.Column("avg_agent_success_rate", sa.Float, nullable=True),
        sa.Column("user_rating", sa.Integer, nullable=True),
        sa.Column("user_feedback", sa.Text, nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            name="fk_template_analytics_template",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_template_analytics_template", "template_analytics", ["template_id"]
    )
    op.create_index(
        "ix_template_analytics_team", "template_analytics", ["team_node_id"]
    )


def downgrade():
    """Revert templates tables to old schema."""
    # This is a complex migration - downgrade would need significant work
    # For now, just raise an error
    raise NotImplementedError("Downgrade not supported for this migration")
