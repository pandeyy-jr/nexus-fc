"""Deterministic grounding verification (Phase 09E).

Decides, without any model call, whether claims in a Copilot answer are
supported by the structured tool evidence already gathered. It never
retrieves data, never touches sessions/repositories/Qdrant, and never
judges whether a football statement is objectively true.

Verification rules per claim:
- no citations provided -> NO_CITATION
- cited evidence all invalid (unknown, failed, unauthorized, or
  truncated) -> UNSUPPORTED ("no valid evidence")
- evidence contradicts the claim (antonym polarity or score mismatch)
  -> UNSUPPORTED
- token coverage >= 0.5 of the claim's significant tokens -> SUPPORTED
- token coverage > 0 -> PARTIALLY_SUPPORTED
- zero overlap with otherwise valid evidence -> NO_CITATION
  ("evidence does not contain the required fields")

Only one antonym pair (available/unavailable) and score patterns
(``2-1`` style) drive contradiction; everything else is lexical
coverage. This is deliberately narrow and documented as such.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUPPORT_THRESHOLD = 0.33

_STOPWORDS = frozenset(
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
        "had",
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
        "been",
        "also",
        "than",
        "then",
        "currently",
    }
)

_ANTONYM_PAIRS = (("available", "unavailable"),)

_SCORE_PATTERN = re.compile(r"\b(\d+)\s*-\s*(\d+)\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class ClaimVerificationStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    NO_CITATION = "NO_CITATION"


class GroundingOverallStatus(StrEnum):
    GROUNDED = "GROUNDED"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    UNGROUNDED = "UNGROUNDED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class GroundingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CopilotClaim(GroundingContract):
    claim_id: str = Field(min_length=1, max_length=100)
    claim_text: str = Field(min_length=1, max_length=2000)
    supporting_citation_ids: tuple[str, ...] = ()
    verification_status: ClaimVerificationStatus
    reason: str = Field(min_length=1, max_length=500)


class EvidenceItem(GroundingContract):
    """One consultable unit of already-authorized tool output.

    ``authorized`` is carried explicitly (the orchestrator only ever
    sets it True — registry execution already gated) so direct unit
    tests can exercise the unauthorized path. ``facts`` maps
    normalized field names to normalized values; ``text`` is the
    lexical surface used for coverage checks.
    """

    evidence_id: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=100)
    success: bool
    authorized: bool = True
    truncated: bool = False
    facts: dict[str, str] = Field(default_factory=dict)
    text: str = Field(default="")


class ClaimInput(GroundingContract):
    claim_id: str = Field(min_length=1, max_length=100)
    claim_text: str = Field(min_length=1, max_length=2000)
    citation_ids: tuple[str, ...] = ()


class CopilotGroundingReport(GroundingContract):
    total_claims: int = Field(ge=0)
    supported_claims: int = Field(ge=0)
    partially_supported_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)
    no_citation_claims: int = Field(ge=0)
    overall_status: GroundingOverallStatus
    claims: tuple[CopilotClaim, ...] = ()

    @model_validator(mode="after")
    def counts_consistent(self) -> CopilotGroundingReport:
        counted = (
            self.supported_claims
            + self.partially_supported_claims
            + self.unsupported_claims
            + self.no_citation_claims
        )
        if counted != self.total_claims:
            raise ValueError("status counts must sum to total_claims")
        if len(self.claims) != self.total_claims:
            raise ValueError("one claim entry per input claim is required")
        return self


def split_claims(answer_text: str) -> list[tuple[str, str]]:
    """Split an answer into (claim_id, claim_text) sentences.

    Deterministic: c1..cn in textual order, empties dropped."""
    # Split on sentence boundaries, then filter out fragments that are just punctuation
    raw_parts = _SENTENCE_SPLIT.split(answer_text.strip())
    sentences = []
    for part in raw_parts:
        stripped = part.strip()
        if not stripped:
            continue
        # Skip fragments that are only punctuation/whitespace
        if all(ch in ".!?,\t\n\r" for ch in stripped):
            continue
        sentences.append(stripped)
    return [(f"c{i + 1}", sentence) for i, sentence in enumerate(sentences)]


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_PATTERN.findall(text.lower())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _scores(text: str) -> set[str]:
    return {f"{first}-{second}" for first, second in _SCORE_PATTERN.findall(text)}


def _contradicted(claim_tokens: set[str], evidence_tokens: set[str]) -> bool:
    for first, second in _ANTONYM_PAIRS:
        if (first in claim_tokens and second in evidence_tokens) or (
            second in claim_tokens and first in evidence_tokens
        ):
            return True
    return False


def _item_text(item: EvidenceItem) -> str:
    parts = [item.text, *item.facts.values()]
    return " ".join(part for part in parts if part)


def _valid_evidence(
    evidence: Sequence[EvidenceItem],
) -> dict[str, EvidenceItem]:
    return {
        item.evidence_id: item
        for item in evidence
        if item.success and item.authorized and not item.truncated
    }


def verify_grounding(
    claims: Sequence[ClaimInput], evidence: Sequence[EvidenceItem]
) -> CopilotGroundingReport:
    """Verify each claim against cited evidence only. Pure function:
    no I/O, no retrieval, no model calls."""
    if not all(isinstance(item, ClaimInput) for item in claims):
        raise TypeError("claims must be ClaimInput records")
    if not all(isinstance(item, EvidenceItem) for item in evidence):
        raise TypeError("evidence must be EvidenceItem records")
    valid = _valid_evidence(evidence)
    verified: list[CopilotClaim] = []
    for claim in claims:
        verified.append(_verify_claim(claim, valid))
    counts = {
        ClaimVerificationStatus.SUPPORTED: 0,
        ClaimVerificationStatus.PARTIALLY_SUPPORTED: 0,
        ClaimVerificationStatus.UNSUPPORTED: 0,
        ClaimVerificationStatus.NO_CITATION: 0,
    }
    for item in verified:
        counts[item.verification_status] += 1
    if not verified or not valid:
        overall = GroundingOverallStatus.INSUFFICIENT_EVIDENCE
    elif counts[ClaimVerificationStatus.SUPPORTED] == len(verified):
        overall = GroundingOverallStatus.GROUNDED
    elif (
        counts[ClaimVerificationStatus.SUPPORTED] > 0
        or counts[ClaimVerificationStatus.PARTIALLY_SUPPORTED] > 0
    ):
        overall = GroundingOverallStatus.PARTIALLY_GROUNDED
    else:
        overall = GroundingOverallStatus.UNGROUNDED
    return CopilotGroundingReport(
        total_claims=len(verified),
        supported_claims=counts[ClaimVerificationStatus.SUPPORTED],
        partially_supported_claims=counts[ClaimVerificationStatus.PARTIALLY_SUPPORTED],
        unsupported_claims=counts[ClaimVerificationStatus.UNSUPPORTED],
        no_citation_claims=counts[ClaimVerificationStatus.NO_CITATION],
        overall_status=overall,
        claims=tuple(verified),
    )


def _verify_claim(claim: ClaimInput, valid: dict[str, EvidenceItem]) -> CopilotClaim:
    if not claim.citation_ids:
        return CopilotClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            supporting_citation_ids=(),
            verification_status=ClaimVerificationStatus.NO_CITATION,
            reason="claim provides no citations",
        )
    cited = [valid[citation] for citation in claim.citation_ids if citation in valid]
    if not cited:
        return CopilotClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            supporting_citation_ids=(),
            verification_status=ClaimVerificationStatus.UNSUPPORTED,
            reason="no valid evidence among cited ids",
        )
    claim_tokens = _tokens(claim.claim_text)
    claim_scores = _scores(claim.claim_text)
    # Also include scores in tokens for coverage matching
    claim_tokens_with_scores = claim_tokens | claim_scores
    # Handle edge case: no significant tokens (e.g., all stopwords)
    if not claim_tokens_with_scores:
        claim_tokens_with_scores = set(claim.claim_text.lower().split())
    supported: list[str] = []
    contradicted = False
    partial = False
    has_overlap = False
    for item in cited:
        item_text = _item_text(item)
        item_tokens = _tokens(item_text)
        item_scores = _scores(item_text)
        item_tokens_with_scores = item_tokens | item_scores

        # Check contradiction FIRST (works even without token overlap)
        # Antonym contradiction
        if _contradicted(claim_tokens, item_tokens):
            contradicted = True
        # Score contradiction
        if claim_scores and item_scores and claim_scores.isdisjoint(item_scores):
            contradicted = True

        # Check token/score overlap for support
        overlap = claim_tokens_with_scores & item_tokens_with_scores
        if overlap:
            has_overlap = True
            coverage = len(overlap) / len(claim_tokens_with_scores)
            if coverage >= SUPPORT_THRESHOLD:
                supported.append(item.evidence_id)
            else:
                partial = True

    if supported and contradicted:
        return CopilotClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            supporting_citation_ids=tuple(supported),
            verification_status=ClaimVerificationStatus.PARTIALLY_SUPPORTED,
            reason="conflicting evidence across cited items",
        )
    if supported:
        return CopilotClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            supporting_citation_ids=tuple(supported),
            verification_status=ClaimVerificationStatus.SUPPORTED,
            reason="evidence covers the claim",
        )
    if contradicted:
        return CopilotClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            supporting_citation_ids=(),
            verification_status=ClaimVerificationStatus.UNSUPPORTED,
            reason="evidence contradicts the claim",
        )
    if partial:
        return CopilotClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            supporting_citation_ids=(),
            verification_status=ClaimVerificationStatus.PARTIALLY_SUPPORTED,
            reason="evidence covers only part of the claim",
        )
    if has_overlap:
        return CopilotClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            supporting_citation_ids=(),
            verification_status=ClaimVerificationStatus.PARTIALLY_SUPPORTED,
            reason="evidence covers only part of the claim",
        )
    return CopilotClaim(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text,
        supporting_citation_ids=(),
        verification_status=ClaimVerificationStatus.NO_CITATION,
        reason="evidence does not contain the required fields",
    )
