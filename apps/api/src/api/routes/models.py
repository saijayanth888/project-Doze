"""Model registry routes — list, champion, and individual model lookup."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_registry
from api.schemas.models import ChampionInfo, ModelInfo, ModelList
from services.mock_data import mock_champion
from services.model_registry import ModelRegistry

logger = logging.getLogger("modelforge.routes.models")

router = APIRouter()


@router.get("/", response_model=ModelList)
async def list_models(
    registry: ModelRegistry = Depends(get_registry),
) -> ModelList:
    """Return all registered models."""
    models_raw = registry.get_all_models()

    if not models_raw:
        # Fall back to a synthetic entry derived from the mock champion
        champ = mock_champion()
        models_raw = [
            {
                "id": f"gen-{champ['generation']}",
                "base_model": champ["base_model"],
                "adapter_path": champ.get("adapter_path"),
                "generation": champ["generation"],
                "scores": champ["scores"],
                "promoted": True,
            }
        ]

    models = [ModelInfo(**m) for m in models_raw]
    return ModelList(total=len(models), models=models)


@router.get("/champion", response_model=ChampionInfo)
async def get_champion(
    registry: ModelRegistry = Depends(get_registry),
) -> ChampionInfo:
    """Return the current champion model."""
    champ_raw = registry.get_champion()

    if champ_raw is None:
        champ_raw = mock_champion()

    return ChampionInfo(**champ_raw)


@router.get("/{model_id}", response_model=ModelInfo)
async def get_model(
    model_id: str,
    registry: ModelRegistry = Depends(get_registry),
) -> ModelInfo:
    """Return a single model by ID."""
    model_raw = registry.get_model(model_id)
    if model_raw is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    return ModelInfo(**model_raw)
