"""Pre-built research campaigns (paper-ready experiment matrices).

Listing/inspection only at this layer. The 4-week autopilot lives in
services.campaign_runner and gets its own endpoints in a follow-up task.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from api.deps import get_db
from services.campaign_configs import CAMPAIGNS, get_campaign
from services.campaign_runner import get_campaign_runner

router = APIRouter()


@router.get("")
async def list_campaigns():
    return {
        "campaigns": [
            {
                "id": cid,
                "description": cfg["description"],
                "experiment_count": len(cfg["experiments"]),
                "experiments": cfg["experiments"],
            }
            for cid, cfg in CAMPAIGNS.items()
        ]
    }


@router.get("/status")
async def campaign_status():
    return get_campaign_runner().get_status()


@router.post("/pause")
async def pause_campaign():
    get_campaign_runner().pause()
    return {"status": "paused"}


@router.post("/resume")
async def resume_campaign():
    get_campaign_runner().resume()
    return {"status": "running"}


@router.post("/stop")
async def stop_campaign():
    get_campaign_runner().stop()
    return {"status": "stopping"}


@router.get("/{campaign_id}")
async def get_campaign_route(campaign_id: str):
    cfg = get_campaign(campaign_id)
    if not cfg:
        raise HTTPException(404, f"campaign {campaign_id!r} not found")
    return {"id": campaign_id, **cfg}


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: str, db=Depends(get_db)):
    cfg = get_campaign(campaign_id)
    if not cfg:
        raise HTTPException(404, f"campaign {campaign_id!r} not found")
    runner = get_campaign_runner()
    result = await runner.start(campaign_id, list(cfg["experiments"]), db)
    return result


@router.get("/{campaign_id}/results")
async def campaign_results(campaign_id: str, db=Depends(get_db)):
    if not db or not getattr(db, "_pool", None):
        return {"plan_id": campaign_id, "results": []}
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT experiment_index, config, status, scores, duration_seconds,
                   error, started_at, completed_at
            FROM campaign_results
            WHERE plan_id = $1
            ORDER BY experiment_index ASC
            """,
            campaign_id,
        )
    return {"plan_id": campaign_id, "results": [dict(r) for r in rows]}
