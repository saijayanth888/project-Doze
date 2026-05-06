"""HTTP surface for paper-grade experiment data.

Endpoints
---------
GET  /api/experiments              — list all experiment records (joined view).
GET  /api/experiments/export       — same data as a CSV download.
GET  /api/experiments/ablations    — list predefined ablation studies.
GET  /api/experiments/ablations/{id} — full plan for one ablation.
POST /api/experiments/ablation     — kick off a sequential ablation run set.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from agents import start_evolution
from api.deps import get_db
from services import ablation_presets, experiment_tracker
from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.routes.experiments")
router = APIRouter()


@router.get("")
@router.get("/")
async def list_experiments(
    limit: int = 500,
    db: LineageDB = Depends(get_db),
) -> dict[str, Any]:
    records = await experiment_tracker.build_records(db, limit=int(limit))
    return {"count": len(records), "records": records}


@router.get("/export")
async def export_experiments(db: LineageDB = Depends(get_db)) -> StreamingResponse:
    """CSV download with one row per (run, generation), flattened. Suitable
    for pandas / R / spreadsheets when writing the paper."""
    records = await experiment_tracker.build_records(db, limit=10000)
    rows = experiment_tracker.to_csv_rows(records)
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(row)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="modelforge_experiments.csv"'},
    )


@router.get("/ablations")
async def list_ablations() -> dict[str, Any]:
    return {"ablations": ablation_presets.list_ablations()}


@router.get("/ablations/{ablation_id}")
async def get_ablation_detail(ablation_id: str) -> dict[str, Any]:
    a = ablation_presets.get_ablation(ablation_id)
    if not a:
        raise HTTPException(status_code=404, detail=f"Unknown ablation '{ablation_id}'")
    runs = ablation_presets.materialize_runs(ablation_id)
    return {
        "ablation_id": ablation_id,
        "name": a.get("name"),
        "description": a.get("description"),
        "run_count": len(runs),
        "base": a.get("base") or {},
        "runs": runs,
    }


_ABLATION_STATE: dict[str, dict[str, Any]] = {}


async def _run_ablation_sequential(ablation_id: str, batch_id: str, db: LineageDB) -> None:
    """Run each config in the ablation sequentially, awaiting the prior task's
    completion before starting the next. Single-GPU host — never run in parallel."""
    runs = ablation_presets.materialize_runs(ablation_id)
    state = _ABLATION_STATE[batch_id]
    state["total"] = len(runs)
    state["completed_runs"] = []
    state["status"] = "running"
    try:
        for i, cfg in enumerate(runs):
            state["current_index"] = i
            state["current_label"] = cfg.get("__ablation_label")
            run_id = f"run-{uuid4().hex[:8]}"
            try:
                await db.save_run(run_id, "starting", cfg)
                task = start_evolution(run_id, cfg, db)
                state["completed_runs"].append({"run_id": run_id, "label": cfg.get("__ablation_label")})
                # Wait for this run to finish before kicking off the next.
                # Single-GPU: parallel runs would OOM.
                await task
            except Exception as exc:
                logger.exception("ablation %s run %d failed", ablation_id, i)
                state["completed_runs"].append({
                    "run_id": run_id, "label": cfg.get("__ablation_label"), "error": str(exc),
                })
        state["status"] = "complete"
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = str(exc)


@router.post("/ablation")
async def run_ablation(body: dict[str, Any], db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    """Queue a sequential ablation. The endpoint returns immediately; poll
    GET /api/experiments/ablation/{batch_id} for progress."""
    ablation_id = str(body.get("ablation_id") or "")
    if not ablation_id:
        raise HTTPException(status_code=400, detail="ablation_id required")
    if not ablation_presets.get_ablation(ablation_id):
        raise HTTPException(status_code=404, detail=f"Unknown ablation '{ablation_id}'")
    batch_id = f"abl-{uuid4().hex[:8]}"
    _ABLATION_STATE[batch_id] = {
        "batch_id": batch_id,
        "ablation_id": ablation_id,
        "status": "queued",
        "current_index": -1,
        "completed_runs": [],
    }
    asyncio.create_task(_run_ablation_sequential(ablation_id, batch_id, db))
    return {"batch_id": batch_id, "ablation_id": ablation_id, "status": "queued"}


@router.get("/ablation/{batch_id}")
async def get_ablation_status(batch_id: str) -> dict[str, Any]:
    state = _ABLATION_STATE.get(batch_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Unknown batch '{batch_id}'")
    return state
