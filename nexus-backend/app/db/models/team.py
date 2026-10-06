from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, utc_now

if TYPE_CHECKING:
    from app.db.models.membership import PlayerTeamMembership


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (Index("ix_teams_is_active_name", "is_active", "name"),)

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    short_name: Mapped[str] = mapped_column(String(30))
    age_group: Mapped[str] = mapped_column(String(40))
    gender_category: Mapped[str] = mapped_column(String(40))
    season: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    memberships: Mapped[list["PlayerTeamMembership"]] = relationship(
        back_populates="team"
    )
