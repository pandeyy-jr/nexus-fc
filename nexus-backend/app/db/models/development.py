from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.training import (
    DevelopmentCategory,
    DevelopmentPriority,
    DevelopmentStatus,
)
from app.db.base import Base
from app.db.types import StringEnumType, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.player import Player
    from app.db.models.team import Team
    from app.db.models.user import User

_DEVELOPMENT_CATEGORIES = ", ".join(f"'{value.value}'" for value in DevelopmentCategory)
_DEVELOPMENT_STATUSES = ", ".join(f"'{value.value}'" for value in DevelopmentStatus)
_DEVELOPMENT_PRIORITIES = ", ".join(f"'{value.value}'" for value in DevelopmentPriority)


class PlayerDevelopmentGoal(Base):
    __tablename__ = "player_development_goals"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({_DEVELOPMENT_CATEGORIES})",
            name="development_category_values",
        ),
        CheckConstraint(
            f"status IN ({_DEVELOPMENT_STATUSES})", name="development_status_values"
        ),
        CheckConstraint(
            f"priority IN ({_DEVELOPMENT_PRIORITIES})",
            name="development_priority_values",
        ),
        Index("ix_development_goals_player_status", "player_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    player_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), index=True
    )
    team_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    category: Mapped[DevelopmentCategory] = mapped_column(
        StringEnumType(DevelopmentCategory)
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[DevelopmentStatus] = mapped_column(
        StringEnumType(DevelopmentStatus), default=DevelopmentStatus.NOT_STARTED
    )
    priority: Mapped[DevelopmentPriority] = mapped_column(
        StringEnumType(DevelopmentPriority), default=DevelopmentPriority.MEDIUM
    )
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
    player: Mapped["Player"] = relationship(lazy="joined")
    team: Mapped["Team | None"] = relationship(lazy="joined")
    creator: Mapped["User"] = relationship(lazy="joined")
    assessments: Mapped[list["PlayerDevelopmentAssessment"]] = relationship(
        back_populates="goal"
    )


class PlayerDevelopmentAssessment(Base):
    __tablename__ = "player_development_assessments"
    __table_args__ = (
        CheckConstraint(
            f"progress_status IN ({_DEVELOPMENT_STATUSES})",
            name="assessment_progress_status_values",
        ),
        Index("ix_development_assessments_player_date", "player_id", "assessment_date"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    player_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), index=True
    )
    goal_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("player_development_goals.id", ondelete="RESTRICT"),
        nullable=True,
    )
    assessment_date: Mapped[date] = mapped_column(Date)
    assessor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    progress_status: Mapped[DevelopmentStatus] = mapped_column(
        StringEnumType(DevelopmentStatus)
    )
    assessment_note: Mapped[str] = mapped_column(String(2000))
    next_action: Mapped[str | None] = mapped_column(String(1000), nullable=True)
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
    player: Mapped["Player"] = relationship(foreign_keys=[player_id], lazy="joined")
    goal: Mapped["PlayerDevelopmentGoal | None"] = relationship(
        back_populates="assessments"
    )
    assessor: Mapped["User"] = relationship(foreign_keys=[assessor_id], lazy="joined")
