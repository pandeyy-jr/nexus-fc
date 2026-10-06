from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VideoSourceRecord(Base):
    __tablename__ = "video_sources"
    __table_args__ = (
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds > 0",
            name="duration_positive",
        ),
        CheckConstraint(
            "frame_rate IS NULL OR frame_rate > 0", name="frame_rate_positive"
        ),
        CheckConstraint("width IS NULL OR width > 0", name="width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="height_positive"),
        CheckConstraint(
            "processing_status IN ('RECEIVED', 'READY', 'FAILED')",
            name="processing_status_values",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    match_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("matches.id", ondelete="RESTRICT"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(180))
    media_type: Mapped[str] = mapped_column(String(100))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    frame_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processing_status: Mapped[str] = mapped_column(
        String(20), default="READY", server_default="READY", nullable=False
    )
    storage_reference: Mapped[str] = mapped_column(String(255), unique=True)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
