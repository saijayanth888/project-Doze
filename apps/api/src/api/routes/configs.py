"""Evolution config presets (built-in + custom in Postgres)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from api.schemas.configs import PresetDetail, PresetList, PresetSummary, SavePresetRequest
from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.routes.configs")

router = APIRouter()


@router.get("/presets", response_model=PresetList)
async def list_presets(db: LineageDB = Depends(get_db)) -> PresetList:
    rows = await db.list_evolution_presets()
    out = [
        PresetSummary(
            name=r["name"],
            is_builtin=bool(r.get("is_builtin")),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]
    return PresetList(presets=out, total=len(out))


@router.post("/presets", response_model=PresetDetail)
async def save_preset(
    body: SavePresetRequest,
    db: LineageDB = Depends(get_db),
) -> PresetDetail:
    if body.name.startswith("__"):
        raise HTTPException(status_code=400, detail="Reserved preset name")
    await db.upsert_evolution_preset(body.name, body.config, is_builtin=False)
    row = await db.get_evolution_preset(body.name)
    if not row:
        raise HTTPException(status_code=500, detail="Failed to persist preset")
    cfg = row["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    return PresetDetail(
        name=row["name"],
        is_builtin=bool(row.get("is_builtin")),
        config=dict(cfg) if isinstance(cfg, dict) else {},
        created_at=row.get("created_at"),
    )


@router.get("/presets/{name}", response_model=PresetDetail)
async def get_preset(name: str, db: LineageDB = Depends(get_db)) -> PresetDetail:
    row = await db.get_evolution_preset(name)
    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")
    cfg = row["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    return PresetDetail(
        name=row["name"],
        is_builtin=bool(row.get("is_builtin")),
        config=dict(cfg) if isinstance(cfg, dict) else {},
        created_at=row.get("created_at"),
    )


@router.delete("/presets/{name}")
async def delete_preset(name: str, db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    row = await db.get_evolution_preset(name)
    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")
    if bool(row.get("is_builtin")):
        raise HTTPException(status_code=403, detail="Cannot delete built-in preset")
    ok = await db.delete_evolution_preset(name)
    if not ok:
        raise HTTPException(status_code=500, detail="Delete failed")
    return {"deleted": True, "name": name}
