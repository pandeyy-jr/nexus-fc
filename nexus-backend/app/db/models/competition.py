from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.matches import CompetitionType
from app.db.base import Base
from app.db.types import StringEnumType, UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.match import Match

_COMPETITION_TYPES = ", ".join(f"'{item.value}'" for item in CompetitionType)


class Competition(Base):
    __tablename__ = "competitions"
    __table_args__ = (
        CheckConstraint(
            f"competition_type IN ({_COMPETITION_TYPES})",
            name="competition_type_values",
        ),
        Index("ix_competitions_name_season", "name", "season"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160))
    short_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    competition_type: Mapped[CompetitionType] = mapped_column(
        StringEnumType(CompetitionType)
    )
    season: Mapped[str] = mapped_column(String(20))
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
    matches: Mapped[list["Match"]] = relationship(back_populates="competition")