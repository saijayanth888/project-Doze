"""Per-workflow execution.

Given a workflow row from Postgres + a trigger payload, this:

1. Records a ``automation_workflow_runs`` row in ``running`` state.
2. Builds the context (trigger payload + an empty ``last`` slot).
3. Evaluates the workflow's condition; short-circuits to ``skipped`` when false.
4. Runs each action sequentially, rendering its config template against the
   live context. Each action's output becomes ``context["last"]`` for the next.
5. Updates the run row with status, traces, error, and duration.
6. Mirrors a one-line summary onto the workflow row so the UI list can show it.

A single failing action ends the workflow with status ``failed`` and the error
text; subsequent actions are skipped (no retries — failures are explicit, the
user can click "Run now" again).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .actions import ACTION_REGISTRY, ActionResult, render_config
from .conditions import evaluate as evaluate_condition

logger = logging.getLogger("modelforge.automation.runner")


async def execute_workflow(
    *,
    workflow: dict[str, Any],
    trigger_kind: str,
    trigger_payload: dict[str, Any] | None,
    engine: Any,
) -> dict[str, Any]:
    """Run one workflow firing end-to-end. Returns a dict summary of the run."""
    workflow_id = str(workflow.get("id"))
    name = workflow.get("name") or "(unnamed)"
    db = engine.db
    started = time.perf_counter()
    payload = dict(trigger_payload or {})

    run_row = await db.start_workflow_run(
        workflow_id=workflow_id,
        trigger_kind=trigger_kind,
        trigger_payload=payload,
    )
    run_id = (run_row or {}).get("id")
    logger.info("[workflow:%s] start run_id=%s trigger=%s", name, run_id, trigger_kind)

    context: dict[str, Any] = {**payload, "last": {}, "workflow": {"id": workflow_id, "name": name}}
    step_traces: list[dict[str, Any]] = []
    final_status = "success"
    final_error: str | None = None
    summary_message = ""

    # ── 1. condition gate ──────────────────────────────────────────────
    condition = workflow.get("condition")
    try:
        passed = bool(evaluate_condition(condition, context))
    except Exception as exc:
        passed = False
        logger.warning("[workflow:%s] condition errored: %s", name, exc)
    if not passed:
        summary_message = "Condition false — skipped"
        await _finish(db, run_id, status="skipped", condition_passed=False,
                      step_traces=[], error=None, started=started)
        await db.record_workflow_run_summary(workflow_id, status="skipped", message=summary_message)
        logger.info("[workflow:%s] skipped — condition false", name)
        return {"workflow_id": workflow_id, "run_id": run_id, "status": "skipped",
                "message": summary_message, "step_traces": []}

    # ── 2. actions ─────────────────────────────────────────────────────
    actions: list[dict[str, Any]] = list(workflow.get("actions") or [])
    if not actions:
        summary_message = "No actions configured"
        await _finish(db, run_id, status="success", condition_passed=True,
                      step_traces=[], error=None, started=started)
        await db.record_workflow_run_summary(workflow_id, status="success", message=summary_message)
        return {"workflow_id": workflow_id, "run_id": run_id, "status": "success",
                "message": summary_message, "step_traces": []}

    for idx, action_def in enumerate(actions):
        kind = str(action_def.get("kind") or "")
        raw_cfg = action_def.get("config") or {}
        per_step_cond = action_def.get("condition")
        cls = ACTION_REGISTRY.get(kind)
        step_started = time.perf_counter()

        # Per-action condition gate: lets a step depend on a previous step's
        # output (e.g. notify.slack only when drift.check found something).
        if per_step_cond:
            try:
                if not evaluate_condition(per_step_cond, context):
                    step_traces.append({
                        "index": idx, "kind": kind, "status": "skipped",
                        "message": "Per-action condition false",
                        "config": raw_cfg, "output": {},
                        "duration_ms": int((time.perf_counter() - step_started) * 1000),
                        "error": None,
                    })
                    summary_message = f"Step {idx + 1} ({kind}) skipped"
                    continue
            except Exception as exc:
                step_traces.append({
                    "index": idx, "kind": kind, "status": "error",
                    "message": "Per-action condition errored",
                    "config": raw_cfg, "output": {},
                    "duration_ms": 0, "error": str(exc),
                })
                final_status = "failed"
                final_error = str(exc)
                summary_message = f"Step {idx + 1} ({kind}) condition errored"
                break

        if cls is None:
            trace = {
                "index": idx, "kind": kind, "status": "error",
                "message": f"Unknown action kind '{kind}'",
                "config": raw_cfg, "output": {},
                "duration_ms": 0, "error": "unknown_action",
            }
            step_traces.append(trace)
            final_status = "failed"
            final_error = trace["message"]
            summary_message = trace["message"]
            break

        try:
            rendered_cfg = render_config(raw_cfg, context)
        except Exception as exc:
            trace = {
                "index": idx, "kind": kind, "status": "error",
                "message": "Template rendering failed",
                "config": raw_cfg, "output": {},
                "duration_ms": 0, "error": str(exc),
            }
            step_traces.append(trace)
            final_status = "failed"
            final_error = trace["message"]
            summary_message = trace["message"]
            break

        action = cls()
        try:
            result: ActionResult = await action.execute(
                config=rendered_cfg, context=context, engine=engine,
            )
        except Exception as exc:
            logger.exception("[workflow:%s] step %d (%s) raised", name, idx, kind)
            result = ActionResult(status="error", error=str(exc), message="Unhandled exception")

        duration_ms = int((time.perf_counter() - step_started) * 1000)
        trace = {
            "index": idx, "kind": kind,
            "status": result.status, "message": result.message,
            "config": raw_cfg, "output": result.output,
            "duration_ms": duration_ms, "error": result.error,
        }
        step_traces.append(trace)

        # Feed this step's output into the context for the next step's templating.
        # Include "status" in context["last"] so the last_action_status condition
        # operator in conditions.py can gate downstream steps (e.g. the
        # dataset.build_trading → evolution.start chain in Sunday workflows).
        last_ctx = dict(result.output or {})
        last_ctx["status"] = result.status
        context["last"] = last_ctx
        # Also expose under the action kind for convenience:
        # `{cleanup.adapters.deleted}` works after a CleanupAdapters step.
        context[kind] = result.output or {}

        if result.status == "error":
            final_status = "failed"
            final_error = result.error or result.message
            summary_message = f"Step {idx + 1} ({kind}) failed: {result.message}"
            break
        # On the last successful step, surface its message.
        summary_message = result.message or f"{kind} ok"

    # ── 3. persist ─────────────────────────────────────────────────────
    await _finish(db, run_id, status=final_status, condition_passed=True,
                  step_traces=step_traces, error=final_error, started=started)
    await db.record_workflow_run_summary(
        workflow_id,
        status=final_status,
        message=summary_message,
    )

    logger.info("[workflow:%s] done run_id=%s status=%s steps=%d",
                name, run_id, final_status, len(step_traces))

    return {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "status": final_status,
        "message": summary_message,
        "step_traces": step_traces,
        "error": final_error,
    }


async def _finish(db, run_id, *, status, condition_passed, step_traces, error, started: float) -> None:
    if run_id is None:
        return
    duration_ms = int((time.perf_counter() - started) * 1000)
    try:
        await db.finish_workflow_run(
            int(run_id),
            status=status,
            condition_passed=condition_passed,
            step_traces=step_traces,
            error=error,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.warning("[workflow] finish_workflow_run(%s) failed: %s", run_id, exc)


__all__ = ["execute_workflow"]
