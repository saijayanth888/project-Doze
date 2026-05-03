import logging
import subprocess

logger = logging.getLogger("modelforge.gpu")

_MAC_FALLBACK = {
    "gpu_available": False,
    "device": "cpu",
    "cuda_available": False,
    "note": "Running on Mac — GPU metrics available on DGX Spark",
}


def get_gpu_status() -> dict:
    try:
        import torch

        cuda_available = torch.cuda.is_available()

        if not cuda_available:
            return _MAC_FALLBACK

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
            logger.warning("nvidia-smi failed: %s", result.stderr.strip())
            return {**_MAC_FALLBACK, "cuda_available": True, "device": "cuda"}

        line = result.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        gpu_name = parts[0]
        vram_total_mb = float(parts[1])
        vram_used_mb = float(parts[2])
        util_percent = float(parts[3])
        temp_celsius = float(parts[4])

        return {
            "gpu_available": True,
            "device": "cuda",
            "cuda_available": True,
            "gpu_name": gpu_name,
            "vram_total_gb": round(vram_total_mb / 1024, 2),
            "vram_used_gb": round(vram_used_mb / 1024, 2),
            "util_percent": util_percent,
            "temp_celsius": temp_celsius,
        }

    except Exception as exc:
        logger.warning("get_gpu_status failed, returning cpu fallback: %s", exc)
        return _MAC_FALLBACK
