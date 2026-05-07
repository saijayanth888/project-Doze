"""Runtime DRAM guard for unified-memory hosts (DGX Spark).

Pre-flight check before kicking off long-running training/eval/mutation jobs.
On unified-memory hardware, exhausting DRAM can wedge the host (OOM killer
doesn't always recover cleanly). Failing fast with a clear RuntimeError is
preferable to taking down the box.

This is intentionally a pure-Python check — it does NOT shell out to sudo to
flush page caches, because we run inside a non-privileged container and that
would silently fail. Host-side cache management is handled by an external
cron (``/usr/local/bin/spark-memory-guard.sh``).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("modelforge.memory_guard")


def check_memory(min_gb: float, label: str = "task") -> float:
    """Log current DRAM availability; raise if below ``min_gb``.

    Returns available GB so callers can branch on tight-but-OK situations.
    Soft-fails (logs and returns 0.0) if psutil isn't importable, so the
    Mac dev image — which doesn't install psutil — keeps working.
    """
    try:
        import psutil
    except ImportError:
        logger.debug("[memory:%s] psutil not installed — skipping check", label)
        return 0.0

    mem = psutil.virtual_memory()
    available_gb = mem.available / 1e9
    logger.info(
        "[memory:%s] available=%.1fGB total=%.0fGB used=%d%%",
        label, available_gb, mem.total / 1e9, mem.percent,
    )
    if available_gb < min_gb:
        raise RuntimeError(
            f"ABORT {label}: only {available_gb:.1f}GB DRAM available, "
            f"need {min_gb:.1f}GB. Free memory or stop other jobs before retrying."
        )
    return available_gb
