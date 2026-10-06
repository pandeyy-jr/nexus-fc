from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.football import SquadStatus
from app.db.base import Base
from app.db.types import StringEnumType, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.player import Player
    from app.db.models.team import Team

_SQUAD_STATUSES = ", ".join(f"'{status.value}'" for status in SquadStatus)


class PlayerTeamMembership(Base):
    __tablename__ = "player_team_memberships"
    __table_args__ = (
        CheckConstraint(
            f"squad_status IN ({_SQUAD_STATUSES})", name="squad_status_values"
        ),
        CheckConstraint(
            "left_at IS NULL OR left_at >= joined_at", name="membership_dates"
        ),
        Index(
            "uq_current_player_team_membership",
            "player_id",
            "team_id",
            unique=True,
            sqlite_where=text("left_at IS NULL"),
            postgresql_where=text("left_at IS NULL"),
        ),
        Index("ix_memberships_team_joined", "team_id", "joined_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    player_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), index=True
    )
    team_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="RESTRICT"), index=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, server_default=func.now(), nullable=False
    )
    left_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    squad_status: Mapped[SquadStatus] = mapped_column(
        StringEnumType(SquadStatus), default=SquadStatus.ACTIVE
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
    player: Mapped["Player"] = relationship(back_populates="memberships", lazy="joined")
    team: Mapped["Team"] = relationship(back_populates="memberships", lazy="joined")
