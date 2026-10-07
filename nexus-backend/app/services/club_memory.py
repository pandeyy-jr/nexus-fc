import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory import (
    DecisionStatus,
    DecisionType,
    HumanDecision,
    MemorySourceType,
    MemoryType,
)
from app.db.models.memory import DecisionReplay as DecisionReplayRecord
from app.db.models.user import User
from app.repositories import matches, memory, users, video_sources
from app.schemas.memory import (
    DecisionCreate,
    DecisionReplay,
    DecisionReplayCreate,
    DecisionReplayEvaluation,
    DecisionReplayView,
    DecisionView,
    EvaluationMetadata,
    EvaluationObservation,
    EvaluationObservationCode,
    EvaluationStatus,
    EvidenceCreate,
    EvidenceView,
    MemoryCreate,
    MemoryView,
    RecommendationRelation,
    ReplayAIRecommendation,
    ReplayEvidenceItem,
    ReplayHumanDecision,
    ReplayOutcomeReference,
    ReplayTimelineItem,
    ReplayTimelinePhase,
    TemporalRelation,
)
from app.services.memory_governance import can_retrieve


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _parse_reference_ids(value: str | None) -> list[UUID] | None:
    """Parse a stored JSON list of UUID strings.

    Returns ``None`` when a stored value exists but is unreadable, so
    callers can distinguish "no links recorded" from "links recorded but
    unparseable" and surface a controlled warning instead of silently
    pretending the links never existed.
    """
    if not value:
        return []
    try:
        return [UUID(item) for item in json.loads(value)]
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return None


async def record_memory(
    session: AsyncSession,
    actor: User,
    payload: MemoryCreate,
    evidence: list[EvidenceCreate] | None = None,
) -> MemoryView:
    """Create a memory with its evidence atomically.

    Authorization stays outside: the caller decides who may record.
    This service only stamps ``created_by`` and enforces invariants.
    Source fields are write-once (no update path exists), so provenance
    can never be silently rewritten.
    """
    try:
        record = await memory.add_memory(
            session, {**payload.model_dump(), "created_by": actor.id}
        )
        views: list[EvidenceView] = []
        for item in evidence or []:
            if (
                item.match_id is not None
                and await matches.get_match(session, item.match_id) is None
            ):
                raise _not_found("Referenced match not found")
            if (
                item.video_id is not None
                and await video_sources.get_video_source(session, item.video_id) is None
            ):
                raise _not_found("Referenced video source not found")
            reference = await memory.add_evidence(session, record.id, item.model_dump())
            views.append(EvidenceView.model_validate(reference))
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Memory conflicts with existing records",
        ) from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Memory could not be saved",
        ) from exc
    await session.refresh(record)
    return MemoryView.model_validate(record)


async def record_decision(
    session: AsyncSession, actor: User, payload: DecisionCreate
) -> DecisionView:
    """Record a human decision. AI recommendations are never decisions:
    they carry no human ``decision_maker`` and must not be passed here.
    ``created_by`` (recorder) and ``decision_maker`` (decider) are stored
    as separate fields and never conflated. A supplied decision_maker
    must be an existing active user, validated server-side.
    """
    try:
        if payload.decision_maker is not None:
            maker = await users.get_by_id(session, payload.decision_maker)
            if maker is None:
                raise _not_found("Decision maker not found")
            if not maker.is_active:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Decision maker is not active",
                )
        if (
            payload.related_memory_id is not None
            and await memory.get_memory(session, payload.related_memory_id) is None
        ):
            raise _not_found("Related memory not found")
        if (
            payload.related_evidence_id is not None
            and await memory.get_evidence(session, payload.related_evidence_id) is None
        ):
            raise _not_found("Related evidence not found")
        record = await memory.add_decision(
            session, {**payload.model_dump(), "created_by": actor.id}
        )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Decision conflicts with existing records",
        ) from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Decision could not be saved",
        ) from exc
    await session.refresh(record)
    return DecisionView.model_validate(record)


