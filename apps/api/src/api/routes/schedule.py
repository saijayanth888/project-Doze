"""Legacy single-row evolution_schedule table proxy.

The Automation engine's workflow tier (see ``services.automation_engine``)
fully supersedes this table — the seeded "Nightly Evolution" workflow is
the recommended path for cron-driven runs. This route is here so anything
still poking the legacy schedule row keeps working.

The route is intentionally tiny: GET to read, PUT to update.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends

from api.deps import get_db
from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.routes.schedule")
router = APIRouter()


@router.get("")
async def get_schedule(db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    """Return the legacy single-row schedule, or ``{}`` if not initialised."""
    row = await db.get_schedule()
    return dict(row) if row else {}


@router.put("")
async def update_schedule(
    body: dict[str, Any] = Body(...),
    db: LineageDB = Depends(get_db),
) -> dict[str, Any]:
    saved = await db.update_schedule(
        enabled=body.get("enabled"),
        cron=body.get("cron"),
        config=body.get("config"),
    )
    return saved or {}
