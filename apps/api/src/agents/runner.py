"""Runner: kicks the LangGraph evolution agent off as a background task.

Responsibilities:

- Choose the right backends (mock on Mac, real on DGX) based on
  ``utils.gpu.get_gpu_status()``.
- Persist every state transition into ``LineageDB`` so the existing REST
  and WebSocket endpoints continue to work unchanged.
- Track per-run cancellation flags for ``POST /api/evolve/{id}/stop``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from agents.eval_backend import (
    EvalBackend,
    LMEvalHarnessBackend,
    MockEvalBackend,
)
from agents.evolution_graph import EvolutionState, _avg, build_graph
from agents.training_backend import (
    LoRATrainingBackend,
    MockTrainingBackend,
    TrainingBackend,
)
from services.data_curator import (
    DataCuratorBackend,
    HuggingFaceDataCurator,
    MockDataCurator,
)
from services import run_events
from services.lineage_db import LineageDB
from services.model_registry import ModelRegistry


async def _notify_automation(message: str, emoji: str, *, event_type: str | None = None) -> None:
    """Best-effort fan-out to the in-process automation engine (Slack + log).

    Wrapped in try/except so a notify failure can never abort an evolution
    run. The engine is a no-op when not yet attached (e.g. during tests or
    before APScheduler ships in the image).
    """
    try:
        from services.automation import get_engine
        eng = get_engine()
        if eng:
            await eng.notify(message, emoji, event_type=event_type)
    except Exception:
        pass
from services.n8n_webhook import (
    build_evolution_payload,
    emit_evolution_complete,
    post_evolution_event,
)
from utils.gpu import get_gpu_status

logger = logging.getLogger("modelforge.agents.runner")

# ── In-process registry ─────────────────────────────────────────
_TASKS: dict[str, asyncio.Task] = {}
_CANCEL_FLAGS: dict[str, bool] = {}


def request_stop(run_id: str) -> bool:
    """Mark ``run_id`` for cooperative cancellation. Returns True if known."""
    if run_id not in _TASKS:
        return False
    _CANCEL_FLAGS[run_id] = True
    return True


def _select_backends(prefer_real: bool) -> tuple[TrainingBackend, EvalBackend, DataCuratorBackend]:
    if not prefer_real:
        return MockTrainingBackend(), MockEvalBackend(), MockDataCurator()
    try:
        curator: DataCuratorBackend
        try:
            curator = HuggingFaceDataCurator()
        except Exception as exc:
            logger.warning("Curator backend unavailable (%s) — using mock curator.", exc)
            curator = MockDataCurator()
        return LoRATrainingBackend(), LMEvalHarnessBackend(), curator
    except Exception as exc:
        logger.warning("GPU backends unavailable (%s) — falling back to mock backends.", exc)
        return MockTrainingBackend(), MockEvalBackend(), MockDataCurator()


async def _run(run_id: str, config: dict, db: LineageDB) -> None:
    """Drive the graph, persisting after every node."""
    gpu = get_gpu_status()
    prefer_real = bool(gpu.get("gpu_available"))
    training, eval_backend, curator = _select_backends(prefer_real)
    logger.info(
        "[evolution %s] starting (training=%s, eval=%s, curator=%s, gpu=%s)",
        run_id,
        training.name,
        eval_backend.name,
        getattr(curator, "name", "unknown"),
        prefer_real,
    )
    # Wipe any stale buffer from a previous run with the same id (re-runs after
    # a stop/restart) so the events panel shows a clean timeline.
    run_events.reset_run(run_id)
    run_events.publish(
        run_id,
        phase="init",
        label=f"Run {run_id} started",
        sub=f"training={training.name} · eval={eval_backend.name} · curator={getattr(curator, 'name', '?')} · gpu={prefer_real}",
    )
    await _notify_automation(
        f"Evolution started: {config.get('base_model','?')} × {config.get('max_generations','?')} gen — run {run_id}",
        "🚀",
        event_type="evolution_started",
    )

    state: EvolutionState = {
        "run_id": run_id,
        "config": config,
        "generation": 0,
        "max_generations": int(config.get("max_generations", 10)),
        "parent_scores": {},
        "child_scores": {},
        "decision": "",
        "decision_reason": "",
        "method": "",
        "adapter_path": None,
        "training_data_size": 0,
        "training_seconds": 0.0,
        "eval_seconds": 0.0,
        "cancelled": False,
        "error": None,
        "champion_path": None,
        "champion_avg": 0.0,
    }

    async def on_state_change(s: EvolutionState, step: str) -> None:
        # Cooperative cancellation
        if _CANCEL_FLAGS.get(run_id):
            s["cancelled"] = True

        await db.update_run_status(
            run_id,
            status="stopped"
            if s.get("cancelled")
            else ("running" if not s.get("error") else "failed"),
            generation=s.get("generation", 0),
            current_step=step,
            error=s.get("error"),
        )

        # Persist a generation row whenever we just finished a decision.
        if step == "promote_or_discard" and s.get("child_scores"):
            await db.save_generation(
                run_id,
                {
                    "generation": s["generation"],
                    "promoted": s.get("decision") == "promote",
                    "is_champion": s.get("decision") == "promote",
                    "parent_scores": s.get("parent_scores", {}),
                    "child_scores": s.get("child_scores", {}),
                    "weak_categories": s.get("weak_categories", []),
                    "decision_reason": s.get("decision_reason"),
                    "method": s.get("method"),
                    "training_data_size": s.get("training_data_size", 0),
                    # Persist the full run config so AdaptersPage can show
                    # training hyperparameters (lora_rank/alpha/lr/batch/base) in
                    # its detail pane. The route already reads `data.config`.
                    "config": dict(config or {}),
                    "duration_seconds": (
                        s.get("training_seconds", 0.0) + s.get("eval_seconds", 0.0)
                    ),
                    # ── Methodology metadata for the paper (Phase-3 patch) ──
                    # Also persisted in the generation row's `data` JSONB so
                    # the read path can recover them without a schema migration.
                    "curated_sample_count": int(s.get("curated_sample_count") or 0),
                    "self_generated_count": int(s.get("self_generated_count") or 0),
                    "trained_benchmarks": list(s.get("trained_benchmarks") or []),
                    "held_out_benchmarks": list(s.get("held_out_benchmarks") or []),
                    "trained_benchmark_delta": s.get("trained_benchmark_delta"),
                    "held_out_benchmark_delta": s.get("held_out_benchmark_delta"),
                    "regression_report": s.get("regression_report"),
                    "pareto_report": s.get("pareto_report"),
                    "training_seconds": float(s.get("training_seconds") or 0.0),
                    "eval_seconds": float(s.get("eval_seconds") or 0.0),
                },
            )
            for benchmark, score in s.get("child_scores", {}).items():
                await db.save_score(
                    run_id=run_id,
                    generation=s["generation"],
                    benchmark=benchmark,
                    score=float(score),
                    promoted=s.get("decision") == "promote",
                )

            # Sync the file-based registry so /api/models/champion (read by the
            # dashboard Champion card) reflects the new winner. Without this the
            # dashboard sticks on the previous champion forever even after a
            # successful promotion lands in Postgres.
            if s.get("decision") == "promote":
                try:
                    raw_base = str((config or {}).get("base_model") or "").strip()
                    try:
                        from utils.hf_model_id import resolve_hf_base_model_id
                        base_model_resolved = resolve_hf_base_model_id(raw_base or None)
                    except Exception:
                        base_model_resolved = raw_base or "unknown"
                    scores = {k: float(v) for k, v in s.get("child_scores", {}).items()}
                    avg = sum(scores.values()) / len(scores) if scores else 0.0
                    info = {
                        "name": f"mf-{run_id}-g{s['generation']}",
                        "base_model": base_model_resolved,
                        "generation": int(s["generation"]),
                        "adapter_path": s.get("adapter_path"),
                        "adapter_id": f"{run_id}__gen{s['generation']}",
                        "scores": scores,
                        "avg_score": round(avg, 4),
                        "method": s.get("method"),
                        "ollama_model": None,
                        "promoted_at": datetime.now(timezone.utc).isoformat(),
                    }
                    ModelRegistry().set_champion(info)
                    logger.info(
                        "[evolution %s] champion updated in registry: gen=%d avg=%.4f",
                        run_id, s["generation"], info["avg_score"],
                    )
                except Exception as exc:
                    logger.warning("[evolution %s] failed to update champion registry: %s", run_id, exc)

            evt = "champion_promoted" if s.get("decision") == "promote" else "generation_complete"
            base_model = str((config or {}).get("base_model") or "unknown")
            dur = float(s.get("training_seconds", 0.0) or 0.0) + float(
                s.get("eval_seconds", 0.0) or 0.0
            )
            await post_evolution_event(
                build_evolution_payload(
                    event_type=evt,
                    run_id=run_id,
                    generation=s["generation"],
                    decision=s.get("decision"),
                    decision_reason=s.get("decision_reason"),
                    child_scores=s.get("child_scores"),
                    champion_avg=s.get("champion_avg"),
                    step="promote_or_discard",
                    total_generations=int(s.get("max_generations", 0) or 0),
                    duration_seconds=dur or None,
                    champion_model_id=f"{base_model}@gen{s['generation']}",
                    weak_categories=s.get("weak_categories", []),
                )
            )
            # In-process Slack/log fan-out (replaces n8n).
            scs = s.get("child_scores") or {}
            avg = sum(float(v) for v in scs.values()) / max(1, len(scs))
            promoted = s.get("decision") == "promote"
            await _notify_automation(
                f"Gen {s['generation']} {'promoted' if promoted else 'discarded'} — avg {avg:.3f}"
                + (f" ({s.get('decision_reason')})" if not promoted and s.get('decision_reason') else ""),
                "🏆" if promoted else "❌",
                event_type="champion_promoted" if promoted else "generation_complete",
            )

    graph = build_graph(
        training=training,
        eval_backend=eval_backend,
        curator=curator,
        on_state_change=on_state_change,
    )

    try:
        await db.update_run_status(run_id, status="running", current_step="starting")
        final: dict[str, Any] = await graph.ainvoke(state)
        if final.get("cancelled"):
            await db.update_run_status(
                run_id,
                status="stopped",
                generation=final.get("generation", 0),
                current_step="cancelled",
            )
        else:
            await db.complete_run(run_id)
            fc = final.get("config") or {}
            if not isinstance(fc, dict):
                fc = {}
            base_model = str(fc.get("base_model") or "unknown")
            await post_evolution_event(
                build_evolution_payload(
                    event_type="run_complete",
                    run_id=run_id,
                    generation=int(final.get("generation", 0)),
                    champion_avg=float(final.get("champion_avg", 0.0)),
                    child_scores=final.get("child_scores"),
                    step="complete",
                    total_generations=int(final.get("generation", 0) or 0),
                    duration_seconds=float(final.get("training_seconds", 0.0) or 0.0)
                    + float(final.get("eval_seconds", 0.0) or 0.0),
                    champion_model_id=f"{base_model}@gen{int(final.get('generation', 0) or 0)}",
                    weak_categories=final.get("weak_categories", []),
                )
            )
            await emit_evolution_complete(
                run_id,
                {
                    "champion_avg": float(final.get("champion_avg", 0.0)),
                    "final_scores": final.get("child_scores") or {},
                    "generations_completed": int(final.get("generation", 0) or 0),
                    "base_model": base_model,
                },
            )
            await _notify_automation(
                f"Run complete — champion avg {float(final.get('champion_avg', 0.0)):.3f} "
                f"after {int(final.get('generation', 0) or 0)} generation(s)",
                "✅",
                event_type="evolution_complete",
            )
        logger.info(
            "[evolution %s] finished — last gen %s, champion avg %.4f",
            run_id,
            final.get("generation"),
            final.get("champion_avg", 0.0),
        )
        run_events.publish(
            run_id,
            phase="init",
            label=f"Run finished — last gen {final.get('generation')}",
            sub=f"champion avg {final.get('champion_avg', 0.0):.4f}",
        )
    except Exception as exc:
        run_events.publish(
            run_id,
            phase="error",
            level="error",
            label=f"Run failed: {type(exc).__name__}",
            sub=str(exc)[:300],
        )
        logger.exception("[evolution %s] failed", run_id)
        await _notify_automation(
            f"Run {run_id} failed: {type(exc).__name__}: {str(exc)[:200]}",
            "🔴",
            event_type="evolution_failed",
        )
        await db.update_run_status(
            run_id,
            status="failed",
            generation=state.get("generation", 0),
            current_step="error",
            error=str(exc),
        )
        await post_evolution_event(
            build_evolution_payload(
                event_type="error",
                run_id=run_id,
                generation=int(state.get("generation", 0)),
                error=str(exc),
                step="error",
            )
        )
    finally:
        _TASKS.pop(run_id, None)
        _CANCEL_FLAGS.pop(run_id, None)


def start_evolution(run_id: str, config: dict, db: LineageDB) -> asyncio.Task:
    """Launch ``_run`` as a fire-and-forget asyncio task and remember it."""
    if run_id in _TASKS:
        raise RuntimeError(f"Run {run_id} is already in flight")
    task = asyncio.create_task(_run(run_id, config, db), name=f"evolution:{run_id}")
    _TASKS[run_id] = task
    _CANCEL_FLAGS[run_id] = False
    return task


# Re-exported for tests/inspection.
__all__ = ["_avg", "request_stop", "start_evolution"]
