"""HTTP surface for the workflow engine.

Mounted under ``/api/automation`` (see ``api/router.py``):

* ``GET    /workflows``                — list workflows (with last-run summary)
* ``POST   /workflows``                — create
* ``GET    /workflows/{id}``           — detail
* ``PUT    /workflows/{id}``           — update (name, trigger, condition, actions, enabled)
* ``DELETE /workflows/{id}``           — delete (user kind only)
* ``POST   /workflows/{id}/trigger``   — manual fire
* ``GET    /workflows/{id}/runs``      — execution history
* ``GET    /workflow_runs``            — global execution history
* ``GET    /workflow_runs/{run_id}``   — single run detail with step traces
* ``POST   /hooks/{id}?secret=...``    — webhook ingress
* ``GET    /actions/schema``           — UI form metadata for the action library
* ``GET    /triggers/schema``          — UI form metadata for trigger types
* ``GET    /events/known``             — known domain event topics
* ``GET    /cron/preview?expr=…``      — next 5 fires for a cron expression
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api.deps import get_db
from services import automation as automation_module
from services.automation_engine import action_schemas, trigger_schemas
from services.automation_engine.actions import ACTION_REGISTRY
from services.automation_engine.triggers import KNOWN_EVENTS
from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.routes.workflows")
router = APIRouter()

_VALID_TRIGGER_TYPES = {"cron", "event", "webhook", "manual"}


def _engine_or_503():
    eng = automation_module.get_engine()
    if eng is None:
        raise HTTPException(status_code=503, detail="Automation engine not started")
    return eng


def _validate_actions_payload(actions: Any) -> None:
    """Reject shapes that would crash workflow_runner at execution time.

    Without this, a typo in a workflow's ``actions`` array — wrong ``kind``,
    missing ``kind`` field, ``config`` not a dict — only surfaces when the
    workflow eventually fires, leaving a red row in the dashboard and
    confused logs. Validate up-front so the API returns a 400 with the
    actionable detail.
    """
    if not isinstance(actions, list):
        raise HTTPException(status_code=400, detail="actions must be a list")
    for idx, step in enumerate(actions):
        if not isinstance(step, dict):
            raise HTTPException(
                status_code=400,
                detail=f"actions[{idx}] must be an object",
            )
        kind = step.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise HTTPException(
                status_code=400,
                detail=f"actions[{idx}].kind must be a non-empty string",
            )
        if kind not in ACTION_REGISTRY:
            known = sorted(ACTION_REGISTRY.keys())
            raise HTTPException(
                status_code=400,
                detail=(
                    f"actions[{idx}].kind='{kind}' is not registered. "
                    f"Known kinds: {known}"
                ),
            )
        cfg = step.get("config", {})
        if cfg is not None and not isinstance(cfg, dict):
            raise HTTPException(
                status_code=400,
                detail=f"actions[{idx}].config must be an object or null",
            )


# ── Workflow CRUD ───────────────────────────────────────────────────────


@router.get("/workflows")
async def list_workflows(
    kind: str | None = Query(None, pattern="^(system|user)$"),
    db: LineageDB = Depends(get_db),
) -> dict[str, Any]:
    return {"workflows": await db.list_workflows(kind=kind)}


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    wf = await db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")
    return wf


@router.post("/workflows")
async def create_workflow(body: dict[str, Any] = Body(...),
                          db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    name = str(body.get("name") or "").strip()
    trigger_type = str(body.get("trigger_type") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if trigger_type not in _VALID_TRIGGER_TYPES:
        raise HTTPException(status_code=400, detail="invalid trigger_type")
    actions = body.get("actions") or []
    _validate_actions_payload(actions)

    eng = automation_module.get_engine()
    webhook_secret = (
        eng.new_webhook_secret() if (trigger_type == "webhook" and eng) else None
    )
    try:
        wf = await db.create_workflow(
            name=name,
            description=body.get("description"),
            enabled=bool(body.get("enabled", True)),
            kind="user",
            trigger_type=trigger_type,
            trigger_config=body.get("trigger_config") or {},
            condition=body.get("condition"),
            actions=actions,
            webhook_secret=webhook_secret,
        )
    except Exception as exc:
        # Likely uniqueness violation on (kind, name).
        raise HTTPException(status_code=400, detail=str(exc))
    if not wf:
        raise HTTPException(status_code=500, detail="failed to create workflow")
    if eng:
        eng.remount(wf)
    return wf


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, body: dict[str, Any] = Body(...),
                          db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    current = await db.get_workflow(workflow_id)
    if not current:
        raise HTTPException(status_code=404, detail="workflow not found")
    # Ban changes that would corrupt a system workflow's identity.
    if current.get("kind") == "system":
        for forbidden in ("name", "kind"):
            if forbidden in body:
                body.pop(forbidden, None)
    if "actions" in body:
        _validate_actions_payload(body["actions"])
    if "trigger_type" in body and body["trigger_type"] not in _VALID_TRIGGER_TYPES:
        raise HTTPException(status_code=400, detail="invalid trigger_type")

    # If swapping into a webhook trigger and no secret is set yet, mint one.
    eng = automation_module.get_engine()
    if (
        body.get("trigger_type") == "webhook"
        and not current.get("webhook_secret")
        and "webhook_secret" not in body
        and eng
    ):
        body["webhook_secret"] = eng.new_webhook_secret()

    try:
        saved = await db.update_workflow(workflow_id, body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not saved:
        raise HTTPException(status_code=500, detail="update failed")
    if eng:
        eng.remount(saved)
    return saved


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    current = await db.get_workflow(workflow_id)
    if not current:
        raise HTTPException(status_code=404, detail="workflow not found")
    if current.get("kind") == "system":
        raise HTTPException(status_code=403, detail="system workflows cannot be deleted")
    ok = await db.delete_workflow(workflow_id)
    eng = automation_module.get_engine()
    if eng:
        eng._unmount(workflow_id)  # noqa: SLF001  (intentional engine cleanup)
    return {"deleted": bool(ok)}


# ── Manual trigger ──────────────────────────────────────────────────────


@router.post("/workflows/{workflow_id}/trigger")
async def trigger_workflow(
    workflow_id: str,
    body: dict[str, Any] | None = Body(default=None),
    force: bool = Query(
        default=False,
        description=(
            "Allow manual trigger even when the workflow is disabled. Operators "
            "use ``?force=true`` to dry-run a disabled workflow for debugging. "
            "Defaults to False so the dashboard's Run-Now button can't accidentally "
            "fire a workflow the operator explicitly turned off."
        ),
    ),
    db: LineageDB = Depends(get_db),
) -> dict[str, Any]:
    """Manual fire. Honours the ``enabled`` flag by default.

    Prior behaviour: manual triggers ran regardless of ``enabled``. This
    surprised operators who disabled a workflow expecting all firing paths
    (cron + manual) to stop. Fixed 2026-05-18 — manual now refuses unless
    ``?force=true`` is passed.
    """
    wf = await db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")
    if not wf.get("enabled") and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "workflow_disabled",
                "workflow_id": workflow_id,
                "workflow_name": wf.get("name"),
                "message": (
                    "Workflow is disabled. Re-enable it (PUT /workflows/{id} "
                    "with body {\"enabled\": true}) or pass ?force=true to "
                    "trigger anyway for one-off debugging."
                ),
            },
        )
    eng = _engine_or_503()
    summary = await eng.trigger_workflow(workflow_id, payload=(body or {}), trigger_kind="manual")
    if summary is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    return summary


# ── Execution history ──────────────────────────────────────────────────


@router.get("/workflow_runs")
async def list_global_runs(limit: int = 50, db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    return {"runs": await db.list_workflow_runs(limit=int(limit))}


@router.get("/workflows/{workflow_id}/runs")
async def list_workflow_runs(workflow_id: str, limit: int = 25,
                             db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    return {"runs": await db.list_workflow_runs(workflow_id, limit=int(limit))}


@router.get("/workflow_runs/{run_id}")
async def get_workflow_run(run_id: int, db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    row = await db.get_workflow_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    return row


# ── Webhook ingress ────────────────────────────────────────────────────


@router.post("/hooks/{workflow_id}")
async def webhook_in(workflow_id: str, secret: str = Query(""),
                     body: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    eng = _engine_or_503()
    summary = await eng.fire_webhook(workflow_id, secret=secret, body=body or {})
    if summary is None:
        raise HTTPException(status_code=404, detail="workflow not found or not webhook-triggered")
    if summary.get("status") == "denied":
        raise HTTPException(status_code=403, detail=summary.get("reason"))
    return summary


# ── Schemas (UI form builder) ──────────────────────────────────────────


@router.get("/actions/schema")
async def get_actions_schema() -> dict[str, Any]:
    return {"actions": action_schemas()}


@router.get("/triggers/schema")
async def get_triggers_schema() -> dict[str, Any]:
    return {"triggers": trigger_schemas()}


@router.get("/events/known")
async def get_known_events() -> dict[str, Any]:
    return {"events": KNOWN_EVENTS}


# ── Cron preview ───────────────────────────────────────────────────────


@router.get("/cron/preview")
async def cron_preview(expr: str = Query(..., min_length=1)) -> dict[str, Any]:
    """Return the next 5 firing times for a cron expression."""
    try:
        from datetime import datetime, timezone
        from croniter import croniter
    except ImportError:
        raise HTTPException(status_code=503, detail="croniter not installed in this image")
    try:
        it = croniter(expr.strip(), datetime.now(timezone.utc))
        nexts = [it.get_next(datetime).isoformat() for _ in range(5)]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid cron: {exc}")
    return {"expr": expr.strip(), "next_fires": nexts}
