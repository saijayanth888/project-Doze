"""Predefined ablation studies — sequences of evolution runs that vary one
hyperparameter at a time so the paper can plot the effect.

Each ablation is a list of `runs`, where each run is a partial config that
gets merged on top of the ablation's `base` config. Run them sequentially
via POST /api/experiments/ablation; never in parallel — single GPU.
"""

from __future__ import annotations

from typing import Any

# Defaults shared across the runs in a single ablation. Individual runs
# override specific fields.
_BASE_CONFIG: dict[str, Any] = {
    "base_model": "meta-llama/Llama-3.2-3B-Instruct",
    "max_generations": 1,
    "lora_rank": 16,
    "lora_alpha": 32,
    "learning_rate": 2e-4,
    "batch_size": 2,
    "max_samples": 1000,
}


ABLATION_PRESETS: dict[str, dict[str, Any]] = {
    "ablation-lr-sweep": {
        "name": "Learning rate sweep",
        "description": "Compares champion quality at lr ∈ {1e-5, 5e-5, 1e-4, 2e-4, 5e-4}.",
        "base": dict(_BASE_CONFIG),
        "runs": [
            {"label": "lr=1e-5", "learning_rate": 1e-5},
            {"label": "lr=5e-5", "learning_rate": 5e-5},
            {"label": "lr=1e-4", "learning_rate": 1e-4},
            {"label": "lr=2e-4", "learning_rate": 2e-4},
            {"label": "lr=5e-4", "learning_rate": 5e-4},
        ],
    },
    "ablation-rank-sweep": {
        "name": "LoRA rank sweep",
        "description": "Compares champion quality at LoRA rank ∈ {4, 8, 16, 32, 64}.",
        "base": dict(_BASE_CONFIG),
        "runs": [
            {"label": "r=4",  "lora_rank": 4,  "lora_alpha": 8},
            {"label": "r=8",  "lora_rank": 8,  "lora_alpha": 16},
            {"label": "r=16", "lora_rank": 16, "lora_alpha": 32},
            {"label": "r=32", "lora_rank": 32, "lora_alpha": 64},
            {"label": "r=64", "lora_rank": 64, "lora_alpha": 128},
        ],
    },
    "ablation-data-source": {
        "name": "Training data source",
        "description": (
            "Compares curated-only / self-generated-only / mixed training data. "
            "Toggles MODELFORGE_SELF_GEN_SEEDS via the `data_source` flag in the run config."
        ),
        "base": {**_BASE_CONFIG, "max_generations": 3},
        "runs": [
            {"label": "curated only",         "data_source": "curated_only"},
            {"label": "self-generated only",  "data_source": "self_generated_only"},
            {"label": "mixed",                "data_source": "mixed"},
        ],
    },
    "ablation-specialist-vs-generalist": {
        "name": "Specialists vs generalist",
        "description": (
            "Four single-benchmark specialists vs one all-benchmark generalist. "
            "Each run targets a different `weak_categories` subset."
        ),
        "base": {**_BASE_CONFIG, "max_generations": 3},
        "runs": [
            {"label": "reasoning",  "weak_categories": ["arc_challenge", "hellaswag"]},
            {"label": "code",       "weak_categories": ["humaneval"]},
            {"label": "math",       "weak_categories": ["gsm8k"]},
            {"label": "general",    "weak_categories": ["mmlu"]},
            {"label": "generalist", "weak_categories": ["mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval"]},
        ],
    },
}


def list_ablations() -> list[dict[str, Any]]:
    return [
        {
            "ablation_id": k,
            "name": v["name"],
            "description": v["description"],
            "run_count": len(v["runs"]),
            "labels": [r.get("label") for r in v["runs"]],
        }
        for k, v in ABLATION_PRESETS.items()
    ]


def get_ablation(ablation_id: str) -> dict[str, Any] | None:
    return ABLATION_PRESETS.get(ablation_id)


def materialize_runs(ablation_id: str) -> list[dict[str, Any]]:
    """Merge each `run` over the ablation's `base` so each entry is a full
    evolution config ready to hand to start_evolution()."""
    preset = ABLATION_PRESETS.get(ablation_id)
    if not preset:
        return []
    base = dict(preset.get("base") or {})
    out = []
    for r in preset.get("runs", []):
        merged = dict(base)
        merged.update({k: v for k, v in r.items() if k != "label"})
        merged["__ablation_id"] = ablation_id
        merged["__ablation_label"] = r.get("label")
        out.append(merged)
    return out
