"""Benchmark scores, trends, and per-generation evaluation routes."""

import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query

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


@router.get("/compare-runs")
async def compare_runs(
    run_ids: str = Query(..., description="Comma-separated run IDs"),
    db: LineageDB = Depends(get_db),
) -> dict[str, Any]:
    """Compare champion scores across multiple evolution runs."""
    ids = [r.strip() for r in run_ids.split(",") if r.strip()]
    results: dict[str, Any] = {}
    for run_id in ids:
        try:
            gens = await db.get_all_generations(run_id)
        except Exception as exc:
            logger.warning("compare_runs %s: %s", run_id, exc)
            gens = []
        if not gens:
            results[run_id] = {
                "generations": 0,
                "promoted": 0,
                "final_scores": {},
                "improvement": {},
            }
            continue
        first = gens[0]
        last = gens[-1]
        first_scores = first.get("child_scores") or {}
        last_scores = last.get("child_scores") or {}
        if isinstance(first_scores, str):
            try:
                first_scores = json.loads(first_scores)
            except Exception:
                first_scores = {}
        if isinstance(last_scores, str):
            try:
                last_scores = json.loads(last_scores)
            except Exception:
                last_scores = {}
        improvement: dict[str, float] = {}
        keys = set(first_scores.keys()) | set(last_scores.keys())
        for k in keys:
            try:
                improvement[str(k)] = float(last_scores.get(k, 0)) - float(first_scores.get(k, 0))
            except (TypeError, ValueError):
                improvement[str(k)] = 0.0
        results[run_id] = {
            "generations": len(gens),
            "promoted": sum(1 for g in gens if g.get("promoted")),
            "final_scores": last_scores if isinstance(last_scores, dict) else {},
            "improvement": improvement,
        }
    return results
