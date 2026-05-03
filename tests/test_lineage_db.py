"""LineageDB round-trip with an in-memory pool stub.

We don't rely on a real Postgres in CI's unit-test job — the SQL is
exercised manually via the smoke test in scripts/test_local.py and the
``scripts/init_db.sql`` migration is verified by the Postgres service
container in the integration job.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from services.lineage_db import LineageDB


class _FakeConn:
    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self._next_fetchval: Any = 1
        self._next_fetchrow: Any = None
        self._next_fetch: list[Any] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.queries.append((sql, args))
        return "OK"

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.queries.append((sql, args))
        return self._next_fetchval

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.queries.append((sql, args))
        return self._next_fetchrow

    async def fetch(self, sql: str, *args: Any) -> Any:
        self.queries.append((sql, args))
        return self._next_fetch


class _FakePool:
    def __init__(self) -> None:
        self.conn = _FakeConn()

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                return pool.conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Ctx()


@pytest.fixture
def db() -> LineageDB:
    return LineageDB(pool=_FakePool())


@pytest.mark.asyncio
async def test_no_pool_is_safe():
    empty = LineageDB(pool=None)
    assert await empty.ping() is False
    assert await empty.get_all_generations() == []
    await empty.save_run("r1", "starting", {})


@pytest.mark.asyncio
async def test_save_run_uses_run_id_conflict(db):
    await db.save_run("run-x", "starting", {"base_model": "llama3.2:3b"})
    sql, args = db._pool.conn.queries[-1]
    assert "ON CONFLICT (run_id)" in sql
    assert args[0] == "run-x"
    assert args[2] == "starting"
    assert json.loads(args[3])["base_model"] == "llama3.2:3b"


@pytest.mark.asyncio
async def test_update_run_status_writes_current_generation(db):
    await db.update_run_status("run-x", "running", generation=3, current_step="evaluate")
    sql, args = db._pool.conn.queries[-1]
    assert "current_generation" in sql
    assert args == ("run-x", "running", 3, "evaluate", None)


@pytest.mark.asyncio
async def test_save_generation_upserts_on_run_id_generation(db):
    await db.save_generation(
        "run-x",
        {
            "generation": 2,
            "promoted": True,
            "is_champion": True,
            "child_scores": {"mmlu": 0.61},
            "parent_scores": {"mmlu": 0.6},
            "decision_reason": "improved",
            "method": "lora",
            "training_data_size": 1000,
            "duration_seconds": 1.5,
        },
    )
    sql, args = db._pool.conn.queries[-1]
    assert "ON CONFLICT (run_id, generation)" in sql
    assert args[0] == "run-x"
    assert args[1] == 2
    assert args[2] is True  # promoted
    assert args[3] is True  # is_champion


@pytest.mark.asyncio
async def test_ping_true_when_fetchval_succeeds(db):
    assert await db.ping() is True
