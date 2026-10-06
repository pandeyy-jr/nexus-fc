"""Add match catalog, match, squad, participation, event, and substitution tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_match_domain"
down_revision: str | None = "0005_phase04_domains"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMPETITION_TYPES = (
    "LEAGUE",
    "CUP",
    "FRIENDLY",
    "TOURNAMENT",
    "CONTINENTAL",
    "OTHER",
)
MATCH_SIDES = ("HOME", "AWAY", "NEUTRAL")
MATCH_STATUSES = (
    "SCHEDULED",
    "LIVE",
    "COMPLETED",
    "POSTPONED",
    "CANCELLED",
    "ABANDONED",
)
SQUAD_STATUSES = ("SELECTED", "STARTER", "SUBSTITUTE", "UNUSED", "WITHDRAWN")
EVENT_TYPES = (
    "GOAL",
    "OWN_GOAL",
    "YELLOW_CARD",
    "RED_CARD",
    "SECOND_YELLOW",
    "SUBSTITUTION",
    "PENALTY_WON",
    "PENALTY_MISSED",
    "VAR_REVIEW",
    "KICK_OFF",
    "HALF_TIME",
    "FULL_TIME",
    "OTHER",
)
EVENT_SOURCES = ("MANUAL", "OFFICIAL_REPORT", "VIDEO_REVIEW", "OTHER")
SUBSTITUTION_REASONS = ("TACTICAL", "INJURY", "REST", "OTHER")


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "opponents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("short_name", sa.String(length=40), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_opponents"),
        sa.UniqueConstraint("name", name="uq_opponents_name"),
    )
    op.create_index("ix_opponents_name", "opponents", ["name"], unique=False)

    op.create_table(
        "venues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
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
            "capacity IS NULL OR capacity BETWEEN 1 AND 200000",
            name="ck_venues_capacity_range",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_venues"),
    )
    op.create_index("ix_venues_name", "venues", ["name"], unique=False)

    op.create_table(
        "competitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("short_name", sa.String(length=40), nullable=True),
        sa.Column("competition_type", sa.String(length=40), nullable=False),
        sa.Column("season", sa.String(length=20), nullable=False),
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
            f"competition_type IN ({_values(COMPETITION_TYPES)})",
            name="ck_competitions_competition_type_values",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_competitions"),
    )
    op.create_index(
        "ix_competitions_name_season", "competitions", ["name", "season"], unique=False
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("opponent_id", sa.Uuid(), nullable=False),
        sa.Column("competition_id", sa.Uuid(), nullable=True),
        sa.Column("venue_id", sa.Uuid(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("home_away", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("matchday", sa.Integer(), nullable=True),
        sa.Column("season", sa.String(length=20), nullable=True),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=4000), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
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
            f"home_away IN ({_values(MATCH_SIDES)})", name="ck_matches_home_away_values"
        ),
        sa.CheckConstraint(
            f"status IN ({_values(MATCH_STATUSES)})",
            name="ck_matches_match_status_values",
        ),
        sa.CheckConstraint(
            "matchday IS NULL OR matchday > 0", name="ck_matches_matchday_positive"
        ),
        sa.CheckConstraint(
            "(home_score IS NULL AND away_score IS NULL) OR "
            "(home_score IS NOT NULL AND away_score IS NOT NULL)",
            name="ck_matches_score_pair",
        ),
        sa.CheckConstraint(
            "home_score IS NULL OR (home_score >= 0 AND away_score >= 0)",
            name="ck_matches_score_nonnegative",
        ),
        sa.CheckConstraint(
            "actual_start_at IS NULL OR actual_end_at IS NULL OR "
            "actual_end_at >= actual_start_at",
            name="ck_matches_actual_time_order",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_matches_team_id_teams",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opponent_id"],
            ["opponents.id"],
            name="fk_matches_opponent_id_opponents",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["competition_id"],
            ["competitions.id"],
            name="fk_matches_competition_id_competitions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            ["venues.id"],
            name="fk_matches_venue_id_venues",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_matches_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_matches_updated_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matches"),
    )
    op.create_index("ix_matches_team_id", "matches", ["team_id"], unique=False)
    op.create_index("ix_matches_opponent_id", "matches", ["opponent_id"], unique=False)
    op.create_index(
        "ix_matches_team_scheduled",
        "matches",
        ["team_id", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_matches_opponent_scheduled",
        "matches",
        ["opponent_id", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_matches_competition", "matches", ["competition_id"], unique=False
    )

    op.create_table(
        "match_squads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("squad_status", sa.String(length=40), nullable=False),
        sa.Column("shirt_number", sa.Integer(), nullable=True),
        sa.Column("starting", sa.Boolean(), nullable=False),
        sa.Column("captain", sa.Boolean(), nullable=False),
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
            name="ck_match_squads_squad_status_values",
        ),
        sa.CheckConstraint(
            "shirt_number IS NULL OR shirt_number BETWEEN 0 AND 99",
            name="ck_match_squads_shirt_number_range",
        ),
        sa.CheckConstraint(
            "(squad_status = 'STARTER' AND starting IS TRUE) OR "
            "squad_status = 'WITHDRAWN' OR "
            "(squad_status != 'STARTER' AND starting IS FALSE)",
            name="ck_match_squads_starting_status_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name="fk_match_squads_match_id_matches",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_match_squads_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_match_squads"),
        sa.UniqueConstraint("match_id", "player_id", name="uq_match_squad_player"),
    )
    op.create_index(
        "ix_match_squads_match_id", "match_squads", ["match_id"], unique=False
    )
    op.create_index(
        "ix_match_squads_player_id", "match_squads", ["player_id"], unique=False
    )
    op.create_index(
        "uq_match_squad_captain",
        "match_squads",
        ["match_id"],
        unique=True,
        sqlite_where=sa.text("captain IS TRUE"),
        postgresql_where=sa.text("captain IS TRUE"),
    )

    op.create_table(
        "match_participations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_squad_id", sa.Uuid(), nullable=False),
        sa.Column("started_at_minute", sa.Integer(), nullable=True),
        sa.Column("ended_at_minute", sa.Integer(), nullable=True),
        sa.Column("minutes_played", sa.Integer(), nullable=True),
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
            "started_at_minute IS NULL OR started_at_minute BETWEEN 0 AND 130",
            name="ck_match_participations_started_minute_range",
        ),
        sa.CheckConstraint(
            "ended_at_minute IS NULL OR ended_at_minute BETWEEN 0 AND 130",
            name="ck_match_participations_ended_minute_range",
        ),
        sa.CheckConstraint(
            "minutes_played IS NULL OR minutes_played BETWEEN 0 AND 130",
            name="ck_match_participations_minutes_played_range",
        ),
        sa.CheckConstraint(
            "started_at_minute IS NULL OR ended_at_minute IS NULL OR "
            "ended_at_minute >= started_at_minute",
            name="ck_match_participations_participation_minute_order",
        ),
        sa.ForeignKeyConstraint(
            ["match_squad_id"],
            ["match_squads.id"],
            name="fk_match_participations_match_squad_id_match_squads",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_match_participations"),
        sa.UniqueConstraint("match_squad_id", name="uq_match_participation_squad"),
    )
    op.create_index(
        "ix_match_participations_match_squad_id",
        "match_participations",
        ["match_squad_id"],
        unique=False,
    )

    op.create_table(
        "match_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("side", sa.String(length=40), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=True),
        sa.Column("assist_player_id", sa.Uuid(), nullable=True),
        sa.Column("related_player_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("added_time_minute", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("is_penalty", sa.Boolean(), nullable=False),
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
            f"event_type IN ({_values(EVENT_TYPES)})",
            name="ck_match_events_event_type_values",
        ),
        sa.CheckConstraint(
            f"side IN ({_values(MATCH_SIDES)})",
            name="ck_match_events_event_side_values",
        ),
        sa.CheckConstraint(
            f"source IN ({_values(EVENT_SOURCES)})",
            name="ck_match_events_event_source_values",
        ),
        sa.CheckConstraint(
            "minute BETWEEN 0 AND 130", name="ck_match_events_event_minute_range"
        ),
        sa.CheckConstraint(
            "added_time_minute IS NULL OR added_time_minute BETWEEN 0 AND 30",
            name="ck_match_events_added_time_range",
        ),
        sa.CheckConstraint(
            "event_type NOT IN ('YELLOW_CARD', 'RED_CARD', 'SECOND_YELLOW') "
            "OR player_id IS NOT NULL",
            name="ck_match_events_card_player_required",
        ),
        sa.CheckConstraint(
            "event_type NOT IN ('GOAL', 'OWN_GOAL', 'YELLOW_CARD', 'RED_CARD', "
            "'SECOND_YELLOW', 'SUBSTITUTION', 'PENALTY_WON', 'PENALTY_MISSED') "
            "OR side != 'NEUTRAL'",
            name="ck_match_events_event_side_required",
        ),
        sa.CheckConstraint(
            "is_penalty IS FALSE OR event_type IN "
            "('GOAL', 'OWN_GOAL', 'PENALTY_MISSED')",
            name="ck_match_events_penalty_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name="fk_match_events_match_id_matches",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_match_events_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assist_player_id"],
            ["players.id"],
            name="fk_match_events_assist_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["related_player_id"],
            ["players.id"],
            name="fk_match_events_related_player_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_match_events_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_match_events"),
    )
    op.create_index(
        "ix_match_events_match_id", "match_events", ["match_id"], unique=False
    )
    op.create_index(
        "ix_match_events_match_minute",
        "match_events",
        ["match_id", "minute", "added_time_minute"],
        unique=False,
    )

    op.create_table(
        "substitutions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("player_out_id", sa.Uuid(), nullable=False),
        sa.Column("player_in_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("side", sa.String(length=40), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("added_time_minute", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "player_out_id != player_in_id", name="ck_substitutions_different_players"
        ),
        sa.CheckConstraint(
            f"side IN ({_values(MATCH_SIDES)})",
            name="ck_substitutions_substitution_side_values",
        ),
        sa.CheckConstraint(
            "minute BETWEEN 0 AND 130",
            name="ck_substitutions_substitution_minute_range",
        ),
        sa.CheckConstraint(
            "added_time_minute IS NULL OR added_time_minute BETWEEN 0 AND 30",
            name="ck_substitutions_substitution_added_time_range",
        ),
        sa.CheckConstraint(
            f"reason IN ({_values(SUBSTITUTION_REASONS)})",
            name="ck_substitutions_reason_values",
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matches.id"],
            name="fk_substitutions_match_id_matches",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_out_id"],
            ["players.id"],
            name="fk_substitutions_player_out_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_in_id"],
            ["players.id"],
            name="fk_substitutions_player_in_id_players",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["match_events.id"],
            name="fk_substitutions_event_id_match_events",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_substitutions_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_substitutions"),
        sa.UniqueConstraint("event_id", name="uq_substitution_event"),
    )
    op.create_index(
        "ix_substitutions_match_id", "substitutions", ["match_id"], unique=False
    )
    op.create_index(
        "ix_substitutions_match_minute",
        "substitutions",
        ["match_id", "minute"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_substitutions_match_minute", table_name="substitutions")
    op.drop_index("ix_substitutions_match_id", table_name="substitutions")
    op.drop_table("substitutions")
    op.drop_index("ix_match_events_match_minute", table_name="match_events")
    op.drop_index("ix_match_events_match_id", table_name="match_events")
    op.drop_table("match_events")
    op.drop_index(
        "ix_match_participations_match_squad_id", table_name="match_participations"
    )
    op.drop_table("match_participations")
    op.drop_index("uq_match_squad_captain", table_name="match_squads")
    op.drop_index("ix_match_squads_player_id", table_name="match_squads")
    op.drop_index("ix_match_squads_match_id", table_name="match_squads")
    op.drop_table("match_squads")
    op.drop_index("ix_matches_competition", table_name="matches")
    op.drop_index("ix_matches_opponent_scheduled", table_name="matches")
    op.drop_index("ix_matches_team_scheduled", table_name="matches")
    op.drop_index("ix_matches_opponent_id", table_name="matches")
    op.drop_index("ix_matches_team_id", table_name="matches")
    op.drop_table("matches")
    op.drop_index("ix_competitions_name_season", table_name="competitions")
    op.drop_table("competitions")
    op.drop_index("ix_venues_name", table_name="venues")
    op.drop_table("venues")
    op.drop_index("ix_opponents_name", table_name="opponents")
    op.drop_table("opponents")
