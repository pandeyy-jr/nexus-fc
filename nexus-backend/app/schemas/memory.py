import json
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.memory import (
    DecisionStatus,
    DecisionType,
    HumanDecision,
    MemoryEvidenceType,
    MemorySensitivity,
    MemorySourceType,
    MemoryType,
    RedactionStatus,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    occurred_at: datetime
    source_type: MemorySourceType
    source_id: str = Field(min_length=1, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    extra_data: str | None = Field(default=None, max_length=4000)
    sensitivity: MemorySensitivity = MemorySensitivity.CLUB_GENERAL
    retention_until: datetime | None = None

    @field_validator("occurred_at")
    @classmethod
    def occurred_is_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("retention_until")
    @classmethod
    def retention_is_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        moment = _utc(value)
        if moment <= datetime.now(UTC):
            raise ValueError("retention_until must be in the future")
        return moment

    @field_validator("title", "summary", "source_id")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("Text must not be blank")
        return cleaned

    @field_validator("extra_data")
    @classmethod
    def extra_data_is_json_object(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("extra_data must be a JSON object string") from exc
        if not isinstance(parsed, dict):
            raise ValueError("extra_data must be a JSON object string")
        return value


class EvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: MemorySourceType
    source_id: str = Field(min_length=1, max_length=100)
    match_id: UUID | None = None
    video_id: UUID | None = None
    frame_number: int | None = Field(default=None, ge=0)
    timestamp_seconds: float | None = Field(default=None, ge=0)
    evidence_type: MemoryEvidenceType
    excerpt: str | None = Field(default=None, max_length=2000)
    provenance: str | None = Field(default=None, max_length=1000)

    @field_validator("source_id", "excerpt", "provenance")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean_text(value)
        return cleaned or None


class DecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_type: DecisionType
    summary: str = Field(min_length=1, max_length=2000)
    context: str | None = Field(default=None, max_length=500)
    rationale: str = Field(min_length=1, max_length=2000)
    decision_at: datetime
    decision_maker: UUID | None = None
    status: DecisionStatus = DecisionStatus.PENDING
    related_memory_id: UUID | None = None
    related_evidence_id: UUID | None = None

    @field_validator("decision_at")
    @classmethod
    def decision_is_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("summary", "rationale")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("Text must not be blank")
        return cleaned


class MemoryCreateRequest(BaseModel):
    """Creation envelope: memory plus bounded initial evidence."""

    model_config = ConfigDict(extra="forbid")

    memory: MemoryCreate
    evidence: list[EvidenceCreate] = Field(default_factory=list, max_length=50)


class EvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    memory_record_id: UUID
    source_type: MemorySourceType
    source_id: str
    match_id: UUID | None
    video_id: UUID | None
    frame_number: int | None
    timestamp_seconds: float | None
    evidence_type: MemoryEvidenceType
    excerpt: str | None
    provenance: str | None
    created_at: datetime


class MemoryView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    memory_type: MemoryType
    title: str
    summary: str
    occurred_at: datetime
    created_by: UUID
    source_type: MemorySourceType
    source_id: str
    confidence: float | None
    created_at: datetime
    extra_data: str | None
    sensitivity: MemorySensitivity
    retention_until: datetime | None
    redaction_status: RedactionStatus
    redacted_at: datetime | None
    redacted_by: UUID | None
    evidence: list[EvidenceView] = Field(default_factory=list)


class DecisionView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    decision_type: DecisionType
    summary: str
    context: str | None
    rationale: str
    decision_at: datetime
    decision_maker: UUID | None
    status: DecisionStatus
    related_memory_id: UUID | None
    related_evidence_id: UUID | None
    created_by: UUID
    created_at: datetime


class DecisionReplayCreate(BaseModel):
    """Creation request for a decision replay record.

    All fields are validated server-side. The actor is derived from auth.
    """

    model_config = ConfigDict(extra="forbid")

    decision_type: DecisionType
    match_id: UUID | None = None
    player_id: UUID | None = None
    decision_at: datetime
    decision_maker: UUID | None = None
    ai_recommendation_text: str | None = Field(default=None, max_length=4000)
    ai_model: str | None = Field(default=None, max_length=200)
    ai_model_version: str | None = Field(default=None, max_length=100)
    ai_recommendation_at: datetime | None = None
    ai_request_id: UUID | None = None
    ai_grounded: bool | None = None
    ai_cited_evidence_ids: list[UUID] | None = None
    human_decision: HumanDecision | None = None
    human_decision_at: datetime | None = None
    rationale: str | None = Field(default=None, max_length=4000)
    evidence_ids: list[UUID] | None = None
    outcome_evidence_ids: list[UUID] | None = None
    outcome_refs: str | None = Field(default=None, max_length=2000)

    @field_validator("decision_at", "ai_recommendation_at", "human_decision_at")
    @classmethod
    def timestamps_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_chronology(self) -> "DecisionReplayCreate":
        if self.ai_recommendation_at and self.human_decision_at:
            if self.human_decision_at < self.ai_recommendation_at:
                raise ValueError(
                    "human_decision_at cannot be before ai_recommendation_at"
                )
        if self.decision_at and self.ai_recommendation_at:
            if self.ai_recommendation_at > self.decision_at:
                raise ValueError("ai_recommendation_at cannot be after decision_at")
        if self.decision_at and self.human_decision_at:
            if self.human_decision_at > self.decision_at:
                raise ValueError("human_decision_at cannot be after decision_at")
        return self


class DecisionReplayView(BaseModel):
    """Read-only view of a decision replay record."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    decision_type: DecisionType
    match_id: UUID | None
    player_id: UUID | None
    decision_at: datetime
    decision_maker: UUID | None
    ai_recommendation_text: str | None
    ai_model: str | None
    ai_model_version: str | None
    ai_recommendation_at: datetime | None
    ai_request_id: UUID | None
    ai_grounded: bool | None
    ai_cited_evidence_ids: list[UUID] | None
    human_decision: HumanDecision | None
    human_decision_at: datetime | None
    rationale: str | None
    evidence_ids: list[UUID] | None
    outcome_evidence_ids: list[UUID] | None
    outcome_refs: str | None
    created_by: UUID
    created_at: datetime


class ReplayTimelinePhase(StrEnum):
    """Phase of the decision timeline."""

    EVIDENCE = "EVIDENCE"
    AI_RECOMMENDATION = "AI_RECOMMENDATION"
    HUMAN_DECISION = "HUMAN_DECISION"
    OUTCOME = "OUTCOME"


class ReplayTimelineItem(BaseModel):
    """One item in the decision replay timeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    phase: ReplayTimelinePhase
    description: str = Field(min_length=1, max_length=1000)
    source_type: str | None = Field(default=None, max_length=100)
    source_id: str | None = Field(default=None, max_length=200)
    evidence_id: UUID | None = None
    is_decision_time_evidence: bool = False
    is_outcome_evidence: bool = False


class TemporalRelation(StrEnum):
    """Position of an observed item relative to the decision moment."""

    BEFORE_DECISION = "BEFORE_DECISION"
    AT_DECISION = "AT_DECISION"
    AFTER_DECISION = "AFTER_DECISION"


class ReplayEvidenceItem(BaseModel):
    """Hydrated evidence item for a replay, subject to governance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID
    source_type: str
    source_id: str
    evidence_type: str
    excerpt: str | None = None
    match_id: UUID | None = None
    video_id: UUID | None = None
    frame_number: int | None = None
    timestamp_seconds: float | None = None
    created_at: datetime
    governance_status: str = Field(min_length=1, max_length=50)
    temporal_relation: TemporalRelation
    provenance: str | None = None
    is_decision_time_evidence: bool = False
    is_outcome_evidence: bool = False


class ReplayAIRecommendation(BaseModel):
    """AI recommendation as captured at decision time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str | None = None
    model: str | None = None
    model_version: str | None = None
    timestamp: datetime | None = None
    request_id: UUID | None = None
    grounded: bool | None = None
    cited_evidence_ids: list[UUID] = Field(default_factory=list)


class ReplayHumanDecision(BaseModel):
    """Human decision as recorded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: HumanDecision | None = None
    timestamp: datetime | None = None
    rationale: str | None = None
    decision_maker: UUID | None = None


class ReplayOutcomeReference(BaseModel):
    """Outcome evidence reference (descriptive only, never a verdict)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID
    source_type: str
    source_id: str
    timestamp: datetime
    description: str
    temporal_relation: TemporalRelation
    provenance: str | None = None


class DecisionReplay(BaseModel):
    """Complete reconstructed decision replay.

    Separates what was known at decision time from later outcomes.
    AI recommendation and human decision are distinct.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: UUID
    decision_type: DecisionType
    decision_status: str | None = None
    decision_time: datetime
    decision_maker: UUID | None = None
    match_id: UUID | None = None
    player_id: UUID | None = None
    ai_recommendation: ReplayAIRecommendation | None = None
    human_decision: ReplayHumanDecision | None = None
    timeline: list[ReplayTimelineItem] = Field(default_factory=list)
    evidence: list[ReplayEvidenceItem] = Field(default_factory=list)
    outcome_references: list[ReplayOutcomeReference] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class RetrievalQuery(BaseModel):
    """Explicit retrieval request. ``text`` is accepted as a
    future-compatible field only — the database backend matches on
    explicit filters, never on semantic similarity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str | None = Field(default=None, max_length=500)
    memory_type: MemoryType | None = None
    source_type: MemorySourceType | None = None
    source_id: str | None = Field(default=None, max_length=100)
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    has_confidence: bool | None = None
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    max_confidence: float | None = Field(default=None, ge=0, le=1)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("occurred_from", "occurred_to")
    @classmethod
    def range_is_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None


class RetrievalMatch(BaseModel):
    """One governed hit. ``match_reason`` names the deterministic
    mechanism (explicit filters); it is never a relevance score.
    ``similarity_score`` is the vector engine's raw number for the
    query — informational only, never memory/AI confidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory: MemoryView
    match_reason: str = Field(min_length=1, max_length=500)
    governance_status: str = Field(default="allowed", min_length=1, max_length=50)
    similarity_score: float | None = Field(default=None)
    index_key: str | None = Field(default=None, min_length=1, max_length=128)
    embedding_version: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def vector_fields_together(self) -> "RetrievalMatch":
        present = [
            self.similarity_score is not None,
            self.index_key is not None,
            self.embedding_version is not None,
        ]
        if any(present) and not all(present):
            raise ValueError(
                "similarity_score, index_key, and embedding_version "
                "must be set together or not at all"
            )
        return self


class RetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: RetrievalQuery
    results: list[RetrievalMatch]
    result_count: int = Field(ge=0)

    @model_validator(mode="after")
    def count_matches_results(self) -> "RetrievalResponse":
        if self.result_count != len(self.results):
            raise ValueError("result_count must equal len(results)")
        return self


class VectorRetrievalEvaluation(BaseModel):
    """Structured counts for one vector retrieval pass. No Recall@K /
    Precision@K: those need ground-truth relevance labels, which do
    not exist here. ``latency_ms`` is local wall-clock for the pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: str = Field(default="vector-search", min_length=1, max_length=50)
    candidate_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    stale_count: int = Field(ge=0)
    authorized_count: int = Field(ge=0)
    filtered_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    embedding_model: str | None = Field(default=None, max_length=200)
    embedding_version: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def counts_consistent(self) -> "VectorRetrievalEvaluation":
        if self.resolved_count + self.stale_count != self.candidate_count:
            raise ValueError("resolved + stale must equal candidates")
        if self.authorized_count + self.filtered_count != self.resolved_count:
            raise ValueError("authorized + filtered must equal resolved")
        if self.returned_count != self.authorized_count:
            raise ValueError("returned must equal authorized")
        return self


class MemoryIndexDocument(BaseModel):
    """Derived, embeddable representation of one memory.

    Only retrieval-legitimate content is included: title, summary, and
    evidence excerpts. Explicitly excluded: ``extra_data`` (arbitrary
    JSON), ``confidence`` (not text), ``created_by``/``redacted_by``
    (identities, not semantics), raw video, tensors, ORM internals.
    Provenance travels as identifiers, never via embedded text alone.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    index_key: str = Field(min_length=1, max_length=128)
    memory_id: UUID
    text: str = Field(min_length=1, max_length=10000)
    memory_type: MemoryType
    sensitivity: MemorySensitivity
    source_type: MemorySourceType
    source_id: str
    occurred_at: datetime
    evidence_ids: tuple[UUID, ...] = ()
    match_ids: tuple[UUID, ...] = ()
    video_ids: tuple[UUID, ...] = ()
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_version: str = Field(min_length=1, max_length=100)
    source_content_hash: str = Field(min_length=1, max_length=128)
    generated_at: datetime


class IndexingResult(BaseModel):
    """Structured output of one indexing run: document plus vector."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document: MemoryIndexDocument
    embedding: tuple[float, ...]
    embedding_dim: int = Field(ge=1)

    @model_validator(mode="after")
    def vector_matches_dim(self) -> "IndexingResult":
        if len(self.embedding) != self.embedding_dim:
            raise ValueError("embedding length must equal embedding_dim")
        return self


class VectorRemovalRequest(BaseModel):
    """Contract for future Qdrant cleanup of stale vectors. Defines WHAT
    must be removed and WHY; the Qdrant delete call itself is not
    implemented here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index_key: str = Field(min_length=1, max_length=128)
    memory_id: UUID
    reason: str = Field(min_length=1, max_length=50)
    requested_at: datetime
