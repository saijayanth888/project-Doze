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


def _looks_like_gguf_adapter_dir(adapter_abs_path: Path) -> Path | None:
    """Return the .gguf LoRA file in the adapter dir, or None.

    Ollama (>= 0.2) only ingests **GGUF**-format LoRA adapters. The PEFT/HF
    output (`adapter_model.safetensors` + `adapter_config.json`) cannot be
    consumed by Ollama directly — it must be converted via
    `llama.cpp/convert-lora-to-gguf.py` first. This helper short-circuits the
    POST so callers get a clear "format mismatch" answer rather than a cryptic
    "neither 'from' or 'files' was specified" from the server.
    """
    if not adapter_abs_path.is_dir():
        return None
    for candidate in adapter_abs_path.glob("*.gguf"):
        return candidate
    return None


async def try_create_ollama_model(
    *,
    base_model: str,
    adapter_abs_path: Path,
    alias: str,
) -> tuple[bool, str, str | None]:
    """POST /api/create to Ollama. Returns (ok, message, error_kind).

    `error_kind` is a stable identifier the API surface can map to UI copy:
      - "format_mismatch": adapter is PEFT/safetensors, not GGUF.
      - "ollama_error":   Ollama reachable but rejected the request.
      - "ollama_unreachable": connection refused / DNS / timeout.
    """
    gguf = _looks_like_gguf_adapter_dir(adapter_abs_path)
    if gguf is None:
        msg = (
            "Adapter is in PEFT format (adapter_model.safetensors); Ollama "
            "requires a GGUF LoRA. Convert via "
            "`python llama.cpp/convert_lora_to_gguf.py` and place the .gguf "
            "file in the adapter directory before serving."
        )
        logger.info("[serve] PEFT adapter at %s — skipping Ollama create", adapter_abs_path)
        return False, msg, "format_mismatch"

    # Ollama 0.2+ deprecated the inline `modelfile` field. The supported shape
    # is `{ "model": "name", "from": "<base>", "adapters": {"file.gguf": "<sha256>"} }`
    # where the adapter blob is uploaded separately via /api/blobs first.
    base = (settings.ollama_host or "").rstrip("/")
    create_url = f"{base}/api/create"
    blobs_url = f"{base}/api/blobs"

    try:
        # 1) Read + upload the GGUF blob to get its sha256 digest.
        gguf_bytes = gguf.read_bytes()
        import hashlib
        digest = hashlib.sha256(gguf_bytes).hexdigest()
        async with httpx.AsyncClient(timeout=300.0) as client:
            put_resp = await client.put(f"{blobs_url}/sha256:{digest}", content=gguf_bytes)
            # 200 (already there) or 201 (created) are both fine.
            if put_resp.status_code not in (200, 201):
                text = put_resp.text[:500]
                logger.warning("Ollama blob upload failed %s: %s", put_resp.status_code, text)
                return False, text, "ollama_error"

            # 2) Create the model referencing the uploaded blob.
            payload = {
                "model": alias,
                "from": base_model,
                "adapters": {gguf.name: f"sha256:{digest}"},
                "parameters": {"temperature": 0.7},
                "stream": False,
            }
            resp = await client.post(create_url, json=payload)
            if resp.status_code >= 400:
                text = resp.text[:500]
                logger.warning("Ollama create failed %s: %s", resp.status_code, text)
                return False, text, "ollama_error"
            return True, "created", None
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning("Ollama create unreachable: %s", exc)
        return False, str(exc), "ollama_unreachable"
    except Exception as exc:
        logger.warning("Ollama create error: %s", exc)
        return False, str(exc), "ollama_error"


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
