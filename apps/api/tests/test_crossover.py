"""Unit tests for the EPT crossover operator.

These run without a model — we fabricate two PEFT-shaped weight dicts of
small random tensors, write them to a tmp directory, and verify the operator
respects the documented contract for each strategy.

The test only requires `torch` + `safetensors` (already in the GPU image's
requirements). It is purely CPU.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
safetensors_torch = pytest.importorskip("safetensors.torch")

from agents.ept.crossover import CrossoverStrategy, crossover  # noqa: E402  (import after path setup)


# ── Helpers ──────────────────────────────────────────────────────────────


def _fake_lora_weights(n_layers: int = 4, rank: int = 8, hidden: int = 64, *, seed: int) -> dict[str, "torch.Tensor"]:
    """Build a PEFT-shaped weight dict with N transformer layers' q/v_proj LoRAs.

    Keys mirror what real PEFT writes (`base_model.model.model.layers.<N>.<proj>.lora_A.weight` etc.)
    so the layer-aware crossover strategy has something to bucket on.
    """
    g = torch.Generator().manual_seed(seed)
    out: dict[str, torch.Tensor] = {}
    for li in range(n_layers):
        for proj in ("q_proj", "v_proj"):
            base = f"base_model.model.model.layers.{li}.self_attn.{proj}"
            out[f"{base}.lora_A.weight"] = torch.randn(rank, hidden, generator=g)
            out[f"{base}.lora_B.weight"] = torch.randn(hidden, rank, generator=g)
    return out


def _write_adapter(path: Path, weights: dict[str, "torch.Tensor"], *, rank: int = 8) -> None:
    """Mimic PEFT's on-disk layout: safetensors + adapter_config.json."""
    path.mkdir(parents=True, exist_ok=True)
    safetensors_torch.save_file(weights, str(path / "adapter_model.safetensors"))
    cfg = {
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "r": int(rank),
        "lora_alpha": int(rank * 2),
        "target_modules": ["q_proj", "v_proj"],
        "lora_dropout": 0.05,
        "bias": "none",
    }
    (path / "adapter_config.json").write_text(json.dumps(cfg, indent=2))


def _read_child_weights(child_path: Path) -> dict[str, "torch.Tensor"]:
    return safetensors_torch.load_file(str(child_path / "adapter_model.safetensors"))


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def two_parents(tmp_path):
    a_dir = tmp_path / "parent-a"
    b_dir = tmp_path / "parent-b"
    weights_a = _fake_lora_weights(seed=1)
    weights_b = _fake_lora_weights(seed=2)
    _write_adapter(a_dir, weights_a)
    _write_adapter(b_dir, weights_b)
    return {
        "a_dir": a_dir,
        "b_dir": b_dir,
        "weights_a": weights_a,
        "weights_b": weights_b,
    }


# ── Tests ────────────────────────────────────────────────────────────────


def test_crossover_uniform_alpha_half_is_arithmetic_mean(tmp_path, two_parents):
    """UNIFORM with α=0.5 must produce exactly the elementwise mean."""
    out_dir = tmp_path / "children"
    child_path = crossover(
        str(two_parents["a_dir"]), str(two_parents["b_dir"]),
        output_dir=str(out_dir),
        alpha=0.5, strategy=CrossoverStrategy.UNIFORM, seed=0,
    )
    p = Path(child_path)
    assert p.is_dir(), "child directory should exist"
    assert (p / "adapter_model.safetensors").is_file()
    assert (p / "adapter_config.json").is_file(), "config should be copied from parent A"
    assert (p / "crossover_metadata.json").is_file()

    child_w = _read_child_weights(p)
    assert set(child_w.keys()) == set(two_parents["weights_a"].keys())
    for k, v in child_w.items():
        expected = 0.5 * two_parents["weights_a"][k] + 0.5 * two_parents["weights_b"][k]
        assert torch.allclose(v, expected, atol=1e-6), f"mean mismatch on {k}"


@pytest.mark.parametrize("alpha", [0.0, 0.25, 0.75, 1.0])
def test_crossover_uniform_alpha_extremes_match_formula(tmp_path, two_parents, alpha):
    """UNIFORM α=1 → all parent A; α=0 → all parent B; in between → blend."""
    child_path = crossover(
        str(two_parents["a_dir"]), str(two_parents["b_dir"]),
        output_dir=str(tmp_path / "children"),
        alpha=alpha, strategy=CrossoverStrategy.UNIFORM,
    )
    child_w = _read_child_weights(Path(child_path))
    for k, v in child_w.items():
        expected = alpha * two_parents["weights_a"][k] + (1 - alpha) * two_parents["weights_b"][k]
        assert torch.allclose(v, expected, atol=1e-6), f"alpha={alpha} mismatch on {k}"


