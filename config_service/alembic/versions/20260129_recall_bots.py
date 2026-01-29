"""Add recall_bots table for tracking Recall.ai meeting bots.

Tracks active and completed Recall.ai bots that join meetings for
real-time transcription during incident war rooms.

Revision ID: 20260129_recall_bots
Revises: 20260128_visitor_playground
Create Date: 2026-01-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260129_recall_bots"
down_revision = "20260128_visitor_playground"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create recall_bots table
    op.create_table(
        "recall_bots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("team_node_id", sa.String(64), nullable=False),
        sa.Column("incident_id", sa.String(64), nullable=True),
        # Recall.ai data
        sa.Column("recall_bot_id", sa.String(255), nullable=False, unique=True),
        sa.Column("meeting_url", sa.Text(), nullable=False),
        sa.Column(
            "meeting_platform",
            sa.String(50),
            nullable=True,
        ),  # zoom, google_meet, teams, webex, etc.
        # Bot configuration
        sa.Column("bot_name", sa.String(255), nullable=True),
        sa.Column("bot_image_url", sa.Text(), nullable=True),
        # Status tracking
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="requested",
        ),  # requested, joining, in_call, recording, done, error, stopped
        sa.Column("status_message", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        # Transcript tracking
        sa.Column("transcript_segments_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_transcript_at", sa.DateTime(timezone=True), nullable=True),
        # Metadata
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=True,
        ),
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
            nullable=False,
        ),
    )

    # Indexes for common queries
    op.create_index("ix_recall_bots_org_id", "recall_bots", ["org_id"])
    op.create_index("ix_recall_bots_team_node_id", "recall_bots", ["team_node_id"])
    op.create_index("ix_recall_bots_incident_id", "recall_bots", ["incident_id"])
    op.create_index("ix_recall_bots_recall_bot_id", "recall_bots", ["recall_bot_id"], unique=True)
    op.create_index("ix_recall_bots_status", "recall_bots", ["status"])
    op.create_index("ix_recall_bots_created_at", "recall_bots", ["created_at"])
    op.create_index(
        "ix_recall_bots_org_status",
        "recall_bots",
        ["org_id", "status"],
    )

    # Create recall_transcript_segments table for storing real-time transcript data
    op.create_table(
        "recall_transcript_segments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("recall_bot_id", sa.String(255), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("incident_id", sa.String(64), nullable=True),
        # Transcript data
        sa.Column("speaker", sa.String(255), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("timestamp_ms", sa.BigInteger(), nullable=True),
        sa.Column("is_partial", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("confidence", sa.Float(), nullable=True),
        # Metadata
        sa.Column(
            "raw_event",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Indexes for transcript segments
    op.create_index("ix_recall_transcript_segments_recall_bot_id", "recall_transcript_segments", ["recall_bot_id"])
    op.create_index("ix_recall_transcript_segments_org_id", "recall_transcript_segments", ["org_id"])
    op.create_index("ix_recall_transcript_segments_incident_id", "recall_transcript_segments", ["incident_id"])
    op.create_index("ix_recall_transcript_segments_created_at", "recall_transcript_segments", ["created_at"])
    op.create_index(
        "ix_recall_transcript_segments_bot_timestamp",
        "recall_transcript_segments",
        ["recall_bot_id", "timestamp_ms"],
    )


def downgrade() -> None:
    # Drop recall_transcript_segments
    op.drop_index("ix_recall_transcript_segments_bot_timestamp", table_name="recall_transcript_segments")
    op.drop_index("ix_recall_transcript_segments_created_at", table_name="recall_transcript_segments")
    op.drop_index("ix_recall_transcript_segments_incident_id", table_name="recall_transcript_segments")
    op.drop_index("ix_recall_transcript_segments_org_id", table_name="recall_transcript_segments")
    op.drop_index("ix_recall_transcript_segments_recall_bot_id", table_name="recall_transcript_segments")
    op.drop_table("recall_transcript_segments")

    # Drop recall_bots
    op.drop_index("ix_recall_bots_org_status", table_name="recall_bots")
    op.drop_index("ix_recall_bots_created_at", table_name="recall_bots")
    op.drop_index("ix_recall_bots_status", table_name="recall_bots")
    op.drop_index("ix_recall_bots_recall_bot_id", table_name="recall_bots")
    op.drop_index("ix_recall_bots_incident_id", table_name="recall_bots")
    op.drop_index("ix_recall_bots_team_node_id", table_name="recall_bots")
    op.drop_index("ix_recall_bots_org_id", table_name="recall_bots")
    op.drop_table("recall_bots")
