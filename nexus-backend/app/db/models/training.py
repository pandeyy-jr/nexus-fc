from datetime import date, datetime, time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.training import AttendanceStatus, TrainingSessionType
from app.db.base import Base
from app.db.types import StringEnumType, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.player import Player
    from app.db.models.team import Team
    from app.db.models.user import User

_SESSION_TYPES = ", ".join(f"'{value.value}'" for value in TrainingSessionType)
_ATTENDANCE_STATUSES = ", ".join(f"'{value.value}'" for value in AttendanceStatus)


class TrainingSession(Base):
    __tablename__ = "training_sessions"
    __table_args__ = (
        CheckConstraint(
            f"session_type IN ({_SESSION_TYPES})", name="session_type_values"
        ),
        CheckConstraint("end_time > start_time", name="session_time_order"),
        CheckConstraint(
            "planned_intensity IS NULL OR planned_intensity BETWEEN 1 AND 10",
            name="planned_intensity_range",
        ),
        CheckConstraint(
            "planned_duration_minutes IS NULL OR "
            "planned_duration_minutes BETWEEN 1 AND 600",
            name="planned_duration_range",
        ),
        Index("ix_training_sessions_team_date", "team_id", "session_date"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), index=True
    )
    session_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time())
    end_time: Mapped[time] = mapped_column(Time())
    session_type: Mapped[TrainingSessionType] = mapped_column(
        StringEnumType(TrainingSessionType)
    )
    objective: Mapped[str | None] = mapped_column(String(500), nullable=True)
    planned_intensity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
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
    team: Mapped["Team"] = relationship(lazy="joined")
    creator: Mapped["User"] = relationship(lazy="joined")
    participations: Mapped[list["TrainingParticipation"]] = relationship(
        back_populates="session"
    )


class TrainingParticipation(Base):
    __tablename__ = "training_participations"
    __table_args__ = (
        CheckConstraint(
            f"attendance_status IN ({_ATTENDANCE_STATUSES})",
            name="attendance_status_values",
        ),
        CheckConstraint(
            "planned_load IS NULL OR planned_load BETWEEN 0 AND 1000",
            name="planned_load_range",
        ),
        CheckConstraint(
            "actual_load IS NULL OR actual_load BETWEEN 0 AND 1000",
            name="actual_load_range",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes BETWEEN 0 AND 600",
            name="duration_minutes_range",
        ),
        UniqueConstraint(
            "training_session_id",
            "player_id",
            name="uq_training_participation_session_player",
        ),
        Index("ix_training_participations_player", "player_id", "recorded_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    training_session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_sessions.id", ondelete="RESTRICT"),
        index=True,
    )
    player_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), index=True
    )
    attendance_status: Mapped[AttendanceStatus] = mapped_column(
        StringEnumType(AttendanceStatus), default=AttendanceStatus.PLANNED
    )
    planned_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_response: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    coach_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), nullable=False
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
    session: Mapped["TrainingSession"] = relationship(back_populates="participations")
    player: Mapped["Player"] = relationship(lazy="joined")
