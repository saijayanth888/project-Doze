"""Evolution run management routes — start, status, and stop."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from agents import request_stop, start_evolution
from api.deps import get_db
from api.schemas.evolution import (
    EvolutionPollStatus,
    EvolutionRequest,
    EvolutionStatus,
    EvolutionStopResponse,
)
from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.routes.evolution")

router = APIRouter()


@router.get("/status", response_model=EvolutionPollStatus)
async def get_evolution_aggregate_status(
    db: LineageDB = Depends(get_db),
) -> EvolutionPollStatus:
    """Single poll endpoint for the dashboard (active run or latest completed / idle)."""
    run = await db.get_dashboard_run()
    if run is None:
        return EvolutionPollStatus()

    config = run.get("config") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            config = {}

    started = run.get("started_at")
    elapsed = None
    if isinstance(started, datetime):
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        elapsed = max(0.0, (datetime.now(UTC) - started).total_seconds())

    st = str(run.get("status", "unknown"))
    if st in ("completed", "failed", "stopped"):
        poll_status = "idle"
    else:
        poll_status = "running"

    return EvolutionPollStatus(
        run_id=run.get("run_id"),
        status=poll_status,
        generation=int(run.get("current_generation", 0) or 0),
        current_step=run.get("current_step"),
        started_at=started if isinstance(started, datetime) else None,
        elapsed_seconds=elapsed,
        error=run.get("error"),
        config=config if isinstance(config, dict) else {},
    )


@router.post("/start", response_model=EvolutionStatus)
async def start_evolution_route(
    req: EvolutionRequest,
    db: LineageDB = Depends(get_db),
) -> EvolutionStatus:
    """Persist a new run and kick the LangGraph agent off in the background."""
    run_id = f"run-{uuid4().hex[:8]}"
    config = req.model_dump()

    try:
        await db.save_run(run_id, "starting", config)
        logger.info("Evolution run %s persisted", run_id)
    except Exception as exc:
        logger.warning("Could not persist run %s to DB: %s", run_id, exc)

    try:
        start_evolution(run_id=run_id, config=config, db=db)
        logger.info("Evolution run %s scheduled", run_id)
    except Exception as exc:
        logger.exception("Failed to schedule run %s", run_id)
        raise HTTPException(status_code=500, detail=f"Failed to start: {exc}") from exc

    return EvolutionStatus(
        run_id=run_id,
        status="starting",
        generation=0,
        current_step="initialising",
        config=config,
    )


@router.get("/{run_id}", response_model=EvolutionStatus)
async def get_evolution_status(
    run_id: str,
    db: LineageDB = Depends(get_db),
) -> EvolutionStatus:
    """Return the current status of an evolution run."""
    try:
        run = await db.get_run(run_id)
    except Exception as exc:
        logger.warning("DB error fetching run %s: %s", run_id, exc)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc

    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    config = run.get("config") or {}
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            config = {}

    return EvolutionStatus(
        run_id=run_id,
        status=run.get("status", "unknown"),
        generation=run.get("current_generation", 0),
        current_step=run.get("current_step"),
        started_at=run.get("started_at"),
        elapsed_seconds=None,
        error=run.get("error"),
        config=config,
    )


@router.post("/{run_id}/stop", response_model=EvolutionStopResponse)
async def stop_evolution(
    run_id: str,
    db: LineageDB = Depends(get_db),
) -> EvolutionStopResponse:
    """Cooperatively stop a running run by setting the cancel flag."""
    in_memory = request_stop(run_id)

    try:
        run = await db.get_run(run_id)
        if run is None and not in_memory:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        if run is not None:
            await db.update_run_status(run_id, "stopped")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("DB error stopping run %s: %s", run_id, exc)

    return EvolutionStopResponse(
        run_id=run_id,
        stopped=True,
        message=f"Run {run_id} stopped",
    )
