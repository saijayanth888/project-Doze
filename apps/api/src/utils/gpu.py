"""GPU metrics for `/api/system/gpu`.

The FastAPI container is often CPU-only in Compose while **Ollama** holds the NVIDIA
devices. We try `nvidia-smi` first (works when the container has GPU access),
then PyTorch CUDA, then a neutral fallback — never assume Apple Silicon.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess

logger = logging.getLogger("modelforge.gpu")

_SPARK_INFERENCE_NOTE = (
    "Evolution and playground inference use the Ollama service. "
    "With `docker compose --profile gpu up`, Ollama is GPU-backed even if this API "
    "container does not report NVIDIA metrics."
)


def _fallback_no_smi(note: str | None = None) -> dict:
    if note is None:
        if platform.system() == "Darwin":
            note = (
                "No NVIDIA metrics on macOS from this container. "
                f"On DGX Spark, use Linux + NVIDIA Container Toolkit; compose gives `api` `gpus: all`. "
                f"{_SPARK_INFERENCE_NOTE}"
            )
        else:
            note = (
                "No NVIDIA metrics from this API process (no `nvidia-smi` or driver access). "
                f"{_SPARK_INFERENCE_NOTE} "
                "Ensure `api` has GPU access (see `docker-compose.yml` `gpus: all`) and restart the stack."
            )
    return {
        "gpu_available": False,
        "device": "cpu",
        "cuda_available": False,
        "note": note,
        "inference_note": _SPARK_INFERENCE_NOTE,
        "ollama_inference_ok": False,
    }


def _from_nvidia_smi() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("nvidia-smi failed: %s", (result.stderr or "").strip())
            return None
        line = result.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            return None
        def _safe_float(val):
            """Parse nvidia-smi value; returns None for [N/A] (e.g. GB10 unified memory)."""
            v = val.strip().strip("[]")
            if v in ("N/A", ""):
                return None
            try:
                return float(v)
            except ValueError:
                return None

        gpu_name = parts[0]
        vram_total_mb = _safe_float(parts[1])
        vram_used_mb = _safe_float(parts[2])
        util_percent = _safe_float(parts[3])
        temp_celsius = _safe_float(parts[4])

        return {
            "gpu_available": True,
            "device": "cuda",
            "cuda_available": True,
            "gpu_name": gpu_name,
            "vram_total_gb": round(vram_total_mb / 1024, 2) if vram_total_mb is not None else None,
            "vram_used_gb": round(vram_used_mb / 1024, 2) if vram_used_mb is not None else None,
            "util_percent": util_percent,
            "temp_celsius": temp_celsius,
            "note": None,
            "inference_note": _SPARK_INFERENCE_NOTE,
            "ollama_inference_ok": False,
        }
    except Exception as exc:
        logger.warning("nvidia-smi error: %s", exc)
        return None


def _from_torch_cuda() -> dict | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        name = None
        try:
            name = torch.cuda.get_device_name(0)
        except Exception:
            pass
        return {
            "gpu_available": True,
            "device": "cuda",
            "cuda_available": True,
            "gpu_name": name,
            "vram_total_gb": None,
            "vram_used_gb": None,
            "util_percent": None,
            "temp_celsius": None,
            "note": "CUDA visible to PyTorch; install/use nvidia-smi in this image for VRAM and utilization.",
            "inference_note": _SPARK_INFERENCE_NOTE,
            "ollama_inference_ok": False,
        }
    except Exception as exc:
        logger.debug("torch.cuda path skipped: %s", exc)
        return None


def get_gpu_status() -> dict:
    """Return GPU telemetry when available; otherwise an honest CPU / no-metrics fallback."""
    smi = _from_nvidia_smi()
    if smi is not None:
        return smi

    torch_gpu = _from_torch_cuda()
    if torch_gpu is not None:
        return torch_gpu

    logger.warning("get_gpu_status: no NVIDIA metrics, using fallback")
    return _fallback_no_smi()
