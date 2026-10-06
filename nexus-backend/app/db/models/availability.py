from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.training import AvailabilityReasonCategory, AvailabilityStatus
from app.db.base import Base
from app.db.types import StringEnumType, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.player import Player
    from app.db.models.user import User

_AVAILABILITY_STATUSES = ", ".join(f"'{value.value}'" for value in AvailabilityStatus)
_AVAILABILITY_REASONS = ", ".join(
    f"'{value.value}'" for value in AvailabilityReasonCategory
)


class PlayerAvailability(Base):
    __tablename__ = "player_availability"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_AVAILABILITY_STATUSES})", name="availability_status_values"
        ),
        CheckConstraint(
            f"reason_category IN ({_AVAILABILITY_REASONS})",
            name="availability_reason_values",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="availability_dates",
        ),
        Index(
            "uq_player_availability_open",
            "player_id",
            unique=True,
            sqlite_where=text("effective_until IS NULL"),
            postgresql_where=text("effective_until IS NULL"),
        ),
        Index("ix_player_availability_history", "player_id", "effective_from"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    player_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[AvailabilityStatus] = mapped_column(
        StringEnumType(AvailabilityStatus)
    )
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime())
    effective_until: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    reason_category: Mapped[AvailabilityReasonCategory] = mapped_column(
        StringEnumType(AvailabilityReasonCategory)
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recorded_by: Mapped[UUID] = mapped_column(
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
    recorder: Mapped["User"] = relationship(lazy="joined")
