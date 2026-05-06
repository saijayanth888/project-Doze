"""Read-only aggregator that builds paper-grade experiment records.

The same data lives in `evolution_runs` (config / status / timestamps) and
`generations` (scores / decisions / training-data metadata persisted by the
runner's `save_generation` call). Rather than denormalize into a new table
that can drift, this module joins them on demand.

Output shape per record::

    {
      run_id, base_model, generation,
      config: {lora_rank, lora_alpha, learning_rate, batch_size, max_samples},
      training_data: {
        curated_count, self_generated_count,
        source_benchmarks, held_out_benchmarks
      },
      training_metrics: {
        final_loss, training_duration_sec, tokens_trained
      },
      eval_results: {
        per_benchmark_scores, parent_scores, delta_per_benchmark,
        pareto_dominant, decision, decision_reason
      },
      system_metrics: {
        gpu_name, peak_memory_gb, total_duration_sec
      }
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable

from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.experiments")


def _coerce_jsonb(val: Any) -> Any:
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val


async def build_records(db: LineageDB, *, limit: int = 500) -> list[dict[str, Any]]:
    """Return one experiment record per (run, generation) row, newest run first."""
    if db is None:
        return []
    runs = await db.list_runs(include_archived=True, limit=int(limit))
    out: list[dict[str, Any]] = []
    for run in runs or []:
        run_id = run.get("run_id")
        if not run_id:
            continue
        cfg = _coerce_jsonb(run.get("config")) or {}
        try:
            gens = await db.get_all_generations(run_id=run_id)
        except Exception as exc:
            logger.debug("get_all_generations(%s) failed: %s", run_id, exc)
            gens = []
        # Each `gen.data` is the JSONB blob the runner persisted with all the
        # methodology metadata (curated_sample_count, trained_benchmarks,
        # pareto_report, etc.). Pull it back out.
        for g in gens or []:
            data = _coerce_jsonb(g.get("data")) or {}
            child_scores = _coerce_jsonb(g.get("child_scores")) or {}
            parent_scores = _coerce_jsonb(g.get("parent_scores")) or {}
            delta = {
                k: round(float(child_scores[k]) - float(parent_scores.get(k, 0.0)), 5)
                for k in child_scores
                if isinstance(child_scores.get(k), (int, float))
                and isinstance(parent_scores.get(k), (int, float))
            }
            pareto = _coerce_jsonb(data.get("pareto_report")) or {}
            out.append({
                "run_id": run_id,
                "base_model": run.get("base_model"),
                "generation": int(g.get("generation") or 0),
                "config": {
                    "lora_rank":     cfg.get("lora_rank"),
                    "lora_alpha":    cfg.get("lora_alpha"),
                    "learning_rate": cfg.get("learning_rate"),
                    "batch_size":    cfg.get("batch_size"),
                    "max_samples":   cfg.get("max_samples"),
                },
                "training_data": {
                    "curated_count":         data.get("curated_sample_count"),
                    "self_generated_count":  data.get("self_generated_count"),
                    "source_benchmarks":     data.get("trained_benchmarks") or _coerce_jsonb(g.get("weak_categories")) or [],
                    "held_out_benchmarks":   data.get("held_out_benchmarks") or [],
                },
                "training_metrics": {
                    # final_loss / tokens_trained are only available when the
                    # SFTTrainer callback writes them — currently None for older
                    # rows. The export consumer should treat them as optional.
                    "final_loss":            data.get("final_loss"),
                    "training_duration_sec": data.get("training_seconds") or g.get("duration_seconds"),
                    "tokens_trained":        data.get("tokens_trained"),
                },
                "eval_results": {
                    "per_benchmark_scores":  child_scores,
                    "parent_scores":         parent_scores,
                    "delta_per_benchmark":   delta,
                    "pareto_dominant":       bool(pareto.get("promote")) if pareto else None,
                    "decision":              "promoted" if g.get("promoted") else "discarded",
                    "decision_reason":       g.get("decision_reason"),
                    "trained_benchmark_delta":  data.get("trained_benchmark_delta"),
                    "held_out_benchmark_delta": data.get("held_out_benchmark_delta"),
                },
                "system_metrics": {
                    "gpu_name":           data.get("gpu_name"),
                    "peak_memory_gb":     data.get("peak_memory_gb"),
                    "total_duration_sec": (
                        float(data.get("training_seconds") or 0.0)
                        + float(data.get("eval_seconds") or 0.0)
                    ) or None,
                },
                "timestamps": {
                    "created_at":    g.get("created_at"),
                    "run_started":   run.get("started_at"),
                    "run_completed": run.get("completed_at"),
                    "archived_at":   run.get("archived_at"),
                },
            })
    return out


def to_csv_rows(records: Iterable[dict]) -> list[list[str]]:
    """Flatten the nested records into CSV rows. Header first."""
    benches = ["mmlu", "arc_challenge", "hellaswag", "gsm8k", "humaneval"]
    header = [
        "run_id", "base_model", "generation",
        "lora_rank", "lora_alpha", "learning_rate", "batch_size", "max_samples",
        "curated_count", "self_generated_count",
        "source_benchmarks", "held_out_benchmarks",
        "final_loss", "training_duration_sec", "tokens_trained",
        "decision", "pareto_dominant",
        "trained_benchmark_delta", "held_out_benchmark_delta",
        *[f"score_{b}" for b in benches],
        *[f"delta_{b}" for b in benches],
        "decision_reason",
        "created_at",
    ]
    rows: list[list[str]] = [header]
    for r in records:
        cfg = r.get("config") or {}
        td = r.get("training_data") or {}
        tm = r.get("training_metrics") or {}
        er = r.get("eval_results") or {}
        scores = er.get("per_benchmark_scores") or {}
        deltas = er.get("delta_per_benchmark") or {}
        rows.append([
            str(r.get("run_id") or ""),
            str(r.get("base_model") or ""),
            str(r.get("generation") or ""),
            str(cfg.get("lora_rank") or ""),
            str(cfg.get("lora_alpha") or ""),
            str(cfg.get("learning_rate") or ""),
            str(cfg.get("batch_size") or ""),
            str(cfg.get("max_samples") or ""),
            str(td.get("curated_count") or ""),
            str(td.get("self_generated_count") or ""),
            "|".join(td.get("source_benchmarks") or []),
            "|".join(td.get("held_out_benchmarks") or []),
            str(tm.get("final_loss") if tm.get("final_loss") is not None else ""),
            str(tm.get("training_duration_sec") if tm.get("training_duration_sec") is not None else ""),
            str(tm.get("tokens_trained") if tm.get("tokens_trained") is not None else ""),
            str(er.get("decision") or ""),
            str(er.get("pareto_dominant") if er.get("pareto_dominant") is not None else ""),
            str(er.get("trained_benchmark_delta") if er.get("trained_benchmark_delta") is not None else ""),
            str(er.get("held_out_benchmark_delta") if er.get("held_out_benchmark_delta") is not None else ""),
            *[f"{float(scores.get(b)):.4f}" if isinstance(scores.get(b), (int, float)) else "" for b in benches],
            *[f"{float(deltas.get(b)):+.4f}" if isinstance(deltas.get(b), (int, float)) else "" for b in benches],
            str(er.get("decision_reason") or "").replace("\n", " ").replace("\r", " "),
            str(r.get("timestamps", {}).get("created_at") or ""),
        ])
    return rows
