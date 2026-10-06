from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.matches import (
    MatchEventSource,
    MatchEventType,
    MatchSide,
    MatchSquadStatus,
    MatchStatus,
    SubstitutionReason,
)
from app.db.base import Base
from app.db.types import StringEnumType, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.competition import Competition
    from app.db.models.opponent import Opponent
    from app.db.models.player import Player
    from app.db.models.team import Team
    from app.db.models.user import User
    from app.db.models.venue import Venue

_SIDES = ", ".join(f"'{item.value}'" for item in MatchSide)
_MATCH_STATUSES = ", ".join(f"'{item.value}'" for item in MatchStatus)
_SQUAD_STATUSES = ", ".join(f"'{item.value}'" for item in MatchSquadStatus)
_EVENT_TYPES = ", ".join(f"'{item.value}'" for item in MatchEventType)
_EVENT_SOURCES = ", ".join(f"'{item.value}'" for item in MatchEventSource)
_SUBSTITUTION_REASONS = ", ".join(f"'{item.value}'" for item in SubstitutionReason)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint(f"home_away IN ({_SIDES})", name="home_away_values"),
        CheckConstraint(f"status IN ({_MATCH_STATUSES})", name="match_status_values"),
        CheckConstraint("matchday IS NULL OR matchday > 0", name="matchday_positive"),
        CheckConstraint(
            "(home_score IS NULL AND away_score IS NULL) OR "
            "(home_score IS NOT NULL AND away_score IS NOT NULL)",
            name="score_pair",
        ),
        CheckConstraint(
            "home_score IS NULL OR (home_score >= 0 AND away_score >= 0)",
            name="score_nonnegative",
        ),
        CheckConstraint(
            "actual_start_at IS NULL OR actual_end_at IS NULL OR "
            "actual_end_at >= actual_start_at",
            name="actual_time_order",
        ),
        Index("ix_matches_team_scheduled", "team_id", "scheduled_at"),
        Index("ix_matches_opponent_scheduled", "opponent_id", "scheduled_at"),
        Index("ix_matches_competition", "competition_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), index=True
    )
    opponent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("opponents.id", ondelete="RESTRICT"), index=True
    )
    competition_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("competitions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    venue_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("venues.id", ondelete="RESTRICT"), nullable=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime())
    actual_start_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    actual_end_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    home_away: Mapped[MatchSide] = mapped_column(StringEnumType(MatchSide))
    status: Mapped[MatchStatus] = mapped_column(
        StringEnumType(MatchStatus), default=MatchStatus.SCHEDULED
    )
    matchday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season: Mapped[str | None] = mapped_column(String(20), nullable=True)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    team: Mapped["Team"] = relationship(lazy="joined")
    opponent: Mapped["Opponent"] = relationship(back_populates="matches", lazy="joined")
    competition: Mapped["Competition | None"] = relationship(
        back_populates="matches", lazy="joined"
    )
    venue: Mapped["Venue | None"] = relationship(back_populates="matches", lazy="joined")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by], lazy="joined")
    updater: Mapped["User | None"] = relationship(
        foreign_keys=[updated_by], lazy="joined"
    )
    squad: Mapped[list["MatchSquad"]] = relationship(back_populates="match")
    events: Mapped[list["MatchEvent"]] = relationship(back_populates="match")
    substitutions: Mapped[list["Substitution"]] = relationship(back_populates="match")


class MatchSquad(Base):
    __tablename__ = "match_squads"
    __table_args__ = (
        CheckConstraint(
            f"squad_status IN ({_SQUAD_STATUSES})", name="squad_status_values"
        ),
        CheckConstraint(
            "shirt_number IS NULL OR shirt_number BETWEEN 0 AND 99",
            name="shirt_number_range",
        ),
        CheckConstraint(
            "(squad_status = 'STARTER' AND starting IS TRUE) OR "
            "squad_status = 'WITHDRAWN' OR "
            "(squad_status != 'STARTER' AND starting IS FALSE)",
            name="starting_status_consistency",
        ),
        UniqueConstraint("match_id", "player_id", name="uq_match_squad_player"),
        Index(
            "uq_match_squad_captain",
            "match_id",
            unique=True,
            sqlite_where=text("captain IS TRUE"),
            postgresql_where=text("captain IS TRUE"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    match_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("matches.id", ondelete="RESTRICT"), index=True
    )
    player_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), index=True
    )
    squad_status: Mapped[MatchSquadStatus] = mapped_column(
        StringEnumType(MatchSquadStatus), default=MatchSquadStatus.SELECTED
    )
    shirt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    starting: Mapped[bool] = mapped_column(default=False, nullable=False)
    captain: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    match: Mapped["Match"] = relationship(back_populates="squad")
    player: Mapped["Player"] = relationship(lazy="joined")
    participation: Mapped["MatchParticipation | None"] = relationship(
        back_populates="match_squad", uselist=False
    )


