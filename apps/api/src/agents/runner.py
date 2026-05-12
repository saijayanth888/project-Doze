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
    TradingEvalBackend,
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
    """Plain-text fan-out to the in-process automation engine.

    Wrapped in try/except so a notify failure can never abort an evolution
    run. The engine is a no-op when not yet attached.
    """
    try:
        from services.automation import get_engine
        eng = get_engine()
        if eng:
            await eng.notify(message, emoji, event_type=event_type)
    except Exception:
        pass


async def _notify_blocks(
    text: str,
    blocks: list,
    *,
    event_type: str | None,
    log_message: str | None = None,
) -> None:
    """Rich Block Kit notification — see :mod:`services.slack_blocks`.

    Falls back to plain ``notify(text)`` when no engine is attached.
    """
    try:
        from services.automation import get_engine
        eng = get_engine()
        if not eng:
            return
        # Engines that haven't been upgraded yet won't have notify_blocks.
        if hasattr(eng, "notify_blocks"):
            await eng.notify_blocks(text, blocks, event_type=event_type, log_message=log_message)
        else:
            await eng.notify(text, "🔔", event_type=event_type)
    except Exception:
        pass


def _emit_event(topic: str, payload: dict | None = None) -> None:
    """Publish a domain event for event-triggered workflows.

    Best-effort + sync-callable: never raises, never blocks. Workflows whose
    trigger pattern matches will fire in parallel via the bus.
    """
    try:
        from services.event_bus import bus
        bus.publish_nowait(topic, payload or {})
    except Exception:
        pass


def _avg_subset(scores: dict | None, keys: list[str]) -> float | None:
    """Average ``scores[k]`` across only the keys present and numeric."""
    if not isinstance(scores, dict):
        return None
    vals = [float(scores[k]) for k in keys if isinstance(scores.get(k), (int, float))]
    return (sum(vals) / len(vals)) if vals else None


