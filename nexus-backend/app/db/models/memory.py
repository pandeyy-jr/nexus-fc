from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.memory import (
    DecisionStatus,
    DecisionType,
    MemoryEvidenceType,
    MemorySensitivity,
    MemorySourceType,
    MemoryType,
    RedactionStatus,
)
from app.db.base import Base
from app.db.types import StringEnumType, UTCDateTime

_MEMORY_TYPES = ", ".join(f"'{item.value}'" for item in MemoryType)
_SOURCE_TYPES = ", ".join(f"'{item.value}'" for item in MemorySourceType)
_EVIDENCE_TYPES = ", ".join(f"'{item.value}'" for item in MemoryEvidenceType)
_DECISION_TYPES = ", ".join(f"'{item.value}'" for item in DecisionType)
_DECISION_STATUSES = ", ".join(f"'{item.value}'" for item in DecisionStatus)
_SENSITIVITIES = ", ".join(f"'{item.value}'" for item in MemorySensitivity)
_REDACTION_STATUSES = ", ".join(f"'{item.value}'" for item in RedactionStatus)
_HUMAN_DECISIONS = ", ".join(
    f"'{item}'"
    for item in ("ACCEPTED", "REJECTED", "MODIFIED", "DEFERRED", "NO_ACTION")
)


