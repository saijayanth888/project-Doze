"""Training dataset listing, upload, quality metrics."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.deps import get_db
from api.schemas.datasets import (
    DatasetList,
    DatasetPreview,
    DatasetQuality,
    DatasetSummary,
    DatasetUploadResponse,
    SavePairRequest,
    SavePairResponse,
)
from config.settings import settings
from services.lineage_db import LineageDB
from services.n8n_webhook import emit_dataset_uploaded

logger = logging.getLogger("modelforge.routes.datasets")

router = APIRouter()


def _norm_hash(instr: str, resp: str) -> str:
    s = re.sub(r"\s+", " ", (instr + "|" + resp).lower()).strip()
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _count_arrow_rows(arrow_path: Path) -> int:
    """Count rows in a HuggingFace `Dataset.save_to_disk()` shard.

    The curator writes via `Dataset.save_to_disk()` which produces an Arrow IPC
    file but stores no `num_samples` field in `dataset_info.json`. Counting via
    pyarrow is fast (<1ms for our shard sizes) and avoids loading column data.
    """
    try:
        import pyarrow as pa  # bundled with `datasets`
        with pa.memory_map(str(arrow_path), "r") as src:
            reader = pa.ipc.open_stream(src)
            total = 0
            for batch in reader:
                total += batch.num_rows
            return total
    except Exception:
        return 0


def _scan_curated(data_root: Path) -> list[DatasetSummary]:
    out: list[DatasetSummary] = []
    curated = data_root / "curated"
    if not curated.is_dir():
        return out
    for p in sorted(curated.iterdir()):
        if not p.is_dir() or not p.name.startswith("gen-"):
            continue
        try:
            gen = int(p.name.replace("gen-", ""))
        except ValueError:
            gen = 0
        size_mb = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / (1024 * 1024)
        # Prefer our sidecar (categories, num_samples, sources) — the curator
        # writes this alongside the arrow shard. Fall back to `dataset_info.json`
        # for backward compat with older runs that pre-date the sidecar.
        n_samples = 0
        categories: list[str] = []
        sources: list[str] = []
        mf_meta_fp = p / "mf_meta.json"
        if mf_meta_fp.is_file():
            try:
                meta = json.loads(mf_meta_fp.read_text(encoding="utf-8"))
                n_samples = int(meta.get("num_samples", 0))
                categories = list(meta.get("categories") or [])
                sources = list(meta.get("sources") or [])
            except Exception:
                pass
        if n_samples == 0:
            meta_fp = p / "dataset_info.json"
            if meta_fp.is_file():
                try:
                    meta = json.loads(meta_fp.read_text(encoding="utf-8"))
                    n_samples = int(meta.get("num_samples", 0))
                    categories = list(meta.get("categories") or categories)
                    sources = list(meta.get("sources") or sources)
                except Exception:
                    pass
        # Last resort: actually count rows in the arrow shard (slow on large
        # datasets but cached by the OS page cache after the first hit).
        if n_samples == 0:
            for shard in sorted(p.glob("data-*.arrow")):
                n_samples += _count_arrow_rows(shard)
        ts = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
        out.append(
            DatasetSummary(
                dataset_id=p.name,
                generation=gen,
                num_samples=n_samples,
                categories=categories,
                sources=sources or ["curated"],
                size_mb=round(size_mb, 4),
                created_at=ts,
                kind="curated",
            )
        )
    return out


def _scan_custom(data_root: Path) -> list[DatasetSummary]:
    out: list[DatasetSummary] = []
    custom = data_root / "custom"
    if not custom.is_dir():
        return out
    for p in sorted(custom.iterdir()):
        if not p.is_dir():
            continue
        meta_fp = p / "meta.json"
        jsonl = p / "dataset.jsonl"
        if not meta_fp.is_file():
            continue
        try:
            meta = json.loads(meta_fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        size_mb = jsonl.stat().st_size / (1024 * 1024) if jsonl.is_file() else 0.0
        ts_s = meta.get("created_at")
        try:
            created = datetime.fromisoformat(str(ts_s).replace("Z", "+00:00"))
        except Exception:
            created = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
        out.append(
            DatasetSummary(
                dataset_id=p.name,
                generation=None,
                num_samples=int(meta.get("num_samples", 0)),
                categories=list(meta.get("categories") or []),
                sources=["upload"],
                size_mb=round(size_mb, 4),
                created_at=created,
                kind="custom",
            )
        )
    return out


@router.get("/", response_model=DatasetList)
async def list_datasets() -> DatasetList:
    root = settings.resolve_data_root()
    items = _scan_curated(root) + _scan_custom(root)
    return DatasetList(datasets=sorted(items, key=lambda x: x.dataset_id), total=len(items))


@router.post("/upload", response_model=DatasetUploadResponse)
async def upload_dataset(
    file: UploadFile = File(...),
    db: LineageDB = Depends(get_db),
) -> DatasetUploadResponse:
    if not file.filename or not file.filename.endswith(".jsonl"):
        raise HTTPException(status_code=400, detail="Expected a .jsonl file")

    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="File must be UTF-8") from exc

    lines_kept: list[dict[str, str]] = []
    dup_batch: set[str] = set()
    dup_skip = 0
    categories: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            dup_skip += 1
            continue
        ins = obj.get("instruction")
        res = obj.get("response")
        if ins is None or res is None:
            dup_skip += 1
            continue
        ins_s, res_s = str(ins), str(res)
        h = _norm_hash(ins_s, res_s)
        if h in dup_batch:
            dup_skip += 1
            continue
        dup_batch.add(h)
        lines_kept.append({"instruction": ins_s, "response": res_s})
        if obj.get("category"):
            categories.append(str(obj["category"]))

    hashes = list(dup_batch)
    existing = await db.find_existing_content_hashes(hashes)
    final_lines: list[dict[str, str]] = []
    for row in lines_kept:
        h = _norm_hash(row["instruction"], row["response"])
        if h in existing:
            dup_skip += 1
            continue
        final_lines.append(row)

    ds_id = str(uuid.uuid4())
    base = settings.resolve_data_root() / "custom" / ds_id
    base.mkdir(parents=True, exist_ok=True)
    jl_path = base / "dataset.jsonl"
    with jl_path.open("w", encoding="utf-8") as out_f:
        for row in final_lines:
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            h = _norm_hash(row["instruction"], row["response"])
            await db.insert_training_sample_row(
                generation=0,
                source="upload",
                dataset_name=ds_id,
                category=None,
                instruction=row["instruction"],
                response=row["response"],
                content_hash=h,
            )

    cat_hist = [str(c) for c, _n in Counter(categories).most_common(20)]
    meta = {
        "name": file.filename,
        "num_samples": len(final_lines),
        "categories": cat_hist,
        "created_at": datetime.now(UTC).isoformat(),
    }
    (base / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    await emit_dataset_uploaded(ds_id, file.filename, len(final_lines))

    return DatasetUploadResponse(
        dataset_id=ds_id,
        num_samples=len(final_lines),
        duplicates_skipped=dup_skip,
        message=f"Stored {len(final_lines)} rows",
    )


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: str) -> dict[str, bool]:
    root = settings.resolve_data_root() / "custom" / dataset_id
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Custom dataset not found")
    shutil.rmtree(root, ignore_errors=True)
    return {"deleted": True}


@router.get("/{dataset_id}/quality", response_model=DatasetQuality)
async def dataset_quality(
    dataset_id: str,
    db: LineageDB = Depends(get_db),
) -> DatasetQuality:
    root = settings.resolve_data_root()
    path_dir = root / "custom" / dataset_id
    if not path_dir.is_dir():
        path_dir = root / "curated" / dataset_id
    if not path_dir.is_dir():
        raise HTTPException(status_code=404, detail="Dataset not found")

    jl = path_dir / "dataset.jsonl"
    if not jl.is_file():
        raise HTTPException(status_code=400, detail="No dataset.jsonl")

    rows: list[dict[str, str]] = []
    hashes: list[str] = []
    with jl.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                ins = str(obj.get("instruction", ""))
                res = str(obj.get("response", ""))
                rows.append({"instruction": ins, "response": res})
                hashes.append(_norm_hash(ins, res))
            except json.JSONDecodeError:
                continue

    n = len(rows)
    dup_rate = 1.0 - (len(set(hashes)) / n) if n else 0.0

    ilens = [len(r["instruction"]) for r in rows]
    rlens = [len(r["response"]) for r in rows]
    avg_i = sum(ilens) / n if n else 0.0
    avg_r = sum(rlens) / n if n else 0.0

    # Histogram buckets: 0-128, 128-512, 512-2048, 2048+
    def hist(vals: list[int]) -> list[int]:
        b = [0, 0, 0, 0]
        for v in vals:
            if v < 128:
                b[0] += 1
            elif v < 512:
                b[1] += 1
            elif v < 2048:
                b[2] += 1
            else:
                b[3] += 1
        return b

    overlap = await db.count_hash_overlap_excluding_dataset(hashes, dataset_id)

    diversity: float | None = None
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        sample_texts = [r["instruction"][:512] for r in rows[: min(200, len(rows))]]
        if len(sample_texts) >= 2:
            emb = model.encode(sample_texts)
            import numpy as np

            arr = np.array(emb)
            sim = np.dot(arr, arr.T).mean()
            diversity = float(max(0.0, min(1.0, 1.0 - float(sim))))
    except Exception:
        diversity = None

    return DatasetQuality(
        dataset_id=dataset_id,
        duplicate_rate=round(dup_rate, 4),
        avg_instruction_len=round(avg_i, 2),
        avg_response_len=round(avg_r, 2),
        length_histogram={
            "instruction_buckets": hist(ilens),
            "response_buckets": hist(rlens),
        },
        category_distribution={},
        overlap_with_training=overlap,
        embedding_diversity=diversity,
    )


@router.post("/save-pair", response_model=SavePairResponse)
async def save_pair(
    body: SavePairRequest,
    db: LineageDB = Depends(get_db),
) -> SavePairResponse:
    root = settings.resolve_data_root() / "custom" / body.dataset_id
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Dataset not found")
    jl = root / "dataset.jsonl"
    h = _norm_hash(body.instruction, body.response)
    existing = await db.find_existing_content_hashes([h])
    if h in existing:
        return SavePairResponse(ok=True, dataset_id=body.dataset_id, appended=False)
    line = json.dumps(
        {"instruction": body.instruction, "response": body.response},
        ensure_ascii=False,
    )
    with jl.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    await db.insert_training_sample_row(
        generation=0,
        source="playground",
        dataset_name=body.dataset_id,
        category=None,
        instruction=body.instruction,
        response=body.response,
        content_hash=h,
    )
    meta_fp = root / "meta.json"
    if meta_fp.is_file():
        try:
            meta = json.loads(meta_fp.read_text(encoding="utf-8"))
            meta["num_samples"] = int(meta.get("num_samples", 0)) + 1
            meta_fp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except Exception:
            pass
    return SavePairResponse(ok=True, dataset_id=body.dataset_id, appended=True)


@router.get("/{dataset_id}", response_model=DatasetPreview)
async def get_dataset(dataset_id: str) -> DatasetPreview:
    root = settings.resolve_data_root()
    path_dir = root / "curated" / dataset_id
    kind = "curated"
    if not path_dir.is_dir():
        path_dir = root / "custom" / dataset_id
        kind = "custom"
    if not path_dir.is_dir():
        raise HTTPException(status_code=404, detail="Dataset not found")

    meta: dict = {}
    meta_fp = path_dir / "meta.json"
    if meta_fp.is_file():
        try:
            meta = json.loads(meta_fp.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    elif kind == "curated":
        info_fp = path_dir / "dataset_info.json"
        if info_fp.is_file():
            try:
                meta = json.loads(info_fp.read_text(encoding="utf-8"))
            except Exception:
                meta = {}

    samples: list[dict[str, str]] = []
    total: int | None = None
    categories: list[str] = []

    # 1) Custom uploads: dataset.jsonl
    jl = path_dir / "dataset.jsonl"
    if jl.is_file():
        with jl.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 5:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    samples.append(
                        {
                            "instruction": str(obj.get("instruction", "")),
                            "response": str(obj.get("response", "")),
                            "category": str(obj.get("category", "")),
                            "source": str(obj.get("source", "")),
                        }
                    )
                except json.JSONDecodeError:
                    continue

    # 2) Curated datasets: HuggingFace Arrow shards from `Dataset.save_to_disk()`.
    # The previous implementation only checked dataset.jsonl, so curated dirs
    # always returned `samples: []` — making the preview pane look broken.
    if not samples:
        try:
            from datasets import Dataset  # type: ignore
            ds = Dataset.load_from_disk(str(path_dir))
            total = int(len(ds))
            preview_n = min(10, total)
            for i in range(preview_n):
                row = ds[i]
                samples.append(
                    {
                        "instruction": str(row.get("instruction", ""))[:1500],
                        "response": str(row.get("response", ""))[:1500],
                        "category": str(row.get("category", "") or ""),
                        "source": str(row.get("source", "") or row.get("dataset_name", "") or ""),
                    }
                )
            # Distinct categories actually present in the data, not just metadata.
            try:
                cats_seen = sorted(set(str(c) for c in ds["category"] if c))
                categories = cats_seen[:32]
            except Exception:
                pass
        except Exception as exc:
            logger.debug("[datasets] arrow preview skipped for %s: %s", dataset_id, exc)

    # Fall back to the sidecar's category list if we couldn't read from arrow.
    if not categories:
        sidecar = path_dir / "mf_meta.json"
        if sidecar.is_file():
            try:
                m = json.loads(sidecar.read_text(encoding="utf-8"))
                categories = [str(c) for c in (m.get("categories") or [])]
                if total is None:
                    total = int(m.get("num_samples") or 0) or None
            except Exception:
                pass

    return DatasetPreview(
        dataset_id=dataset_id,
        kind=kind,
        metadata=meta,
        samples=samples,
        total=total,
        categories=categories,
    )
