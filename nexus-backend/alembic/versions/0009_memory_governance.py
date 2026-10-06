"""Add memory governance columns: sensitivity, retention, redaction."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_memory_governance"
down_revision: str | None = "0008_club_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("memory_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sensitivity",
                sa.String(length=40),
                server_default="CLUB_GENERAL",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "redaction_status",
                sa.String(length=40),
                server_default="ACTIVE",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("redacted_by", sa.Uuid(), nullable=True))
        batch_op.create_check_constraint(
            "ck_memory_records_sensitivity_values",
            "sensitivity IN ('CLUB_GENERAL', 'PERFORMANCE', 'PLAYER_DEVELOPMENT', "
            "'AVAILABILITY', 'TACTICAL', 'SCOUTING', 'DECISION', 'RESTRICTED')",
        )
        batch_op.create_check_constraint(
            "ck_memory_records_redaction_values",
            "redaction_status IN ('ACTIVE', 'REDACTED')",
        )
        batch_op.create_foreign_key(
            "fk_memory_records_redacted_by",
            "users",
            ["redacted_by"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_memory_records_sensitivity", ["sensitivity"])


def downgrade() -> None:
    with op.batch_alter_table("memory_records") as batch_op:
        batch_op.drop_index("ix_memory_records_sensitivity")
        batch_op.drop_constraint("fk_memory_records_redacted_by", type_="foreignkey")
        batch_op.drop_constraint("ck_memory_records_redaction_values", type_="check")
        batch_op.drop_constraint("ck_memory_records_sensitivity_values", type_="check")
        batch_op.drop_column("redacted_by")
        batch_op.drop_column("redacted_at")
        batch_op.drop_column("redaction_status")
        batch_op.drop_column("retention_until")
        batch_op.drop_column("sensitivity")
