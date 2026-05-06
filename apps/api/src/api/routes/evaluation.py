"""Benchmark scores, trends, and per-generation evaluation routes."""

import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.deps import get_db, get_registry
from api.schemas.evaluation import (
    BenchmarkInfo,
    BenchmarkResult,
    BenchmarksResponse,
    ScoresResponse,
    ScoreTrend,
)
from services.lineage_db import LineageDB
from services.model_registry import ModelRegistry

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

# Registry / external tools sometimes use non-canonical keys; normalize for charts and weighted avg.
_BENCHMARK_ALIASES: dict[str, str] = {
    "mmlu": "mmlu",
    "mmlu_eval": "mmlu",
    "mmlueval": "mmlu",
    "arc_challenge": "arc_challenge",
    "arc_c": "arc_challenge",
    "arcc": "arc_challenge",
    "hellaswag": "hellaswag",
    "gsm8k": "gsm8k",
    "humaneval": "humaneval",
}


def _canonical_benchmark_key(key: str) -> str | None:
    k = str(key).strip().lower().replace("-", "_")
    cand = _BENCHMARK_ALIASES.get(k) or (k if k in _BENCHMARK_WEIGHTS else None)
    return cand if cand in _BENCHMARK_WEIGHTS else None


def _normalize_trend_row(t: Any) -> Any:
    if not isinstance(t, dict):
        return t
    bm = t.get("benchmark")
    if bm is None:
        return t
    canon = _canonical_benchmark_key(str(bm))
    if canon:
        return {**t, "benchmark": canon}
    return t


def _weighted_avg(scores: dict[str, float]) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for key, weight in _BENCHMARK_WEIGHTS.items():
        if key in scores:
            weighted_sum += scores[key] * weight
            total_weight += weight
    return round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.0


def _registry_champion_trends_and_results(
    registry: ModelRegistry,
) -> tuple[list[dict], list[BenchmarkResult]]:
    """When Postgres has no score rows, use champion ``scores`` from ``registry.json`` if present."""
    from api.routes.models import _normalize_champion_dict

    raw = registry.get_champion()
    if not isinstance(raw, dict):
        return [], []
    norm = _normalize_champion_dict(raw)
    scores_in = norm.get("scores") or {}
    if not isinstance(scores_in, dict) or not scores_in:
        return [], []

    scores: dict[str, float] = {}
    for k, v in scores_in.items():
        canon = _canonical_benchmark_key(str(k))
        if canon is None:
            continue
        try:
            scores[canon] = float(v)
        except (TypeError, ValueError):
            continue
    if not scores:
        return [], []

    try:
        gen = int(norm.get("generation", 0) or 0)
    except (TypeError, ValueError):
        gen = 0
    promoted = True
    trends: list[dict] = []
    for bm, child_score in scores.items():
        trends.append(
            {
                "generation": gen,
                "benchmark": bm,
                "parent_score": 0.0,
                "child_score": child_score,
                "delta": child_score,
                "promoted": promoted,
            }
        )
    avg = _weighted_avg(scores)
    results = [
        BenchmarkResult(
            generation=gen,
            scores=scores,
            avg_score=avg,
            promoted=promoted,
        )
    ]
    return trends, results


@router.get("/scores", response_model=ScoresResponse)
async def get_scores(
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> ScoresResponse:
    """Return benchmark score trends across all generations."""
    raw_trends: list = []
    try:
        if await db.has_evolution_runs():
            raw_trends = await db.get_score_trends()
    except Exception as exc:
        logger.warning("DB unavailable for score trends: %s", exc)
        raw_trends = []

    if not raw_trends:
        reg_trends, _ = _registry_champion_trends_and_results(registry)
        raw_trends = reg_trends

    raw_trends = [_normalize_trend_row(t) for t in raw_trends]

    if not raw_trends:
        return ScoresResponse(
            total_datapoints=0,
            generations=0,
            benchmarks=0,
            trends=[],
        )

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
    registry: ModelRegistry = Depends(get_registry),
) -> list[BenchmarkResult]:
    """Return per-generation aggregated benchmark scores."""
    raw_trends: list = []
    try:
        if await db.has_evolution_runs():
            raw_trends = await db.get_score_trends()
    except Exception as exc:
        logger.warning("DB unavailable for generation results: %s", exc)
        raw_trends = []

    if not raw_trends:
        _, reg_results = _registry_champion_trends_and_results(registry)
        return reg_results

    raw_trends = [_normalize_trend_row(t) for t in raw_trends]

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

    if not results:
        _, reg_results = _registry_champion_trends_and_results(registry)
        return reg_results

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
