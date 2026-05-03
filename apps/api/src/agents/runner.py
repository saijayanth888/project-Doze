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
from services.lineage_db import LineageDB
from services.n8n_webhook import build_evolution_payload, post_evolution_event
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


def _select_backends(prefer_real: bool) -> tuple[TrainingBackend, EvalBackend]:
    if not prefer_real:
        return MockTrainingBackend(), MockEvalBackend()
    try:
        return LoRATrainingBackend(), LMEvalHarnessBackend()
    except Exception as exc:
        logger.warning("GPU backends unavailable (%s) — falling back to mock backends.", exc)
        return MockTrainingBackend(), MockEvalBackend()


async def _run(run_id: str, config: dict, db: LineageDB) -> None:
    """Drive the graph, persisting after every node."""
    gpu = get_gpu_status()
    prefer_real = bool(gpu.get("gpu_available"))
    training, eval_backend = _select_backends(prefer_real)
    logger.info(
        "[evolution %s] starting (training=%s, eval=%s, gpu=%s)",
        run_id,
        training.name,
        eval_backend.name,
        prefer_real,
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
                    "decision_reason": s.get("decision_reason"),
                    "method": s.get("method"),
                    "training_data_size": s.get("training_data_size", 0),
                    "duration_seconds": (
                        s.get("training_seconds", 0.0) + s.get("eval_seconds", 0.0)
                    ),
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
                )
            )

    graph = build_graph(
        training=training,
        eval_backend=eval_backend,
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
                )
            )
        logger.info(
            "[evolution %s] finished — last gen %s, champion avg %.4f",
            run_id,
            final.get("generation"),
            final.get("champion_avg", 0.0),
        )
    except Exception as exc:
        logger.exception("[evolution %s] failed", run_id)
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
