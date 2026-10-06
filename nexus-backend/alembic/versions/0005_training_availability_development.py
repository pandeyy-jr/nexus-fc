"""Add training, operational availability, and player development tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_phase04_domains"
down_revision: str | None = "0004_distinct_positions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SESSION_TYPES = (
    "RECOVERY",
    "TECHNICAL",
    "TACTICAL",
    "FITNESS",
    "MATCH_PREPARATION",
    "RECOVERY_AFTER_MATCH",
    "INDIVIDUAL",
    "OTHER",
)
ATTENDANCE_STATUSES = ("PLANNED", "ATTENDED", "PARTIAL", "ABSENT", "EXCUSED")
AVAILABILITY_STATUSES = ("AVAILABLE", "LIMITED", "UNAVAILABLE")
AVAILABILITY_REASONS = (
    "COACHING",
    "REST",
    "SUSPENSION",
    "ADMINISTRATIVE",
    "MEDICAL_RESTRICTION",
    "OTHER",
)
DEVELOPMENT_CATEGORIES = (
    "TECHNICAL",
    "TACTICAL",
    "PHYSICAL",
    "MENTAL",
    "POSITIONAL",
    "OTHER",
)
DEVELOPMENT_STATUSES = (
    "NOT_STARTED",
    "IN_PROGRESS",
    "COMPLETED",
    "PAUSED",
    "CANCELLED",
)
DEVELOPMENT_PRIORITIES = ("LOW", "MEDIUM", "HIGH")


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "training_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("session_type", sa.String(length=40), nullable=False),
        sa.Column("objective", sa.String(length=500), nullable=True),
        sa.Column("planned_intensity", sa.Integer(), nullable=True),
        sa.Column("planned_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
            f"session_type IN ({_values(SESSION_TYPES)})",
            name="ck_training_sessions_session_type_values",
        ),
        sa.CheckConstraint(
            "end_time > start_time", name="ck_training_sessions_session_time_order"
        ),
        sa.CheckConstraint(
            "planned_intensity IS NULL OR planned_intensity BETWEEN 1 AND 10",
            name="ck_training_sessions_planned_intensity_range",
        ),
        sa.CheckConstraint(
            "planned_duration_minutes IS NULL OR "
            "planned_duration_minutes BETWEEN 1 AND 600",
            name="ck_training_sessions_planned_duration_range",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_training_sessions_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_training_sessions_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_training_sessions"),
    )
    op.create_index(
        "ix_training_sessions_team_id", "training_sessions", ["team_id"], unique=False
    )
    op.create_index(
        "ix_training_sessions_team_date",
        "training_sessions",
        ["team_id", "session_date"],
        unique=False,
    )

    op.create_table(
        "training_participations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("training_session_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("attendance_status", sa.String(length=40), nullable=False),
        sa.Column("planned_load", sa.Float(), nullable=True),
        sa.Column("actual_load", sa.Float(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("player_response", sa.String(length=1000), nullable=True),
        sa.Column("coach_note", sa.String(length=1000), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
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
            f"attendance_status IN ({_values(ATTENDANCE_STATUSES)})",
            name="ck_training_participations_attendance_status_values",
        ),
        sa.CheckConstraint(
            "planned_load IS NULL OR planned_load BETWEEN 0 AND 1000",
            name="ck_training_participations_planned_load_range",
        ),
        sa.CheckConstraint(
            "actual_load IS NULL OR actual_load BETWEEN 0 AND 1000",
            name="ck_training_participations_actual_load_range",
        ),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes BETWEEN 0 AND 600",
            name="ck_training_participations_duration_minutes_range",
        ),
        sa.ForeignKeyConstraint(
            ["training_session_id"],
            ["training_sessions.id"],
            name="fk_training_participations_training_session_id_training_sessions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_training_participations_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_training_participations"),
        sa.UniqueConstraint(
            "training_session_id",
            "player_id",
            name="uq_training_participation_session_player",
        ),
    )
    op.create_index(
        "ix_training_participations_training_session_id",
        "training_participations",
        ["training_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_training_participations_player_id",
        "training_participations",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        "ix_training_participations_player",
        "training_participations",
        ["player_id", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "player_availability",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_category", sa.String(length=40), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
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
            f"status IN ({_values(AVAILABILITY_STATUSES)})",
            name="ck_player_availability_availability_status_values",
        ),
        sa.CheckConstraint(
            f"reason_category IN ({_values(AVAILABILITY_REASONS)})",
            name="ck_player_availability_availability_reason_values",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_player_availability_availability_dates",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_player_availability_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["users.id"],
            name="fk_player_availability_recorded_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_player_availability"),
    )
    op.create_index(
        "ix_player_availability_player_id",
        "player_availability",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        "ix_player_availability_history",
        "player_availability",
        ["player_id", "effective_from"],
        unique=False,
    )
    op.create_index(
        "uq_player_availability_open",
        "player_availability",
        ["player_id"],
        unique=True,
        sqlite_where=sa.text("effective_until IS NULL"),
        postgresql_where=sa.text("effective_until IS NULL"),
    )

    op.create_table(
        "player_development_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=40), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
            f"category IN ({_values(DEVELOPMENT_CATEGORIES)})",
            name="ck_player_development_goals_development_category_values",
        ),
        sa.CheckConstraint(
            f"status IN ({_values(DEVELOPMENT_STATUSES)})",
            name="ck_player_development_goals_development_status_values",
        ),
        sa.CheckConstraint(
            f"priority IN ({_values(DEVELOPMENT_PRIORITIES)})",
            name="ck_player_development_goals_development_priority_values",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_player_development_goals_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_player_development_goals_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_player_development_goals_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_player_development_goals"),
    )
    op.create_index(
        "ix_player_development_goals_player_id",
        "player_development_goals",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        "ix_development_goals_player_status",
        "player_development_goals",
        ["player_id", "status"],
        unique=False,
    )

    op.create_table(
        "player_development_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=True),
        sa.Column("assessment_date", sa.Date(), nullable=False),
        sa.Column("assessor_id", sa.Uuid(), nullable=False),
        sa.Column("progress_status", sa.String(length=40), nullable=False),
        sa.Column("assessment_note", sa.String(length=2000), nullable=False),
        sa.Column("next_action", sa.String(length=1000), nullable=True),
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
            f"progress_status IN ({_values(DEVELOPMENT_STATUSES)})",
            name="ck_player_development_assessments_assessment_progress_status_values",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_player_development_assessments_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["player_development_goals.id"],
            name="fk_player_development_assessments_goal_id_player_development_goals",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assessor_id"],
            ["users.id"],
            name="fk_player_development_assessments_assessor_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_player_development_assessments"),
    )
    op.create_index(
        "ix_player_development_assessments_player_id",
        "player_development_assessments",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        "ix_development_assessments_player_date",
        "player_development_assessments",
        ["player_id", "assessment_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_development_assessments_player_date",
        table_name="player_development_assessments",
    )
    op.drop_index(
        "ix_player_development_assessments_player_id",
        table_name="player_development_assessments",
    )
    op.drop_table("player_development_assessments")
    op.drop_index(
        "ix_development_goals_player_status",
        table_name="player_development_goals",
    )
    op.drop_index(
        "ix_player_development_goals_player_id",
        table_name="player_development_goals",
    )
    op.drop_table("player_development_goals")
    op.drop_index("uq_player_availability_open", table_name="player_availability")
    op.drop_index("ix_player_availability_history", table_name="player_availability")
    op.drop_index("ix_player_availability_player_id", table_name="player_availability")
    op.drop_table("player_availability")
    op.drop_index(
        "ix_training_participations_player",
        table_name="training_participations",
    )
    op.drop_index(
        "ix_training_participations_player_id",
        table_name="training_participations",
    )
    op.drop_index(
        "ix_training_participations_training_session_id",
        table_name="training_participations",
    )
    op.drop_table("training_participations")
    op.drop_index("ix_training_sessions_team_date", table_name="training_sessions")
    op.drop_index("ix_training_sessions_team_id", table_name="training_sessions")
    op.drop_table("training_sessions")
