"""Create initial role and user tables."""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name="fk_users_role_id_roles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_role_id", "users", ["role_id"], unique=False)

    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
    )
    op.bulk_insert(
        roles_table,
        [
            {"id": uuid4(), "name": "PLAYER", "description": "Player"},
            {"id": uuid4(), "name": "HEAD_COACH", "description": "Head coach"},
            {
                "id": uuid4(),
                "name": "ASSISTANT_COACH",
                "description": "Assistant coach",
            },
            {"id": uuid4(), "name": "ANALYST", "description": "Analyst"},
            {
                "id": uuid4(),
                "name": "SPORTS_SCIENTIST",
                "description": "Sports scientist",
            },
            {"id": uuid4(), "name": "MEDICAL_STAFF", "description": "Medical staff"},
            {"id": uuid4(), "name": "SCOUT", "description": "Scout"},
            {"id": uuid4(), "name": "DIRECTOR", "description": "Director"},
            {"id": uuid4(), "name": "ADMIN", "description": "Administrator"},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_table("users")
    op.drop_table("roles")
