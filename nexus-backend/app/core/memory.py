from enum import StrEnum


class MemoryType(StrEnum):
    """Small explicit vocabulary — only types the architecture supports."""

    MATCH = "MATCH"
    TRAINING = "TRAINING"
    PLAYER_DEVELOPMENT = "PLAYER_DEVELOPMENT"
    AVAILABILITY = "AVAILABILITY"
    TACTICAL = "TACTICAL"
    SCOUTING = "SCOUTING"
    DECISION = "DECISION"


class MemorySourceType(StrEnum):
    """Origin of a memory. AI-generated origins must never be rewritten
    as human-authored evidence."""

    HUMAN_RECORDED = "HUMAN_RECORDED"
    MATCH_EVENT = "MATCH_EVENT"
    TRAINING_RECORD = "TRAINING_RECORD"
    VISION = "VISION"
    TACTICAL_ANALYSIS = "TACTICAL_ANALYSIS"
    SYSTEM_GENERATED = "SYSTEM_GENERATED"


class MemoryEvidenceType(StrEnum):
    TEXT_EXCERPT = "TEXT_EXCERPT"
    FRAME_REFERENCE = "FRAME_REFERENCE"
    METRIC_VALUE = "METRIC_VALUE"
    EXTERNAL_LINK = "EXTERNAL_LINK"


class DecisionType(StrEnum):
    TACTICAL = "TACTICAL"
    SELECTION = "SELECTION"
    TRAINING = "TRAINING"
    DEVELOPMENT = "DEVELOPMENT"
    OTHER = "OTHER"


class DecisionStatus(StrEnum):
    """Outcome of a human decision. No automatic correctness judgments."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class HumanDecision(StrEnum):
    """Explicit enum for human decision values in replay records.

    Separate from DecisionStatus which tracks decision lifecycle.
    This captures the specific human action taken regarding an AI recommendation.
    """

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"
    DEFERRED = "DEFERRED"
    NO_ACTION = "NO_ACTION"


class MemorySensitivity(StrEnum):
    """Access classification. Conservative by default; PLAYER sees only
    CLUB_GENERAL. Never inferred from content — set explicitly."""

    CLUB_GENERAL = "CLUB_GENERAL"
    PERFORMANCE = "PERFORMANCE"
    PLAYER_DEVELOPMENT = "PLAYER_DEVELOPMENT"
    AVAILABILITY = "AVAILABILITY"
    TACTICAL = "TACTICAL"
    SCOUTING = "SCOUTING"
    DECISION = "DECISION"
    RESTRICTED = "RESTRICTED"


class RedactionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REDACTED = "REDACTED"