async def get_memory_view(session: AsyncSession, memory_id: UUID) -> MemoryView:
    record = await memory.get_memory(session, memory_id)
    if record is None:
        raise _not_found("Memory not found")
    return MemoryView.model_validate(record)


async def add_memory_evidence(
    session: AsyncSession,
    actor: User,
    memory_id: UUID,
    payload: EvidenceCreate,
) -> EvidenceView:
    """Append evidence to an existing memory. Provenance fields come only
    from the validated payload; the parent link is fixed server-side and
    existing rows are never rewritten."""
    from app.services import memory_governance

    record = await memory.get_memory(session, memory_id)
    if record is None:
        raise _not_found("Memory not found")
    memory_governance.require_retrieval(actor, record)
    try:
        if (
            payload.match_id is not None
            and await matches.get_match(session, payload.match_id) is None
        ):
            raise _not_found("Referenced match not found")
        if (
            payload.video_id is not None
            and await video_sources.get_video_source(session, payload.video_id) is None
        ):
            raise _not_found("Referenced video source not found")
        reference = await memory.add_evidence(session, record.id, payload.model_dump())
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence conflicts with existing records",
        ) from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Evidence could not be saved",
        ) from exc
    await session.refresh(reference)
    return EvidenceView.model_validate(reference)


async def list_memory_views(
    session: AsyncSession,
    *,
    memory_type: MemoryType | None = None,
    source_type: MemorySourceType | None = None,
    source_id: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    has_confidence: bool | None = None,
    min_confidence: float | None = None,
    max_confidence: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[MemoryView]:
    records = await memory.list_memories(
        session,
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
    return [MemoryView.model_validate(record) for record in records]


async def get_decision_view(session: AsyncSession, decision_id: UUID) -> DecisionView:
    record = await memory.get_decision(session, decision_id)
    if record is None:
        raise _not_found("Decision not found")
    return DecisionView.model_validate(record)


async def list_decision_views(
    session: AsyncSession,
    *,
    decision_type: DecisionType | None = None,
    status: DecisionStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DecisionView]:
    records = await memory.list_decisions(
        session, decision_type=decision_type, status=status, limit=limit, offset=offset
    )
    return [DecisionView.model_validate(record) for record in records]


async def _replay_to_view(record: DecisionReplayRecord) -> DecisionReplayView:
    """Convert DecisionReplay ORM to view, parsing JSON string fields."""
    import json

    def parse_uuid_list(value: str | None) -> list[UUID] | None:
        if value is None:
            return None
        try:
            return [UUID(u) for u in json.loads(value)]
        except (json.JSONDecodeError, ValueError):
            return None

    return DecisionReplayView(
        id=record.id,
        decision_type=record.decision_type,
        match_id=record.match_id,
        player_id=record.player_id,
        decision_at=record.decision_at,
        decision_maker=record.decision_maker,
        ai_recommendation_text=record.ai_recommendation_text,
        ai_model=record.ai_model,
        ai_model_version=record.ai_model_version,
        ai_recommendation_at=record.ai_recommendation_at,
        ai_request_id=record.ai_request_id,
        ai_grounded=record.ai_grounded,
        ai_cited_evidence_ids=parse_uuid_list(record.ai_cited_evidence_ids),
        human_decision=HumanDecision(record.human_decision)
        if record.human_decision
        else None,
        human_decision_at=record.human_decision_at,
        rationale=record.rationale,
        evidence_ids=parse_uuid_list(record.evidence_ids),
        outcome_evidence_ids=parse_uuid_list(record.outcome_evidence_ids),
        outcome_refs=record.outcome_refs,
        created_by=record.created_by,
        created_at=record.created_at,
    )


async def create_decision_replay(
    session: AsyncSession, actor: User, payload: DecisionReplayCreate
) -> DecisionReplayView:
    """Create an immutable decision replay record.

    Validates chronology and references. Actor becomes created_by.
    """
    # Validate referenced entities exist
    if payload.match_id is not None:
        match_obj = await matches.get_match(session, payload.match_id)
        if match_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Match not found"
            )
    if payload.player_id is not None:
        player_obj = await users.get_by_id(session, payload.player_id)
        if player_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Player not found"
            )
    if payload.decision_maker is not None:
        maker = await users.get_by_id(session, payload.decision_maker)
        if maker is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Decision maker not found"
            )
        if not maker.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Decision maker is not active",
            )

    # Convert list[UUID] to JSON string for storage
    import json

    def uuids_to_json(uuids: list[UUID] | None) -> str | None:
        if uuids is None:
            return None
        return json.dumps([str(u) for u in uuids])

    fields = {
        "decision_type": payload.decision_type,
        "match_id": payload.match_id,
        "player_id": payload.player_id,
        "decision_at": payload.decision_at,
        "decision_maker": payload.decision_maker,
        "ai_recommendation_text": payload.ai_recommendation_text,
        "ai_model": payload.ai_model,
        "ai_model_version": payload.ai_model_version,
        "ai_recommendation_at": payload.ai_recommendation_at,
        "ai_request_id": payload.ai_request_id,
        "ai_grounded": payload.ai_grounded,
        "ai_cited_evidence_ids": uuids_to_json(payload.ai_cited_evidence_ids),
        "human_decision": payload.human_decision.value
        if payload.human_decision
        else None,
        "human_decision_at": payload.human_decision_at,
        "rationale": payload.rationale,
        "evidence_ids": uuids_to_json(payload.evidence_ids),
        "outcome_evidence_ids": uuids_to_json(payload.outcome_evidence_ids),
        "outcome_refs": payload.outcome_refs,
        "created_by": actor.id,
    }
    try:
        record = await memory.add_decision_replay(session, fields)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Decision replay conflicts with existing records",
        ) from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Decision replay could not be saved",
        ) from exc
    return await _replay_to_view(record)


