"""Serve LoRA adapters via Ollama Modelfile or soft-pointer + vLLM hint."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from config.settings import settings

logger = logging.getLogger("modelforge.adapter_serve")

_SAFE_ALIAS_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def adapter_alias(adapter_id: str) -> str:
    """Ollama-safe model name fragment."""
    cleaned = _SAFE_ALIAS_RE.sub("-", adapter_id.replace("__gen", "-g")).strip("-")
    return f"mf-{cleaned[:120]}"


def adapter_dir_abs(run_id: str, generation: int, data_root: Path) -> Path:
    return data_root / "adapters" / run_id / f"gen-{generation}"


async def try_create_ollama_model(
    *,
    base_model: str,
    adapter_abs_path: Path,
    alias: str,
) -> tuple[bool, str]:
    """POST /api/create to Ollama. Returns (ok, message)."""
    modelfile = (
        f'FROM {base_model}\n'
        f'ADAPTER {adapter_abs_path.resolve()}\n'
        "PARAMETER temperature 0.7\n"
    )
    url = f"{settings.ollama_host.rstrip('/')}/api/create"
    payload = {"name": alias, "modelfile": modelfile, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                text = resp.text[:500]
                logger.warning("Ollama create failed %s: %s", resp.status_code, text)
                return False, text
            return True, "created"
    except Exception as exc:
        logger.warning("Ollama create unreachable: %s", exc)
        return False, str(exc)


async def ollama_has_model(tag: str) -> bool:
    """Return True if ``tag`` appears in ``GET /api/tags``."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_host.rstrip('/')}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models") or []
            names = {m.get("name") or m.get("model") for m in models if isinstance(m, dict)}
            return tag in names
    except Exception:
        return False
