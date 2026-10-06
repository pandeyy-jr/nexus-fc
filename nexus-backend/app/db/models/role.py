from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.roles import RoleName
from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.user import User


class RoleNameType(TypeDecorator[RoleName]):
    impl = String(50)
    cache_ok = True

    def process_bind_param(self, value: RoleName | str | None, dialect) -> str | None:
        if value is None:
            return None
        return RoleName(value).value

    def process_result_value(self, value: str | None, dialect) -> RoleName | None:
        if value is None:
            return None
        return RoleName(value)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint(
            "name IN ("
            "'HEAD_COACH', 'ASSISTANT_COACH', 'ANALYST', 'SPORTS_SCIENTIST', "
            "'MEDICAL_STAFF', 'SCOUT', 'PLAYER', 'DIRECTOR', 'ADMIN'"
            ")",
            name="role_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[RoleName] = mapped_column(RoleNameType(), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    users: Mapped[list["User"]] = relationship(back_populates="role")
