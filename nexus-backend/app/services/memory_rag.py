from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory import MemorySourceType, MemoryType
from app.db.models.user import User
from app.schemas.memory import RetrievalMatch, RetrievalQuery
from app.schemas.memory_rag import (
    ClaimSupport,
    GroundingStatus,
    RagContext,
    RagContextItem,
    RagEvaluationResult,
    StructuredAnswer,
    VerifiedClaim,
)
from app.services.memory_retrieval import RetrievalBackend, retrieve_memories

# Lexical baseline only: common words carry no grounding signal.
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
        "which",
        "when",
        "had",
        "been",
        "also",
        "than",
        "then",
    }
)

# Coverage at or above this fraction of a claim's significant tokens
# counts as SUPPORTED; anything above zero counts as PARTIALLY_SUPPORTED.
SUPPORT_THRESHOLD = 0.5


class LlmAnswerProvider(Protocol):
    """Minimal answer contract. Future OpenAI/Gemini/local providers
    implement ``answer``; nothing here knows about model vendors."""

    model_id: str

    async def answer(
        self, question: str, context_texts: Sequence[str]
    ) -> StructuredAnswer: ...


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in STOPWORDS
    }


def build_rag_context(matches: Sequence[RetrievalMatch]) -> RagContext:
    """Flatten governed matches into citable context items: one per
    memory (title + summary) plus one per non-empty evidence excerpt.
    Input order is preserved for determinism."""
    items: list[RagContextItem] = []
    for match in matches:
        memory = match.memory
        items.append(
            RagContextItem(
                item_id=memory.id,
                memory_id=memory.id,
                evidence_id=None,
                text=f"{memory.title}\n{memory.summary}",
                source_type=memory.source_type.value,
                source_id=memory.source_id,
            )
        )
        for evidence in memory.evidence:
            if evidence.excerpt and evidence.excerpt.strip():
                items.append(
                    RagContextItem(
                        item_id=evidence.id,
                        memory_id=memory.id,
                        evidence_id=evidence.id,
                        text=evidence.excerpt,
                        source_type=evidence.source_type.value,
                        source_id=evidence.source_id,
                    )
                )
    return RagContext(query_text="", items=tuple(items))


def verify_answer(context: RagContext, answer: StructuredAnswer) -> RagEvaluationResult:
    """Deterministic citation verification. Decides only whether each
    claim is supported by the SUPPLIED context — never whether a
    football statement is objectively true, and never via another LLM.

    Rules: no citations -> NO_CITATION; citations with none present in
    this context -> UNSUPPORTED (and recorded as invalid); otherwise
    lexical coverage of the claim's significant tokens across the cited
    texts decides SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED.
    """
    if not isinstance(context, RagContext):
        raise TypeError("context must be a RagContext")
    if not isinstance(answer, StructuredAnswer):
        raise TypeError("answer must be a StructuredAnswer")
    by_id: dict[UUID, RagContextItem] = {item.item_id: item for item in context.items}
    verified: list[VerifiedClaim] = []
    invalid: set[UUID] = set()
    for claim in answer.claims:
        if not claim.citation_ids:
            verified.append(
                VerifiedClaim(
                    claim_id=claim.claim_id,
                    claim_text=claim.claim_text,
                    citation_ids=(),
                    support_status=ClaimSupport.NO_CITATION,
                    matched_evidence_ids=(),
                )
            )
            continue
        matched = [cid for cid in claim.citation_ids if cid in by_id]
        invalid.update(cid for cid in claim.citation_ids if cid not in by_id)
        if not matched:
            status = ClaimSupport.UNSUPPORTED
        else:
            pool: set[str] = set()
            for cid in matched:
                pool.update(_tokens(by_id[cid].text))
            claim_tokens = _tokens(claim.claim_text)
            if not claim_tokens:
                status = ClaimSupport.UNSUPPORTED
            else:
                coverage = len(claim_tokens & pool) / len(claim_tokens)
                if coverage >= SUPPORT_THRESHOLD:
                    status = ClaimSupport.SUPPORTED
                elif coverage > 0:
                    status = ClaimSupport.PARTIALLY_SUPPORTED
                else:
                    status = ClaimSupport.UNSUPPORTED
        verified.append(
            VerifiedClaim(
                claim_id=claim.claim_id,
                claim_text=claim.claim_text,
                citation_ids=claim.citation_ids,
                support_status=status,
                matched_evidence_ids=tuple(matched),
            )
        )
    counts = {status: 0 for status in ClaimSupport}
    for item in verified:
        counts[item.support_status] += 1
    if not context.items:
        grounding = GroundingStatus.INSUFFICIENT_EVIDENCE
    elif not verified:
        grounding = GroundingStatus.INSUFFICIENT_EVIDENCE
    elif all(item.support_status is ClaimSupport.SUPPORTED for item in verified):
        grounding = GroundingStatus.GROUNDED
    elif any(
        item.support_status
        in (ClaimSupport.SUPPORTED, ClaimSupport.PARTIALLY_SUPPORTED)
        for item in verified
    ):
        grounding = GroundingStatus.PARTIALLY_GROUNDED
    else:
        grounding = GroundingStatus.UNGROUNDED
    return RagEvaluationResult(
        answer_text=answer.answer_text,
        total_claims=len(verified),
        supported_claims=counts[ClaimSupport.SUPPORTED],
        partially_supported_claims=counts[ClaimSupport.PARTIALLY_SUPPORTED],
        unsupported_claims=counts[ClaimSupport.UNSUPPORTED],
        uncited_claims=counts[ClaimSupport.NO_CITATION],
        invalid_citations=tuple(sorted(invalid, key=str)),
        grounding_status=grounding,
        verified_claims=tuple(verified),
    )


async def answer_question(
    session: AsyncSession,
    actor: User,
    question: str,
    llm: LlmAnswerProvider,
    backend: RetrievalBackend | None = None,
    limit: int = 5,
    memory_type: MemoryType | None = None,
    source_type: MemorySourceType | None = None,
    source_id: str | None = None,
) -> tuple[StructuredAnswer, RagEvaluationResult]:
    """Thin orchestration seam: governed retrieval -> context -> LLM ->
    verification. With no retrieval hits the LLM is not called; the
    empty answer verifies as INSUFFICIENT_EVIDENCE. Provider errors
    propagate explicitly — never swallowed into a fabricated answer."""
    if not question or not question.strip():
        raise ValueError("question must not be blank")
    response = await retrieve_memories(
        session,
        actor,
        RetrievalQuery(
            text=question.strip(),
            limit=limit,
            memory_type=memory_type,
            source_type=source_type,
            source_id=source_id,
        ),
        backend,
    )
    context = build_rag_context(response.results)
    if not context.items:
        empty = StructuredAnswer(
            answer_text="",
            claims=(),
            model_id=llm.model_id,
            generated_at=datetime.now(UTC),
        )
        return empty, verify_answer(context, empty)
    answer = await llm.answer(question.strip(), [item.text for item in context.items])
    return answer, verify_answer(context, answer)


__all__ = [
    "LlmAnswerProvider",
    "SUPPORT_THRESHOLD",
    "STOPWORDS",
    "answer_question",
    "build_rag_context",
    "verify_answer",
]
