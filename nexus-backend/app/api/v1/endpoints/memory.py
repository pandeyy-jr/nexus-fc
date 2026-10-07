from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status

from app.api.dependencies import CurrentUser, SessionDependency
from app.api.memory_dependencies import MemoryRedactor, MemoryWriter
from app.core.memory import DecisionStatus, DecisionType, MemorySourceType, MemoryType
from app.schemas.memory import (
    DecisionCreate,
    DecisionReplay,
    DecisionReplayCreate,
    DecisionReplayEvaluation,
    DecisionReplayView,
    DecisionView,
    EvidenceCreate,
    EvidenceView,
    MemoryCreateRequest,
    MemoryView,
)
from app.schemas.memory_rag import RagQueryRequest, RagQueryResponse
from app.services import club_memory, memory_governance
from app.services.memory_rag import LlmAnswerProvider, answer_question

router = APIRouter()


def get_rag_llm() -> LlmAnswerProvider:
    """LLM provider seam. No production provider is configured: requests
    fail closed with 503 until a real provider is wired. Tests override
    this dependency with a deterministic fake. No API keys are handled
    here — provider construction owns its own secrets."""
    raise HTTPException(
        status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="RAG LLM provider is not configured",
    )


@router.post("", response_model=MemoryView, status_code=http_status.HTTP_201_CREATED)
async def post_memory(
    body: MemoryCreateRequest,
    session: SessionDependency,
    actor: MemoryWriter,
) -> MemoryView:
    return await club_memory.record_memory(session, actor, body.memory, body.evidence)


@router.get("", response_model=list[MemoryView])
async def get_memories(
    session: SessionDependency,
    actor: CurrentUser,
    memory_type: MemoryType | None = None,
    source_type: MemorySourceType | None = None,
    source_id: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    has_confidence: bool | None = None,
    min_confidence: float | None = None,
    max_confidence: float | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MemoryView]:
    return await memory_governance.list_governed_memory_views(
        session,
        actor,
        memory_type=memory_type,
        source_type=source_type,
        source_id=source_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        has_confidence=has_confidence,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/decisions", response_model=DecisionView, status_code=http_status.HTTP_201_CREATED
)
async def post_decision(
    body: DecisionCreate,
    session: SessionDependency,
    actor: MemoryWriter,
) -> DecisionView:
    return await club_memory.record_decision(session, actor, body)


@router.get("/decisions", response_model=list[DecisionView])
async def get_decisions(
    session: SessionDependency,
    actor: CurrentUser,
    decision_type: DecisionType | None = None,
    status: DecisionStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DecisionView]:
    return await memory_governance.list_governed_decision_views(
        session,
        actor,
        decision_type=decision_type,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/decisions/replay",
    response_model=DecisionReplayView,
    status_code=http_status.HTTP_201_CREATED,
)
async def post_decision_replay(
    body: DecisionReplayCreate,
    session: SessionDependency,
    actor: CurrentUser,
) -> DecisionReplayView:
    return await club_memory.create_decision_replay(session, actor, body)


@router.get("/decisions/replay", response_model=list[DecisionReplayView])
async def get_decision_replays(
    session: SessionDependency,
    actor: CurrentUser,
    decision_type: DecisionType | None = None,
    match_id: UUID | None = None,
    player_id: UUID | None = None,
    decision_from: datetime | None = None,
    decision_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DecisionReplayView]:
    return await club_memory.list_decision_replay_views(
        session,
        decision_type=decision_type,
        match_id=match_id,
        player_id=player_id,
        decision_from=decision_from,
        decision_to=decision_to,
        limit=limit,
        offset=offset,
    )


@router.get("/decisions/replay/{replay_id}", response_model=DecisionReplayView)
async def get_decision_replay(
    replay_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> DecisionReplayView:
    return await club_memory.get_decision_replay_view(session, replay_id)


@router.get(
    "/decisions/replay/{replay_id}/reconstruction", response_model=DecisionReplay
)
async def get_decision_replay_reconstruction(
    replay_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> DecisionReplay:
    """Reconstruct a complete, chronologically ordered decision replay.

    Hydrates evidence through authorized services, builds a timeline
    separating decision-time evidence from outcome evidence, and applies
    governance to all hydrated items. Returns warnings for any
    inaccessible or missing data.
    """
    return await club_memory.reconstruct_decision_replay(session, actor, replay_id)


@router.get(
    "/decisions/replay/{replay_id}/evaluation",
    response_model=DecisionReplayEvaluation,
)
async def get_decision_replay_evaluation(
    replay_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> DecisionReplayEvaluation:
    """Deterministic, evidence-based evaluation of a decision replay.

    Derives factual observations from the governed reconstruction:
    what evidence existed at decision time, what the human did relative
    to the AI recommendation, and what outcomes were observed. It never
    judges decision quality, never infers causality, and computes no
    confidence. Read-only; governance is applied by the reconstruction
    choke point it reuses.
    """
    return await club_memory.evaluate_decision_replay(session, actor, replay_id)


@router.get("/decisions/{decision_id}", response_model=DecisionView)
async def get_decision(
    decision_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> DecisionView:
    return await memory_governance.get_governed_decision_view(
        session, actor, decision_id
    )


@router.get("/{memory_id}", response_model=MemoryView)
async def get_memory(
    memory_id: UUID,
    session: SessionDependency,
    actor: CurrentUser,
) -> MemoryView:
    return await memory_governance.get_governed_memory_view(session, actor, memory_id)


@router.post(
    "/{memory_id}/evidence",
    response_model=EvidenceView,
    status_code=http_status.HTTP_201_CREATED,
)
async def post_memory_evidence(
    memory_id: UUID,
    body: EvidenceCreate,
    session: SessionDependency,
    actor: MemoryWriter,
) -> EvidenceView:
    return await club_memory.add_memory_evidence(session, actor, memory_id, body)


@router.post("/{memory_id}/redact", response_model=MemoryView)
async def post_memory_redact(
    memory_id: UUID,
    session: SessionDependency,
    actor: MemoryRedactor,
) -> MemoryView:
    return await memory_governance.redact_memory(session, actor, memory_id)


@router.post("/rag/query", response_model=RagQueryResponse)
async def post_rag_query(
    body: RagQueryRequest,
    session: SessionDependency,
    actor: CurrentUser,
    llm: Annotated[LlmAnswerProvider, Depends(get_rag_llm)],
) -> RagQueryResponse:
    """Governed RAG question answering. The route does no retrieval,
    governance, prompting, or verification itself — it delegates to the
    RAG application service, which enforces the full governed chain.
    Production rate limiting remains a deployment concern: no
    rate-limit mechanism exists in this codebase yet."""
    try:
        answer, evaluation = await answer_question(
            session,
            actor,
            body.question,
            llm,
            backend=None,
            limit=body.limit,
            memory_type=body.memory_type,
            source_type=body.source_type,
            source_id=body.source_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG provider unavailable",
        ) from exc
    return RagQueryResponse(answer=answer, evaluation=evaluation)
