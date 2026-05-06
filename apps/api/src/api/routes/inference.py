"""Inference and model comparison routes."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db, get_ollama, get_registry
from api.schemas.inference import (
    AdapterCompareRequest,
    CompareRequest,
    CompareResponse,
    InferenceRequest,
    InferenceResponse,
)
from config.settings import settings
from services.lineage_db import LineageDB
from services.model_registry import ModelRegistry

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


def _resolve_base_model_for_adapter(adapter_id: str, db_meta: dict | None, registry_champ: dict | None) -> str | None:
    """Find the HF base model for the given adapter id.

    Order: lineage row's run config → champion registry (when adapter matches)
    → None. The PEFT inference helper applies its own resolver to handle
    Ollama-style tags like `llama3.2:3b`.
    """
    if db_meta and isinstance(db_meta, dict):
        bm = db_meta.get("base_model")
        if bm:
            return str(bm)
    if registry_champ and isinstance(registry_champ, dict):
        if str(registry_champ.get("adapter_id") or "") == adapter_id:
            bm = registry_champ.get("base_model")
            if bm:
                return str(bm)
    return None


@router.post("/adapter/compare", response_model=CompareResponse)
async def compare_with_adapter(
    req: AdapterCompareRequest,
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> CompareResponse:
    """Run the same prompt twice on the API-process GPU: once with the base
    model, once with base + PEFT adapter applied. This is the "honest" champion
    comparison path — Ollama can't load PEFT/safetensors LoRAs, so the
    Playground's existing /infer/compare with two Ollama tags would produce
    two identical responses against the base model.
    """
    from services import peft_inference

    if not peft_inference.is_available():
        raise HTTPException(
            status_code=503,
            detail="PEFT inference unavailable in this image (torch/peft missing).",
        )

    # Look up which base model this adapter belongs to.
    if "__gen" not in req.adapter_id:
        raise HTTPException(status_code=400, detail="adapter_id must look like run-XXX__genN")
    run_id, gen_part = req.adapter_id.split("__gen", 1)
    try:
        gen = int(gen_part)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bad generation in adapter_id") from exc

    db_run = await db.get_run(run_id)
    base_model_raw = _resolve_base_model_for_adapter(req.adapter_id, db_run, registry.get_champion())

    loop = asyncio.get_running_loop()
    try:
        # Sequential, not parallel: both calls share the same single-GPU base
        # model from the cache, so running them at the same time would either
        # OOM or serialize on the cuda kernel queue anyway.
        base_res = await loop.run_in_executor(
            None,
            lambda: peft_inference.run_base_sync(
                base_model_raw=base_model_raw,
                prompt=req.prompt,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
            ),
        )
        champ_res = await loop.run_in_executor(
            None,
            lambda: peft_inference.run_with_adapter_sync(
                base_model_raw=base_model_raw,
                adapter_id=req.adapter_id,
                prompt=req.prompt,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
            ),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("/api/infer/adapter/compare failed")
        raise HTTPException(status_code=500, detail=f"adapter inference failed: {exc}") from exc

    return CompareResponse(
        prompt=req.prompt,
        base=InferenceResponse(
            response=base_res["response"],
            model=base_res["model"],
            tokens=base_res.get("tokens"),
            latency_ms=base_res.get("latency_ms"),
            source="peft",
        ),
        champion=InferenceResponse(
            response=champ_res["response"],
            model=champ_res["model"],
            tokens=champ_res.get("tokens"),
            latency_ms=champ_res.get("latency_ms"),
            source="peft+adapter",
        ),
    )
