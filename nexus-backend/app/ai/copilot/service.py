"""Copilot orchestration service (Phase 09C).

Server-side loop: question → provider turn → validated tool calls →
existing ToolRegistry → transcript → ... → structured CopilotResponse.

Hard safety properties:
- Budgets (tool calls, iterations, sizes) are server constants the
  model and request can never raise.
- Actor identity, roles, and governance live server-side only.
- Tool output is untrusted DATA: evidence, never authority. Text that
  looks like instructions inside tool results is never executed.
- Failures become structured error codes; never stack traces, secrets,
  prompts, or SQL internals.
"""

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.copilot.grounding import (
    ClaimInput,
    CopilotGroundingReport,
    EvidenceItem,
    split_claims,
    verify_grounding,
)
from app.ai.copilot.models import (
    CopilotCitation,
    CopilotProviderResponse,
    CopilotRequest,
    CopilotResponse,
    CopilotToolCall,
    CopilotToolResult,
)
from app.ai.copilot.provider import (
    ModelProvider,
    ModelProviderError,
    ModelProviderTimeout,
    ModelProviderUnavailable,
)
from app.ai.copilot.registry import ToolExecutionContext, ToolRegistry
from app.db.models.user import User

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 5
MAX_ITERATIONS = 6
MAX_TOOL_RESULT_CHARS = 8000
MAX_CONTEXT_CHARS = 24000

_ERROR_BUDGET_EXHAUSTED = "TOOL_BUDGET_EXHAUSTED"
_ERROR_CONTEXT_BUDGET_EXHAUSTED = "CONTEXT_BUDGET_EXHAUSTED"
_ERROR_ITERATION_LIMIT = "ITERATION_LIMIT_EXHAUSTED"
_ERROR_PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
_ERROR_PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
_ERROR_PROVIDER_FAILED = "PROVIDER_FAILED"
_ERROR_MALFORMED_RESPONSE = "MALFORMED_PROVIDER_RESPONSE"
_ERROR_EMPTY_ANSWER = "EMPTY_FINAL_ANSWER"


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _citation_extractors() -> dict[
    str, Callable[[Mapping[str, Any]], list[CopilotCitation]]
]:
    """Per-tool evidence mapping. Unknown tool shapes yield no
    citations rather than guessed ones."""

    def memories(data: Mapping[str, Any]) -> list[CopilotCitation]:
        citations: list[CopilotCitation] = []
        results = data.get("results")
        if not isinstance(results, list):
            return citations
        for item in results:
            if not isinstance(item, Mapping):
                continue
            memory = item.get("memory")
            if not isinstance(memory, Mapping) or "id" not in memory:
                continue
            evidence = memory.get("evidence") or []
            evidence_ids = [
                str(entry["id"])
                for entry in evidence
                if isinstance(entry, Mapping) and "id" in entry
            ]
            first = next(
                (entry for entry in evidence if isinstance(entry, Mapping)), {}
            )
            citations.append(
                CopilotCitation(
                    source_type="memory",
                    source_id=str(memory["id"]),
                    evidence_ids=evidence_ids,
                    occurred_at=memory.get("occurred_at"),
                    match_id=_optional_str(first.get("match_id")),
                    video_id=_optional_str(first.get("video_id")),
                    frame_number=first.get("frame_number"),
                    timestamp_seconds=first.get("timestamp_seconds"),
                )
            )
        return citations

    def single(
        source_type: str,
    ) -> Callable[[Mapping[str, Any]], list[CopilotCitation]]:
        def extract(data: Mapping[str, Any]) -> list[CopilotCitation]:
            identifier = data.get("id")
            if identifier is None:
                return []
            return [CopilotCitation(source_type=source_type, source_id=str(identifier))]

        return extract

    def children(
        data: Mapping[str, Any], key: str, source_type: str
    ) -> list[CopilotCitation]:
        citations: list[CopilotCitation] = []
        entries = data.get(key)
        if not isinstance(entries, list):
            return citations
        for entry in entries:
            if isinstance(entry, Mapping) and entry.get("id") is not None:
                citations.append(
                    CopilotCitation(source_type=source_type, source_id=str(entry["id"]))
                )
        return citations

    return {
        "search_club_memory": memories,
        "get_player_status": single("player"),
        "get_match_summary": single("match"),
        "get_player_match_history": lambda data: children(data, "matches", "match"),
        "get_training_summary": lambda data: children(
            data, "entries", "training_session"
        ),
        "get_player_availability": lambda data: children(
            data, "records", "availability"
        ),
    }


