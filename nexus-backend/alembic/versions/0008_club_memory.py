"""Persist Club Memory records, evidence references, and decisions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_club_memory"
down_revision: str | None = "0007_video_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=2000), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("extra_data", sa.String(length=4000), nullable=True),
        sa.CheckConstraint(
            "memory_type IN ('MATCH', 'TRAINING', 'PLAYER_DEVELOPMENT', "
            "'AVAILABILITY', 'TACTICAL', 'SCOUTING', 'DECISION')",
            name="ck_memory_records_memory_type_values",
        ),
        sa.CheckConstraint(
            "source_type IN ('HUMAN_RECORDED', 'MATCH_EVENT', 'TRAINING_RECORD', "
            "'VISION', 'TACTICAL_ANALYSIS', 'SYSTEM_GENERATED')",
            name="ck_memory_records_source_values",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_memory_records_confidence_range",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_records_type_occurred",
        "memory_records",
        ["memory_type", "occurred_at"],
    )
    op.create_index(
        "ix_memory_records_source", "memory_records", ["source_type", "source_id"]
    )

    op.create_table(
        "evidence_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_record_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=True),
        sa.Column("video_id", sa.Uuid(), nullable=True),
        sa.Column("frame_number", sa.Integer(), nullable=True),
        sa.Column("timestamp_seconds", sa.Float(), nullable=True),
        sa.Column("evidence_type", sa.String(length=40), nullable=False),
        sa.Column("excerpt", sa.String(length=2000), nullable=True),
        sa.Column("provenance", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('HUMAN_RECORDED', 'MATCH_EVENT', 'TRAINING_RECORD', "
            "'VISION', 'TACTICAL_ANALYSIS', 'SYSTEM_GENERATED')",
            name="ck_evidence_references_source_values",
        ),
        sa.CheckConstraint(
            "evidence_type IN ('TEXT_EXCERPT', 'FRAME_REFERENCE', "
            "'METRIC_VALUE', 'EXTERNAL_LINK')",
            name="ck_evidence_references_type_values",
        ),
        sa.CheckConstraint(
            "frame_number IS NULL OR frame_number >= 0",
            name="ck_evidence_references_frame_nonnegative",
        ),
        sa.CheckConstraint(
            "timestamp_seconds IS NULL OR timestamp_seconds >= 0",
            name="ck_evidence_references_timestamp_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["memory_record_id"], ["memory_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["video_id"], ["video_sources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_references_memory", "evidence_references", ["memory_record_id"]
    )
    op.create_index("ix_evidence_references_match", "evidence_references", ["match_id"])
    op.create_index(
        "ix_evidence_references_source",
        "evidence_references",
        ["source_type", "source_id"],
    )

    op.create_table(
        "decision_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("decision_type", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.String(length=2000), nullable=False),
        sa.Column("context", sa.String(length=500), nullable=True),
        sa.Column("rationale", sa.String(length=2000), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_maker", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("related_memory_id", sa.Uuid(), nullable=True),
        sa.Column("related_evidence_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision_type IN ('TACTICAL', 'SELECTION', 'TRAINING', "
            "'DEVELOPMENT', 'OTHER')",
            name="ck_decision_records_type_values",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'SUPERSEDED')",
            name="ck_decision_records_status_values",
        ),
        sa.ForeignKeyConstraint(["decision_maker"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["related_memory_id"], ["memory_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["related_evidence_id"], ["evidence_references.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_decision_records_type_at",
        "decision_records",
        ["decision_type", "decision_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_decision_records_type_at", table_name="decision_records")
    op.drop_table("decision_records")
    op.drop_index("ix_evidence_references_source", table_name="evidence_references")
    op.drop_index("ix_evidence_references_match", table_name="evidence_references")
    op.drop_index("ix_evidence_references_memory", table_name="evidence_references")
    op.drop_table("evidence_references")
    op.drop_index("ix_memory_records_source", table_name="memory_records")
    op.drop_index("ix_memory_records_type_occurred", table_name="memory_records")
    op.drop_table("memory_records")
