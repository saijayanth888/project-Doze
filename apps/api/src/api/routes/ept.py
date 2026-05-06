"""HTTP surface for the EPT (Evolutionary Population Training) engine."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("modelforge.routes.ept")
router = APIRouter()


def _runner_or_404():
    from agents.ept import get_runner
    r = get_runner()
    if r is None:
        raise HTTPException(status_code=404, detail="No EPT runner — start one with POST /api/ept/start")
    return r


@router.post("/start")
async def start(body: dict[str, Any]) -> dict[str, Any]:
    """Start a new EPT run. Request body keys map to PopulationConfig fields:
    population_size, num_parents, max_generations, base_model,
    target_benchmarks, eval_benchmarks, mutation_steps, mutation_lr,
    mutation_samples, crossover_strategy, alpha_min, alpha_max, lora_rank,
    lora_alpha, batch_size, seed."""
    from agents.ept.runner import start_runner
    try:
        runner = start_runner(body or {})
    except RuntimeError as exc:
        # 409 Conflict — another run is in flight.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": runner.manager.run_id, "status": runner.status}


@router.get("/status")
async def status() -> dict[str, Any]:
    """Current EPT runner status (or {is_running:false} if nothing started)."""
    from agents.ept import get_runner
    r = get_runner()
    if r is None:
        return {
            "is_running": False,
            "run_id": None,
            "generation": 0,
            "phase": "idle",
            "champion": None,
        }
    return r.status


@router.get("/population")
async def population() -> dict[str, Any]:
    """Current population with per-member scores + parent links."""
    return _runner_or_404().serialize_population()


@router.get("/history")
async def history() -> dict[str, Any]:
    """All generation snapshots. The frontend uses this for the lineage tree
    and the evolution line chart."""
    return _runner_or_404().serialize_history()


@router.get("/lineage/{member_id}")
async def lineage(member_id: str) -> dict[str, Any]:
    r = _runner_or_404()
    chain = r.manager.get_lineage(member_id)
    if not chain:
        raise HTTPException(status_code=404, detail=f"Unknown member '{member_id}'")
    return {"member_id": member_id, "lineage": chain}


@router.get("/events")
async def events(limit: int = 200) -> dict[str, Any]:
    """Event log emitted by the population manager (init/curate/eval/gen…).
    Use this to drive a live timeline in the EPT page."""
    r = _runner_or_404()
    items = list(r.events)[-int(limit):]
    return {"events": items}


@router.post("/stop")
async def stop() -> dict[str, Any]:
    r = _runner_or_404()
    r.request_stop()
    return {"run_id": r.manager.run_id, "stopping": True}
