"""Add user profile timestamps and constrain the role catalog."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_user_profile"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_VALUES = (
    "HEAD_COACH",
    "ASSISTANT_COACH",
    "ANALYST",
    "SPORTS_SCIENTIST",
    "MEDICAL_STAFF",
    "SCOUT",
    "PLAYER",
    "DIRECTOR",
    "ADMIN",
)


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(length=120)))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True)))
    op.execute(sa.text("UPDATE users SET full_name = email WHERE full_name IS NULL"))
    op.execute(
        sa.text("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL")
    )

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "full_name",
            existing_type=sa.String(length=120),
            nullable=False,
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )

    values = ", ".join(f"'{role}'" for role in ROLE_VALUES)
    with op.batch_alter_table("roles") as batch_op:
        batch_op.create_check_constraint(
            op.f("ck_roles_role_name"),
            f"name IN ({values})",
        )


def downgrade() -> None:
    with op.batch_alter_table("roles") as batch_op:
        batch_op.drop_constraint(op.f("ck_roles_role_name"), type_="check")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("full_name")