async def _maybe_promote_to_tracks(
    db: LineageDB,
    *,
    run_id: str,
    generation: int,
    adapter_path: str | None,
    child_scores: dict,
) -> None:
    """For each enabled track, promote the new champion if it beats the
    current track champion *on that track's target benchmarks*.

    A track's owner is whichever adapter is best on its target benches —
    independent of which run produced it. A run that targeted a broad set of
    benches can win multiple tracks; a run that targeted only one bench
    wins at most that track. Auto-promotion is skipped when the new
    champion has no scores for any of the track's target benches (avoids
    promoting on the broken-extraction zeros we saw in Phase-2).
    """
    try:
        tracks = await db.list_tracks()
    except Exception as exc:
        logger.warning("[track] list_tracks failed: %s", exc)
        return
    for track in tracks:
        if not track.get("enabled"):
            continue
        targets = list(track.get("target_benchmarks") or [])
        if not targets:
            continue
        new_avg = _avg_subset(child_scores, targets)
        if new_avg is None or new_avg <= 0:
            # No usable scores for this track's benches — skip.
            continue
        prev_scores = track.get("champion_scores") or {}
        prev_avg = _avg_subset(prev_scores, targets) if prev_scores else None
        if prev_avg is not None and new_avg <= prev_avg:
            continue
        try:
            await db.update_track_champion(
                track["track_id"],
                run_id=run_id,
                generation=int(generation),
                adapter_path=adapter_path,
                scores=child_scores,
            )
            try:
                await db.insert_track_generation({
                    "track_id": track["track_id"],
                    "generation": int(generation),
                    "run_id": run_id,
                    "scores": child_scores,
                    "promoted": True,
                    "adapter_path": adapter_path,
                })
            except Exception as exc:
                logger.debug("[track] insert_track_generation failed: %s", exc)
            logger.info(
                "[track] %s now owned by %s::gen%s — avg over %s: %.4f (was %s)",
                track["track_id"], run_id, generation, targets, new_avg,
                f"{prev_avg:.4f}" if prev_avg is not None else "n/a",
            )
            _emit_event("track.promoted", {
                "track_id": track["track_id"],
                "track_name": track.get("name"),
                "run_id": run_id,
                "generation": int(generation),
                "scores": dict(child_scores),
                "new_avg": round(new_avg, 4),
                "prev_avg": round(prev_avg, 4) if prev_avg is not None else None,
                "target_benchmarks": targets,
            })
            try:
                from services.slack_blocks import track_promoted as _track_blocks
                _t_text, _t_blocks = _track_blocks(
                    track_id=str(track["track_id"]),
                    track_name=str(track.get("name") or track["track_id"]),
                    run_id=run_id, generation=int(generation),
                    new_avg=float(new_avg),
                    prev_avg=float(prev_avg) if prev_avg is not None else None,
                    target_benchmarks=list(targets),
                    full_scores=dict(child_scores),
                )
                await _notify_blocks(_t_text, _t_blocks, event_type="track_promoted")
            except Exception as exc:
                logger.debug("[track] slack notify failed: %s", exc)
        except Exception as exc:
            logger.warning("[track] update_track_champion(%s) failed: %s",
                           track["track_id"], exc)
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
    # Task #46 path A: wrap the chosen eval backend in TradingEvalBackend so
    # runs whose config carries a registered ``track_id`` dispatch to the
    # per-track scorer (reflector / debater / arbiter / structured_json /
    # regime_tagger / indicator_selector). Non-trading runs fall through to
    # the wrapped fallback (Mock or LMEvalHarness) -- additive-only.
    if not prefer_real:
        return (
            MockTrainingBackend(),
            TradingEvalBackend(fallback=MockEvalBackend()),
            MockDataCurator(),
        )
    try:
        curator: DataCuratorBackend
        try:
            curator = HuggingFaceDataCurator()
        except Exception as exc:
            logger.warning("Curator backend unavailable (%s) — using mock curator.", exc)
            curator = MockDataCurator()
        return (
            LoRATrainingBackend(),
            TradingEvalBackend(fallback=LMEvalHarnessBackend()),
            curator,
        )
    except Exception as exc:
        logger.warning("GPU backends unavailable (%s) — falling back to mock backends.", exc)
        return (
            MockTrainingBackend(),
            TradingEvalBackend(fallback=MockEvalBackend()),
            MockDataCurator(),
        )


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
    from services.slack_blocks import evolution_started as _ev_started_blocks
    _text, _blocks = _ev_started_blocks(run_id=run_id, config=dict(config or {}))
    await _notify_blocks(_text, _blocks, event_type="evolution_started")
    _emit_event("evolution.started", {
        "run_id": run_id,
        "base_model": config.get("base_model"),
        "max_generations": config.get("max_generations"),
        "config": config,
    })

    # Task #46 path A: mirror track_id from config into top-level state so
    # downstream nodes (and observers) can read it without re-parsing the
    # config dict. Empty/missing -> empty string (legacy/no-op path).
    _track_id = str((config or {}).get("track_id") or "").strip()

    state: EvolutionState = {
        "run_id": run_id,
        "config": config,
        "track_id": _track_id,
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
    if _track_id:
        logger.info("[evolution %s] track_id=%s — per-track eval dispatch enabled", run_id, _track_id)

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
                    "harness_version": s.get("harness_version", "unknown"),
                    "stderrs": dict(s.get("stderrs") or {}),
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
                    # Resolved canonical HuggingFace id for the run's base
                    # model (e.g. "meta-llama/Llama-3.2-3B-Instruct" even when
                    # the user-typed config had `llama3.2:3b`). Set by
                    # augment_training; harmless when unset for old rows.
                    "base_model_hf_id": s.get("base_model_hf_id"),
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

                # Auto-promote this champion into any track it beats on its
                # target benchmarks. Lights up the PEFT inference path on
                # /forge for that track. Best-effort — never aborts the run.
                try:
                    await _maybe_promote_to_tracks(
                        db,
                        run_id=run_id,
                        generation=int(s["generation"]),
                        adapter_path=s.get("adapter_path"),
                        child_scores=dict(s.get("child_scores") or {}),
                    )
                except Exception as exc:
                    logger.warning("[evolution %s] track auto-promotion failed: %s", run_id, exc)

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
            from services.slack_blocks import (
                generation_discarded as _gen_discarded_blocks,
                generation_promoted as _gen_promoted_blocks,
            )
            _builder = _gen_promoted_blocks if promoted else _gen_discarded_blocks
            _text, _blocks = _builder(
                run_id=run_id,
                generation=int(s["generation"]),
                child_scores=dict(s.get("child_scores") or {}),
                parent_scores=dict(s.get("parent_scores") or {}),
                decision_reason=s.get("decision_reason"),
                duration_seconds=dur if dur else None,
            )
            await _notify_blocks(
                _text, _blocks,
                event_type="champion_promoted" if promoted else "generation_complete",
            )
            # Domain events for workflow triggers.
            event_payload = {
                "run_id": run_id,
                "generation": int(s["generation"]),
                "child_scores": dict(s.get("child_scores") or {}),
                "child_avg": round(avg, 4),
                "decision": s.get("decision"),
                "decision_reason": s.get("decision_reason"),
                "promoted": bool(promoted),
            }
            _emit_event("generation.completed", event_payload)
            if promoted:
                _emit_event("champion.promoted", event_payload)
            else:
                _emit_event("generation.discarded", event_payload)

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
            from services.slack_blocks import evolution_completed as _ev_done_blocks
            _completed_text, _completed_blocks = _ev_done_blocks(
                run_id=run_id,
                final_scores=dict(final.get("child_scores") or {}),
                generations=int(final.get("generation", 0) or 0),
                base_model=base_model,
                duration_seconds=(
                    float(final.get("training_seconds", 0.0) or 0.0)
                    + float(final.get("eval_seconds", 0.0) or 0.0)
                ),
                champion_avg=float(final.get("champion_avg", 0.0)),
            )
            await _notify_blocks(_completed_text, _completed_blocks, event_type="evolution_complete")
            _emit_event("evolution.completed", {
                "run_id": run_id,
                "champion_avg": float(final.get("champion_avg", 0.0)),
                "generations": int(final.get("generation", 0) or 0),
                "child_scores": final.get("child_scores") or {},
                "base_model": base_model,
            })
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
        from services.slack_blocks import evolution_failed as _ev_fail_blocks
        _fail_text, _fail_blocks = _ev_fail_blocks(
            run_id=run_id,
            generation=int(state.get("generation", 0)),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        await _notify_blocks(_fail_text, _fail_blocks, event_type="evolution_failed")
        _emit_event("evolution.failed", {
            "run_id": run_id,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "generation": int(state.get("generation", 0)),
        })
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
