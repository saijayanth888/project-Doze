"""LoRA adapter management: list, serve, rollback, delete, compare."""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db, get_ollama, get_registry
from api.schemas.adapters import (
    AdapterCompareResponse,
    AdapterInfo,
    AdapterList,
    CleanupResponse,
    RollbackResponse,
    ServeAdapterResponse,
)
from config.settings import settings
from services.adapter_serve import (
    adapter_alias,
    adapter_dir_abs,
    ollama_has_model,
    try_create_ollama_model,
)
from services.lineage_db import LineageDB
from services.model_registry import ModelRegistry
from services.n8n_webhook import emit_adapter_deleted, emit_adapter_rollback
from services.ollama_client import OllamaClient

logger = logging.getLogger("modelforge.routes.adapters")

router = APIRouter()

_GEN_RE = re.compile(r"^gen-(\d+)$")


def _format_adapter_id(run_id: str, generation: int) -> str:
    return f"{run_id}__gen{generation}"


def _parse_adapter_id(adapter_id: str) -> tuple[str, int]:
    if "__gen" not in adapter_id:
        raise HTTPException(status_code=400, detail="Invalid adapter_id")
    run_id, gen_s = adapter_id.rsplit("__gen", 1)
    if not run_id:
        raise HTTPException(status_code=400, detail="Invalid adapter_id")
    try:
        return run_id, int(gen_s)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid generation in adapter_id") from exc


def _dir_size_mb(path: Any) -> float:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return round(total / (1024 * 1024), 4)


def _dir_created_at(path: Any) -> datetime | None:
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=UTC)
    except OSError:
        return None


def _weighted_avg(scores: dict[str, float]) -> float:
    if not scores:
        return 0.0
    return round(sum(scores.values()) / len(scores), 4)


def _adapter_status(row: dict[str, Any] | None, is_champion: bool) -> str:
    if is_champion:
        return "champion"
    if row is None:
        return "archived"
    if row.get("archived"):
        return "archived"
    if row.get("promoted"):
        return "promoted"
    return "discarded"


