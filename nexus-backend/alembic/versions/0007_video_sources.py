"""Persist ingested video source metadata."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_video_sources"
down_revision: str | None = "0006_match_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=180), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("frame_rate", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "processing_status",
            sa.String(length=20),
            server_default="READY",
            nullable=False,
        ),
        sa.Column("storage_reference", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "file_size_bytes > 0", name="ck_video_sources_file_size_positive"
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds > 0",
            name="ck_video_sources_duration_positive",
        ),
        sa.CheckConstraint(
            "frame_rate IS NULL OR frame_rate > 0",
            name="ck_video_sources_frame_rate_positive",
        ),
        sa.CheckConstraint(
            "width IS NULL OR width > 0", name="ck_video_sources_width_positive"
        ),
        sa.CheckConstraint(
            "height IS NULL OR height > 0", name="ck_video_sources_height_positive"
        ),
        sa.CheckConstraint(
            "processing_status IN ('RECEIVED', 'READY', 'FAILED')",
            name="ck_video_sources_processing_status_values",
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_reference"),
    )
    op.create_index("ix_video_sources_match_id", "video_sources", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_video_sources_match_id", table_name="video_sources")
    op.drop_table("video_sources")
