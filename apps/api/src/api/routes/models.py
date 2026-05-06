"""Model registry routes — list, champion, and individual model lookup."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import ValidationError

from api.deps import get_ollama, get_registry
from api.schemas.models import ChampionInfo, ModelInfo, ModelList
from services.model_registry import ModelRegistry

logger = logging.getLogger("modelforge.routes.models")

router = APIRouter()

# Static `/champion` must stay before `/{model_id}` so "champion" is never captured as a model id.


def _normalize_champion_dict(raw: dict) -> dict:
    """Coerce registry JSON into ChampionInfo-compatible fields (avoid 500 on loose types)."""
    scores_in = raw.get("scores")
    scores: dict[str, float] = {}
    if isinstance(scores_in, dict):
        for k, v in scores_in.items():
            if isinstance(v, int | float):
                scores[str(k)] = float(v)
            elif isinstance(v, str):
                try:
                    scores[str(k)] = float(v)
                except ValueError:
                    continue
    try:
        gen = int(raw.get("generation", 0) or 0)
    except (TypeError, ValueError):
        gen = 0
    base = raw.get("base_model") or raw.get("name") or ""
    try:
        avg = float(raw.get("avg_score", 0) or 0)
    except (TypeError, ValueError):
        avg = 0.0
    ollama_model = raw.get("ollama_model")
    adapter_id = raw.get("adapter_id")
    return {
        "generation": gen,
        "base_model": str(base),
        "adapter_path": raw.get("adapter_path"),
        "scores": scores,
        "avg_score": avg,
        "method": raw.get("method"),
        "promoted_at": raw.get("promoted_at"),
        "adapter_id": str(adapter_id) if adapter_id else None,
        "ollama_model": str(ollama_model) if ollama_model else None,
    }


@router.get("/champion", response_model=ChampionInfo)
async def get_champion(
    registry: ModelRegistry = Depends(get_registry),
) -> ChampionInfo:
    """Return the current champion model."""
    try:
        champ_raw = registry.get_champion()
    except Exception as exc:
        logger.exception("Registry read failed for champion: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Registry unavailable",
        ) from exc

    if not champ_raw or not isinstance(champ_raw, dict):
        raise HTTPException(status_code=404, detail="No champion registered yet")

    normalized = _normalize_champion_dict(champ_raw)
    if not normalized["base_model"]:
        raise HTTPException(status_code=404, detail="No champion registered yet")

    try:
        return ChampionInfo(**normalized)
    except ValidationError as exc:
        logger.warning("Invalid champion payload in registry.json: %s", exc)
        raise HTTPException(
            status_code=404,
            detail="No valid champion registered yet",
        ) from exc


@router.get("", response_model=ModelList)
@router.get("/", response_model=ModelList)
async def list_models(
    registry: ModelRegistry = Depends(get_registry),
    ollama=Depends(get_ollama),
) -> ModelList:
    """Return available model tags for the UI.

    Combines:
    - registered models from the local model registry
    - Ollama model tags (`/api/tags`) so users can pick/pull base models
    """
    models_raw = registry.get_all_models()

    models: list[ModelInfo] = []
    seen_ids: set[str] = set()

    for m in models_raw:
        try:
            info = ModelInfo(**m)
            if info.id not in seen_ids:
                models.append(info)
                seen_ids.add(info.id)
        except ValidationError as exc:
            logger.warning("Skipping invalid model row in registry: %s", exc)

    try:
        ollama_rows = await ollama.list_models()
        for row in ollama_rows:
            name = row.get("name") or row.get("model")
            if not name:
                continue
            name = str(name)
            if name in seen_ids:
                continue
            models.append(
                ModelInfo(
                    id=name,
                    base_model=name,
                    adapter_path=None,
                    generation=0,
                    scores={},
                    promoted=False,
                    created_at=None,
                )
            )
            seen_ids.add(name)
    except Exception as exc:
        logger.warning("Ollama model tag listing failed: %s", exc)

    return ModelList(total=len(models), models=models)


@router.post("/pull")
async def pull_model(body: dict, ollama=Depends(get_ollama)) -> dict:
    """Pull a model into Ollama."""
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="model tag required")
    await ollama.pull(str(model))
    return {"status": "ok", "model": str(model)}


@router.get("/{model_id}", response_model=ModelInfo)
async def get_model(
    model_id: str = Path(
        ...,
        min_length=1,
        description="Model id. Static GET /models/champion is registered above; do not use `champion` here.",
    ),
    registry: ModelRegistry = Depends(get_registry),
) -> ModelInfo:
    """Return a single model by ID."""
    model_raw = registry.get_model(model_id)
    if model_raw is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    try:
        return ModelInfo(**model_raw)
    except ValidationError as exc:
        logger.warning("Invalid model payload for id=%s: %s", model_id, exc)
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found") from exc
