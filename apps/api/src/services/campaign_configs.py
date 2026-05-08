"""Pre-built research campaigns.

Each campaign is a list of experiment specs that the campaign runner
executes back-to-back. The shape is intentionally narrow — every spec
is a kwargs dict for `/api/evolve/start` (or `/api/ept/start` when
`method == "ept"`) — so we don't bake in a parallel mini-DSL.

The campaign IDs here are the same ones the frontend Campaign page
lists. Adding a new campaign = add a key to this dict + redeploy.
"""

from __future__ import annotations

CAMPAIGNS: dict[str, dict] = {
    "baseline_all_models": {
        "description": "Baseline eval of small/mid models (no training).",
        "experiments": [
            {"model": m, "max_generations": 0, "eval_only": True}
            for m in [
                "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
                "meta-llama/Llama-3.2-1B-Instruct",
                "meta-llama/Llama-3.2-3B-Instruct",
                "Qwen/Qwen2.5-3B-Instruct",
                "microsoft/Phi-3.5-mini-instruct",
            ]
        ],
    },
    "large_models_baseline": {
        "description": "Baseline eval of 7B+ models — runs separately so DGX unified memory has full headroom.",
        "experiments": [
            {"model": m, "max_generations": 0, "eval_only": True}
            for m in [
                "Qwen/Qwen2.5-7B-Instruct",
                "meta-llama/Llama-3.1-8B-Instruct",
            ]
        ],
    },
    "sequential_evolution_3b": {
        "description": "5-gen sequential evolution on 3B models.",
        "experiments": [
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "max_generations": 5},
            {"model": "Qwen/Qwen2.5-3B-Instruct", "max_generations": 5},
            {"model": "microsoft/Phi-3.5-mini-instruct", "max_generations": 5},
        ],
    },
    "ept_vs_sequential": {
        "description": "Compare EPT population evolution vs sequential.",
        "experiments": [
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "max_generations": 5, "method": "sequential"},
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "max_generations": 5, "method": "ept", "population_size": 4},
        ],
    },
    "crossover_strategy_comparison": {
        "description": "Compare crossover strategies in EPT.",
        "experiments": [
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "method": "ept", "crossover": "uniform"},
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "method": "ept", "crossover": "ties"},
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "method": "ept", "crossover": "dare"},
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "method": "ept", "crossover": "layer_wise"},
        ],
    },
    "specialist_vs_generalist": {
        "description": "4 specialists vs 1 generalist on the same base model.",
        "experiments": [
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "target_benchmarks": ["arc_challenge", "hellaswag"], "name": "reasoning"},
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "target_benchmarks": ["gsm8k"], "name": "math"},
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "target_benchmarks": ["humaneval"], "name": "code"},
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "target_benchmarks": ["mmlu"], "name": "knowledge"},
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "target_benchmarks": "all", "name": "generalist"},
        ],
    },
    "lr_ablation": {
        "description": "Learning rate sweep — 1 generation each.",
        "experiments": [
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "learning_rate": lr, "max_generations": 1}
            for lr in [1e-5, 5e-5, 1e-4, 2e-4, 5e-4]
        ],
    },
    "rank_ablation": {
        "description": "LoRA rank sweep — 1 generation each.",
        "experiments": [
            {"model": "meta-llama/Llama-3.2-3B-Instruct", "lora_rank": r, "max_generations": 1}
            for r in [4, 8, 16, 32, 64]
        ],
    },
}


def get_campaign(campaign_id: str) -> dict | None:
    return CAMPAIGNS.get(campaign_id)
