"""Phase 07B-2 Transformer tests: shapes, masks, configs, errors,
determinism. CPU-only, tiny dims, no training, no football claims."""

import copy
import math

import pytest

from app.ai.tactics.transformer import (
    InvalidTransformerInput,
    TemporalRepresentation,
    TemporalTransformer,
    TransformerConfig,
)


def config(**kwargs: object) -> TransformerConfig:
    payload: dict[str, object] = {
        "feature_dim": 9,
        "model_dim": 8,
        "num_heads": 2,
        "num_layers": 1,
        "feedforward_dim": 16,
    }
    payload.update(kwargs)
    return TransformerConfig(**payload)  # type: ignore[arg-type]


def batch(
    rows: int, length: int, dim: int = 9, scale: float = 0.1
) -> list[list[list[float]]]:
    return [
        [[(b + r + c * 0.01) * scale for c in range(dim)] for r in range(length)]
        for b in range(rows)
    ]


def assert_finite(output: TemporalRepresentation) -> None:
    for row in output.pooled:
        assert all(math.isfinite(v) for v in row)
    for sequence in output.frames:
        for row in sequence:
            assert all(math.isfinite(v) for v in row)


# 1. Model initialization.
def test_initialization_defaults() -> None:
    model = TemporalTransformer(config())
    assert model.training is False
    assert model.config.dropout == 0.0
    assert model.eval() is model
    assert model.train().training is True
    model.eval()
    with pytest.raises(ValueError):
        TransformerConfig(
            feature_dim=9, model_dim=7, num_heads=2, num_layers=1, feedforward_dim=8
        )


# 2. Correct output shape.
def test_output_shape() -> None:
    model = TemporalTransformer(config())
    output = model(batch(2, 4))
    assert len(output.pooled) == 2
    assert all(len(row) == 8 for row in output.pooled)
    assert len(output.frames) == 2
    assert all(len(seq) == 4 for seq in output.frames)
    assert all(len(row) == 8 for seq in output.frames for row in seq)
    assert output.valid_lengths == (4, 4)
    assert output.model_dim == 8


# 3/4. Variable length + padding mask behavior.
def test_padding_mask_excludes_padded_positions() -> None:
    model = TemporalTransformer(config())
    data = batch(1, 4)
    truncated = model([data[0][:2]])
    padded = model(data, valid_lengths=[2])
    # Valid positions see identical keys in both runs, so they must match.
    assert truncated.frames[0][0] == pytest.approx(padded.frames[0][0])
    assert truncated.frames[0][1] == pytest.approx(padded.frames[0][1])
    assert truncated.pooled[0] == pytest.approx(padded.pooled[0])
    # Padded outputs are zeroed and pooled only over valid positions.
    assert all(v == 0.0 for v in padded.frames[0][2])
    assert all(v == 0.0 for v in padded.frames[0][3])


# 5. Different configurable model sizes.
@pytest.mark.parametrize(
    "model_dim,num_heads,num_layers,ff_dim",
    [(8, 2, 1, 16), (12, 3, 2, 24), (4, 1, 3, 8)],
)
def test_configurable_sizes(
    model_dim: int, num_heads: int, num_layers: int, ff_dim: int
) -> None:
    model = TemporalTransformer(
        config(
            model_dim=model_dim,
            num_heads=num_heads,
            num_layers=num_layers,
            feedforward_dim=ff_dim,
        )
    )
    output = model(batch(1, 3))
    assert len(output.pooled[0]) == model_dim
    assert_finite(output)


# 6/7. Invalid dimension / shape rejection.
def test_invalid_inputs_rejected() -> None:
    model = TemporalTransformer(config())
    with pytest.raises(InvalidTransformerInput):
        model(batch(1, 2, dim=5))
    with pytest.raises(InvalidTransformerInput):
        model([])
    with pytest.raises(InvalidTransformerInput):
        model([[[]]])
    with pytest.raises(InvalidTransformerInput):
        model([[[0.0] * 9], [[0.0] * 9, [0.0] * 9]])
    with pytest.raises(InvalidTransformerInput):
        model(batch(1, 2), valid_lengths=[1, 2])
    with pytest.raises(InvalidTransformerInput):
        model(batch(1, 2), valid_lengths=[0])
    with pytest.raises(InvalidTransformerInput):
        model(batch(1, 2), valid_lengths=[9])
    with pytest.raises(InvalidTransformerInput):
        model([[[float("nan")] * 9, [0.0] * 9]])
    tiny = TemporalTransformer(config(max_sequence_length=2))
    with pytest.raises(InvalidTransformerInput):
        tiny(batch(1, 3))


# 8. Deterministic behavior under evaluation mode.
def test_eval_determinism() -> None:
    first = TemporalTransformer(config()).eval()
    second = TemporalTransformer(config()).eval()
    data = batch(2, 4)
    left = first(data, valid_lengths=[4, 2])
    right = second(data, valid_lengths=[4, 2])
    assert left.pooled == right.pooled
    assert left.frames == right.frames
    assert model_dump(left) == model_dump(right)


def model_dump(output: TemporalRepresentation) -> object:
    return (output.pooled, output.frames, output.valid_lengths)


# 9. Batch processing.
def test_batch_processing() -> None:
    model = TemporalTransformer(config())
    joint = model(batch(3, 2))
    solo = [model([sequence]) for sequence in batch(3, 2)]
    for index in range(3):
        assert joint.pooled[index] == pytest.approx(solo[index].pooled[0])
        assert joint.frames[index] == solo[index].frames[0]


# 10/11. No NaN/Inf on CPU, varied magnitudes.
def test_finite_outputs_cpu() -> None:
    model = TemporalTransformer(config())
    assert_finite(model(batch(2, 5, scale=1.0)))
    assert_finite(model(batch(1, 1, scale=0.001)))
    assert_finite(model(batch(2, 6), valid_lengths=[6, 1]))


# 12. Model does not mutate input tensors.
def test_inputs_not_mutated() -> None:
    model = TemporalTransformer(config())
    data = batch(2, 4)
    snapshot = copy.deepcopy(data)
    model(data, valid_lengths=[4, 3])
    assert data == snapshot


def test_positional_encoding_modes_differ() -> None:
    plain = TemporalTransformer(config(positional_encoding="none"))
    positioned = TemporalTransformer(config(positional_encoding="sinusoidal"))
    data = batch(1, 4)
    assert plain(data).pooled != positioned(data).pooled
