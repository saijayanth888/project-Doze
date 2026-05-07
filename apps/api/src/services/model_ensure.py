"""Pre-flight model availability for campaigns.

Walks an experiment list, resolves every referenced base model to a canonical
HF ``repo_id`` (Ollama-style tags are mapped via :mod:`utils.hf_model_id`), and
calls ``huggingface_hub.snapshot_download`` for any repo that isn't already in
the local cache. Training and lm-eval both load through Transformers, so an HF
cache hit is what they actually need.

Lets a campaign be kicked off from the UI without anyone first running
``huggingface-cli download`` by hand.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from utils.hf_model_id import resolve_hf_base_model_id

logger = logging.getLogger("modelforge.services.model_ensure")

# Files we actually need for training / eval. Skipping ``*.pth`` and the
# ``original/consolidated*`` shards avoids pulling the multi-GB legacy
# PyTorch checkpoint when the equivalent safetensors set will already be
# downloaded.
_ALLOW_PATTERNS = [
    "*.json",
    "*.txt",
    "*.model",
    "tokenizer.*",
    "*.safetensors",
    "*.safetensors.index.json",
]


def _hf_cache_root() -> Path:
    explicit = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if explicit:
        return Path(explicit)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _cached_repo_dir(repo_id: str) -> Path:
    return _hf_cache_root() / f"models--{repo_id.replace('/', '--')}"


def is_hf_repo_cached(repo_id: str) -> bool:
    snaps = _cached_repo_dir(repo_id) / "snapshots"
    if not snaps.is_dir():
        return False
    return any(snaps.iterdir())


def repo_ids_for_experiments(experiments: list[dict]) -> list[str]:
    """Unique, ordered list of HF repo ids referenced by ``experiments``."""
    seen: set[str] = set()
    out: list[str] = []
    for exp in experiments:
        raw = exp.get("model") or exp.get("base_model")
        if not raw:
            continue
        repo_id = resolve_hf_base_model_id(str(raw))
        if "/" not in repo_id:
            continue  # unmapped Ollama tag — let the runner surface that itself
        if repo_id in seen:
            continue
        seen.add(repo_id)
        out.append(repo_id)
    return out


async def ensure_hf_repo(
    repo_id: str,
    *,
    notify: Callable[[str, str], Awaitable[None]] | None = None,
) -> None:
    """Download ``repo_id`` into the HF cache if not already present."""
    if is_hf_repo_cached(repo_id):
        logger.info("[ensure] cached: %s", repo_id)
        return

    if notify:
        await notify(f"Downloading {repo_id} to local HF cache…", "⬇️")

    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")

    def _do() -> str:
        return snapshot_download(
            repo_id=repo_id,
            allow_patterns=_ALLOW_PATTERNS,
            token=token,
        )

    try:
        path = await asyncio.to_thread(_do)
    except GatedRepoError as exc:
        raise RuntimeError(
            f"HF repo {repo_id!r} is gated and the configured HF_TOKEN "
            f"doesn't have access. Accept the license at "
            f"https://huggingface.co/{repo_id} and retry."
        ) from exc
    except RepositoryNotFoundError as exc:
        raise RuntimeError(f"HF repo {repo_id!r} not found") from exc

    logger.info("[ensure] downloaded %s -> %s", repo_id, path)
    if notify:
        await notify(f"Downloaded {repo_id}", "✅")


async def ensure_all_for_experiments(
    experiments: list[dict],
    *,
    notify: Callable[[str, str], Awaitable[None]] | None = None,
) -> list[str]:
    """Ensure every referenced HF repo is locally cached."""
    repos = repo_ids_for_experiments(experiments)
    missing = [r for r in repos if not is_hf_repo_cached(r)]
    if not missing:
        if notify and repos:
            await notify(
                f"Pre-flight: all {len(repos)} model(s) already cached.", "✅"
            )
        return repos

    if notify:
        preview = ", ".join(missing[:6]) + ("…" if len(missing) > 6 else "")
        await notify(
            f"Pre-flight: downloading {len(missing)} of {len(repos)} model(s) · {preview}",
            "📦",
        )
    for repo_id in missing:
        await ensure_hf_repo(repo_id, notify=notify)
    return repos
