"""ForgeAgent HTTP surface — classifier-routed inference across tracks.

Endpoints
---------
* ``GET  /api/forge/tracks``    — list tracks with champion status
* ``POST /api/forge/classify``  — dry-run the classifier (no inference)
* ``POST /api/forge/query``     — full pipeline: classify → execute → answer
* ``POST /api/forge/compare``   — answer the same prompt with every enabled
                                  track (A/B grid for the UI's compare panel)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from agents.forge_agent import classify_prompt, execute_route
from api.deps import get_db
from services.lineage_db import LineageDB

logger = logging.getLogger("modelforge.routes.forge")
router = APIRouter()


@router.get("/tracks")
async def list_tracks(db: LineageDB = Depends(get_db)) -> dict[str, Any]:
    rows = await db.list_tracks()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "track_id": r.get("track_id"),
            "name": r.get("name"),
            "description": r.get("description"),
            "base_model": r.get("base_model"),
            "target_benchmarks": r.get("target_benchmarks") or [],
            "champion_adapter_path": r.get("champion_adapter_path"),
            "champion_run_id": r.get("champion_run_id"),
            "champion_generation": r.get("champion_generation"),
            "champion_scores": r.get("champion_scores") or {},
            "enabled": bool(r.get("enabled")),
            "has_adapter": bool(r.get("champion_run_id")) and bool(r.get("champion_generation")),
        })
    return {"tracks": out}


@router.post("/classify")
async def classify_only(
    body: dict[str, Any] = Body(...),
    db: LineageDB = Depends(get_db),
) -> dict[str, Any]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    route = await classify_prompt(prompt, db=db)
    return {
        "route": {
            "track_id": route.track_id,
            "track_name": route.track_name,
            "method": route.method,
            "confidence": round(route.confidence, 3),
            "reason": route.reason,
            "all_scores": route.all_scores,
            "track": route.track,
        },
    }


@router.post("/query")
async def forge_query(
    body: dict[str, Any] = Body(...),
    db: LineageDB = Depends(get_db),
) -> dict[str, Any]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    max_tokens = int(body.get("max_tokens") or 256)
    temperature = float(body.get("temperature") or 0.7)
    pinned_track = body.get("track_id")  # optional override
    force_base = bool(body.get("force_base") or False)

    if pinned_track:
        # Skip classification — user pinned a specific track.
        track = await db.get_track(str(pinned_track))
        if not track:
            raise HTTPException(status_code=404, detail=f"unknown track {pinned_track}")
        from agents.forge_agent import ForgeRoute
        route = ForgeRoute(
            track_id=track.get("track_id"),
            track_name=str(track.get("name") or track.get("track_id")),
            method="pinned",
            confidence=1.0,
            reason="user-pinned track",
            all_scores=[],
            track=track,
        )
    else:
        route = await classify_prompt(prompt, db=db)

    answer = await execute_route(
        route,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        force_base=force_base,
    )
    return answer.to_dict()


@router.post("/compare")
async def forge_compare(
    body: dict[str, Any] = Body(...),
    db: LineageDB = Depends(get_db),
) -> dict[str, Any]:
    """Answer the same prompt with every enabled track. Returns the chosen
    route (so the UI can highlight it) plus per-track answers.

    Capped at 4 concurrent backends so we don't OOM the GPU on a host that
    only loads PEFT for one of the tracks at a time.
    """
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    max_tokens = int(body.get("max_tokens") or 200)
    temperature = float(body.get("temperature") or 0.7)

    tracks = [t for t in await db.list_tracks() if t.get("enabled")]
    if not tracks:
        raise HTTPException(status_code=400, detail="no enabled tracks")

    chosen_route = await classify_prompt(prompt, db=db)

    from agents.forge_agent import ForgeRoute

    async def _run_track(t):
        r = ForgeRoute(
            track_id=t.get("track_id"),
            track_name=str(t.get("name") or t.get("track_id")),
            method="compare",
            confidence=1.0,
            reason="compare-mode A/B",
            all_scores=[],
            track=t,
        )
        try:
            ans = await execute_route(
                r, prompt=prompt, max_tokens=max_tokens, temperature=temperature,
            )
            return ans.to_dict()
        except Exception as exc:
            return {
                "route": {
                    "track_id": t.get("track_id"),
                    "track_name": str(t.get("name") or t.get("track_id")),
                    "method": "compare",
                    "confidence": 1.0,
                    "reason": "compare-mode A/B",
                    "all_scores": [],
                    "track": t,
                },
                "response": "",
                "error": str(exc)[:500],
                "backend": "error",
                "model": "",
                "adapter_id": None,
                "tokens": 0,
                "latency_ms": 0.0,
                "base_model": "",
            }

    sem = asyncio.Semaphore(4)
    async def gated(t):
        async with sem:
            return await _run_track(t)

    answers = await asyncio.gather(*(gated(t) for t in tracks))
    return {
        "chosen": {
            "track_id": chosen_route.track_id,
            "track_name": chosen_route.track_name,
            "method": chosen_route.method,
            "confidence": round(chosen_route.confidence, 3),
            "reason": chosen_route.reason,
        },
        "answers": answers,
    }
