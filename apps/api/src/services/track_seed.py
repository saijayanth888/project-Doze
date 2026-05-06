"""Default ForgeAgent tracks. Seeded once on startup if the table is empty.

Each track is a specialist branch of evolution targeting a subset of the
benchmarks. The classifier in ``agents/forge_agent.py`` routes user prompts to
the matching track and runs inference with that track's champion adapter.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("modelforge.track_seed")

DEFAULT_BASE = "meta-llama/Llama-3.2-3B-Instruct"

DEFAULT_TRACKS: list[dict[str, Any]] = [
    {
        "track_id": "reasoning",
        "name": "Reasoning Specialist",
        "description": "Logic, analysis, reading comprehension, common-sense inference.",
        "base_model": DEFAULT_BASE,
        "target_benchmarks": ["arc_challenge", "hellaswag"],
    },
    {
        "track_id": "code",
        "name": "Code Specialist",
        "description": "Programming, debugging, code generation, algorithms.",
        "base_model": DEFAULT_BASE,
        "target_benchmarks": ["humaneval"],
    },
    {
        "track_id": "math",
        "name": "Math Specialist",
        "description": "Arithmetic, word problems, equations, statistics.",
        "base_model": DEFAULT_BASE,
        "target_benchmarks": ["gsm8k"],
    },
    {
        "track_id": "general",
        "name": "General Knowledge",
        "description": "Broad knowledge, factual recall, and explanations.",
        "base_model": DEFAULT_BASE,
        "target_benchmarks": ["mmlu"],
    },
]


async def seed_default_tracks(db) -> None:
    """Insert any of the four default tracks that don't already exist.

    Existing rows are left alone — never clobber a user's customised track on
    boot. Safe to call repeatedly.
    """
    try:
        existing = await db.list_tracks()
    except Exception as exc:
        logger.warning("seed_default_tracks: list_tracks failed: %s", exc)
        return
    have = {t.get("track_id") for t in existing}
    for track in DEFAULT_TRACKS:
        if track["track_id"] in have:
            continue
        try:
            await db.upsert_track(track)
            logger.info("[tracks] seeded default %s", track["track_id"])
        except Exception as exc:
            logger.warning("seed_default_tracks: upsert %s failed: %s", track["track_id"], exc)