class CopilotService:
    """Bounded, governed question-answering loop over registered tools."""

    def __init__(
        self,
        registry: ToolRegistry,
        provider: ModelProvider,
        *,
        max_tool_calls: int = MAX_TOOL_CALLS,
        max_iterations: int = MAX_ITERATIONS,
        max_tool_result_chars: int = MAX_TOOL_RESULT_CHARS,
        max_context_chars: int = MAX_CONTEXT_CHARS,
    ) -> None:
        for label, value, ceiling in (
            ("max_tool_calls", max_tool_calls, MAX_TOOL_CALLS),
            ("max_iterations", max_iterations, MAX_ITERATIONS),
            ("max_tool_result_chars", max_tool_result_chars, MAX_TOOL_RESULT_CHARS),
            ("max_context_chars", max_context_chars, MAX_CONTEXT_CHARS),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{label} must be an integer")
            if value < 1 or value > ceiling:
                raise ValueError(f"{label} must be within 1..{ceiling}")
        self._registry = registry
        self._provider = provider
        self._max_tool_calls = max_tool_calls
        self._max_iterations = max_iterations
        self._max_tool_result_chars = max_tool_result_chars
        self._max_context_chars = max_context_chars
        self._extractors = _citation_extractors()

    async def ask(
        self, session: AsyncSession, actor: User, request: CopilotRequest
    ) -> CopilotResponse:
        request_id = uuid4()
        question = request.question.strip()
        base: dict[str, Any] = {
            "tools_used": [],
            "tool_call_count": 0,
            "citations": [],
            "warnings": [],
            "seen": set(),
            "transcript": [],
            "context_chars": 0,
        }
        if not question:
            return self._finish(
                request_id,
                "",
                False,
                [],
                [],
                0,
                ["Empty question cannot be answered."],
                "EMPTY_QUESTION",
                None,
            )
        context = ToolExecutionContext(
            actor=actor, session=session, request_id=request_id
        )
        visible = self._registry.list_for_actor(actor)
        transcript: list[CopilotToolResult] = base["transcript"]

        for _ in range(self._max_iterations):
            turn = await self._provider_turn(question, visible, transcript)
            if turn["failure"] is not None:
                return self._finish(
                    request_id,
                    "",
                    False,
                    base["citations"],
                    base["tools_used"],
                    base["tool_call_count"],
                    base["warnings"],
                    turn["failure"],
                    None,
                )
            response = turn["response"]
            assert response is not None
            if response.final_answer is not None:
                return self._finish_answer(request_id, response.final_answer, base)
            outcome = await self._run_calls(
                response.tool_calls, context, base, transcript
            )
            if outcome is not None:
                return outcome

        base["warnings"].append(
            "Analysis could not be completed within the safety/tool budget."
        )
        return self._finish(
            request_id,
            "",
            False,
            base["citations"],
            base["tools_used"],
            base["tool_call_count"],
            base["warnings"],
            _ERROR_ITERATION_LIMIT,
            None,
        )

    # -- provider turns ----------------------------------------------------

    async def _provider_turn(
        self,
        question: str,
        visible: Sequence,
        transcript: list[CopilotToolResult],
    ) -> dict[str, Any]:
        """Return {"response": turn} or {"failure": error_code}."""
        try:
            raw = await self._provider.complete(question, visible, transcript)
        except ModelProviderTimeout:
            return {"response": None, "failure": _ERROR_PROVIDER_TIMEOUT}
        except ModelProviderUnavailable:
            return {"response": None, "failure": _ERROR_PROVIDER_UNAVAILABLE}
        except ModelProviderError:
            return {"response": None, "failure": _ERROR_PROVIDER_FAILED}
        except Exception:
            return {"response": None, "failure": _ERROR_PROVIDER_FAILED}
        try:
            if isinstance(raw, CopilotProviderResponse):
                raw.model_copy()
                validated = raw
            else:
                validated = CopilotProviderResponse.model_validate(raw)
        except Exception:
            return {"response": None, "failure": _ERROR_MALFORMED_RESPONSE}
        return {"response": validated, "failure": None}

    # -- tool-call processing -----------------------------------------------

    async def _run_calls(
        self,
        calls: Sequence[CopilotToolCall],
        context: ToolExecutionContext,
        base: dict[str, Any],
        transcript: list[CopilotToolResult],
    ) -> CopilotResponse | None:
        """Execute one turn's calls. Returns a finished response when the
        loop must stop, else None to continue with the provider."""
        for call in calls:
            key = self._call_key(call)
            if key in base["seen"]:
                base["warnings"].append(f"repeated tool call ignored: {call.tool_name}")
                continue
            base["seen"].add(key)
            if base["tool_call_count"] >= self._max_tool_calls:
                base["warnings"].append(
                    "Analysis could not be completed within the safety/tool budget."
                )
                return self._finish(
                    context.request_id,
                    "",
                    False,
                    base["citations"],
                    base["tools_used"],
                    base["tool_call_count"],
                    base["warnings"],
                    _ERROR_BUDGET_EXHAUSTED,
                    None,
                )
            executed = await self._registry.execute(
                call.tool_name, call.arguments, context
            )
            base["tool_call_count"] += 1
            if call.tool_name not in base["tools_used"]:
                base["tools_used"].append(call.tool_name)
            transcript_entry = self._transcript_result(call, executed, base)
            if transcript_entry is not None:
                transcript.append(transcript_entry)
            if base["context_chars"] > self._max_context_chars:
                base["warnings"].append(
                    "Analysis could not be completed within the safety/tool budget."
                )
                return self._finish(
                    context.request_id,
                    "",
                    False,
                    base["citations"],
                    base["tools_used"],
                    base["tool_call_count"],
                    base["warnings"],
                    _ERROR_CONTEXT_BUDGET_EXHAUSTED,
                    None,
                )
        return None

    def _transcript_result(
        self, call: CopilotToolCall, executed, base: dict[str, Any]
    ) -> CopilotToolResult | None:
        """Build the transcript entry, enforcing the per-result size cap.
        Oversized results are replaced by an explicit truncation marker
        (which yields no citations) rather than truncated mid-structure."""
        if executed.success:
            data = executed.data or {}
            try:
                size = len(json.dumps(data, sort_keys=True, default=str))
            except (TypeError, ValueError):
                size = self._max_tool_result_chars + 1
            if size > self._max_tool_result_chars:
                base["warnings"].append(f"tool result truncated: {call.tool_name}")
                entry = CopilotToolResult(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    success=True,
                    result={"truncated": True, "original_chars": size},
                    error_code=None,
                    error_message=None,
                )
            else:
                entry = CopilotToolResult(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    success=True,
                    result=data,
                    error_code=None,
                    error_message=None,
                )
                extractor = self._extractors.get(call.tool_name)
                if extractor is not None:
                    try:
                        base["citations"].extend(extractor(data))
                    except Exception:
                        base["warnings"].append(
                            f"citation extraction skipped: {call.tool_name}"
                        )
            base["context_chars"] += len(
                json.dumps(entry.model_dump(mode="json"), sort_keys=True, default=str)
            )
            return entry
        entry = CopilotToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            success=False,
            result=None,
            error_code=executed.error.category.value if executed.error else "UNKNOWN",
            error_message=executed.error.message if executed.error else "failed",
        )
        base["context_chars"] += len(
            json.dumps(entry.model_dump(mode="json"), sort_keys=True, default=str)
        )
        return entry

    @staticmethod
    def _call_key(call: CopilotToolCall) -> str:
        try:
            canonical = json.dumps(call.arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            canonical = repr(sorted(call.arguments.items()))
        return f"{call.tool_name}:{canonical}"

    def _build_evidence_items(
        self, transcript: list[CopilotToolResult]
    ) -> list[EvidenceItem]:
        """Convert transcript entries into EvidenceItems for the verifier.

        Only successful, non-truncated entries become valid evidence.
        Failed and truncated entries are included but marked invalid so
        the verifier can reject citations pointing to them.
        """
        evidence: list[EvidenceItem] = []
        for entry in transcript:
            if entry.success:
                data = entry.result or {}
                truncated = data.get("truncated", False) is True
                # Extract structured facts per tool
                facts = self._extract_facts(entry.tool_name, data)
                # Lexical text surface for coverage checks
                text = json.dumps(data, sort_keys=True, default=str)
                evidence.append(
                    EvidenceItem(
                        evidence_id=entry.call_id,
                        tool_name=entry.tool_name,
                        success=True,
                        authorized=True,
                        truncated=truncated,
                        facts=facts,
                        text=text if not truncated else "",
                    )
                )
            else:
                # Failed tool calls: include so citation validation can reject them
                evidence.append(
                    EvidenceItem(
                        evidence_id=entry.call_id,
                        tool_name=entry.tool_name,
                        success=False,
                        authorized=True,
                        truncated=False,
                        facts={},
                        text="",
                    )
                )
        return evidence

    def _extract_facts(self, tool_name: str, data: dict) -> dict[str, str]:
        """Extract normalized field:value facts from tool output data.

        These are used for precise contradiction detection (e.g., status
        fields, scores). Only known, stable fields are extracted.
        """
        facts: dict[str, str] = {}
        if tool_name == "get_player_status":
            status = data.get("status")
            if status is not None:
                facts["status"] = str(status).lower()
            fn = data.get("first_name")
            ln = data.get("last_name")
            if fn and ln:
                facts["player_name"] = f"{fn} {ln}"
            pos = data.get("preferred_position")
            if pos is not None:
                facts["position"] = str(pos).lower()
        elif tool_name == "get_player_availability":
            records = data.get("records") or []
            for rec in records:
                if isinstance(rec, dict):
                    status = rec.get("status")
                    if status is not None:
                        facts["availability_status"] = str(status).lower()
                    reason = rec.get("reason_category")
                    if reason is not None:
                        facts["availability_reason"] = str(reason).lower()
        elif tool_name == "get_match_summary":
            home = data.get("home_score")
            away = data.get("away_score")
            if home is not None and away is not None:
                facts["score"] = f"{home}-{away}"
            status = data.get("status")
            if status is not None:
                facts["match_status"] = str(status).lower()
            opp = data.get("opponent")
            if opp and isinstance(opp, dict):
                name = opp.get("name")
                if name:
                    facts["opponent"] = str(name).lower()
        elif tool_name == "get_player_match_history":
            matches = data.get("matches") or []
            for m in matches:
                if isinstance(m, dict):
                    home = m.get("home_score")
                    away = m.get("away_score")
                    if home is not None and away is not None:
                        facts[f"match_{m.get('id', '')}_score"] = f"{home}-{away}"
        elif tool_name == "get_training_summary":
            entries = data.get("entries") or []
            for e in entries:
                if isinstance(e, dict):
                    attendance = e.get("attendance_status")
                    if attendance is not None:
                        facts["attendance"] = str(attendance).lower()
                    session = e.get("session")
                    if session and isinstance(session, dict):
                        stype = session.get("session_type")
                        if stype:
                            facts["session_type"] = str(stype).lower()
        elif tool_name == "search_club_memory":
            results = data.get("results") or []
            for r in results:
                if isinstance(r, dict):
                    mem = r.get("memory") or {}
                    title = mem.get("title")
                    if title:
                        facts["memory_title"] = str(title).lower()
                    summary = mem.get("summary")
                    if summary:
                        facts["memory_summary"] = str(summary).lower()
        return facts

    # -- finalization --------------------------------------------------------

    def _finish_answer(
        self,
        request_id,
        answer: str,
        base: dict[str, Any],
    ) -> CopilotResponse:
        text = answer.strip()
        if not text:
            return self._finish(
                request_id,
                "",
                False,
                base["citations"],
                base["tools_used"],
                base["tool_call_count"],
                base["warnings"],
                _ERROR_EMPTY_ANSWER,
                None,
            )
        grounded = len(base["citations"]) > 0
        warnings = list(base["warnings"])
        if not grounded:
            warnings = warnings + ["Answer is not grounded in tool evidence."]

        # Build evidence items from successful transcript entries
        evidence = self._build_evidence_items(base["transcript"])
        # Split answer into claims
        claims = [
            ClaimInput(claim_id=cid, claim_text=ctext, citation_ids=())
            for cid, ctext in split_claims(text)
        ]
        # Run deterministic grounding verification
        grounding_report = verify_grounding(claims, evidence)

        # Attach citation IDs to claims for reference in the report
        # (The verifier doesn't use them for lookup since we only pass valid evidence)
        # We keep the report as-is for structured output.

        return self._finish(
            request_id,
            text,
            grounded,
            base["citations"],
            base["tools_used"],
            base["tool_call_count"],
            warnings,
            None,
            grounding_report,
        )

    def _finish(
        self,
        request_id,
        answer: str,
        grounded: bool,
        citations: list[CopilotCitation],
        tools_used: list[str],
        tool_call_count: int,
        warnings: list[str],
        error: str | None,
        grounding_report: CopilotGroundingReport | None = None,
    ) -> CopilotResponse:
        response = CopilotResponse(
            answer=answer,
            grounded=grounded,
            citations=citations,
            tools_used=tools_used,
            tool_call_count=tool_call_count,
            model=self._provider.model_id,
            warnings=warnings,
            error=error,
            request_id=request_id,
            grounding_report=grounding_report,
        )
        logger.info(
            "copilot request completed",
            extra={
                "copilot_model": self._provider.model_id,
                "copilot_tool_calls": tool_call_count,
                "copilot_success": error is None,
                "copilot_error": error or "",
            },
        )
        return response
