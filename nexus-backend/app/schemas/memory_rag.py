from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.memory import MemorySourceType, MemoryType


class ClaimSupport(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NO_CITATION = "NO_CITATION"


class GroundingStatus(StrEnum):
    GROUNDED = "GROUNDED"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    UNGROUNDED = "UNGROUNDED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AnswerClaim(BaseModel):
    """One factual claim from a generated answer, as produced."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=100)
    claim_text: str = Field(min_length=1, max_length=2000)
    citation_ids: tuple[UUID, ...] = ()


class StructuredAnswer(BaseModel):
    """Model output in a verifiable shape. No truth claims attached."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer_text: str = Field(max_length=8000)
    claims: tuple[AnswerClaim, ...] = ()
    model_id: str = Field(min_length=1, max_length=200)
    generated_at: datetime


class VerifiedClaim(BaseModel):
    """A claim plus its deterministic verification outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=100)
    claim_text: str = Field(min_length=1, max_length=2000)
    citation_ids: tuple[UUID, ...] = ()
    support_status: ClaimSupport
    matched_evidence_ids: tuple[UUID, ...] = ()


class RagContextItem(BaseModel):
    """One citable unit of governed retrieval context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: UUID
    memory_id: UUID
    evidence_id: UUID | None = None
    text: str = Field(min_length=1, max_length=10000)
    source_type: str = Field(min_length=1, max_length=50)
    source_id: str = Field(min_length=1, max_length=100)


class RagContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_text: str = Field(max_length=500)
    items: tuple[RagContextItem, ...] = ()


class RagEvaluationResult(BaseModel):
    """Deterministic grounding counts. No quality scores — every value
    is directly computed from the claims, citations, and context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer_text: str = Field(max_length=8000)
    total_claims: int = Field(ge=0)
    supported_claims: int = Field(ge=0)
    partially_supported_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)
    uncited_claims: int = Field(ge=0)
    invalid_citations: tuple[UUID, ...] = ()
    grounding_status: GroundingStatus
    verified_claims: tuple[VerifiedClaim, ...] = ()

    @model_validator(mode="after")
    def counts_consistent(self) -> "RagEvaluationResult":
        counted = (
            self.supported_claims
            + self.partially_supported_claims
            + self.unsupported_claims
            + self.uncited_claims
        )
        if counted != self.total_claims:
            raise ValueError("status counts must sum to total_claims")
        if len(self.verified_claims) != self.total_claims:
            raise ValueError("one verified claim per input claim is required")
        return self


class RagQueryRequest(BaseModel):
    """RAG question envelope. Only the question plus retrieval filters
    the existing retrieval service already supports. Anything else —
    memory IDs, prompts, roles, sensitivities — is rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=500)
    memory_type: MemoryType | None = None
    source_type: MemorySourceType | None = None
    source_id: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=5, ge=1, le=20)


class RagQueryResponse(BaseModel):
    """Public RAG result: answer plus its grounding verdict. No vectors,
    prompts, ORM objects, or provider internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: StructuredAnswer
    evaluation: RagEvaluationResult
