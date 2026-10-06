from datetime import date, datetime
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
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.football import DominantFoot, PlayerPosition, PlayerStatus
from app.db.base import Base
from app.db.types import StringEnumType, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.membership import PlayerTeamMembership
    from app.db.models.user import User

_POSITIONS = ", ".join(f"'{position.value}'" for position in PlayerPosition)
_FEET = ", ".join(f"'{foot.value}'" for foot in DominantFoot)
_PLAYER_STATUSES = ", ".join(f"'{status.value}'" for status in PlayerStatus)


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (
        CheckConstraint(
            f"preferred_position IN ({_POSITIONS})", name="preferred_position_values"
        ),
        CheckConstraint(
            f"secondary_position IS NULL OR secondary_position IN ({_POSITIONS})",
            name="secondary_position_values",
        ),
        CheckConstraint(
            "secondary_position IS NULL OR secondary_position != preferred_position",
            name="distinct_positions",
        ),
        CheckConstraint(
            f"dominant_foot IS NULL OR dominant_foot IN ({_FEET})",
            name="dominant_foot_values",
        ),
        CheckConstraint(f"status IN ({_PLAYER_STATUSES})", name="player_status_values"),
        CheckConstraint(
            "squad_number IS NULL OR squad_number BETWEEN 0 AND 99",
            name="squad_number_range",
        ),
        CheckConstraint(
            "height_cm IS NULL OR height_cm BETWEEN 100 AND 250",
            name="height_cm_range",
        ),
        CheckConstraint(
            "weight_kg IS NULL OR weight_kg BETWEEN 30 AND 200",
            name="weight_kg_range",
        ),
        Index("ix_players_last_first_name", "last_name", "first_name"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    date_of_birth: Mapped[date] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(80))
    preferred_position: Mapped[PlayerPosition] = mapped_column(
        StringEnumType(PlayerPosition)
    )
    secondary_position: Mapped[PlayerPosition | None] = mapped_column(
        StringEnumType(PlayerPosition), nullable=True
    )
    squad_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dominant_foot: Mapped[DominantFoot | None] = mapped_column(
        StringEnumType(DominantFoot), nullable=True
    )
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    profile_photo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[PlayerStatus] = mapped_column(
        StringEnumType(PlayerStatus), default=PlayerStatus.ACTIVE
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
    user: Mapped["User | None"] = relationship(lazy="joined")
    memberships: Mapped[list["PlayerTeamMembership"]] = relationship(
        back_populates="player"
    )
