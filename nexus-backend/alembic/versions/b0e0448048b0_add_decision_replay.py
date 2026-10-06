"""add_decision_replay

Revision ID: b0e0448048b0
Revises: 0009_memory_governance
Create Date: 2026-10-01 18:39:59.153644
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b0e0448048b0'
down_revision: Union[str, None] = '0009_memory_governance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_replays",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("decision_type", sa.String(length=40), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=True),
        sa.Column("player_id", sa.Uuid(), nullable=True),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_maker", sa.Uuid(), nullable=True),
        sa.Column("ai_recommendation_text", sa.String(length=4000), nullable=True),
        sa.Column("ai_model", sa.String(length=200), nullable=True),
        sa.Column("ai_model_version", sa.String(length=100), nullable=True),
        sa.Column("ai_recommendation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ai_request_id", sa.Uuid(), nullable=True),
        sa.Column("ai_grounded", sa.Boolean(), nullable=True),
        sa.Column("ai_cited_evidence_ids", sa.String(length=4000), nullable=True),
        sa.Column("human_decision", sa.String(length=50), nullable=True),
        sa.Column("human_decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rationale", sa.String(length=4000), nullable=True),
        sa.Column("evidence_ids", sa.String(length=4000), nullable=True),
        sa.Column("outcome_evidence_ids", sa.String(length=4000), nullable=True),
        sa.Column("outcome_refs", sa.String(length=2000), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision_type IN ('TACTICAL', 'SELECTION', 'TRAINING', 'DEVELOPMENT', 'OTHER')",
            name="ck_decision_replays_type_values",
        ),
        sa.CheckConstraint(
            "human_decision IN ('ACCEPTED', 'REJECTED', 'MODIFIED', 'DEFERRED', 'NO_ACTION')",
            name="ck_decision_replays_human_decision_values",
        ),
        sa.ForeignKeyConstraint(["decision_maker"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_decision_replays_type_at",
        "decision_replays",
        ["decision_type", "decision_at"],
    )
    op.create_index(
        "ix_decision_replays_match", "decision_replays", ["match_id"]
    )
    op.create_index(
        "ix_decision_replays_player", "decision_replays", ["player_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_decision_replays_player", table_name="decision_replays")
    op.drop_index("ix_decision_replays_match", table_name="decision_replays")
    op.drop_index("ix_decision_replays_type_at", table_name="decision_replays")
    op.drop_table("decision_replays")