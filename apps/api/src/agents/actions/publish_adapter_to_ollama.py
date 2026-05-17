"""``adapter.publish_ollama`` — push a promoted LoRA adapter into Ollama.

This is the last hop in the trading-bot → model-forge → Ollama pipeline.
It fires when ``track.promoted`` lands on the event bus for a track whose
id starts with ``trading-``. The job:

1. Locate the on-disk adapter dir for ``<run_id>/gen-<generation>`` under
   the model-forge data root.
2. Make sure a GGUF LoRA file exists in that dir (the only LoRA format
   Ollama can ingest). If not, run llama.cpp's
   ``convert_lora_to_gguf.py`` as a subprocess to produce one. If
   conversion is unavailable, return ``skipped`` with an actionable
   reason -- the operator can convert manually and re-trigger.
3. Read the .gguf bytes, PUT them to Ollama's ``/api/blobs`` endpoint
   (sha256-keyed), and POST ``/api/create`` referencing the blob. This
   sidesteps any host-vs-container path-mapping concern: the blob is
   uploaded over HTTP so Ollama only ever sees its own filesystem.
4. Create + atomically swing a ``-current`` alias via ``/api/copy``
   (delete old + recreate) so trading-bot can always pull
   ``qwen3:30b-reflector-current`` without knowing the date stamp.

Failure modes are explicit:

* Ollama unreachable → ``skipped`` (NOT failed) so the workflow run
  shows up as skipped rather than red on the dashboard.
* GGUF missing AND no conversion script available → ``skipped`` with
  an operator-actionable message.
* GGUF conversion subprocess fails → ``error`` (the conversion script
  is on disk; if it can't produce output something is wrong).
* Ollama create rejects the request → ``error`` with the server reply.

Subprocess safety: ``_invoke_converter`` uses
``asyncio.create_subprocess_exec`` with an argv list (no shell, no
string interpolation). The script path is resolved via env-var or a
fixed allow-list of host paths; the only user-influenced argument is
``adapter_dir`` itself, which has already been resolved to a Path
rooted under ``settings.resolve_data_root()`` upstream.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from config.settings import settings
from services.automation_engine.actions import Action, ActionResult

logger = logging.getLogger("modelforge.automation.actions.publish_adapter_to_ollama")


# ── Path discovery helpers ─────────────────────────────────────────────


def _role_from_track_id(track_id: str) -> str:
    """Strip the ``trading-`` prefix so the role lands in the model tag."""
    track_id = str(track_id or "").strip()
    if track_id.startswith("trading-"):
        return track_id[len("trading-") :]
    return track_id or "unknown"


def _adapter_dir(run_id: str, generation: int) -> Path:
    """``<data_root>/adapters/<run_id>/gen-<N>`` -- no existence check."""
    data_root = settings.resolve_data_root()
    return data_root / "adapters" / str(run_id) / f"gen-{int(generation)}"


def _find_gguf(adapter_dir: Path) -> Path | None:
    """First ``.gguf`` file in the adapter dir, or ``None``."""
    if not adapter_dir.is_dir():
        return None
    for cand in sorted(adapter_dir.glob("*.gguf")):
        return cand
    return None


# ── GGUF conversion (best-effort subprocess) ───────────────────────────


def _resolve_convert_script() -> Path | None:
    """Find llama.cpp's ``convert_lora_to_gguf.py`` on this host.

    Resolution order:

    1. ``MODELFORGE_LLAMA_CPP_CONVERT`` env var (full path to script).
    2. ``MODELFORGE_LLAMA_CPP_DIR`` env var (clone root; script is at
       ``<dir>/convert_lora_to_gguf.py``).
    3. Fixed allow-list of common locations.

    Returns ``None`` when nothing matches; the caller surfaces a
    ``skipped`` result with the env-var hint.
    """
    explicit = os.environ.get("MODELFORGE_LLAMA_CPP_CONVERT")
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p

    dir_env = os.environ.get("MODELFORGE_LLAMA_CPP_DIR")
    candidates: list[Path] = []
    if dir_env:
        candidates.append(Path(dir_env) / "convert_lora_to_gguf.py")
    candidates += [
        Path("/opt/llama.cpp/convert_lora_to_gguf.py"),
        Path("/app/llama.cpp/convert_lora_to_gguf.py"),
        Path("/usr/local/llama.cpp/convert_lora_to_gguf.py"),
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


async def _invoke_converter(
    script: Path, adapter_dir: Path, out_path: Path, quantization: str,
) -> tuple[int, bytes, bytes]:
    """Spawn the converter as a clean argv-list subprocess.

    Returns ``(returncode, stdout, stderr)``. Uses
    ``create_subprocess_exec`` so there is no shell, no string
    interpolation, and no possibility of shell injection -- the same
    pattern the trainer/eval workers use.
    """
    argv = [
        "python",
        str(script),
        str(adapter_dir),
        "--outfile",
        str(out_path),
        "--outtype",
        str(quantization),
    ]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return int(proc.returncode or 0), out_b or b"", err_b or b""


async def _convert_to_gguf(
    adapter_dir: Path, *, quantization: str = "f16",
) -> tuple[Path | None, str]:
    """Best-effort GGUF conversion. Returns ``(gguf_path, message)``."""
    script = _resolve_convert_script()
    if script is None:
        return None, (
            "llama.cpp convert_lora_to_gguf.py not found. Set "
            "MODELFORGE_LLAMA_CPP_CONVERT or MODELFORGE_LLAMA_CPP_DIR, "
            "or convert manually and drop a .gguf into the adapter dir."
        )

    out_path = adapter_dir / "adapter.gguf"
    logger.info("[publish-ollama] converting %s → %s", adapter_dir, out_path)
    try:
        rc, stdout_b, stderr_b = await _invoke_converter(
            script, adapter_dir, out_path, quantization,
        )
    except FileNotFoundError as exc:
        return None, f"convert subprocess spawn failed: {exc}"
    except OSError as exc:
        return None, f"convert subprocess OS error: {exc}"

    if rc != 0:
        tail = (stderr_b or stdout_b).decode(errors="replace").strip()[-500:]
        return None, f"convert_lora_to_gguf.py exited {rc}: {tail}"
    if not out_path.is_file():
        return None, "convert script returned 0 but no .gguf file was produced"
    return out_path, f"converted via {script.name} ({quantization})"


# ── Ollama HTTP helpers ────────────────────────────────────────────────


async def _ollama_reachable(client: httpx.AsyncClient, base: str) -> bool:
    """``GET /api/tags`` ping. ``False`` lets us return ``skipped``."""
    try:
        resp = await client.get(f"{base}/api/tags")
        return resp.status_code < 500
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
        return False


_BLOB_CHUNK_BYTES = 8 * 1024 * 1024  # 8 MiB — matches typical proxy buffers.


def _hash_gguf_streaming(gguf_path: Path) -> tuple[str, int]:
    """Compute sha256(gguf_path) without loading the file into memory.

    Returns ``(hex_digest, file_size_bytes)``. Quantized 30B LoRAs land in
    the 5-15GB range; the previous ``read_bytes()`` path doubled that as
    a Python ``bytes`` object on top of the file cache and tripled it
    when httpx encoded the body for the PUT.
    """
    h = hashlib.sha256()
    size = 0
    with gguf_path.open("rb") as f:
        while True:
            chunk = f.read(_BLOB_CHUNK_BYTES)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


async def _aiter_file_chunks(gguf_path: Path):
    """Async generator yielding ``_BLOB_CHUNK_BYTES`` reads.

    httpx's AsyncClient ``content=`` accepts an async iterable of bytes
    and streams the PUT body without buffering the full payload. File
    IO is delegated to a thread executor so the event loop isn't
    blocked while reading multi-GB blobs.
    """
    loop = asyncio.get_running_loop()
    f = gguf_path.open("rb")
    try:
        while True:
            chunk = await loop.run_in_executor(None, f.read, _BLOB_CHUNK_BYTES)
            if not chunk:
                return
            yield chunk
    finally:
        f.close()


async def _put_blob(
    client: httpx.AsyncClient,  # kept for ABI compat; unused — see note below
    base: str,
    gguf_path: Path,
    *,
    digest: str,
    content_length: int,
) -> tuple[bool, str, str]:
    """Stream a GGUF blob to Ollama, keyed by its sha256 digest.

    HTTP client: aiohttp (NOT httpx). On Ollama 0.23.1 this endpoint
    sends a response pattern that httpx.AsyncClient parses as
    ``ReadError('')`` on every variant we tested (sync POST works, async
    POST fails — streaming or full-body, http2 on or off, IPv4 alias or
    bridge IP). aiohttp's response parser handles the same response
    cleanly, returns 200. The other Ollama endpoints in this action
    (/api/create, /api/copy, /api/delete) use httpx and work fine
    because their responses are small JSON and don't trip the parser
    edge case.
    Audit 2026-05-17 — full repro in /tmp/blob_upload_isolation.py.

    Function signature accepts the httpx client to keep the call site
    in execute() unchanged (it passes the existing client we never use).
    Streaming chunked transfer is preserved so peak memory stays at
    one chunk (8 MiB) rather than the full blob (5-15 GB for typical
    quantized adapters on top of a 30B+ base).

    HTTP verb: POST. Ollama 0.23+ rejects PUT with 405 Method Not
    Allowed — the documented method for /api/blobs/<digest> is POST.
    """
    _ = client  # explicit acknowledgement that the param is unused

    import aiohttp
    url = f"{base}/api/blobs/sha256:{digest}"
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(content_length),
    }

    async def _aiohttp_chunks():
        # aiohttp accepts an async iterable directly; same chunk size as
        # the httpx variant for parity in network behaviour.
        loop = asyncio.get_event_loop()
        with gguf_path.open("rb") as fh:
            while True:
                chunk = await loop.run_in_executor(None, fh.read, _BLOB_CHUNK_BYTES)
                if not chunk:
                    return
                yield chunk

    try:
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.post(url, data=_aiohttp_chunks(), headers=headers) as resp:
                if resp.status not in (200, 201):
                    body = (await resp.text())[:200]
                    return False, digest, f"blob upload HTTP {resp.status}: {body}"
                return True, digest, f"blob uploaded ({content_length / (1024 ** 3):.2f} GiB)"
    except Exception as exc:
        return False, digest, f"blob upload network error: {exc!r}"


async def _create_model(
    client: httpx.AsyncClient,
    base: str,
    *,
    model_name: str,
    from_model: str,
    gguf_filename: str,
    digest: str,
    system_prompt: str | None,
) -> tuple[bool, str]:
    """POST ``/api/create`` for the versioned model name."""
    payload: dict[str, Any] = {
        "model": model_name,
        "from": from_model,
        "adapters": {gguf_filename: f"sha256:{digest}"},
        "stream": False,
    }
    if system_prompt:
        payload["system"] = system_prompt
    try:
        resp = await client.post(f"{base}/api/create", json=payload)
    except httpx.RequestError as exc:
        return False, f"create network error: {exc}"
    if resp.status_code >= 400:
        return False, f"create HTTP {resp.status_code}: {resp.text[:300]}"
    return True, "created"


async def _swing_alias(
    client: httpx.AsyncClient, base: str, *, source: str, alias: str,
) -> tuple[bool, str]:
    """Repoint ``alias`` at ``source`` (delete + copy)."""
    if alias == source:
        return True, "alias matches versioned name; no copy needed"

    try:
        del_resp = await client.request(
            "DELETE", f"{base}/api/delete", json={"name": alias},
        )
        if del_resp.status_code >= 500:
            logger.warning(
                "[publish-ollama] alias delete HTTP %s: %s",
                del_resp.status_code, del_resp.text[:200],
            )
    except httpx.RequestError as exc:
        logger.warning("[publish-ollama] alias delete network error: %s", exc)

    try:
        cp_resp = await client.post(
            f"{base}/api/copy",
            json={"source": source, "destination": alias},
        )
    except httpx.RequestError as exc:
        return False, f"copy network error: {exc}"
    if cp_resp.status_code >= 400:
        return False, f"copy HTTP {cp_resp.status_code}: {cp_resp.text[:200]}"
    return True, "alias updated"


# ── Action ─────────────────────────────────────────────────────────────


class PublishAdapterToOllama(Action):
    """Push a promoted LoRA adapter to host Ollama as a named model."""

    kind = "adapter.publish_ollama"
    label = "Publish adapter to Ollama"
    description = (
        "Take the adapter from a freshly promoted track, convert/locate its "
        "GGUF blob, upload it to Ollama, create a versioned model name and "
        "swing a -current alias. Wire this to the track.promoted event."
    )
    schema = [
        {
            "name": "ollama_host", "type": "string",
            "label": "Ollama base URL", "default": "",
            "help": "Leave blank to use the server's configured OLLAMA_HOST.",
        },
        {
            "name": "base_model", "type": "string",
            "label": "Base model tag", "default": "qwen3:30b",
            "help": "Used as FROM in the Modelfile and as the prefix in the "
                    "versioned model name.",
        },
        {
            "name": "model_name_pattern", "type": "string",
            "label": "Versioned model name pattern",
            "default": "{base_model}-{role}-v{date}",
            "help": "Placeholders: {base_model}, {role}, {date} (UTC "
                    "YYYYMMDD), {generation}, {run_id}.",
        },
        {
            "name": "alias_pattern", "type": "string",
            "label": "Current-alias pattern",
            "default": "{base_model}-{role}-current",
            "help": "Same placeholders as the versioned pattern.",
        },
        {
            "name": "system_prompt", "type": "textarea",
            "label": "Optional SYSTEM prompt baked into the Modelfile",
            "default": "",
        },
        {
            "name": "quantization", "type": "string",
            "label": "GGUF quantization (only used if conversion runs)",
            "default": "f16",
        },
    ]

    # ── name rendering ───────────────────────────────────────────────

    @staticmethod
    def _slug(base_model: str) -> str:
        """``qwen3:30b`` → ``qwen3-30b`` (Ollama tag-safe prefix)."""
        return str(base_model or "model").replace(":", "-")

    @classmethod
    def _render_name(
        cls, pattern: str, *,
        base_model: str, role: str, date: str,
        generation: int, run_id: str,
    ) -> str:
        return (
            (pattern or "")
            .replace("{base_model}", cls._slug(base_model))
            .replace("{role}", role)
            .replace("{date}", date)
            .replace("{generation}", str(generation))
            .replace("{run_id}", str(run_id))
        )

    # ── execute ──────────────────────────────────────────────────────

    async def execute(self, *, config, context, engine):  # noqa: ARG002
        # 1) Payload.
        track_id = str(context.get("track_id") or "").strip()
        run_id = str(context.get("run_id") or "").strip()
        generation_raw = context.get("generation")
        try:
            generation = int(generation_raw) if generation_raw is not None else None
        except (TypeError, ValueError):
            generation = None

        if not track_id or not run_id or generation is None:
            return ActionResult(
                status="error",
                error="missing payload",
                message=(
                    "track.promoted payload incomplete -- need track_id, "
                    f"run_id, generation; got {track_id!r}/{run_id!r}/{generation_raw!r}"
                ),
            )

        # 2) Adapter dir on disk.
        adapter_dir = _adapter_dir(run_id, int(generation))
        if not adapter_dir.is_dir():
            return ActionResult(
                status="error",
                error="adapter_dir_missing",
                message=f"Adapter directory not on disk: {adapter_dir}",
            )

        # 3) GGUF: existing file wins, otherwise convert.
        gguf_path = _find_gguf(adapter_dir)
        conversion_note = "preexisting .gguf in adapter dir"
        if gguf_path is None:
            quant = str(config.get("quantization") or "f16")
            gguf_path, conversion_note = await _convert_to_gguf(
                adapter_dir, quantization=quant,
            )
            if gguf_path is None:
                if "not found" in conversion_note.lower():
                    return ActionResult(
                        status="skipped",
                        message=f"GGUF unavailable: {conversion_note}",
                        output={"adapter_dir": str(adapter_dir)},
                    )
                return ActionResult(
                    status="error",
                    error="gguf_conversion_failed",
                    message=conversion_note,
                    output={"adapter_dir": str(adapter_dir)},
                )

        # 4) Render model name + alias.
        base_model = str(config.get("base_model") or "qwen3:30b").strip()
        role = _role_from_track_id(track_id)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        model_name = self._render_name(
            str(config.get("model_name_pattern") or "{base_model}-{role}-v{date}"),
            base_model=base_model, role=role, date=date_str,
            generation=int(generation), run_id=run_id,
        )
        alias_name = self._render_name(
            str(config.get("alias_pattern") or "{base_model}-{role}-current"),
            base_model=base_model, role=role, date=date_str,
            generation=int(generation), run_id=run_id,
        )

        # 5) Compute the digest + size by streaming the file. Loading
        # the entire blob into memory (a 5-15 GB single ``bytes`` object)
        # was the failure mode this replaces: it spiked the API
        # container's RSS hard enough to trigger the cgroup OOM-killer
        # on the unified-memory host.
        try:
            digest, gguf_size = _hash_gguf_streaming(gguf_path)
        except OSError as exc:
            return ActionResult(
                status="error",
                error="gguf_read_failed",
                message=f"Could not read {gguf_path}: {exc}",
            )

        # 6) Push to Ollama.
        host_override = str(config.get("ollama_host") or "").strip()
        base = (host_override or settings.ollama_host or "").rstrip("/")
        if not base:
            return ActionResult(
                status="error",
                error="no_ollama_host",
                message="No ollama_host configured (action + settings empty)",
            )
        system_prompt = str(config.get("system_prompt") or "").strip() or None

        async with httpx.AsyncClient(timeout=300.0) as client:
            if not await _ollama_reachable(client, base):
                return ActionResult(
                    status="skipped",
                    message=f"Ollama unreachable at {base} -- adapter left on disk at {adapter_dir}",
                    output={
                        "ollama_host": base,
                        "adapter_dir": str(adapter_dir),
                        "gguf_path": str(gguf_path),
                        "intended_model_name": model_name,
                        "intended_alias": alias_name,
                    },
                )

            put_ok, _, put_msg = await _put_blob(
                client, base, gguf_path,
                digest=digest, content_length=gguf_size,
            )
            if not put_ok:
                return ActionResult(
                    status="error",
                    error="blob_upload_failed",
                    message=put_msg,
                    output={"digest": digest, "ollama_host": base},
                )

            create_ok, create_msg = await _create_model(
                client, base,
                model_name=model_name, from_model=base_model,
                gguf_filename=gguf_path.name, digest=digest,
                system_prompt=system_prompt,
            )
            if not create_ok:
                return ActionResult(
                    status="error",
                    error="ollama_create_failed",
                    message=create_msg,
                    output={
                        "digest": digest, "ollama_host": base,
                        "model_name": model_name,
                    },
                )

            alias_ok, alias_msg = await _swing_alias(
                client, base, source=model_name, alias=alias_name,
            )
            if not alias_ok:
                # Versioned model published; alias step failed. Surface
                # both names so the operator can re-alias by hand.
                return ActionResult(
                    status="error",
                    error="alias_failed",
                    message=f"Created {model_name} but alias swing failed: {alias_msg}",
                    output={
                        "model_name": model_name, "alias": alias_name,
                        "ollama_host": base,
                    },
                )

        output = {
            "model_name": model_name,
            "alias": alias_name,
            "base_model": base_model,
            "role": role,
            "run_id": run_id,
            "generation": int(generation),
            "track_id": track_id,
            "adapter_dir": str(adapter_dir),
            "gguf_path": str(gguf_path),
            "gguf_size_bytes": gguf_size,
            "digest": digest,
            "ollama_host": base,
            "conversion_note": conversion_note,
        }
        return ActionResult(
            status="ok",
            message=f"Published {model_name} (alias {alias_name})",
            output=output,
        )


# Self-register with the central registry. This MUST be at the bottom
# of the module (after ``PublishAdapterToOllama`` is bound) -- the
# automation engine's ``actions.py`` loads us at the bottom of its own
# file, so by the time ``register_action`` resolves the class symbol
# the definition above is complete.
try:  # pragma: no cover -- the import side-effect IS the test
    from services.automation_engine.actions import register_action
    register_action(PublishAdapterToOllama)
except Exception as _exc:  # pragma: no cover
    logger.warning(
        "[publish-ollama] self-registration failed: %s", _exc,
    )


__all__ = ["PublishAdapterToOllama"]
