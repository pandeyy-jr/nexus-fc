"""Phase 07B-2 — temporal Transformer core (untrained architecture).

Minimal encoder-only Transformer over ``(batch, sequence, feature)``
nested float lists. Dependency-free pure Python (no torch/numpy):
mathematics mirrors ``nn.TransformerEncoder`` semantics so a future
torch port is mechanical.

This is an ML architecture foundation, NOT a trained football model.
No datasets, no weights, no training, no tactical interpretation.

Domain separation: inputs/outputs are plain nested lists inside
:class:`TemporalRepresentation`. ``torch.Tensor`` never enters the
tactical domain contracts.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL_VERSION = "07B-2.1"
_NEG_INF = float("-inf")


class TransformerConfig(BaseModel):
    """All architecture parameters explicit; nothing hardcoded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_dim: int = Field(ge=1, le=4096)
    model_dim: int = Field(ge=1, le=4096)
    num_heads: int = Field(ge=1, le=64)
    num_layers: int = Field(ge=1, le=48)
    feedforward_dim: int = Field(ge=1, le=16384)
    dropout: float = Field(default=0.0, ge=0.0, le=1.0)
    max_sequence_length: int = Field(default=512, ge=1, le=8192)
    positional_encoding: Literal["sinusoidal", "none"] = "sinusoidal"
    seed: int = Field(default=7)

    @model_validator(mode="after")
    def validate_head_split(self) -> TransformerConfig:
        if self.model_dim % self.num_heads != 0:
            raise ValueError("model_dim must be divisible by num_heads")
        return self


class InvalidTransformerInput(ValueError):
    """A batch, mask, or shape cannot be processed by the model."""


@dataclass(frozen=True)
class TemporalRepresentation:
    """Structured model output; plain lists, never tensors."""

    pooled: tuple[tuple[float, ...], ...]
    frames: tuple[tuple[tuple[float, ...], ...], ...]
    valid_lengths: tuple[int, ...]
    model_dim: int
    model_version: str = MODEL_VERSION
    metadata: dict[str, object] = field(default_factory=dict)


def _check_finite(values: Sequence[float], what: str) -> None:
    if any(not math.isfinite(v) for v in values):
        raise InvalidTransformerInput(f"Non-finite values in {what}")


def _softmax(scores: list[float]) -> list[float]:
    finite = [s for s in scores if s > _NEG_INF]
    peak = max(finite) if finite else 0.0
    weights = [math.exp(s - peak) if s > _NEG_INF else 0.0 for s in scores]
    total = sum(weights)
    if total <= 0:
        return [0.0] * len(scores)
    return [w / total for w in weights]


def _layer_norm(vector: list[float], eps: float = 1e-5) -> list[float]:
    mean = sum(vector) / len(vector)
    variance = sum((v - mean) ** 2 for v in vector) / len(vector)
    scale = 1.0 / math.sqrt(variance + eps)
    return [(v - mean) * scale for v in vector]


def _matvec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(w * v for w, v in zip(row, vector, strict=True)) for row in matrix]


def _gelu(value: float) -> float:
    return 0.5 * value * (1.0 + math.erf(value / math.sqrt(2.0)))