class MatchParticipation(Base):
    __tablename__ = "match_participations"
    __table_args__ = (
        CheckConstraint(
            "started_at_minute IS NULL OR started_at_minute BETWEEN 0 AND 130",
            name="started_minute_range",
        ),
        CheckConstraint(
            "ended_at_minute IS NULL OR ended_at_minute BETWEEN 0 AND 130",
            name="ended_minute_range",
        ),
        CheckConstraint(
            "minutes_played IS NULL OR minutes_played BETWEEN 0 AND 130",
            name="minutes_played_range",
        ),
        CheckConstraint(
            "started_at_minute IS NULL OR ended_at_minute IS NULL OR "
            "ended_at_minute >= started_at_minute",
            name="participation_minute_order",
        ),
        UniqueConstraint("match_squad_id", name="uq_match_participation_squad"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    match_squad_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("match_squads.id", ondelete="RESTRICT"),
        index=True,
    )
    started_at_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ended_at_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minutes_played: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    match_squad: Mapped["MatchSquad"] = relationship(
        back_populates="participation", lazy="joined"
    )


class MatchEvent(Base):
    __tablename__ = "match_events"
    __table_args__ = (
        CheckConstraint(f"event_type IN ({_EVENT_TYPES})", name="event_type_values"),
        CheckConstraint(f"side IN ({_SIDES})", name="event_side_values"),
        CheckConstraint(f"source IN ({_EVENT_SOURCES})", name="event_source_values"),
        CheckConstraint("minute BETWEEN 0 AND 130", name="event_minute_range"),
        CheckConstraint(
            "added_time_minute IS NULL OR added_time_minute BETWEEN 0 AND 30",
            name="added_time_range",
        ),
        CheckConstraint(
            "event_type NOT IN ('YELLOW_CARD', 'RED_CARD', 'SECOND_YELLOW') "
            "OR player_id IS NOT NULL",
            name="card_player_required",
        ),
        CheckConstraint(
            "event_type NOT IN ('GOAL', 'OWN_GOAL', 'YELLOW_CARD', 'RED_CARD', "
            "'SECOND_YELLOW', 'SUBSTITUTION', 'PENALTY_WON', 'PENALTY_MISSED') "
            "OR side != 'NEUTRAL'",
            name="event_side_required",
        ),
        CheckConstraint(
            "is_penalty IS FALSE OR event_type IN ('GOAL', 'OWN_GOAL', 'PENALTY_MISSED')",
            name="penalty_event_type",
        ),
        Index("ix_match_events_match_minute", "match_id", "minute", "added_time_minute"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    match_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("matches.id", ondelete="RESTRICT"), index=True
    )
    side: Mapped[MatchSide] = mapped_column(StringEnumType(MatchSide))
    player_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), nullable=True
    )
    assist_player_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), nullable=True
    )
    related_player_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), nullable=True
    )
    event_type: Mapped[MatchEventType] = mapped_column(StringEnumType(MatchEventType))
    minute: Mapped[int] = mapped_column(Integer)
    added_time_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source: Mapped[MatchEventSource] = mapped_column(
        StringEnumType(MatchEventSource), default=MatchEventSource.MANUAL
    )
    is_penalty: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    match: Mapped["Match"] = relationship(back_populates="events")
    player: Mapped["Player | None"] = relationship(
        foreign_keys=[player_id], lazy="joined"
    )
    assist_player: Mapped["Player | None"] = relationship(
        foreign_keys=[assist_player_id], lazy="joined"
    )
    related_player: Mapped["Player | None"] = relationship(
        foreign_keys=[related_player_id], lazy="joined"
    )
    creator: Mapped["User"] = relationship(lazy="joined")

    @property
    def own_goal(self) -> bool:
        return self.event_type == MatchEventType.OWN_GOAL


class Substitution(Base):
    __tablename__ = "substitutions"
    __table_args__ = (
        CheckConstraint("player_out_id != player_in_id", name="different_players"),
        CheckConstraint(f"side IN ({_SIDES})", name="substitution_side_values"),
        CheckConstraint("minute BETWEEN 0 AND 130", name="substitution_minute_range"),
        CheckConstraint(
            "added_time_minute IS NULL OR added_time_minute BETWEEN 0 AND 30",
            name="substitution_added_time_range",
        ),
        CheckConstraint(f"reason IN ({_SUBSTITUTION_REASONS})", name="reason_values"),
        UniqueConstraint("event_id", name="uq_substitution_event"),
        Index("ix_substitutions_match_minute", "match_id", "minute"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    match_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("matches.id", ondelete="RESTRICT"), index=True
    )
    player_out_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT")
    )
    player_in_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT")
    )
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("match_events.id", ondelete="RESTRICT")
    )
    side: Mapped[MatchSide] = mapped_column(StringEnumType(MatchSide))
    minute: Mapped[int] = mapped_column(Integer)
    added_time_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[SubstitutionReason] = mapped_column(StringEnumType(SubstitutionReason))
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    match: Mapped["Match"] = relationship(back_populates="substitutions")
    player_out: Mapped["Player"] = relationship(
        foreign_keys=[player_out_id], lazy="joined"
    )
    player_in: Mapped["Player"] = relationship(
        foreign_keys=[player_in_id], lazy="joined"
    )
    event: Mapped["MatchEvent"] = relationship(lazy="joined")
    creator: Mapped["User"] = relationship(lazy="joined")