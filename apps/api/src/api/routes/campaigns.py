"""Pre-built research campaigns (paper-ready experiment matrices).

Listing/inspection only at this layer. The 4-week autopilot lives in
services.campaign_runner and gets its own endpoints in a follow-up task.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.campaign_configs import CAMPAIGNS, get_campaign

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


@router.get("/{campaign_id}")
async def get_campaign_route(campaign_id: str):
    cfg = get_campaign(campaign_id)
    if not cfg:
        raise HTTPException(404, f"campaign {campaign_id!r} not found")
    return {"id": campaign_id, **cfg}
