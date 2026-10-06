"""Prevent a player's primary and secondary positions from matching."""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_distinct_positions"
down_revision: str | None = "0003_squad_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("players") as batch_op:
        batch_op.create_check_constraint(
            op.f("ck_players_distinct_positions"),
            "secondary_position IS NULL OR secondary_position != preferred_position",
        )


def downgrade() -> None:
    with op.batch_alter_table("players") as batch_op:
        batch_op.drop_constraint(op.f("ck_players_distinct_positions"), type_="check")