def _sinusoidal_table(max_length: int, model_dim: int) -> list[list[float]]:
    table: list[list[float]] = []
    for position in range(max_length):
        row = []
        for dim in range(model_dim):
            angle = position / (10000.0 ** (2 * (dim // 2) / model_dim))
            row.append(math.sin(angle) if dim % 2 == 0 else math.cos(angle))
        table.append(row)
    return table


class _Linear:
    def __init__(self, rng: random.Random, in_dim: int, out_dim: int) -> None:
        bound = 1.0 / math.sqrt(in_dim)
        self.weight = [
            [rng.uniform(-bound, bound) for _ in range(in_dim)] for _ in range(out_dim)
        ]
        self.bias = [0.0] * out_dim

    def __call__(self, vector: list[float]) -> list[float]:
        projected = _matvec(self.weight, vector)
        return [p + b for p, b in zip(projected, self.bias, strict=True)]


class _EncoderLayer:
    def __init__(self, rng: random.Random, config: TransformerConfig) -> None:
        head_dim = config.model_dim // config.num_heads
        self.head_dim = head_dim
        self.num_heads = config.num_heads
        self.query = _Linear(rng, config.model_dim, config.model_dim)
        self.key = _Linear(rng, config.model_dim, config.model_dim)
        self.value = _Linear(rng, config.model_dim, config.model_dim)
        self.output = _Linear(rng, config.model_dim, config.model_dim)
        self.feedforward_in = _Linear(rng, config.model_dim, config.feedforward_dim)
        self.feedforward_out = _Linear(rng, config.feedforward_dim, config.model_dim)
        self.scale = 1.0 / math.sqrt(head_dim)

    def _attention(
        self, sequence: list[list[float]], valid: list[bool]
    ) -> list[list[float]]:
        queries = [self.query(row) for row in sequence]
        keys = [self.key(row) for row in sequence]
        values = [self.value(row) for row in sequence]
        heads: list[list[list[float]]] = []
        for head in range(self.num_heads):
            start = head * self.head_dim
            stop = start + self.head_dim
            combined: list[list[float]] = []
            for position, query in enumerate(queries):
                query_head = query[start:stop]
                scores = []
                for other, key in enumerate(keys):
                    if valid[other]:
                        scores.append(
                            sum(
                                q * k
                                for q, k in zip(
                                    query_head, key[start:stop], strict=True
                                )
                            )
                            * self.scale
                        )
                    else:
                        scores.append(_NEG_INF)
                weights = _softmax(scores)
                mixed = [0.0] * self.head_dim
                for weight, value in zip(weights, values, strict=True):
                    head_value = value[start:stop]
                    for dim in range(self.head_dim):
                        mixed[dim] += weight * head_value[dim]
                combined.append(mixed if valid[position] else [0.0] * self.head_dim)
            heads.append(combined)
        merged = [
            [channel for head in range(self.num_heads) for channel in heads[head][pos]]
            for pos in range(len(sequence))
        ]
        return [self.output(row) for row in merged]

    def __call__(
        self, sequence: list[list[float]], valid: list[bool]
    ) -> list[list[float]]:
        attended = self._attention(sequence, valid)
        sequence = [
            _layer_norm([a + b for a, b in zip(row, add, strict=True)])
            for row, add in zip(sequence, attended, strict=True)
        ]
        grown = [[_gelu(v) for v in self.feedforward_in(row)] for row in sequence]
        shrunk = [self.feedforward_out(row) for row in grown]
        return [
            _layer_norm([a + b for a, b in zip(row, add, strict=True)])
            for row, add in zip(sequence, shrunk, strict=True)
        ]


class TemporalTransformer:
    """Minimal encoder-only temporal Transformer (eval-first, CPU-only)."""

    def __init__(self, config: TransformerConfig) -> None:
        self.config = config
        rng = random.Random(config.seed)
        self.input_projection = _Linear(rng, config.feature_dim, config.model_dim)
        self.position_table = (
            _sinusoidal_table(config.max_sequence_length, config.model_dim)
            if config.positional_encoding == "sinusoidal"
            else [[0.0] * config.model_dim for _ in range(config.max_sequence_length)]
        )
        self.layers = [_EncoderLayer(rng, config) for _ in range(config.num_layers)]
        self._training = False
        self._dropout_rng = random.Random(config.seed + 1)

    def train(self) -> TemporalTransformer:
        self._training = True
        return self

    def eval(self) -> TemporalTransformer:
        self._training = False
        return self

    @property
    def training(self) -> bool:
        return self._training

    def _maybe_dropout(self, vector: list[float]) -> list[float]:
        rate = self.config.dropout
        if not self._training or rate <= 0:
            return list(vector)
        keep = 1.0 - rate
        return [
            (v / keep if self._dropout_rng.random() >= rate else 0.0) for v in vector
        ]

    def _validate_batch(
        self,
        batch: Sequence[Sequence[Sequence[float]]],
        valid_lengths: Sequence[int] | None,
    ) -> tuple[list[list[list[float]]], list[int]]:
        if not isinstance(batch, Sequence) or isinstance(batch, (str, bytes)):
            raise InvalidTransformerInput("Batch must be a sequence of sequences")
        rows = [list(map(list, sequence)) for sequence in batch]
        if not rows:
            raise InvalidTransformerInput("Batch must hold at least one sequence")
        widths = {len(sequence) for sequence in rows}
        if len(widths) != 1:
            raise InvalidTransformerInput("All batch sequences need equal length")
        sequence_length = widths.pop()
        if sequence_length == 0:
            raise InvalidTransformerInput("Sequences must hold at least one frame")
        if sequence_length > self.config.max_sequence_length:
            raise InvalidTransformerInput("Sequence exceeds maximum length")
        for sequence in rows:
            for row in sequence:
                if len(row) != self.config.feature_dim:
                    raise InvalidTransformerInput(
                        "Feature dimension mismatch: "
                        f"expected {self.config.feature_dim}"
                    )
                _check_finite(row, "input features")
        if valid_lengths is None:
            lengths = [sequence_length] * len(rows)
        else:
            lengths = list(valid_lengths)
            if len(lengths) != len(rows):
                raise InvalidTransformerInput("Mask length must match batch size")
            if any(length < 0 or length > sequence_length for length in lengths):
                raise InvalidTransformerInput("Valid lengths out of range")
        if all(length == 0 for length in lengths):
            raise InvalidTransformerInput("Batch holds no valid positions")
        return rows, lengths

    def forward(
        self,
        batch: Sequence[Sequence[Sequence[float]]],
        valid_lengths: Sequence[int] | None = None,
    ) -> TemporalRepresentation:
        """Run the encoder; inputs are copied, never mutated."""
        rows, lengths = self._validate_batch(batch, valid_lengths)
        frame_outputs: list[list[list[float]]] = []
        pooled: list[list[float]] = []
        for sequence, length in zip(rows, lengths, strict=True):
            valid = [position < length for position in range(len(sequence))]
            hidden = [
                [
                    projected + positional
                    for projected, positional in zip(
                        self._maybe_dropout(self.input_projection(row)),
                        self.position_table[position],
                        strict=True,
                    )
                ]
                for position, row in enumerate(sequence)
            ]
            for layer in self.layers:
                hidden = layer(hidden, valid)
                if self._training:
                    hidden = [self._maybe_dropout(row) for row in hidden]
            masked = [
                list(row) if is_valid else [0.0] * self.config.model_dim
                for row, is_valid in zip(hidden, valid, strict=True)
            ]
            frame_outputs.append(masked)
            live = [
                row for row, is_valid in zip(masked, valid, strict=True) if is_valid
            ]
            pooled.append(
                [sum(column) / len(live) for column in zip(*live, strict=True)]
            )
        for output in (*pooled, *[row for seq in frame_outputs for row in seq]):
            _check_finite(output, "model output")
        return TemporalRepresentation(
            pooled=tuple(tuple(row) for row in pooled),
            frames=tuple(tuple(tuple(row) for row in seq) for seq in frame_outputs),
            valid_lengths=tuple(lengths),
            model_dim=self.config.model_dim,
            metadata={
                "model_version": MODEL_VERSION,
                "feature_dim": self.config.feature_dim,
                "num_heads": self.config.num_heads,
                "num_layers": self.config.num_layers,
            },
        )

    __call__ = forward
