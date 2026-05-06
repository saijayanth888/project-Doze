"""HTTP surface for the in-process automation engine."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from services import automation as automation_module
from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.routes.automation")
router = APIRouter()


def _engine_or_503():
    eng = automation_module.get_engine()
    if eng is None:
        raise HTTPException(status_code=503, detail="Automation engine not started")
    return eng


@router.get("/jobs")
async def list_jobs() -> dict[str, Any]:
    eng = _engine_or_503()
    return {"jobs": await eng.list_jobs()}


@router.put("/jobs/{job_id}")
async def update_job(job_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Enable/disable, retime, or reconfigure a job in one call."""
    eng = _engine_or_503()
    saved = await eng.update_job(
        job_id,
        enabled=body.get("enabled"),
        cron=body.get("cron"),
        config=body.get("config"),
    )
    if saved is None:
        raise HTTPException(status_code=404, detail=f"Unknown job '{job_id}'")
    return saved


@router.post("/jobs/{job_id}/trigger")
async def trigger_job(job_id: str) -> dict[str, Any]:
    eng = _engine_or_503()
    ok = await eng.trigger(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"No handler for '{job_id}'")
    return {"status": "queued", "job_id": job_id}


@router.get("/log")
async def get_execution_log(limit: int = 50, db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    entries = await db.list_automation_log(limit=int(limit))
    return {"entries": entries}


@router.delete("/log")
async def clear_execution_log(db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    deleted = await db.clear_automation_log()
    return {"deleted": int(deleted)}


@router.get("/settings")
async def get_settings(db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    """Slack URL, per-event allow-list, regression threshold, cleanup days."""
    row = await db.get_automation_settings()
    if not row:
        # Should be unreachable: lifespan inserts the row.
        return {}
    # Mask the slack URL so we never echo the secret back to a UI poll.
    out = dict(row)
    url = out.get("slack_webhook_url") or ""
    if url:
        out["slack_webhook_url_masked"] = (
            f"{url[:32]}…{url[-6:]}" if len(url) > 48 else "•••configured•••"
        )
        # Don't return the literal URL — UI uses the masked field.
        out.pop("slack_webhook_url", None)
    return out


@router.put("/settings")
async def update_settings(body: dict[str, Any], db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    saved = await db.update_automation_settings(body)
    if not saved:
        raise HTTPException(status_code=500, detail="failed to update")
    out = dict(saved)
    url = out.get("slack_webhook_url") or ""
    if url:
        out["slack_webhook_url_masked"] = (
            f"{url[:32]}…{url[-6:]}" if len(url) > 48 else "•••configured•••"
        )
        out.pop("slack_webhook_url", None)
    return out


@router.post("/slack/test")
async def slack_test() -> dict[str, Any]:
    eng = _engine_or_503()
    await eng.notify("Test notification from ModelForge", "🧪", event_type=None)
    return {"status": "sent"}
