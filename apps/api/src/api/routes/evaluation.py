"""Benchmark scores, trends, and per-generation evaluation routes."""

import logging
from collections import defaultdict

from fastapi import APIRouter, Depends

from api.deps import get_db
from api.schemas.evaluation import (
    BenchmarkInfo,
    BenchmarkResult,
    BenchmarksResponse,
    ScoresResponse,
    ScoreTrend,
)
from services.lineage_db import LineageDB
from services.mock_data import mock_score_trends

logger = logging.getLogger("modelforge.routes.evaluation")

router = APIRouter()

# ---------------------------------------------------------------------------
# Static benchmark catalogue
# ---------------------------------------------------------------------------

_BENCHMARKS: list[dict] = [
    {
        "key": "mmlu",
        "label": "MMLU",
        "description": "Massive Multitask Language Understanding",
        "weight": 0.25,
    },
    {
        "key": "arc_challenge",
        "label": "ARC Challenge",
        "description": "AI2 Reasoning Challenge",
        "weight": 0.20,
    },
    {
        "key": "hellaswag",
        "label": "HellaSwag",
        "description": "Commonsense NLI",
        "weight": 0.20,
    },
    {
        "key": "gsm8k",
        "label": "GSM8K",
        "description": "Grade School Math",
        "weight": 0.20,
    },
    {
        "key": "humaneval",
        "label": "HumanEval",
        "description": "Code Generation",
        "weight": 0.15,
    },
]

_BENCHMARK_KEYS = [b["key"] for b in _BENCHMARKS]
_BENCHMARK_WEIGHTS: dict[str, float] = {b["key"]: b["weight"] for b in _BENCHMARKS}


def _weighted_avg(scores: dict[str, float]) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for key, weight in _BENCHMARK_WEIGHTS.items():
        if key in scores:
            weighted_sum += scores[key] * weight
            total_weight += weight
    return round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.0


@router.get("/scores", response_model=ScoresResponse)
async def get_scores(
    db: LineageDB = Depends(get_db),
) -> ScoresResponse:
    """Return benchmark score trends across all generations."""
    try:
        raw_trends = await db.get_score_trends()
    except Exception as exc:
        logger.warning("DB unavailable for score trends, using mock: %s", exc)
        raw_trends = []

    if not raw_trends:
        raw_trends = mock_score_trends()

    trends = [ScoreTrend(**t) for t in raw_trends]

    unique_gens = len({t.generation for t in trends})
    unique_benchmarks = len({t.benchmark for t in trends})

    return ScoresResponse(
        total_datapoints=len(trends),
        generations=unique_gens,
        benchmarks=unique_benchmarks,
        trends=trends,
    )


@router.get("/benchmarks", response_model=BenchmarksResponse)
async def get_benchmarks() -> BenchmarksResponse:
    """Return the standard benchmark catalogue with weights."""
    benchmarks = [BenchmarkInfo(**b) for b in _BENCHMARKS]
    return BenchmarksResponse(total=len(benchmarks), benchmarks=benchmarks)


@router.get("/generations", response_model=list[BenchmarkResult])
async def get_generation_results(
    db: LineageDB = Depends(get_db),
) -> list[BenchmarkResult]:
    """Return per-generation aggregated benchmark scores."""
    try:
        raw_trends = await db.get_score_trends()
    except Exception as exc:
        logger.warning("DB unavailable for generation results, using mock: %s", exc)
        raw_trends = []

    if not raw_trends:
        raw_trends = mock_score_trends()

    # Group trends by generation, collect child_score per benchmark
    gen_scores: dict[int, dict[str, float]] = defaultdict(dict)
    gen_promoted: dict[int, bool] = {}

    for trend in raw_trends:
        if isinstance(trend, dict):
            gen = trend["generation"]
            bm = trend["benchmark"]
            child_score = trend["child_score"]
            promoted = trend.get("promoted", False)
        else:
            gen = trend.generation
            bm = trend.benchmark
            child_score = trend.child_score
            promoted = trend.promoted

        gen_scores[gen][bm] = child_score
        gen_promoted[gen] = promoted

    results: list[BenchmarkResult] = []
    for gen in sorted(gen_scores.keys()):
        scores = gen_scores[gen]
        avg = _weighted_avg(scores)
        results.append(
            BenchmarkResult(
                generation=gen,
                scores=scores,
                avg_score=avg,
                promoted=gen_promoted.get(gen, False),
            )
        )

    return results


@router.get("/drift/{gen_a}/{gen_b}")
async def get_drift(gen_a: int, gen_b: int, db: LineageDB = Depends(get_db)):
    return await db.detect_drift(gen_a, gen_b)
