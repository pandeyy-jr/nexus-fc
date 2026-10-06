from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class StringEnumType[T: StrEnum](TypeDecorator[T]):
    impl = String
    cache_ok = True

    def __init__(self, enum_type: type[T], length: int = 40) -> None:
        self.enum_type = enum_type
        super().__init__(length)

    def process_bind_param(self, value: T | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return self.enum_type(value).value

    def process_result_value(self, value: str | None, dialect: Dialect) -> T | None:
        if value is None:
            return None
        return self.enum_type(value)
