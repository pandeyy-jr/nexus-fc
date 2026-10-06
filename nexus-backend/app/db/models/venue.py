from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.match import Match


class Venue(Base):
    __tablename__ = "venues"
    __table_args__ = (
        CheckConstraint(
            "capacity IS NULL OR capacity BETWEEN 1 AND 200000",
            name="capacity_range",
        ),
        Index("ix_venues_name", "name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160))
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    matches: Mapped[list["Match"]] = relationship(back_populates="venue")