class MemoryRecord(Base):
    """Persistent evidence-first club memory.

    ``source_type``/``source_id`` are never rewritten: an AI-generated
    memory keeps its machine origin forever. ``confidence`` is nullable —
    unknown confidence is stored as NULL, never invented. ``extra_data``
    holds a small JSON-encoded object (bounded strings only: no raw
    video, embeddings, tensors, diagnoses, or secrets).
    """

    __tablename__ = "memory_records"
    __table_args__ = (
        CheckConstraint(f"memory_type IN ({_MEMORY_TYPES})", name="memory_type_values"),
        CheckConstraint(
            f"source_type IN ({_SOURCE_TYPES})", name="memory_source_values"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="memory_confidence_range",
        ),
        CheckConstraint(
            f"sensitivity IN ({_SENSITIVITIES})", name="memory_sensitivity_values"
        ),
        CheckConstraint(
            f"redaction_status IN ({_REDACTION_STATUSES})",
            name="memory_redaction_values",
        ),
        Index("ix_memory_records_type_occurred", "memory_type", "occurred_at"),
        Index("ix_memory_records_source", "source_type", "source_id"),
        Index("ix_memory_records_sensitivity", "sensitivity"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    memory_type: Mapped[MemoryType] = mapped_column(StringEnumType(MemoryType))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(2000))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    source_type: Mapped[MemorySourceType] = mapped_column(
        StringEnumType(MemorySourceType)
    )
    source_id: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    extra_data: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    sensitivity: Mapped[MemorySensitivity] = mapped_column(
        StringEnumType(MemorySensitivity),
        default=MemorySensitivity.CLUB_GENERAL,
        server_default="CLUB_GENERAL",
        nullable=False,
    )
    retention_until: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    redaction_status: Mapped[RedactionStatus] = mapped_column(
        StringEnumType(RedactionStatus),
        default=RedactionStatus.ACTIVE,
        server_default="ACTIVE",
        nullable=False,
    )
    redacted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    redacted_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )

    evidence: Mapped[list["EvidenceReference"]] = relationship(
        back_populates="memory_record",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class EvidenceReference(Base):
    """Traceable backing for a memory: match/video/frame links plus origin.

    Deleted automatically with its parent memory (delete-orphan cascade);
    references to matches and videos are RESTRICT so evidence cannot be
    orphaned silently by upstream deletes.
    """

    __tablename__ = "evidence_references"
    __table_args__ = (
        CheckConstraint(
            f"source_type IN ({_SOURCE_TYPES})", name="evidence_source_values"
        ),
        CheckConstraint(
            f"evidence_type IN ({_EVIDENCE_TYPES})", name="evidence_type_values"
        ),
        CheckConstraint(
            "frame_number IS NULL OR frame_number >= 0",
            name="evidence_frame_nonnegative",
        ),
        CheckConstraint(
            "timestamp_seconds IS NULL OR timestamp_seconds >= 0",
            name="evidence_timestamp_nonnegative",
        ),
        Index("ix_evidence_references_memory", "memory_record_id"),
        Index("ix_evidence_references_match", "match_id"),
        Index("ix_evidence_references_source", "source_type", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    memory_record_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memory_records.id", ondelete="CASCADE"),
        index=True,
    )
    source_type: Mapped[MemorySourceType] = mapped_column(
        StringEnumType(MemorySourceType)
    )
    source_id: Mapped[str] = mapped_column(String(100))
    match_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("matches.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    video_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("video_sources.id", ondelete="RESTRICT"),
        nullable=True,
    )
    frame_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timestamp_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_type: Mapped[MemoryEvidenceType] = mapped_column(
        StringEnumType(MemoryEvidenceType)
    )
    excerpt: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    provenance: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    memory_record: Mapped["MemoryRecord"] = relationship(
        back_populates="evidence", lazy="selectin"
    )


class DecisionRecord(Base):
    """A human decision with rationale. AI recommendations are never
    DecisionRecords; the human ``decision_maker`` (when known) is stored
    separately from ``created_by`` (who recorded it). No automatic
    judgment about correctness is stored."""

    __tablename__ = "decision_records"
    __table_args__ = (
        CheckConstraint(
            f"decision_type IN ({_DECISION_TYPES})", name="decision_type_values"
        ),
        CheckConstraint(
            f"status IN ({_DECISION_STATUSES})", name="decision_status_values"
        ),
        Index("ix_decision_records_type_at", "decision_type", "decision_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    decision_type: Mapped[DecisionType] = mapped_column(StringEnumType(DecisionType))
    summary: Mapped[str] = mapped_column(String(2000))
    context: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rationale: Mapped[str] = mapped_column(String(2000))
    decision_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    decision_maker: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[DecisionStatus] = mapped_column(StringEnumType(DecisionStatus))
    related_memory_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memory_records.id", ondelete="RESTRICT"),
        nullable=True,
    )
    related_evidence_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evidence_references.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )


class DecisionReplay(Base):
    """Immutable decision replay record preserving the full decision timeline.

    Captures what was known at decision time, AI recommendation (if any),
    human decision, and later outcomes. Never modified after creation.
    """

    __tablename__ = "decision_replays"
    __table_args__ = (
        CheckConstraint(
            f"decision_type IN ({_DECISION_TYPES})", name="replay_decision_type_values"
        ),
        CheckConstraint(
            f"human_decision IN ({_HUMAN_DECISIONS})",
            name="replay_human_decision_values",
        ),
        Index("ix_decision_replays_type_at", "decision_type", "decision_at"),
        Index("ix_decision_replays_match", "match_id"),
        Index("ix_decision_replays_player", "player_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    decision_type: Mapped[DecisionType] = mapped_column(StringEnumType(DecisionType))
    match_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("matches.id", ondelete="RESTRICT"), nullable=True
    )
    player_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("players.id", ondelete="RESTRICT"), nullable=True
    )
    decision_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    decision_maker: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    ai_recommendation_text: Mapped[str | None] = mapped_column(
        String(4000), nullable=True
    )
    ai_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ai_model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_recommendation_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    ai_request_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    ai_grounded: Mapped[bool | None] = mapped_column(nullable=True)
    ai_cited_evidence_ids: Mapped[str | None] = mapped_column(
        String(4000), nullable=True
    )
    human_decision: Mapped[str | None] = mapped_column(String(50), nullable=True)
    human_decision_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    rationale: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    evidence_ids: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    outcome_evidence_ids: Mapped[str | None] = mapped_column(
        String(4000), nullable=True
    )
    outcome_refs: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
