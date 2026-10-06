"""Phase 08J RAG evaluation tests. All fixtures are SYNTHETIC and
verify citation/grounding mathematics only — never football truth,
never model quality."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.memory import MemoryEvidenceType, MemorySourceType
from app.core.roles import RoleName
from app.schemas.memory import EvidenceCreate
from app.schemas.memory_rag import (
    AnswerClaim,
    ClaimSupport,
    GroundingStatus,
    RagContext,
    RagContextItem,
    StructuredAnswer,
)
from app.services import club_memory
from app.services.memory_governance import redact_memory
from app.services.memory_rag import (
    answer_question,
    verify_answer,
)
from app.services.memory_retrieval import retrieve_memories
from tests.conftest import DatabaseFixture
from tests.test_memory_governance import make_user, payload


class FakeAnswerProvider:
    """Deterministic test LLM stand-in. Returns canned answers only."""

    model_id = "fake-test-llm"

    def __init__(self, answer=None):
        self.calls: list[tuple[str, list[str]]] = []
        self._answer = answer

    async def answer(self, question, context_texts):
        self.calls.append((question, list(context_texts)))
        if self._answer is not None:
            return self._answer
        return StructuredAnswer(
            answer_text="",
            claims=(),
            model_id=self.model_id,
            generated_at=datetime.now(UTC),
        )


def context_item(item_id, text, memory_id=None):
    return RagContextItem(
        item_id=item_id,
        memory_id=memory_id or item_id,
        evidence_id=None,
        text=text,
        source_type="HUMAN_RECORDED",
        source_id="note-test",
    )


def answer(text, claims, model_id="fake-test-llm"):
    return StructuredAnswer(
        answer_text=text,
        claims=tuple(claims),
        model_id=model_id,
        generated_at=datetime.now(UTC),
    )


def claim(cid, text, citations=()):
    return AnswerClaim(claim_id=cid, claim_text=text, citation_ids=tuple(citations))


MEMORY_TEXT = "Pressing triggers\nMid-block triggers on backward passes."
EVIDENCE_TEXT = "Right-back holds width."
OTHER_TEXT = "Goalkeeper distribution starts attacks."


def filled_context():
    mid = uuid4()
    eid = uuid4()
    other = uuid4()
    return (
        RagContext(
            query_text="pressing",
            items=(
                context_item(mid, MEMORY_TEXT, memory_id=mid),
                RagContextItem(
                    item_id=eid,
                    memory_id=mid,
                    evidence_id=eid,
                    text=EVIDENCE_TEXT,
                    source_type="VISION",
                    source_id="track-1",
                ),
                context_item(other, OTHER_TEXT, memory_id=other),
            ),
        ),
        mid,
        eid,
        other,
    )


# CASE A: fully supported answer.
def test_case_a_fully_supported() -> None:
    context, mid, eid, _ = filled_context()
    result = verify_answer(
        context,
        answer(
            "The team presses in a mid-block.",
            [
                claim("c1", "Pressing triggers in the mid-block.", [mid]),
                claim("c2", "Right-back holds width.", [eid]),
            ],
        ),
    )
    assert result.grounding_status is GroundingStatus.GROUNDED
    assert (result.supported_claims, result.total_claims) == (2, 2)
    assert result.unsupported_claims == 0
    assert result.invalid_citations == ()


# CASE B: claim with no citation.
def test_case_b_missing_citation() -> None:
    context, mid, _, _ = filled_context()
    result = verify_answer(
        context,
        answer(
            "Mixed answer.",
            [
                claim("c1", "Pressing triggers in the mid-block.", [mid]),
                claim("c2", "Strikers always score hat tricks.", ()),
            ],
        ),
    )
    assert result.uncited_claims == 1
    assert result.grounding_status is GroundingStatus.PARTIALLY_GROUNDED
    uncited = next(v for v in result.verified_claims if v.claim_id == "c2")
    assert uncited.support_status is ClaimSupport.NO_CITATION


# CASE C: citation outside the current context.
def test_case_c_invalid_citation() -> None:
    context, _, _, _ = filled_context()
    ghost = uuid4()
    result = verify_answer(
        context, answer("Ghost claim.", [claim("c1", "Pressing triggers.", [ghost])])
    )
    assert result.invalid_citations == (ghost,)
    assert result.unsupported_claims == 1
    assert result.grounding_status is GroundingStatus.UNGROUNDED


# CASE E: mixed supported and unsupported claims.
def test_case_e_mixed_answer() -> None:
    context, mid, _, _ = filled_context()
    result = verify_answer(
        context,
        answer(
            "Mixed.",
            [
                claim("c1", "Pressing triggers in the mid-block.", [mid]),
                claim("c2", "Goalkeeper never leaves the line.", [uuid4()]),
            ],
        ),
    )
    assert result.supported_claims == 1
    assert result.unsupported_claims == 1
    assert result.grounding_status is GroundingStatus.PARTIALLY_GROUNDED


# CASE G: two valid citations support the same claim.
def test_case_g_two_citations() -> None:
    context, mid, eid, _ = filled_context()
    result = verify_answer(
        context,
        answer(
            "Supported twice.",
            [claim("c1", "Pressing triggers and right-back holds width.", [mid, eid])],
        ),
    )
    assert result.supported_claims == 1
    assert result.verified_claims[0].matched_evidence_ids == (mid, eid)


def test_partially_supported_answer() -> None:
    context, _, eid, _ = filled_context()
    result = verify_answer(
        context,
        answer(
            "Partial.",
            [
                claim(
                    "c1",
                    "Width matters when fullbacks overlap.",
                    [eid],
                )
            ],
        ),
    )
    assert result.partially_supported_claims == 1
    assert result.grounding_status is GroundingStatus.PARTIALLY_GROUNDED


def test_duplicate_citations() -> None:
    context, mid, _, _ = filled_context()
    result = verify_answer(
        context,
        answer(
            "Dup.",
            [claim("c1", "Pressing triggers in the mid-block.", [mid, mid])],
        ),
    )
    assert result.supported_claims == 1
    assert result.invalid_citations == ()


def test_multiple_evidence_sources() -> None:
    context, mid, eid, other = filled_context()
    result = verify_answer(
        context,
        answer(
            "Both.",
            [
                claim(
                    "c1",
                    "Pressing triggers while goalkeeper distribution starts attacks.",
                    [mid, other],
                ),
                claim("c2", "Right-back holds width.", [eid]),
            ],
        ),
    )
    assert result.supported_claims == 2
    assert result.grounding_status is GroundingStatus.GROUNDED


def test_deterministic_evaluation_result() -> None:
    context, mid, _, _ = filled_context()
    first = verify_answer(
        context, answer("A.", [claim("c1", "Pressing triggers.", [mid])])
    )
    second = verify_answer(
        context, answer("A.", [claim("c1", "Pressing triggers.", [mid])])
    )
    assert first == second


def test_no_false_citation_acceptance() -> None:
    context, _, _, _ = filled_context()
    near_miss = uuid4()
    result = verify_answer(
        context,
        answer("Nope.", [claim("c1", "Pressing triggers.", [near_miss])]),
    )
    assert result.unsupported_claims == 1
    assert result.invalid_citations == (near_miss,)


def test_invalid_inputs_rejected() -> None:
    context, _, _, _ = filled_context()
    with pytest.raises(TypeError):
        verify_answer("nope", answer("A.", []))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        verify_answer(context, "nope")  # type: ignore[arg-type]


async def seed_evidence_memory(database, admin):
    async with database.sessions() as session:
        return await club_memory.record_memory(
            session,
            admin,
            payload(source_id="note-rag-1"),
            [
                EvidenceCreate(
                    source_type=MemorySourceType.HUMAN_RECORDED,
                    source_id="note-rag-1",
                    evidence_type=MemoryEvidenceType.TEXT_EXCERPT,
                    excerpt="Mid-block triggers on backward passes.",
                )
            ],
        )


@pytest.mark.asyncio
async def test_integration_governed_flow(database: DatabaseFixture) -> None:
    admin = await make_user(database, "rag-admin@example.com", RoleName.ADMIN)
    view = await seed_evidence_memory(database, admin)
    llm = FakeAnswerProvider(
        answer(
            "The team uses a mid-block.",
            [
                claim(
                    "c1",
                    "Mid-block triggers on backward passes.",
                    [view.evidence[0].id],
                )
            ],
            model_id="fake-test-llm",
        )
    )
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery as Query

        response = await retrieve_memories(session, admin, Query(text="mid-block"))
        assert response.result_count >= 1
        returned, result = await answer_question(
            session, admin, "How does the team press?", llm
        )
    assert llm.calls and llm.calls[0][0] == "How does the team press?"
    assert result.grounding_status is GroundingStatus.GROUNDED
    assert result.supported_claims == 1
    assert returned.model_dump()["model_id"] == "fake-test-llm"


@pytest.mark.asyncio
async def test_case_f_empty_retrieval(database: DatabaseFixture) -> None:
    admin = await make_user(database, "rag-admin-f@example.com", RoleName.ADMIN)
    llm = FakeAnswerProvider()
    async with database.sessions() as session:
        returned, result = await answer_question(session, admin, "Anything?", llm)
    assert llm.calls == []
    assert result.grounding_status is GroundingStatus.INSUFFICIENT_EVIDENCE
    assert result.total_claims == 0
    assert returned.answer_text == ""


@pytest.mark.asyncio
async def test_case_d_redacted_excluded(database: DatabaseFixture) -> None:
    admin = await make_user(database, "rag-admin-d@example.com", RoleName.ADMIN)
    view = await seed_evidence_memory(database, admin)
    evidence_id = view.evidence[0].id
    async with database.sessions() as session:
        await redact_memory(session, admin, view.id)
    llm = FakeAnswerProvider(
        answer(
            "Stale claim.",
            [claim("c1", "Mid-block triggers on backward passes.", [evidence_id])],
        )
    )
    async with database.sessions() as session:
        from app.schemas.memory import RetrievalQuery as Query

        response = await retrieve_memories(session, admin, Query(text="mid-block"))
        assert response.result_count == 0
        returned, result = await answer_question(
            session, admin, "How does the team press?", llm
        )
    # Redacted content never reaches context: LLM unused, claim unverifiable.
    assert llm.calls == []
    assert result.grounding_status is GroundingStatus.INSUFFICIENT_EVIDENCE
    direct = verify_answer(
        RagContext(query_text="x", items=()),
        answer("Stale.", [claim("c1", "Mid-block triggers.", [evidence_id])]),
    )
    assert direct.unsupported_claims == 1
    assert direct.invalid_citations == (evidence_id,)


@pytest.mark.asyncio
async def test_blank_question_rejected(database: DatabaseFixture) -> None:
    admin = await make_user(database, "rag-admin-b@example.com", RoleName.ADMIN)
    async with database.sessions() as session:
        with pytest.raises(ValueError):
            await answer_question(session, admin, "   ", FakeAnswerProvider())


@pytest.mark.asyncio
async def test_restricted_memory_never_enters_context(
    database: DatabaseFixture,
) -> None:
    from app.core.memory import MemorySensitivity

    admin = await make_user(database, "rag-admin-r@example.com", RoleName.ADMIN)
    player = await make_user(database, "rag-player@example.com", RoleName.PLAYER)
    async with database.sessions() as session:
        await club_memory.record_memory(
            session,
            admin,
            payload(
                source_id="note-rag-restricted",
                sensitivity=MemorySensitivity.RESTRICTED,
            ),
            [
                EvidenceCreate(
                    source_type=MemorySourceType.HUMAN_RECORDED,
                    source_id="note-rag-restricted",
                    evidence_type=MemoryEvidenceType.TEXT_EXCERPT,
                    excerpt="Restricted pressing detail.",
                )
            ],
        )
    llm = FakeAnswerProvider()
    async with database.sessions() as session:
        returned, result = await answer_question(
            session, player, "How does the team press?", llm
        )
    assert llm.calls == []
    assert result.grounding_status is GroundingStatus.INSUFFICIENT_EVIDENCE
    assert MemorySensitivity.RESTRICTED is not None
