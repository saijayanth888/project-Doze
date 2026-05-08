"""Slack Block Kit message for the hourly System Metrics post.

Companion to ``slack_blocks.py`` (evolution) and ``slack_blocks_campaign.py``
(campaign lifecycle). This builder emits a compact, phone-readable card with
CPU, DRAM, GPU, disk, and active-campaign status. The text fallback is what
shows on a phone lock screen — keep it short.
"""

from __future__ import annotations

import os
from typing import Any


def _dashboard_url(path: str = "/dashboard") -> str | None:
    base = os.environ.get("MODELFORGE_DASHBOARD_URL", "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}{path}"


def _bar(pct: float | None, width: int = 10) -> str:
    """ASCII usage bar — visual at-a-glance even on a phone."""
    if pct is None:
        return "—"
    p = max(0.0, min(100.0, float(pct)))
    filled = int(round(p / 100.0 * width))
    return "█" * filled + "░" * (width - filled)


def _fmt_gb(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}GB"


def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f}%"


def system_health(metrics: dict[str, Any]) -> tuple[str, list[dict]]:
    """Build (text_fallback, blocks) for the hourly health post.

    ``metrics`` shape (all fields optional, missing → "—"):
        {
            "cpu_percent": float,
            "ram_total_gb": float, "ram_used_gb": float,
            "ram_avail_gb": float, "ram_percent": float,
            "gpu": {"name": str, "vram_total_gb": float, "vram_used_gb": float,
                    "util_percent": float, "temp_celsius": float,
                    "unified_memory": bool},
            "disk": {"data_root": str, "free_gb": float, "total_gb": float,
                     "used_gb": float, "percent": float},
            "campaign": {"status": str, "name": str, "current_experiment": int,
                         "total_experiments": int, "current_model": str,
                         "current_benchmark": str, "elapsed_h": float} | None,
            "host": str,
        }
    """
    cpu = metrics.get("cpu_percent")
    ram_pct = metrics.get("ram_percent")
    ram_used = metrics.get("ram_used_gb")
    ram_total = metrics.get("ram_total_gb")
    ram_avail = metrics.get("ram_avail_gb")

    gpu = metrics.get("gpu") or {}
    gpu_name = gpu.get("name") or "GPU"
    gpu_util = gpu.get("util_percent")
    gpu_vram_used = gpu.get("vram_used_gb")
    gpu_vram_total = gpu.get("vram_total_gb")
    gpu_temp = gpu.get("temp_celsius")
    is_unified = bool(gpu.get("unified_memory"))

    disk = metrics.get("disk") or {}
    disk_pct = disk.get("percent")
    disk_free = disk.get("free_gb")
    disk_total = disk.get("total_gb")

    campaign = metrics.get("campaign") or None
    host = metrics.get("host") or "spark"

    # ── Header / fallback ─────────────────────────────────────────
    # Lock-screen text: punchiest stat first. CPU + RAM is what the user asked
    # for as the headline, GPU/disk follow in the card.
    text = f"💻 ModelForge · CPU {_fmt_pct(cpu)} · RAM {_fmt_pct(ram_pct)} ({_fmt_gb(ram_used)}/{_fmt_gb(ram_total)})"
    if campaign and campaign.get("status") in ("running", "starting", "ensuring", "paused"):
        cname = campaign.get("name") or "campaign"
        text += f" · 🧪 {cname}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"💻 System Health · {host}", "emoji": True},
        }
    ]

    # ── CPU + RAM row ────────────────────────────────────────────
    cpu_line = f"`{_bar(cpu)}` *{_fmt_pct(cpu)}*  CPU"
    ram_line = (
        f"`{_bar(ram_pct)}` *{_fmt_pct(ram_pct)}*  RAM "
        f"({_fmt_gb(ram_used)}/{_fmt_gb(ram_total)} · {_fmt_gb(ram_avail)} free)"
    )
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"{cpu_line}\n{ram_line}"},
    })

    # ── GPU row ──────────────────────────────────────────────────
    if gpu:
        if is_unified:
            # Spark / Jetson: VRAM is shared with system RAM, so VRAM total/used
            # come back N/A from nvidia-smi. Show util + temp instead and call it out.
            gpu_line = (
                f"`{_bar(gpu_util)}` *{_fmt_pct(gpu_util)}*  GPU util  ·  "
                f"{_fmt_pct(gpu_temp)[:-1]}°C  ({gpu_name}, unified mem)"
            )
        else:
            vram_pct = None
            if gpu_vram_used is not None and gpu_vram_total:
                vram_pct = (gpu_vram_used / gpu_vram_total) * 100
            gpu_line = (
                f"`{_bar(gpu_util)}` *{_fmt_pct(gpu_util)}*  GPU util  ·  "
                f"VRAM {_fmt_gb(gpu_vram_used)}/{_fmt_gb(gpu_vram_total)} "
                f"({_fmt_pct(vram_pct)})  ·  {_fmt_pct(gpu_temp)[:-1]}°C  ({gpu_name})"
            )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": gpu_line},
        })

    # ── Disk row ─────────────────────────────────────────────────
    if disk:
        disk_line = (
            f"`{_bar(disk_pct)}` *{_fmt_pct(disk_pct)}*  Disk  ·  "
            f"{_fmt_gb(disk_free)} free of {_fmt_gb(disk_total)}"
        )
        path = disk.get("data_root")
        if path:
            disk_line += f"  ·  `{path}`"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": disk_line},
        })

    # ── Active campaign / run row ────────────────────────────────
    if campaign:
        c_status = campaign.get("status") or "idle"
        c_name = campaign.get("name") or campaign.get("plan_id") or "campaign"
        c_idx = campaign.get("current_experiment")
        c_total = campaign.get("total_experiments")
        c_model = campaign.get("current_model")
        c_bench = campaign.get("current_benchmark")
        c_elapsed = campaign.get("elapsed_h")

        if c_status in ("running", "starting", "ensuring", "paused"):
            parts: list[str] = []
            if c_idx is not None and c_total:
                parts.append(f"experiment {int(c_idx) + 1}/{int(c_total)}")
            if c_model:
                parts.append(f"model `{c_model}`")
            if c_bench:
                parts.append(f"bench `{c_bench}`")
            if c_elapsed is not None:
                parts.append(f"elapsed {float(c_elapsed):.1f}h")
            line = f"🧪 *{c_name}* · {c_status.upper()}"
            if parts:
                line += "\n" + " · ".join(parts)
        else:
            line = f"🧪 No active campaign (status: {c_status})"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": line},
        })

    # ── Footer w/ optional Open Dashboard button ─────────────────
    url = _dashboard_url("/dashboard")
    if url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Dashboard", "emoji": True},
                    "url": url,
                }
            ],
        })

    return text, blocks


__all__ = ["system_health"]
