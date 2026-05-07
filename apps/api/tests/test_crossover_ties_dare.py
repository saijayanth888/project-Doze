"""TIES (NeurIPS 2023, Yadav et al.) + DARE (Yu et al. 2024) merge tests.

We verify the *invariants* of each strategy on synthetic tensors rather than
fitting real adapters — the latter is covered in the crossover smoke run.
"""
from __future__ import annotations

import torch

from agents.ept.crossover import CrossoverStrategy, _merge_weights


def _two_param_state(values_a: dict[str, list], values_b: dict[str, list]):
    a = {k: torch.tensor(v, dtype=torch.float32) for k, v in values_a.items()}
    b = {k: torch.tensor(v, dtype=torch.float32) for k, v in values_b.items()}
    return a, b


def test_ties_zeros_below_density_threshold():
    a, b = _two_param_state(
        {"w": [3.0, 0.01, -2.5, 0.001, 4.0]},
        {"w": [0.0, 0.0, 0.0, 0.0, 0.0]},
    )
    merged = _merge_weights(a, b, alpha=0.5, strategy=CrossoverStrategy.TIES, density=0.4)
    out = merged["w"]
    # Bottom 60% of |a|'s magnitudes must be trimmed to zero (the 0.01 and 0.001 entries).
    assert out[1] == 0.0
    assert out[3] == 0.0


def test_ties_elects_majority_sign():
    # Both parents agree on signs, so the elected sign must match.
    a, b = _two_param_state(
        {"w": [1.0, -1.0, 1.0]},
        {"w": [2.0, -2.0, 2.0]},
    )
    merged = _merge_weights(a, b, alpha=0.5, strategy=CrossoverStrategy.TIES, density=1.0)
    assert merged["w"][0] > 0
    assert merged["w"][1] < 0
    assert merged["w"][2] > 0


def test_dare_preserves_expectation():
    torch.manual_seed(0)
    a, b = _two_param_state(
        {"w": [10.0] * 1024},
        {"w": [0.0] * 1024},
    )
    merged = _merge_weights(a, b, alpha=0.5, strategy=CrossoverStrategy.DARE, density=0.5)
    # E[ alpha * (w * mask / density) + (1-alpha) * 0 ] = alpha * w. Tolerate noise.
    assert abs(float(merged["w"].mean()) - 5.0) < 0.5


def test_strategy_enum_includes_ties_and_dare():
    assert CrossoverStrategy.TIES.value == "ties"
    assert CrossoverStrategy.DARE.value == "dare"
