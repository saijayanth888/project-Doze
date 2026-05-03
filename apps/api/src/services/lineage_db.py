"""Postgres-backed read/write helpers for evolution lineage data.

Every method is safe to call when the pool is ``None`` (DB unavailable):
reads return empty results, writes are silently no-op'd. This keeps the
API responsive in dev / Mac mode where Postgres may not be running.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("modelforge.lineage_db")


class LineageDB:
    def __init__(self, pool: Any = None) -> None:
        self._pool = pool

    @property
    def has_pool(self) -> bool:
        return self._pool is not None

    async def ping(self) -> bool:
        """Return True iff the pool is reachable (used by /api/system/health)."""
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("LineageDB.ping failed: %s", exc)
            return False

    # ── Generations ────────────────────────────────────────────────
    async def get_all_generations(self, run_id: str | None = None) -> list[dict]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            if run_id is not None:
                rows = await conn.fetch(
                    "SELECT * FROM generations WHERE run_id = $1 ORDER BY generation ASC",
                    run_id,
                )
            else:
                rows = await conn.fetch("SELECT * FROM generations ORDER BY generation ASC")
            return [dict(r) for r in rows]

    async def get_generation(self, run_id: str, generation: int) -> dict | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM generations WHERE run_id = $1 AND generation = $2",
                run_id,
                generation,
            )
            return dict(row) if row else None

    async def save_generation(self, run_id: str, gen_data: dict) -> None:
        """UPSERT a generation row keyed by (run_id, generation)."""
        if self._pool is None:
            return
        generation = int(gen_data.get("generation", 0))
        promoted = bool(gen_data.get("promoted", False))
        is_champion = bool(gen_data.get("is_champion", False))
        parent_scores = gen_data.get("parent_scores", {}) or {}
        child_scores = gen_data.get("child_scores", gen_data.get("scores", {})) or {}
        decision_reason = gen_data.get("decision_reason")
        method = gen_data.get("method")
        training_size = int(gen_data.get("training_data_size", 0))
        duration = float(gen_data.get("duration_seconds", 0.0))

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO generations (
                    run_id, generation, promoted, is_champion,
                    parent_scores, child_scores, decision_reason, method,
                    training_data_size, duration_seconds, data
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9, $10, $11::jsonb)
                ON CONFLICT (run_id, generation) DO UPDATE SET
                    promoted          = EXCLUDED.promoted,
                    is_champion       = EXCLUDED.is_champion,
                    parent_scores     = EXCLUDED.parent_scores,
                    child_scores      = EXCLUDED.child_scores,
                    decision_reason   = EXCLUDED.decision_reason,
                    method            = EXCLUDED.method,
                    training_data_size= EXCLUDED.training_data_size,
                    duration_seconds  = EXCLUDED.duration_seconds,
                    data              = EXCLUDED.data
                """,
                run_id,
                generation,
                promoted,
                is_champion,
                json.dumps(parent_scores),
                json.dumps(child_scores),
                decision_reason,
                method,
                training_size,
                duration,
                json.dumps(gen_data, default=str),
            )

    # ── Evolution runs ─────────────────────────────────────────────
    async def get_run(self, run_id: str) -> dict | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM evolution_runs WHERE run_id = $1", run_id)
            return dict(row) if row else None

    async def get_dashboard_run(self) -> dict | None:
        """Prefer an in-flight run; otherwise the most recent run (any status)."""
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM evolution_runs
                WHERE status NOT IN ('completed', 'failed', 'stopped')
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            if row:
                return dict(row)
            row = await conn.fetchrow(
                "SELECT * FROM evolution_runs ORDER BY started_at DESC LIMIT 1"
            )
            return dict(row) if row else None

    async def save_run(self, run_id: str, status: str, config: dict) -> None:
        if self._pool is None:
            return
        base_model = str(config.get("base_model", "")) or "unknown"
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO evolution_runs (run_id, base_model, status, config)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET
                    base_model = EXCLUDED.base_model,
                    status     = EXCLUDED.status,
                    config     = EXCLUDED.config
                """,
                run_id,
                base_model,
                status,
                json.dumps(config),
            )

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        generation: int = 0,
        current_step: str | None = None,
        error: str | None = None,
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE evolution_runs
                SET status              = $2,
                    current_generation  = $3,
                    current_step        = $4,
                    error               = COALESCE($5, error)
                WHERE run_id = $1
                """,
                run_id,
                status,
                generation,
                current_step,
                error,
            )

    async def complete_run(self, run_id: str) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE evolution_runs
                SET status = 'completed', completed_at = NOW()
                WHERE run_id = $1
                """,
                run_id,
            )

    # ── Benchmark scores ───────────────────────────────────────────
    async def get_score_trends(self) -> list[dict]:
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM benchmark_scores ORDER BY generation ASC")
            return [dict(r) for r in rows]

    async def save_score(
        self,
        run_id: str,
        generation: int,
        benchmark: str,
        score: float,
        promoted: bool,
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO benchmark_scores (run_id, generation, benchmark, score, promoted)
                VALUES ($1, $2, $3, $4, $5)
                """,
                run_id,
                generation,
                benchmark,
                score,
                promoted,
            )
