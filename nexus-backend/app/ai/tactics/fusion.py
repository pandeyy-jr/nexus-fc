"""Phase 07E — temporal + graph fusion (untrained architecture).

Combines one temporal embedding with one graph embedding:

temporal_embedding ──┐
                     ├─> FusionModule -> FusedTacticalRepresentation
graph_embedding ─────┘

Mechanism (deliberately simple): concatenation + projection,
``fused = LayerNorm(ReLU(Linear([temporal, graph])))``.

Missing-modality rule: a missing side is zero-filled AND flagged via
``temporal_available`` / ``graph_available``. Downstream consumers must
gate on the flags; zeros are never presented as information. Both
sides missing is rejected outright.

Untrained architecture only: no training, no tactical predictions.
Plain nested lists throughout — tensors never enter.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

MODEL_VERSION = "07E.1"


class FusionConfig(BaseModel):
    """Explicit dimensions; incompatible inputs are rejected, never reshaped."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    temporal_dim: int = Field(ge=1, le=4096)
    graph_dim: int = Field(ge=1, le=4096)
    fusion_dim: int = Field(ge=1, le=4096)
    dropout: float = Field(default=0.0, ge=0.0, le=1.0)
    seed: int = Field(default=13)


class InvalidFusionInput(ValueError):
    """Embeddings cannot be fused by this module."""


@dataclass(frozen=True)
class FusedTacticalRepresentation:
    temporal_embedding: tuple[float, ...] | None
    graph_embedding: tuple[float, ...] | None
    fused_embedding: tuple[float, ...]
    temporal_available: bool
    graph_available: bool
    fusion_dim: int
    model_version: str = MODEL_VERSION
    metadata: dict[str, object] = field(default_factory=dict)


def _check_vector(values: Sequence[float], dim: int, what: str) -> tuple[float, ...]:
    items = tuple(values)
    if len(items) != dim:
        raise InvalidFusionInput(
            f"{what} dimension mismatch: expected {dim}, got {len(items)}"
        )
    if any(not math.isfinite(v) for v in items):
        raise InvalidFusionInput(f"Non-finite values in {what}")
    return items


def _layer_norm(vector: list[float], eps: float = 1e-5) -> list[float]:
    mean = sum(vector) / len(vector)
    variance = sum((v - mean) ** 2 for v in vector) / len(vector)
    scale = 1.0 / math.sqrt(variance + eps)
    return [(v - mean) * scale for v in vector]


class _Linear:
    def __init__(self, rng: random.Random, in_dim: int, out_dim: int) -> None:
        bound = 1.0 / math.sqrt(in_dim)
        self.weight = [
            [rng.uniform(-bound, bound) for _ in range(in_dim)] for _ in range(out_dim)
        ]
        self.bias = [0.0] * out_dim

    def __call__(self, vector: Sequence[float]) -> list[float]:
        return [
            sum(w * v for w, v in zip(row, vector, strict=True)) + b
            for row, b in zip(self.weight, self.bias, strict=True)
        ]


class TemporalGraphFusion:
    """Minimal concat-plus-projection fusion (eval-first, CPU-only)."""

    def __init__(self, config: FusionConfig) -> None:
        self.config = config
        rng = random.Random(config.seed)
        self.projection = _Linear(
            rng, config.temporal_dim + config.graph_dim, config.fusion_dim
        )
        self._training = False
        self._dropout_rng = random.Random(config.seed + 1)

    def train(self) -> TemporalGraphFusion:
        self._training = True
        return self

    def eval(self) -> TemporalGraphFusion:
        self._training = False
        return self

    @property
    def training(self) -> bool:
        return self._training

    def forward(
        self,
        temporal: Sequence[float] | None,
        graph: Sequence[float] | None,
    ) -> FusedTacticalRepresentation:
        """Fuse one pair; inputs are read-only, never mutated."""
        if temporal is None and graph is None:
            raise InvalidFusionInput("At least one representation is required")
        temporal_items: tuple[float, ...] | None = None
        graph_items: tuple[float, ...] | None = None
        if temporal is not None:
            if isinstance(temporal, (str, bytes)):
                raise InvalidFusionInput("Temporal embedding must be numeric")
            temporal_items = _check_vector(
                temporal, self.config.temporal_dim, "temporal_embedding"
            )
        if graph is not None:
            if isinstance(graph, (str, bytes)):
                raise InvalidFusionInput("Graph embedding must be numeric")
            graph_items = _check_vector(graph, self.config.graph_dim, "graph_embedding")
        combined = (
            tuple(temporal_items)
            if temporal_items is not None
            else (0.0,) * self.config.temporal_dim
        ) + (
            tuple(graph_items)
            if graph_items is not None
            else (0.0,) * self.config.graph_dim
        )
        projected = self.projection(combined)
        if self._training and self.config.dropout > 0:
            keep = 1.0 - self.config.dropout
            projected = [
                (v / keep if self._dropout_rng.random() >= self.config.dropout else 0.0)
                for v in projected
            ]
        activated = [max(0.0, v) for v in projected]
        fused = _layer_norm(activated)
        if any(not math.isfinite(v) for v in fused):
            raise InvalidFusionInput("Non-finite values in fused output")
        return FusedTacticalRepresentation(
            temporal_embedding=temporal_items,
            graph_embedding=graph_items,
            fused_embedding=tuple(fused),
            temporal_available=temporal_items is not None,
            graph_available=graph_items is not None,
            fusion_dim=self.config.fusion_dim,
            metadata={
                "model_version": MODEL_VERSION,
                "temporal_dim": self.config.temporal_dim,
                "graph_dim": self.config.graph_dim,
            },
        )

    def forward_batch(
        self,
        pairs: Sequence[tuple[Sequence[float] | None, Sequence[float] | None]],
    ) -> tuple[FusedTacticalRepresentation, ...]:
        """Independent per-pair fusion; no cross-pair leakage."""
        if not pairs:
            raise InvalidFusionInput("Batch holds no pairs")
        return tuple(self.forward(temporal, graph) for temporal, graph in pairs)

    __call__ = forward
