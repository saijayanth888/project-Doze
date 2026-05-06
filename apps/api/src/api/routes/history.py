"""Run history — read view + archive operation.

The DAOs (``LineageDB.list_runs``, ``LineageDB.archive_run``) already exist
from the Phase-3 work; this just exposes them to the dashboard's
``/history`` page.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.routes.history")
router = APIRouter()


@router.get("/runs")
async def list_history(
    include_archived: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    db: LineageDB = Depends(get_db),
) -> dict[str, Any]:
    """Return run-level history rows with promoted-champion summary."""
    rows = await db.list_runs(include_archived=include_archived, limit=int(limit))
    return {"runs": rows}


@router.post("/runs/{run_id}/archive")
async def archive_run(run_id: str, db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    """Soft-delete a run by setting ``archived_at``. Reversible via SQL."""
    ok = await db.archive_run(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="run not found or already archived")
    return {"archived": True, "run_id": run_id}
