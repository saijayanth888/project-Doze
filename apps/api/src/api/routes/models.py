"""Model registry routes — list, champion, and individual model lookup."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import ValidationError

from api.deps import get_registry
from api.schemas.models import ChampionInfo, ModelInfo, ModelList
from services.model_registry import ModelRegistry

logger = logging.getLogger("modelforge.routes.models")

router = APIRouter()

# Static `/champion` must stay before `/{model_id}` so "champion" is never captured as a model id.


@router.get("/champion", response_model=ChampionInfo)
async def get_champion(
    registry: ModelRegistry = Depends(get_registry),
) -> ChampionInfo:
    """Return the current champion model."""
    champ_raw = registry.get_champion()

    if not champ_raw or not isinstance(champ_raw, dict):
        raise HTTPException(status_code=404, detail="No champion registered yet")

    try:
        return ChampionInfo(**champ_raw)
    except ValidationError as exc:
        logger.warning("Invalid champion payload in registry.json: %s", exc)
        raise HTTPException(
            status_code=404,
            detail="No valid champion registered yet",
        ) from exc


@router.get("/", response_model=ModelList)
async def list_models(
    registry: ModelRegistry = Depends(get_registry),
) -> ModelList:
    """Return all registered models."""
    models_raw = registry.get_all_models()

    models: list[ModelInfo] = []
    for m in models_raw:
        try:
            models.append(ModelInfo(**m))
        except ValidationError as exc:
            logger.warning("Skipping invalid model row in registry: %s", exc)

    return ModelList(total=len(models), models=models)


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
