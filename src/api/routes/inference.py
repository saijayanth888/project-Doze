"""Inference and model comparison routes."""

import asyncio
import logging

from fastapi import APIRouter, Depends

from api.deps import get_ollama
from api.schemas.inference import (
    CompareRequest,
    CompareResponse,
    InferenceRequest,
    InferenceResponse,
)
from config.settings import settings

logger = logging.getLogger("modelforge.routes.inference")

router = APIRouter()


async def _run_inference(
    ollama,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> InferenceResponse:
    """Run a single inference call, falling back to mock on Ollama failure."""
    try:
        result = await ollama.generate(
            model=model,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return InferenceResponse(
            response=result.get("response", ""),
            model=result.get("model", model),
            tokens=result.get("tokens"),
            latency_ms=result.get("latency_ms"),
            source="ollama",
        )
    except Exception as exc:
        logger.warning("Ollama generate failed for model '%s': %s", model, exc)
        preview = prompt[:50] + ("..." if len(prompt) > 50 else "")
        return InferenceResponse(
            response=f"[Mock] {preview}",
            model=model,
            tokens=None,
            latency_ms=None,
            source="mock",
        )


@router.post("/", response_model=InferenceResponse)
async def run_inference(
    req: InferenceRequest,
    ollama=Depends(get_ollama),
) -> InferenceResponse:
    """Run a prompt through an Ollama model."""
    model = req.model_id or settings.default_base_model
    return await _run_inference(
        ollama=ollama,
        model=model,
        prompt=req.prompt,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )


@router.post("/compare", response_model=CompareResponse)
async def compare_models(
    req: CompareRequest,
    ollama=Depends(get_ollama),
) -> CompareResponse:
    """Run the same prompt through two models concurrently and compare results."""
    base_result, champion_result = await asyncio.gather(
        _run_inference(
            ollama=ollama,
            model=req.model_a,
            prompt=req.prompt,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        ),
        _run_inference(
            ollama=ollama,
            model=req.model_b,
            prompt=req.prompt,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        ),
    )

    return CompareResponse(
        prompt=req.prompt,
        base=base_result,
        champion=champion_result,
    )
