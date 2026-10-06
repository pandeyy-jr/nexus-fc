"""Create player, staff, team, and player-team membership tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_squad_domain"
down_revision: str | None = "0002_user_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLAYER_POSITIONS = (
    "GK",
    "CB",
    "LB",
    "RB",
    "LWB",
    "RWB",
    "DM",
    "CM",
    "AM",
    "LW",
    "RW",
    "ST",
    "CF",
)
DOMINANT_FEET = ("LEFT", "RIGHT", "BOTH")
PLAYER_STATUSES = ("ACTIVE", "INACTIVE", "SUSPENDED")
SQUAD_STATUSES = ("ACTIVE", "INACTIVE", "LOANED", "RELEASED")


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("short_name", sa.String(length=30), nullable=False),
        sa.Column("age_group", sa.String(length=40), nullable=False),
        sa.Column("gender_category", sa.String(length=40), nullable=False),
        sa.Column("season", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_teams"),
    )
    op.create_index("ix_teams_name", "teams", ["name"], unique=False)
    op.create_index(
        "ix_teams_is_active_name", "teams", ["is_active", "name"], unique=False
    )

    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("nationality", sa.String(length=80), nullable=True),
        sa.Column("preferred_position", sa.String(length=40), nullable=False),
        sa.Column("secondary_position", sa.String(length=40), nullable=True),
        sa.Column("squad_number", sa.Integer(), nullable=True),
        sa.Column("dominant_foot", sa.String(length=40), nullable=True),
        sa.Column("height_cm", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("profile_photo_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
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
        sa.CheckConstraint(
            f"preferred_position IN ({_values(PLAYER_POSITIONS)})",
            name="ck_players_preferred_position_values",
        ),
        sa.CheckConstraint(
            "secondary_position IS NULL OR "
            f"secondary_position IN ({_values(PLAYER_POSITIONS)})",
            name="ck_players_secondary_position_values",
        ),
        sa.CheckConstraint(
            f"dominant_foot IS NULL OR dominant_foot IN ({_values(DOMINANT_FEET)})",
            name="ck_players_dominant_foot_values",
        ),
        sa.CheckConstraint(
            f"status IN ({_values(PLAYER_STATUSES)})",
            name="ck_players_player_status_values",
        ),
        sa.CheckConstraint(
            "squad_number IS NULL OR squad_number BETWEEN 0 AND 99",
            name="ck_players_squad_number_range",
        ),
        sa.CheckConstraint(
            "height_cm IS NULL OR height_cm BETWEEN 100 AND 250",
            name="ck_players_height_cm_range",
        ),
        sa.CheckConstraint(
            "weight_kg IS NULL OR weight_kg BETWEEN 30 AND 200",
            name="ck_players_weight_kg_range",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_players_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_players"),
        sa.UniqueConstraint("user_id", name="uq_players_user_id"),
    )
    op.create_index(
        "ix_players_last_first_name",
        "players",
        ["last_name", "first_name"],
        unique=False,
    )

    op.create_table(
        "staff",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("job_title", sa.String(length=120), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_staff_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff"),
    )
    op.create_index("ix_staff_user_id", "staff", ["user_id"], unique=True)

    op.create_table(
        "player_team_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("squad_status", sa.String(length=40), nullable=False),
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
        sa.CheckConstraint(
            f"squad_status IN ({_values(SQUAD_STATUSES)})",
            name="ck_player_team_memberships_squad_status_values",
        ),
        sa.CheckConstraint(
            "left_at IS NULL OR left_at >= joined_at",
            name="ck_player_team_memberships_membership_dates",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_player_team_memberships_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_player_team_memberships_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_player_team_memberships"),
    )
    op.create_index(
        "ix_memberships_team_joined",
        "player_team_memberships",
        ["team_id", "joined_at"],
        unique=False,
    )
    op.create_index(
        "ix_player_team_memberships_player_id",
        "player_team_memberships",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        "ix_player_team_memberships_team_id",
        "player_team_memberships",
        ["team_id"],
        unique=False,
    )
    op.create_index(
        "uq_current_player_team_membership",
        "player_team_memberships",
        ["player_id", "team_id"],
        unique=True,
        sqlite_where=sa.text("left_at IS NULL"),
        postgresql_where=sa.text("left_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_current_player_team_membership",
        table_name="player_team_memberships",
    )
    op.drop_index(
        "ix_player_team_memberships_team_id",
        table_name="player_team_memberships",
    )
    op.drop_index(
        "ix_player_team_memberships_player_id",
        table_name="player_team_memberships",
    )
    op.drop_index(
        "ix_memberships_team_joined",
        table_name="player_team_memberships",
    )
    op.drop_table("player_team_memberships")
    op.drop_index("ix_staff_user_id", table_name="staff")
    op.drop_table("staff")
    op.drop_index("ix_players_last_first_name", table_name="players")
    op.drop_table("players")
    op.drop_index("ix_teams_is_active_name", table_name="teams")
    op.drop_index("ix_teams_name", table_name="teams")
    op.drop_table("teams")
