"""LoRA weight-space crossover.

Given two parent adapter directories (each containing
``adapter_model.safetensors`` and ``adapter_config.json``), produce a child
adapter whose weights blend the parents under one of three strategies:

* ``UNIFORM``     — every tensor is alpha*A + (1-alpha)*B
* ``LAYER_WISE``  — alpha shifts gradually across transformer layers
* ``RANDOM_SWAP`` — per-tensor: keep A with probability alpha else B

Returns the path to the new child directory. Crossover is a pure function over
already-trained adapters — no GPU, no optimiser, no training data. The child
inherits the architecture (rank, alpha, target_modules) of parent A; the
parents must be compatible (= trained on the same base + same target modules).

Honest framing
--------------
LoRA merging is not novel research on its own — see TIES, DARE, Model Soups,
LoRA Hub. What this module does is package the operation as a pure,
reproducible function with persisted provenance so a population manager can
wield it inside an automated evolution loop.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
from enum import Enum
from typing import Any

logger = logging.getLogger("modelforge.ept.crossover")


class CrossoverStrategy(str, Enum):
    UNIFORM = "uniform"
    LAYER_WISE = "layer_wise"
    RANDOM_SWAP = "random_swap"
    TIES = "ties"
    DARE = "dare"


def _load_adapter_weights(path: str) -> dict | None:
    """Read adapter weights from safetensors (preferred) or .bin."""
    safetensors_path = os.path.join(path, "adapter_model.safetensors")
    bin_path = os.path.join(path, "adapter_model.bin")
    try:
        if os.path.exists(safetensors_path):
            from safetensors.torch import load_file
            return load_file(safetensors_path)
        if os.path.exists(bin_path):
            import torch
            return torch.load(bin_path, map_location="cpu", weights_only=True)
        logger.error("[crossover] no adapter weights at %s", path)
        return None
    except Exception as exc:
        logger.error("[crossover] load_adapter_weights(%s) failed: %s", path, exc)
        return None


def _merge_weights(
    weights_a: dict,
    weights_b: dict,
    *,
    alpha: float,
    strategy: "CrossoverStrategy",
    density: float = 0.5,
    rng_seed: int | None = None,
) -> dict:
    """Pure-tensor merge used by both TIES and DARE branches.

    Pulled out of ``crossover`` so the math is unit-testable
    without needing real adapter files on disk.
    """
    import torch

    common = set(weights_a.keys()) & set(weights_b.keys())
    out: dict = {}

    if rng_seed is not None:
        torch.manual_seed(rng_seed)

    if strategy == CrossoverStrategy.TIES:
        for key in common:
            wa, wb = weights_a[key], weights_b[key]
            # 1. Trim — keep only the top-`density` fraction by magnitude.
            ka = torch.quantile(wa.abs().float(), max(0.0, 1.0 - density))
            kb = torch.quantile(wb.abs().float(), max(0.0, 1.0 - density))
            wa_t = torch.where(wa.abs() >= ka, wa, torch.zeros_like(wa))
            wb_t = torch.where(wb.abs() >= kb, wb, torch.zeros_like(wb))
            # 2. Elect sign — majority vote weighted by magnitude sum.
            sign = torch.sign(wa_t + wb_t)
            # 3. Merge — keep magnitudes whose sign matches the elected sign.
            mag_a = torch.where(torch.sign(wa_t) == sign, wa_t.abs(), torch.zeros_like(wa_t))
            mag_b = torch.where(torch.sign(wb_t) == sign, wb_t.abs(), torch.zeros_like(wb_t))
            merged = (alpha * mag_a + (1.0 - alpha) * mag_b) * sign
            out[key] = merged.to(wa.dtype)
        return out

    if strategy == CrossoverStrategy.DARE:
        d = max(1e-6, density)
        for key in common:
            wa, wb = weights_a[key], weights_b[key]
            mask_a = (torch.rand_like(wa.float()) < d).to(wa.dtype)
            mask_b = (torch.rand_like(wb.float()) < d).to(wb.dtype)
            wa_d = wa * mask_a / d
            wb_d = wb * mask_b / d
            out[key] = (alpha * wa_d + (1.0 - alpha) * wb_d).to(wa.dtype)
        return out

    raise ValueError(f"_merge_weights does not handle strategy={strategy!r}")


def _save_adapter_weights(weights: dict, child_path: str, config_source: str) -> None:
    """Write child weights as safetensors and copy adapter_config.json."""
    from safetensors.torch import save_file
    save_file(weights, os.path.join(child_path, "adapter_model.safetensors"))
    config_src = os.path.join(config_source, "adapter_config.json")
    if os.path.exists(config_src):
        shutil.copy(config_src, os.path.join(child_path, "adapter_config.json"))
    # Also copy tokenizer assets if present so the child is a drop-in adapter.
    for fn in (
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
        "special_tokens_map.json",
    ):
        src = os.path.join(config_source, fn)
        if os.path.exists(src):
            try:
                shutil.copy(src, os.path.join(child_path, fn))
            except Exception:
                pass


def _group_by_layer(keys: list[str]) -> dict[int, list[str]]:
    """Bucket weight keys by transformer layer index parsed from the name."""
    out: dict[int, list[str]] = {}
    for k in keys:
        m = re.search(r"layers?\.(\d+)", k)
        n = int(m.group(1)) if m else -1
        out.setdefault(n, []).append(k)
    return out


def crossover(
    parent_a_path: str,
    parent_b_path: str,
    output_dir: str,
    *,
    alpha: float = 0.5,
    strategy: CrossoverStrategy | str = CrossoverStrategy.UNIFORM,
    seed: int | None = None,
    child_id: str | None = None,
    **kwargs: Any,
) -> str:
    """Breed two LoRA adapters. Returns the child's directory path."""
    import torch
    if seed is not None:
        torch.manual_seed(seed)

    if isinstance(strategy, str):
        strategy = CrossoverStrategy(strategy)

    cid = child_id or uuid.uuid4().hex[:8]
    child_path = os.path.join(output_dir, f"child-{cid}")
    os.makedirs(child_path, exist_ok=True)

    weights_a = _load_adapter_weights(parent_a_path)
    weights_b = _load_adapter_weights(parent_b_path)
    if weights_a is None or weights_b is None:
        raise ValueError("crossover: failed to load one or both parent adapters")

    keys_a, keys_b = set(weights_a.keys()), set(weights_b.keys())
    if keys_a != keys_b:
        common_keys = keys_a & keys_b
        # Be strict: < 80% overlap means the parents have incompatible shapes
        # (different LoRA ranks / different target modules). Refuse rather than
        # silently producing a half-bred child.
        if len(common_keys) < int(len(keys_a) * 0.8):
            raise ValueError(
                f"crossover: parents incompatible — {len(keys_a)} vs {len(keys_b)} "
                f"weight tensors, only {len(common_keys)} in common"
            )
        logger.warning(
            "[crossover] using %d/%d common keys (parents not identical)",
            len(common_keys), len(keys_a),
        )
    else:
        common_keys = keys_a

    child_weights: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    if strategy == CrossoverStrategy.UNIFORM:
        for k in common_keys:
            child_weights[k] = alpha * weights_a[k] + (1.0 - alpha) * weights_b[k]

    elif strategy == CrossoverStrategy.LAYER_WISE:
        # Walk layers in order; gradually shift alpha so early layers favour A
        # and late layers favour B. Range stays in [alpha, alpha + 0.4*(1-alpha)].
        layers = _group_by_layer(sorted(common_keys))
        ordered = sorted(layers.items())
        n = max(len(ordered) - 1, 1)
        for li, (_, keys) in enumerate(ordered):
            la = alpha + (1.0 - alpha) * (li / n) * 0.4
            for k in keys:
                child_weights[k] = la * weights_a[k] + (1.0 - la) * weights_b[k]

    elif strategy == CrossoverStrategy.RANDOM_SWAP:
        for k in common_keys:
            child_weights[k] = (
                weights_a[k].clone() if torch.rand(1).item() < alpha else weights_b[k].clone()
            )

    elif strategy in (CrossoverStrategy.TIES, CrossoverStrategy.DARE):
        density = float(kwargs.get("density", 0.53 if strategy == CrossoverStrategy.DARE else 0.5))
        child_weights = _merge_weights(
            {k: weights_a[k] for k in common_keys},
            {k: weights_b[k] for k in common_keys},
            alpha=alpha, strategy=strategy, density=density,
            rng_seed=kwargs.get("rng_seed"),
        )
        metadata["density"] = density

    _save_adapter_weights(child_weights, child_path, parent_a_path)

    metadata.update({
        "child_id": cid,
        "parent_a": parent_a_path,
        "parent_b": parent_b_path,
        "alpha": float(alpha),
        "strategy": strategy.value,
        "seed": seed,
        "num_keys": len(child_weights),
        "kind": "ept_crossover",
    })
    with open(os.path.join(child_path, "crossover_metadata.json"), "w") as fh:
        json.dump(metadata, fh, indent=2)

    logger.info(
        "[crossover] %s α=%.2f — bred %s × %s → %s (%d tensors)",
        strategy.value, alpha,
        os.path.basename(parent_a_path), os.path.basename(parent_b_path),
        os.path.basename(child_path), len(child_weights),
    )
    return child_path