@router.get("/", response_model=AdapterList)
async def list_adapters(
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> AdapterList:
    root = settings.resolve_data_root() / "adapters"
    rows = await db.get_all_generations(include_archived=True)
    idx: dict[tuple[str, int], dict] = {(r["run_id"], int(r["generation"])): dict(r) for r in rows}

    champ_reg = registry.get_champion() or {}
    champion_id = champ_reg.get("adapter_id")

    adapters: list[AdapterInfo] = []
    total_disk = 0.0

    if root.is_dir():
        for run_dir in sorted(root.iterdir()):
            if not run_dir.is_dir():
                continue
            run_id = run_dir.name
            for gen_dir in sorted(run_dir.iterdir()):
                if not gen_dir.is_dir():
                    continue
                m = _GEN_RE.match(gen_dir.name)
                if not m:
                    continue
                generation = int(m.group(1))
                aid = _format_adapter_id(run_id, generation)
                row = idx.get((run_id, generation))
                size_mb = _dir_size_mb(gen_dir)
                total_disk += size_mb
                created = _dir_created_at(gen_dir)

                raw_scores: dict[str, float] = {}
                if row:
                    cs = row.get("child_scores") or {}
                    if isinstance(cs, str):
                        try:
                            cs = json.loads(cs)
                        except json.JSONDecodeError:
                            cs = {}
                    raw_scores = {str(k): float(v) for k, v in cs.items()} if isinstance(cs, dict) else {}

                wc = row.get("weak_categories") if row else []
                if isinstance(wc, str):
                    try:
                        wc = json.loads(wc)
                    except json.JSONDecodeError:
                        wc = []
                if not isinstance(wc, list):
                    wc = []

                cfg: dict[str, Any] = {}
                data_blob = row.get("data") if row else {}
                if isinstance(data_blob, str):
                    try:
                        data_blob = json.loads(data_blob)
                    except json.JSONDecodeError:
                        data_blob = {}
                if isinstance(data_blob, dict):
                    cfg = dict(data_blob.get("config") or {})

                run_meta = await db.get_run(run_id)
                base_model = "llama3.2:3b"
                if run_meta and run_meta.get("base_model"):
                    base_model = str(run_meta["base_model"])
                elif cfg.get("base_model"):
                    base_model = str(cfg["base_model"])

                is_champion = bool(row and row.get("is_champion")) or (
                    champion_id is not None and champion_id == aid
                )

                adapters.append(
                    AdapterInfo(
                        adapter_id=aid,
                        run_id=run_id,
                        generation=generation,
                        base_model=base_model,
                        scores=raw_scores or None,
                        size_mb=size_mb,
                        created_at=created,
                        is_champion=is_champion,
                        promoted=bool(row and row.get("promoted")),
                        training_config=cfg,
                        weak_categories=[str(x) for x in wc],
                        adapter_path=str(gen_dir),
                        archived=bool(row and row.get("archived")),
                        status=_adapter_status(row, is_champion),
                    )
                )

    # Champion id fallback from registry only
    if champion_id is None:
        for a in adapters:
            if a.is_champion:
                champion_id = a.adapter_id
                break

    return AdapterList(
        adapters=sorted(adapters, key=lambda x: (x.run_id, x.generation)),
        total=len(adapters),
        champion_id=champion_id,
        total_disk_mb=round(total_disk, 4),
    )


@router.get("/compare/{adapter_a}/{adapter_b}", response_model=AdapterCompareResponse)
async def compare_adapters(
    adapter_a: str,
    adapter_b: str,
    prompt: str | None = Query(default=None),
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
    ollama: OllamaClient = Depends(get_ollama),
) -> AdapterCompareResponse:
    from api.schemas.adapters import AdapterCompareInference

    info_a = await get_adapter(adapter_a, db, registry)
    info_b = await get_adapter(adapter_b, db, registry)

    out_a = out_b = None
    if prompt and prompt.strip():

        async def _one(info: AdapterInfo) -> AdapterCompareInference:
            tag = settings.default_base_model
            reg = registry.get_champion() or {}
            if reg.get("adapter_id") == info.adapter_id and reg.get("ollama_model"):
                tag = str(reg["ollama_model"])
            else:
                alias = adapter_alias(info.adapter_id)
                if await ollama_has_model(alias):
                    tag = alias
            try:
                r = await ollama.generate(model=tag, prompt=prompt, max_tokens=256, temperature=0.7)
                return AdapterCompareInference(
                    adapter_id=info.adapter_id,
                    response=r.get("response"),
                    model=r.get("model"),
                    tokens=r.get("tokens"),
                    latency_ms=r.get("latency_ms"),
                    source="ollama",
                )
            except Exception as exc:
                logger.warning("compare inference failed: %s", exc)
                return AdapterCompareInference(
                    adapter_id=info.adapter_id,
                    response=None,
                    model=tag,
                    source="error",
                )

        out_a = await _one(info_a)
        out_b = await _one(info_b)

    return AdapterCompareResponse(
        adapter_a=info_a,
        adapter_b=info_b,
        inference_a=out_a,
        inference_b=out_b,
    )


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_adapters(
    older_than_days: int = Query(default=30, ge=1, le=365),
    keep_promoted: int = Query(default=5, ge=0, le=50),
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> CleanupResponse:
    """Delete non-champion adapters older than ``older_than_days``, keeping recent promoted."""
    champ_id = (registry.get_champion() or {}).get("adapter_id")
    cutoff = time.time() - older_than_days * 86400

    lst = await list_adapters(db, registry)
    promoted_sorted = sorted(
        [a for a in lst.adapters if a.promoted and a.adapter_id != champ_id],
        key=lambda x: x.created_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    keep_ids = {a.adapter_id for a in promoted_sorted[:keep_promoted]}

    deleted: list[str] = []
    reclaimed = 0.0

    for a in lst.adapters:
        if a.adapter_id == champ_id or a.adapter_id in keep_ids:
            continue
        if a.is_champion:
            continue
        created_ts = (a.created_at.timestamp() if a.created_at else time.time())
        if created_ts > cutoff:
            continue
        run_id, gen = _parse_adapter_id(a.adapter_id)
        root = settings.resolve_data_root() / "adapters" / run_id / f"gen-{gen}"
        sz = _dir_size_mb(root) if root.is_dir() else 0.0
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)
        await db.set_generation_archived(run_id, gen, True)
        await emit_adapter_deleted(a.adapter_id, "cleanup")
        deleted.append(a.adapter_id)
        reclaimed += sz

    return CleanupResponse(
        deleted_count=len(deleted),
        reclaimed_mb=round(reclaimed, 4),
        adapter_ids=deleted,
    )


@router.get("/{adapter_id}", response_model=AdapterInfo)
async def get_adapter(
    adapter_id: str,
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> AdapterInfo:
    run_id, gen = _parse_adapter_id(adapter_id)
    root = settings.resolve_data_root() / "adapters" / run_id / f"gen-{gen}"
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Adapter not found on disk")

    row = await db.get_generation(run_id, gen)
    champ = registry.get_champion() or {}
    is_champion = bool(row and row.get("is_champion")) or champ.get("adapter_id") == adapter_id

    raw_scores: dict[str, float] = {}
    if row:
        cs = row.get("child_scores") or {}
        if isinstance(cs, str):
            try:
                cs = json.loads(cs)
            except json.JSONDecodeError:
                cs = {}
        if isinstance(cs, dict):
            raw_scores = {str(k): float(v) for k, v in cs.items()}

    wc = row.get("weak_categories") if row else []
    if isinstance(wc, str):
        try:
            wc = json.loads(wc)
        except json.JSONDecodeError:
            wc = []
    if not isinstance(wc, list):
        wc = []

    data_blob = row.get("data") if row else {}
    if isinstance(data_blob, str):
        try:
            data_blob = json.loads(data_blob)
        except json.JSONDecodeError:
            data_blob = {}
    cfg = dict(data_blob.get("config") or {}) if isinstance(data_blob, dict) else {}

    run_meta = await db.get_run(run_id)
    base_model = str(run_meta.get("base_model") or cfg.get("base_model") or "llama3.2:3b")

    return AdapterInfo(
        adapter_id=adapter_id,
        run_id=run_id,
        generation=gen,
        base_model=base_model,
        scores=raw_scores or None,
        size_mb=_dir_size_mb(root),
        created_at=_dir_created_at(root),
        is_champion=is_champion,
        promoted=bool(row and row.get("promoted")),
        training_config=cfg,
        weak_categories=[str(x) for x in wc],
        adapter_path=str(root),
        archived=bool(row and row.get("archived")),
        status=_adapter_status(row, is_champion),
    )


@router.delete("/{adapter_id}")
async def delete_adapter(
    adapter_id: str,
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> dict[str, Any]:
    run_id, gen = _parse_adapter_id(adapter_id)
    row = await db.get_generation(run_id, gen)
    champ = registry.get_champion() or {}
    if champ.get("adapter_id") == adapter_id or (row and row.get("is_champion")):
        raise HTTPException(status_code=409, detail="Cannot delete current champion adapter")

    root = settings.resolve_data_root() / "adapters" / run_id / f"gen-{gen}"
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
    await db.set_generation_archived(run_id, gen, True)
    await emit_adapter_deleted(adapter_id, "api_delete")
    return {"deleted": True, "adapter_id": adapter_id}


@router.post("/{adapter_id}/rollback", response_model=RollbackResponse)
async def rollback_adapter(
    adapter_id: str,
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> RollbackResponse:
    run_id, gen = _parse_adapter_id(adapter_id)
    root = settings.resolve_data_root() / "adapters" / run_id / f"gen-{gen}"
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Adapter path not found")

    row = await db.get_generation(run_id, gen)
    if not row:
        raise HTTPException(status_code=404, detail="No generation metadata in DB")

    prev = registry.get_champion() or {}
    prev_id = str(prev.get("adapter_id") or "")

    cs = row.get("child_scores") or {}
    if isinstance(cs, str):
        try:
            cs = json.loads(cs)
        except json.JSONDecodeError:
            cs = {}
    scores = {str(k): float(v) for k, v in cs.items()} if isinstance(cs, dict) else {}

    run_meta = await db.get_run(run_id)
    base_model = str((run_meta or {}).get("base_model") or "llama3.2:3b")
    alias_name = adapter_alias(adapter_id)
    await db.clear_all_champions()
    await db.set_champion_generation(run_id, gen)

    registry.set_champion(
        {
            "name": alias_name,
            "base_model": base_model,
            "generation": gen,
            "adapter_path": str(root),
            "adapter_id": adapter_id,
            "scores": scores,
            "avg_score": _weighted_avg(scores),
            "method": str(row.get("method") or "lora"),
            "promoted_at": datetime.now(UTC).isoformat(),
            "ollama_model": prev.get("ollama_model"),
        }
    )

    await emit_adapter_rollback(prev_id or "none", adapter_id, "manual_rollback")
    return RollbackResponse(
        previous_champion=prev_id or None,
        new_champion=adapter_id,
        rolled_back=True,
        message=f"Champion set to {adapter_id}",
    )


@router.post("/{adapter_id}/serve", response_model=ServeAdapterResponse)
async def serve_adapter(
    adapter_id: str,
    db: LineageDB = Depends(get_db),
    registry: ModelRegistry = Depends(get_registry),
) -> ServeAdapterResponse:
    run_id, gen = _parse_adapter_id(adapter_id)
    root = adapter_dir_abs(run_id, gen, settings.resolve_data_root())
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Adapter not found")

    row = await db.get_generation(run_id, gen)
    run_meta = await db.get_run(run_id)
    base_model = str((run_meta or {}).get("base_model") or "llama3.2:3b")

    alias_name = adapter_alias(adapter_id)
    ok, msg = await try_create_ollama_model(
        base_model=base_model,
        adapter_abs_path=root,
        alias=alias_name,
    )
    if ok:
        cs_ok = row.get("child_scores") if row else {}
        if isinstance(cs_ok, str):
            try:
                cs_ok = json.loads(cs_ok)
            except json.JSONDecodeError:
                cs_ok = {}
        scores_ok = (
            {str(k): float(v) for k, v in cs_ok.items()} if isinstance(cs_ok, dict) else {}
        )
        registry.set_champion(
            {
                "name": alias_name,
                "base_model": base_model,
                "generation": gen,
                "adapter_path": str(root.resolve()),
                "adapter_id": adapter_id,
                "scores": scores_ok,
                "avg_score": _weighted_avg(scores_ok),
                "method": str((row or {}).get("method") or "lora"),
                "ollama_model": alias_name,
                "serve_mode": "ollama",
            }
        )
        return ServeAdapterResponse(
            adapter_id=adapter_id,
            mode="ollama",
            ollama_model=alias_name,
            message=msg,
            vllm_lora_path=None,
        )

    # Soft pointer + vLLM hint
    cs = row.get("child_scores") if row else {}
    if isinstance(cs, str):
        try:
            cs = json.loads(cs)
        except json.JSONDecodeError:
            cs = {}
    scores = {str(k): float(v) for k, v in cs.items()} if isinstance(cs, dict) else {}
    registry.set_champion(
        {
            "name": alias_name,
            "base_model": base_model,
            "generation": gen,
            "adapter_path": str(root.resolve()),
            "adapter_id": adapter_id,
            "scores": scores,
            "avg_score": _weighted_avg(scores),
            "method": str((row or {}).get("method") or "lora"),
            "ollama_model": None,
            "serve_mode": "vllm_hint",
            "vllm_lora_path": str(root.resolve()),
        }
    )
    return ServeAdapterResponse(
        adapter_id=adapter_id,
        mode="vllm_hint",
        ollama_model=None,
        message=f"Ollama create failed ({msg}); registry updated with vLLM hint",
        vllm_lora_path=str(root.resolve()),
    )