def test_crossover_metadata_records_provenance(tmp_path, two_parents):
    """crossover_metadata.json must round-trip the parent paths, alpha and strategy."""
    out_dir = tmp_path / "children"
    child_path = crossover(
        str(two_parents["a_dir"]), str(two_parents["b_dir"]),
        output_dir=str(out_dir),
        alpha=0.42, strategy=CrossoverStrategy.UNIFORM, seed=7,
    )
    meta = json.loads((Path(child_path) / "crossover_metadata.json").read_text())
    assert meta["parent_a"] == str(two_parents["a_dir"])
    assert meta["parent_b"] == str(two_parents["b_dir"])
    assert meta["alpha"] == pytest.approx(0.42)
    assert meta["strategy"] == "uniform"
    assert meta["seed"] == 7
    assert meta["kind"] == "ept_crossover"
    assert meta["num_keys"] == len(two_parents["weights_a"])


def test_crossover_layer_wise_blends_per_layer(tmp_path, two_parents):
    """LAYER_WISE must produce a child whose weights are still in the parents'
    convex hull (each is alpha*A + (1-alpha)*B for some 0 ≤ alpha ≤ 1)."""
    child_path = crossover(
        str(two_parents["a_dir"]), str(two_parents["b_dir"]),
        output_dir=str(tmp_path / "children"),
        alpha=0.5, strategy=CrossoverStrategy.LAYER_WISE, seed=1,
    )
    child_w = _read_child_weights(Path(child_path))
    # Each weight should sit between min and max of the two parents.
    for k, v in child_w.items():
        a, b = two_parents["weights_a"][k], two_parents["weights_b"][k]
        lo = torch.minimum(a, b)
        hi = torch.maximum(a, b)
        assert torch.all(v >= lo - 1e-6), f"layer_wise dipped below parent floor on {k}"
        assert torch.all(v <= hi + 1e-6), f"layer_wise exceeded parent ceiling on {k}"


def test_crossover_random_swap_picks_one_parent_per_tensor(tmp_path, two_parents):
    """RANDOM_SWAP must produce an exact copy of *one* parent's tensor per key."""
    child_path = crossover(
        str(two_parents["a_dir"]), str(two_parents["b_dir"]),
        output_dir=str(tmp_path / "children"),
        alpha=0.5, strategy=CrossoverStrategy.RANDOM_SWAP, seed=42,
    )
    child_w = _read_child_weights(Path(child_path))
    for k, v in child_w.items():
        from_a = torch.equal(v, two_parents["weights_a"][k])
        from_b = torch.equal(v, two_parents["weights_b"][k])
        assert from_a or from_b, f"random_swap produced a blend on {k}"


def test_crossover_seed_is_reproducible_for_random_swap(tmp_path, two_parents):
    """Same seed → identical child weights for the stochastic strategy."""
    out = tmp_path / "out"
    p1 = crossover(
        str(two_parents["a_dir"]), str(two_parents["b_dir"]),
        output_dir=str(out), alpha=0.5,
        strategy=CrossoverStrategy.RANDOM_SWAP, seed=99,
    )
    p2 = crossover(
        str(two_parents["a_dir"]), str(two_parents["b_dir"]),
        output_dir=str(out), alpha=0.5,
        strategy=CrossoverStrategy.RANDOM_SWAP, seed=99,
    )
    w1 = _read_child_weights(Path(p1))
    w2 = _read_child_weights(Path(p2))
    for k in w1:
        assert torch.equal(w1[k], w2[k]), f"seeded random_swap not reproducible on {k}"


def test_crossover_rejects_incompatible_parents(tmp_path):
    """Refuses parents whose key sets overlap by < 80% (different rank/architecture)."""
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    _write_adapter(a_dir, _fake_lora_weights(n_layers=4, seed=10))
    # Parent B has a totally different layer count → no overlap.
    _write_adapter(b_dir, _fake_lora_weights(n_layers=8, seed=11))
    with pytest.raises(ValueError, match="incompatible"):
        crossover(
            str(a_dir), str(b_dir),
            output_dir=str(tmp_path / "out"),
            alpha=0.5, strategy=CrossoverStrategy.UNIFORM,
        )


def test_crossover_accepts_string_strategy(tmp_path, two_parents):
    """The function accepts a string strategy name (Pydantic / API surface)."""
    child_path = crossover(
        str(two_parents["a_dir"]), str(two_parents["b_dir"]),
        output_dir=str(tmp_path / "out"),
        alpha=0.3, strategy="uniform",  # string instead of enum
    )
    assert (Path(child_path) / "adapter_model.safetensors").is_file()
