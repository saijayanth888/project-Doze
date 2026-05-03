"""Mock data for local Mac development. Same seed as frontend (mulberry32(42))."""


# ---------------------------------------------------------------------------
# Lineage tree
# ---------------------------------------------------------------------------


def mock_lineage_tree() -> dict:
    nodes = [
        {
            "id": "gen-0",
            "label": "Base Model",
            "generation": 0,
            "promoted": True,
            "scores": {
                "mmlu": 0.612,
                "arc_challenge": 0.578,
                "hellaswag": 0.721,
                "gsm8k": 0.412,
                "humaneval": 0.298,
            },
            "avg_score": 0.524,
            "is_champion": False,
            "method": "base",
            "decision_reason": "Initial base model",
            "parent_id": None,
        },
        {
            "id": "gen-1",
            "label": "Generation 1",
            "generation": 1,
            "promoted": True,
            "scores": {
                "mmlu": 0.638,
                "arc_challenge": 0.601,
                "hellaswag": 0.743,
                "gsm8k": 0.447,
                "humaneval": 0.321,
            },
            "avg_score": 0.550,
            "is_champion": False,
            "method": "lora",
            "decision_reason": "Improved across all benchmarks",
            "parent_id": "gen-0",
        },
        {
            "id": "gen-2",
            "label": "Generation 2",
            "generation": 2,
            "promoted": False,
            "scores": {
                "mmlu": 0.631,
                "arc_challenge": 0.595,
                "hellaswag": 0.739,
                "gsm8k": 0.441,
                "humaneval": 0.315,
            },
            "avg_score": 0.544,
            "is_champion": False,
            "method": "lora",
            "decision_reason": "Regressed from gen-1, discarded",
            "parent_id": "gen-1",
        },
        {
            "id": "gen-3",
            "label": "Generation 3",
            "generation": 3,
            "promoted": True,
            "scores": {
                "mmlu": 0.659,
                "arc_challenge": 0.624,
                "hellaswag": 0.761,
                "gsm8k": 0.468,
                "humaneval": 0.344,
            },
            "avg_score": 0.571,
            "is_champion": False,
            "method": "lora",
            "decision_reason": "Strong improvement on reasoning tasks",
            "parent_id": "gen-1",
        },
        {
            "id": "gen-4",
            "label": "Generation 4 ★",
            "generation": 4,
            "promoted": True,
            "scores": {
                "mmlu": 0.681,
                "arc_challenge": 0.647,
                "hellaswag": 0.778,
                "gsm8k": 0.491,
                "humaneval": 0.367,
            },
            "avg_score": 0.593,
            "is_champion": True,
            "method": "lora",
            "decision_reason": "Best overall performance — promoted to champion",
            "parent_id": "gen-3",
        },
    ]

    edges = [
        {"source": "gen-0", "target": "gen-1", "promoted": True},
        {"source": "gen-1", "target": "gen-2", "promoted": False},
        {"source": "gen-1", "target": "gen-3", "promoted": True},
        {"source": "gen-3", "target": "gen-4", "promoted": True},
    ]

    promoted_nodes = [n for n in nodes if n["promoted"]]
    champion = next((n for n in nodes if n["is_champion"]), None)

    return {
        "nodes": nodes,
        "edges": edges,
        "total_nodes": len(nodes),
        "total_promoted": len(promoted_nodes),
        "total_discarded": len(nodes) - len(promoted_nodes),
        "champion_id": champion["id"] if champion else None,
    }


# ---------------------------------------------------------------------------
# Score trends
# ---------------------------------------------------------------------------


def mock_score_trends() -> list[dict]:
    benchmarks = ["mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval"]
    base_scores = {
        "mmlu": 0.612,
        "arc_challenge": 0.578,
        "hellaswag": 0.721,
        "gsm8k": 0.412,
        "humaneval": 0.298,
    }
    deltas = {
        "mmlu": 0.017,
        "arc_challenge": 0.017,
        "hellaswag": 0.014,
        "gsm8k": 0.020,
        "humaneval": 0.017,
    }
    promoted_gens = {1, 3, 4}

    trends = []
    for gen in range(1, 5):
        promoted = gen in promoted_gens
        for bm in benchmarks:
            parent_score = round(base_scores[bm] + deltas[bm] * (gen - 1), 4)
            child_score = round(parent_score + (deltas[bm] if promoted else -0.006), 4)
            trends.append(
                {
                    "generation": gen,
                    "benchmark": bm,
                    "parent_score": parent_score,
                    "child_score": child_score,
                    "delta": round(child_score - parent_score, 4),
                    "promoted": promoted,
                }
            )
    return trends


# ---------------------------------------------------------------------------
# Champion
# ---------------------------------------------------------------------------


def mock_champion() -> dict:
    return {
        "generation": 4,
        "base_model": "llama3.2:3b",
        "adapter_path": "adapters/gen-4/adapter_model.safetensors",
        "scores": {
            "mmlu": 0.681,
            "arc_challenge": 0.647,
            "hellaswag": 0.778,
            "gsm8k": 0.491,
            "humaneval": 0.367,
        },
        "avg_score": 0.593,
        "method": "lora",
        "promoted_at": "2025-12-01T10:42:00Z",
    }


# ---------------------------------------------------------------------------
# Activity feed
# ---------------------------------------------------------------------------


def mock_activity_feed() -> list[dict]:
    return [
        {
            "id": "evt-8",
            "type": "champion_promoted",
            "message": "Generation 4 promoted to champion (avg 0.593)",
            "generation": 4,
            "run_id": "run-mock01",
            "timestamp": "2025-12-01T10:42:00Z",
        },
        {
            "id": "evt-7",
            "type": "generation_complete",
            "message": "Generation 4 evaluation complete",
            "generation": 4,
            "run_id": "run-mock01",
            "timestamp": "2025-12-01T10:38:00Z",
        },
        {
            "id": "evt-6",
            "type": "training_complete",
            "message": "Generation 4 LoRA training finished",
            "generation": 4,
            "run_id": "run-mock01",
            "timestamp": "2025-12-01T10:15:00Z",
        },
        {
            "id": "evt-5",
            "type": "generation_discarded",
            "message": "Generation 2 discarded — score regression",
            "generation": 2,
            "run_id": "run-mock01",
            "timestamp": "2025-11-30T22:05:00Z",
        },
        {
            "id": "evt-4",
            "type": "generation_complete",
            "message": "Generation 3 evaluation complete",
            "generation": 3,
            "run_id": "run-mock01",
            "timestamp": "2025-11-30T19:50:00Z",
        },
        {
            "id": "evt-3",
            "type": "generation_complete",
            "message": "Generation 2 evaluation complete",
            "generation": 2,
            "run_id": "run-mock01",
            "timestamp": "2025-11-30T17:30:00Z",
        },
        {
            "id": "evt-2",
            "type": "generation_complete",
            "message": "Generation 1 evaluation complete",
            "generation": 1,
            "run_id": "run-mock01",
            "timestamp": "2025-11-30T14:10:00Z",
        },
        {
            "id": "evt-1",
            "type": "run_started",
            "message": "Evolution run run-mock01 started",
            "generation": 0,
            "run_id": "run-mock01",
            "timestamp": "2025-11-30T12:00:00Z",
        },
    ]


# ---------------------------------------------------------------------------
# GPU status (mock for non-CUDA environments)
# ---------------------------------------------------------------------------


def mock_gpu_status() -> dict:
    return {
        "gpu_available": False,
        "device": "cpu",
        "cuda_available": False,
        "note": "Mock GPU status — no CUDA device detected",
    }