async def get_decision_replay_view(
    session: AsyncSession, replay_id: UUID
) -> DecisionReplayView:
    record = await memory.get_decision_replay(session, replay_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Decision replay not found"
        )
    return await _replay_to_view(record)


async def list_decision_replay_views(
    session: AsyncSession,
    *,
    decision_type: DecisionType | None = None,
    match_id: UUID | None = None,
    player_id: UUID | None = None,
    decision_from: datetime | None = None,
    decision_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[DecisionReplayView]:
    records = await memory.list_decision_replays(
        session,
        decision_type=decision_type,
        match_id=match_id,
        player_id=player_id,
        decision_from=decision_from,
        decision_to=decision_to,
        limit=limit,
        offset=offset,
    )
    return [await _replay_to_view(record) for record in records]


async def reconstruct_decision_replay(
    session: AsyncSession, actor: User, replay_id: UUID
) -> DecisionReplay:
    """Reconstruct a complete decision replay from the stored record.

    Hydrates evidence through authorized services, builds a chronological
    timeline, and separates decision-time evidence from outcome evidence.
    """
    record = await memory.get_decision_replay(session, replay_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Decision replay not found"
        )

    warnings: list[str] = []

    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    decision_time = _as_utc(record.decision_at)

    def _evidence_description(prefix: str, item: "ReplayEvidenceItem") -> str:
        label = f"{prefix}: {item.evidence_type} from {item.source_type}"
        if item.timestamp_seconds is not None:
            return f"{label} (video {item.timestamp_seconds:.1f}s)"
        return f"{label} (no video timestamp; ordered by record time)"

    # Parse stored JSON UUID lists. Invalid stored references warn instead
    # of silently disappearing.
    def parse_uuid_list(label: str, value: str | None) -> list[UUID]:
        parsed = _parse_reference_ids(value)
        if parsed is None:
            warnings.append(f"Stored {label} references could not be parsed")
            return []
        return parsed

    evidence_ids = parse_uuid_list("evidence", record.evidence_ids)
    outcome_evidence_ids = parse_uuid_list(
        "outcome evidence", record.outcome_evidence_ids
    )
    ai_cited_ids = parse_uuid_list("AI cited evidence", record.ai_cited_evidence_ids)

    def classify(observed: datetime) -> TemporalRelation:
        moment = _as_utc(observed)
        if moment < decision_time:
            return TemporalRelation.BEFORE_DECISION
        if moment > decision_time:
            return TemporalRelation.AFTER_DECISION
        return TemporalRelation.AT_DECISION

    # Hydrate all referenced evidence through authorized services
    all_evidence_ids = list(
        dict.fromkeys(evidence_ids + outcome_evidence_ids + ai_cited_ids)
    )
    evidence_items: list[ReplayEvidenceItem] = []
    inaccessible_count = 0
    withheld_outcomes = 0

    for ev_id in all_evidence_ids:
        ev = await memory.get_evidence(session, ev_id)
        if ev is None:
            warnings.append(f"Evidence reference {ev_id} not found")
            continue
        # Temporal truth wins over stored linking: a post-decision record is
        # never presented as decision-time context, and a pre-decision record
        # is never presented as an outcome. Contradictions warn loudly.
        relation = classify(ev.created_at)
        linked_decision_time = ev_id in evidence_ids
        linked_outcome = ev_id in outcome_evidence_ids
        is_decision_time = (
            linked_decision_time and relation != TemporalRelation.AFTER_DECISION
        )
        is_outcome = linked_outcome and relation == TemporalRelation.AFTER_DECISION
        if linked_decision_time and relation == TemporalRelation.AFTER_DECISION:
            warnings.append(
                f"Evidence {ev_id} is referenced as decision-time evidence "
                "but its record was created after the decision time"
            )
        if linked_outcome and relation != TemporalRelation.AFTER_DECISION:
            warnings.append(
                f"Outcome evidence {ev_id} has no recorded time after the decision time"
            )
        # Evidence inherits its parent memory's governance decision
        # (fail closed when the parent cannot be resolved). Denied/redacted/
        # expired records keep their identity (IDs) but never expose content;
        # the reason is not disclosed here.
        memory_record = None
        if ev.memory_record_id:
            memory_record = await memory.get_memory(session, ev.memory_record_id)
        allowed = memory_record is not None and can_retrieve(actor, memory_record)
        if not allowed:
            inaccessible_count += 1
            if is_outcome:
                withheld_outcomes += 1
        evidence_items.append(
            ReplayEvidenceItem(
                evidence_id=ev.id,
                source_type=ev.source_type.value,
                source_id=ev.source_id,
                evidence_type=ev.evidence_type.value,
                excerpt=ev.excerpt if allowed else None,
                match_id=ev.match_id,
                video_id=ev.video_id,
                frame_number=ev.frame_number,
                timestamp_seconds=ev.timestamp_seconds,
                created_at=ev.created_at,
                governance_status="allowed" if allowed else "inaccessible",
                temporal_relation=relation,
                provenance=ev.provenance if allowed else None,
                is_decision_time_evidence=is_decision_time,
                is_outcome_evidence=is_outcome,
            )
        )

    if inaccessible_count:
        warnings.append(f"{inaccessible_count} evidence item(s) were unavailable")
    if withheld_outcomes:
        warnings.append(
            f"{withheld_outcomes} linked outcome reference(s) were withheld"
        )

    # Build timeline items
    timeline: list[ReplayTimelineItem] = []

    # Decision-time evidence (only records that existed by the decision)
    for ev in evidence_items:
        if ev.is_decision_time_evidence and not ev.is_outcome_evidence:
            ts_dt = _as_utc(ev.created_at)
            timeline.append(
                ReplayTimelineItem(
                    timestamp=ts_dt,
                    phase=ReplayTimelinePhase.EVIDENCE,
                    description=_evidence_description("Decision-time evidence", ev),
                    source_type=ev.source_type,
                    source_id=ev.source_id,
                    evidence_id=ev.evidence_id,
                    is_decision_time_evidence=True,
                    is_outcome_evidence=False,
                )
            )

    # AI recommendation (kept separate from the human decision)
    if record.ai_recommendation_text or record.ai_recommendation_at:
        if record.ai_recommendation_at is None:
            warnings.append(
                "AI recommendation timestamp missing; decision time used for ordering"
            )
            ts = decision_time
        else:
            ts = _as_utc(record.ai_recommendation_at)
        grounded_note = ""
        if record.ai_grounded is not None:
            grounded_note = " (grounded)" if record.ai_grounded else " (ungrounded)"
        timeline.append(
            ReplayTimelineItem(
                timestamp=ts,
                phase=ReplayTimelinePhase.AI_RECOMMENDATION,
                description=(
                    f"AI recommendation: {record.ai_model or 'unknown model'}"
                    f"{grounded_note}"
                ),
                source_type="AI",
                source_id=record.ai_model or "unknown",
                evidence_id=None,
                is_decision_time_evidence=True,
                is_outcome_evidence=False,
            )
        )

    # Human decision (the human act, never merged with the AI output)
    if record.human_decision or record.human_decision_at:
        if record.human_decision_at is None:
            warnings.append(
                "Human decision timestamp missing; decision time used for ordering"
            )
            ts = decision_time
        else:
            ts = _as_utc(record.human_decision_at)
        timeline.append(
            ReplayTimelineItem(
                timestamp=ts,
                phase=ReplayTimelinePhase.HUMAN_DECISION,
                description=f"Human decision: {record.human_decision}"
                + (f" — {record.rationale}" if record.rationale else ""),
                source_type="HUMAN",
                source_id=str(record.decision_maker)
                if record.decision_maker
                else "unknown",
                evidence_id=None,
                is_decision_time_evidence=True,
                is_outcome_evidence=False,
            )
        )

    # Outcome evidence (observed after the decision; descriptive only).
    # Fully withheld when governance denies the underlying evidence.
    for ev in evidence_items:
        if ev.is_outcome_evidence and ev.governance_status == "allowed":
            ts_dt = _as_utc(ev.created_at)
            timeline.append(
                ReplayTimelineItem(
                    timestamp=ts_dt,
                    phase=ReplayTimelinePhase.OUTCOME,
                    description=_evidence_description("Outcome evidence", ev),
                    source_type=ev.source_type,
                    source_id=ev.source_id,
                    evidence_id=ev.evidence_id,
                    is_decision_time_evidence=False,
                    is_outcome_evidence=True,
                )
            )

    # Sort timeline deterministically
    timeline.sort(key=lambda x: (x.timestamp, x.phase.value, str(x.evidence_id or "")))

    # Build outcome references (descriptive only — no success/failure
    # labels). Unauthorized outcomes are withheld entirely; authorized ones
    # carry their temporal classification and provenance.
    outcome_refs: list[ReplayOutcomeReference] = []
    for ev in evidence_items:
        if ev.is_outcome_evidence and ev.governance_status == "allowed":
            outcome_refs.append(
                ReplayOutcomeReference(
                    evidence_id=ev.evidence_id,
                    source_type=ev.source_type,
                    source_id=ev.source_id,
                    timestamp=_as_utc(ev.created_at),
                    description=_evidence_description("Outcome", ev),
                    temporal_relation=ev.temporal_relation,
                    provenance=ev.provenance,
                )
            )
    outcome_refs.sort(key=lambda ref: (ref.timestamp, str(ref.evidence_id)))

    # Build AI recommendation object
    ai_rec = None
    if record.ai_recommendation_text or record.ai_recommendation_at:
        ai_rec = ReplayAIRecommendation(
            text=record.ai_recommendation_text,
            model=record.ai_model,
            model_version=record.ai_model_version,
            timestamp=_as_utc(record.ai_recommendation_at)
            if record.ai_recommendation_at
            else None,
            request_id=record.ai_request_id,
            grounded=record.ai_grounded,
            cited_evidence_ids=ai_cited_ids,
        )

    # Build human decision object
    human_dec = None
    if record.human_decision or record.human_decision_at:
        human_dec = ReplayHumanDecision(
            decision=HumanDecision(record.human_decision)
            if record.human_decision
            else None,
            timestamp=_as_utc(record.human_decision_at)
            if record.human_decision_at
            else None,
            rationale=record.rationale,
            decision_maker=record.decision_maker,
        )

    # Build provenance
    provenance = {
        "replay_id": str(record.id),
        "created_by": str(record.created_by),
        "created_at": _as_utc(record.created_at).isoformat(),
        "source": "decision_replays",
    }

    return DecisionReplay(
        decision_id=record.id,
        decision_type=record.decision_type,
        decision_status=None,  # No status is tracked on replay records
        decision_time=decision_time,
        decision_maker=record.decision_maker,
        match_id=record.match_id,
        player_id=record.player_id,
        ai_recommendation=ai_rec,
        human_decision=human_dec,
        timeline=timeline,
        evidence=evidence_items,
        outcome_references=outcome_refs,
        provenance=provenance,
        warnings=warnings,
    )


_HUMAN_DECISION_RELATIONS: dict[HumanDecision, RecommendationRelation] = {
    HumanDecision.ACCEPTED: RecommendationRelation.RECOMMENDATION_ACCEPTED,
    HumanDecision.REJECTED: RecommendationRelation.RECOMMENDATION_REJECTED,
    HumanDecision.MODIFIED: RecommendationRelation.RECOMMENDATION_MODIFIED,
    HumanDecision.DEFERRED: RecommendationRelation.RECOMMENDATION_DEFERRED,
    HumanDecision.NO_ACTION: RecommendationRelation.RECOMMENDATION_NO_ACTION,
}


def _recommendation_relation(
    ai: ReplayAIRecommendation | None,
    human: ReplayHumanDecision | None,
) -> RecommendationRelation:
    """Factual relationship between AI recommendation and human decision.

    Presence and recorded-enum mapping only — mirrors what the record
    says the human did with the recommendation; it never evaluates
    whether either the human act or the AI output was right or wrong.
    """
    if ai is None:
        return RecommendationRelation.NO_RECOMMENDATION_RECORDED
    if human is None or human.decision is None:
        return RecommendationRelation.NO_HUMAN_DECISION_RECORDED
    return _HUMAN_DECISION_RELATIONS[human.decision]


async def evaluate_decision_replay(
    session: AsyncSession, actor: User, replay_id: UUID
) -> DecisionReplayEvaluation:
    """Deterministic, evidence-based evaluation of a decision replay.

    Derives structured factual observations from the governed
    reconstruction: what evidence existed at decision time, what the
    human did relative to the AI recommendation, and what outcome
    evidence was observed later. Decision Replay describes what
    happened — it never decides whether the decision was good or bad.

    Guarantees:
    - read-only: the stored replay record is never modified;
    - governance: only evidence this actor may retrieve can influence
      any observation; unavailable items are counted without exposing
      their contents or the reason for restriction;
    - temporal integrity: post-decision evidence never enters the
      decision-time evidence set;
    - determinism: no wall-clock values and stable ordering
      (timestamp → evidence ID), so repeated evaluation is equivalent;
    - no LLM, no causal inference, no fabricated confidence.
    """
    recon = await reconstruct_decision_replay(session, actor, replay_id)
    record = await memory.get_decision_replay(session, replay_id)
    if record is None:  # defensive: replay removed between reads
        raise _not_found("Decision replay not found")

    warnings = list(recon.warnings)

    def _stored_ids(value: str | None) -> list[UUID]:
        # A malformed stored list already surfaced a controlled warning
        # during reconstruction; here it simply contributes no links.
        parsed = _parse_reference_ids(value)
        return parsed if parsed is not None else []

    stored_ids = (
        _stored_ids(record.evidence_ids)
        + _stored_ids(record.outcome_evidence_ids)
        + _stored_ids(record.ai_cited_evidence_ids)
    )
    stored_outcome_ids = set(_stored_ids(record.outcome_evidence_ids))

    by_id = {ev.evidence_id: ev for ev in recon.evidence}
    missing_ids = sorted({sid for sid in stored_ids if sid not in by_id}, key=str)

    # A linked outcome whose record time is not after the decision makes
    # the stored record temporally self-contradictory — a factual
    # conflict observation, never a judgment about the decision itself.
    conflicted_ids = sorted(
        (
            sid
            for sid in stored_outcome_ids
            if sid in by_id
            and by_id[sid].temporal_relation != TemporalRelation.AFTER_DECISION
        ),
        key=str,
    )

    accessible = [ev for ev in recon.evidence if ev.governance_status == "allowed"]
    withheld_count = len(recon.evidence) - len(accessible)

    decision_time_evidence = sorted(
        (ev for ev in accessible if ev.is_decision_time_evidence),
        key=lambda ev: (ev.created_at, str(ev.evidence_id)),
    )
    # Already governance-filtered and deterministically sorted
    # (timestamp → evidence ID) by the reconstruction.
    outcome_refs = list(recon.outcome_references)

    human_decision = recon.human_decision
    human_missing = human_decision is None or human_decision.decision is None

    if conflicted_ids:
        eval_status = EvaluationStatus.CONFLICTING_EVIDENCE
    elif withheld_count or missing_ids or human_missing:
        eval_status = EvaluationStatus.PARTIALLY_EVALUABLE
    elif not decision_time_evidence and not outcome_refs:
        eval_status = EvaluationStatus.INSUFFICIENT_EVIDENCE
    else:
        eval_status = EvaluationStatus.EVALUABLE

    observations: list[EvaluationObservation] = []

    def _observe(
        code: EvaluationObservationCode, detail: str, ids: list[UUID] | None = None
    ) -> None:
        observations.append(
            EvaluationObservation(
                code=code,
                detail=detail,
                evidence_ids=sorted(ids or [], key=str),
            )
        )

    if decision_time_evidence:
        _observe(
            EvaluationObservationCode.DECISION_TIME_EVIDENCE_PRESENT,
            f"{len(decision_time_evidence)} evidence item(s) available at "
            "decision time",
            [ev.evidence_id for ev in decision_time_evidence],
        )
    else:
        _observe(
            EvaluationObservationCode.DECISION_TIME_EVIDENCE_ABSENT,
            "No evidence was available at decision time",
        )

    if outcome_refs:
        _observe(
            EvaluationObservationCode.OUTCOME_EVIDENCE_PRESENT,
            f"{len(outcome_refs)} linked outcome item(s) recorded after the decision",
            [ref.evidence_id for ref in outcome_refs],
        )
    else:
        _observe(
            EvaluationObservationCode.OUTCOME_EVIDENCE_ABSENT,
            "No outcome evidence is linked to this decision",
        )

    if conflicted_ids:
        _observe(
            EvaluationObservationCode.CONFLICTING_OUTCOME_EVIDENCE,
            "Linked outcome item(s) are not recorded after the decision",
            conflicted_ids,
        )
    if withheld_count:
        _observe(
            EvaluationObservationCode.LINKED_EVIDENCE_UNAVAILABLE,
            f"{withheld_count} linked evidence item(s) are unavailable to this user",
        )
    if missing_ids:
        _observe(
            EvaluationObservationCode.MISSING_LINKED_REFERENCE,
            f"{len(missing_ids)} stored evidence reference(s) could not be resolved",
            missing_ids,
        )
    if not decision_time_evidence and not outcome_refs:
        _observe(
            EvaluationObservationCode.NO_USABLE_EVIDENCE,
            "No decision-time or outcome evidence is available for evaluation",
        )

    return DecisionReplayEvaluation(
        decision_id=recon.decision_id,
        decision_type=recon.decision_type,
        decision_time=recon.decision_time,
        decision_maker=recon.decision_maker,
        status=eval_status,
        recommendation_relation=_recommendation_relation(
            recon.ai_recommendation, human_decision
        ),
        ai_recommendation=recon.ai_recommendation,
        human_decision=human_decision,
        decision_time_evidence=decision_time_evidence,
        outcome_references=outcome_refs,
        observations=observations,
        metadata=EvaluationMetadata(),
        provenance=dict(recon.provenance),
        warnings=warnings,
    )
